"""Serial exact-candidate ASR, native vision and physical QC for Shorts."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

from avo import shorts_contract, shorts_media, shorts_qc
from avo.adapters.transcribe.candidate import CandidateTranscriptionAdapter
from avo.adapters.understand.watch_skill import WatchSkillAdapter

SCORE_KEYS = (
    "promiseClarity",
    "paceAndRedundancy",
    "compositionAndCrop",
    "captionLegibilityAndSync",
    "insertsAndSfx",
    "factualConsistency",
    "rightsPrivacyAndSpoilers",
)


def _read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _now():
    return datetime.now(UTC).isoformat()


def _model_pin(plan):
    raw = Path(plan["source"]["masterPath"]).parent
    pin = (_read(raw / "avo.project.json").get("models") or {}).get("understand") or {}
    _validate_model_pin(pin)
    return raw, pin


def _validate_model_pin(pin):
    endpoint = (pin.get("source") or {}).get("endpoint") or {}
    model = str(pin.get("id") or "")
    host = urlparse(str(endpoint.get("baseUrl") or "")).hostname
    checks = (
        pin.get("source", {}).get("kind") == "endpoint",
        endpoint.get("servedName") == model,
        host in {"localhost", "127.0.0.1", "::1"},
        "qwen3.5" in model.lower(),
        "4b" in model.lower(),
    )
    if not all(checks):
        raise ValueError(
            "Shorts review requires project-pinned local Qwen3.5 4B endpoint"
        )


def review_windows(item):
    """Bound and merge mandatory review intervals without dropping their labels."""
    duration = float(item["editedDurationSec"])
    windows = [
        (0, min(duration, 1.5), "opening"),
        (max(0, duration - 1.5), duration, "ending"),
    ]
    for segment in (item.get("sourceSegments") or [])[1:]:
        seam = float(segment["outputStartSec"])
        windows.append((max(0, seam - 1.5), min(duration, seam + 1.5), "join"))
    for event in [*(item.get("visualInserts") or []), *(item.get("callouts") or [])]:
        windows.extend(_event_windows(event, duration))
    merged = []
    for start, end, label in sorted(windows):
        if merged and start <= merged[-1]["end"]:
            merged[-1]["end"] = max(end, merged[-1]["end"])
            merged[-1]["reason"] += "; " + label
        else:
            merged.append({"start": start, "end": end, "reason": label})
    while len(merged) > 20:
        _merge_nearest(merged)
    return merged


def _event_windows(event, duration):
    start = max(0.0, float(event["startSec"]))
    end = min(duration, float(event["endSec"]))
    label = str(event.get("id") or "visual")
    return [
        (max(0, start - 0.25), min(duration, start + 0.5), label + ":entry"),
        (
            max(0, (start + end) / 2 - 0.25),
            min(duration, (start + end) / 2 + 0.25),
            label + ":hold",
        ),
        (max(0, end - 0.5), min(duration, end + 0.25), label + ":exit"),
    ]


def _merge_nearest(windows):
    index = min(
        range(len(windows) - 1),
        key=lambda i: windows[i + 1]["start"] - windows[i]["end"],
    )
    right = windows.pop(index + 1)
    windows[index]["end"] = right["end"]
    windows[index]["reason"] += "; " + right["reason"]


def _current_proof(item, row):
    revision = int(row.get("proofArtifactRevision") or row.get("proofRevision") or 0)
    checks = (
        not row.get("dirty"),
        row.get("inputFingerprint") == item["inputFingerprint"],
        row.get("state") in {"proof-ready", "proof-approved"},
        revision == row.get("proofRevision"),
    )
    if not all(checks):
        raise ValueError(f"Short {item['id']} has dirty or noncurrent proof")
    artifacts = [a for a in row["artifacts"] if a["revision"] == revision]
    proof = next((a for a in reversed(artifacts) if a["kind"] == "proof"), None)
    if not proof:
        raise ValueError(f"Short {item['id']} has no current proof")
    _verify_artifacts(artifacts)
    return proof, artifacts


def _verify_artifacts(artifacts):
    for artifact in artifacts:
        path = Path(artifact["path"])
        if not path.is_file() or shorts_media.sha256_file(path) != artifact["hash"]:
            raise ValueError(f"review dependency hash mismatch: {path}")


def _identity(plan, item, row, proof, artifacts):
    lock = {
        "planHash": plan["planHash"],
        "inputFingerprint": item["inputFingerprint"],
        "source": plan["source"],
        "output": plan["output"],
        "artifacts": artifacts,
    }
    identity = {
        "shortId": item["id"],
        "proofRevision": proof["revision"],
        "candidateHash": proof["hash"],
        "renderProfile": row.get("renderProfile"),
        "dependencyLockSha256": shorts_contract.content_hash(lock),
    }
    return lock, {
        **identity,
        "candidateIdentityHash": shorts_contract.content_hash(identity),
    }


def _watch_request(plan, item, pin, review_dir, lock, identity, transcription):
    transcript_path = Path(transcription["transcriptPath"])
    dependencies = {
        "lock": lock,
        "planHash": plan["planHash"],
        "transcriptSha256": shorts_media.sha256_file(transcript_path),
    }
    return {
        "option_id": pin["id"],
        "model_pin": pin,
        "scope": "windows",
        "windows": review_windows(item),
        "checkpoint": "motion-proof",
        "artifact_dir": review_dir / "watch",
        "root": review_dir,
        "transcript_ref": str(transcript_path),
        "policy": {
            "effective": {
                "concurrency": 1,
                "vramCeilingBytes": 7 * 1024**3,
                "maxImagesPerPass": 3,
                "imageLongSide": 640,
                "maxOutputTokens": 1536,
                "contextLimit": 8192,
                "maxFrames": 60,
                "operatorManagedLifecycle": True,
            }
        },
        "context": _review_context(plan, item, identity, transcription),
        "contract_context": {**identity, "dependencies": dependencies},
    }


def _candidate_transcript(transcription, expected_hash):
    payload = _read(transcription["transcriptPath"])
    source_hash = (payload.get("source") or {}).get("sha256") or payload.get(
        "sourceSha256"
    )
    if (
        source_hash != expected_hash
        or transcription.get("sourceSha256") != expected_hash
    ):
        raise ValueError("review transcript content is not bound to exact candidate")
    return {
        "text": _transcript_text(payload),
        "language_code": _transcript_language(payload, transcription),
        "sourceSha256": source_hash,
    }


def _transcript_text(payload):
    text = payload.get("text") or " ".join(
        str(word.get("word") or word.get("text") or "")
        for word in payload.get("words") or []
    )
    if not str(text).strip():
        raise ValueError("speech review requires actual candidate transcript text")
    return str(text)


def _transcript_language(payload, transcription):
    return (
        payload.get("language_code")
        or payload.get("language")
        or transcription.get("language")
        or "unknown"
    )


def _review_context(plan, item, identity, transcription):
    transcript = _candidate_transcript(transcription, identity["candidateHash"])
    reference = {
        "reviewDateUTC": _now(),
        "candidateTranscript": transcript,
        "editorialPromise": item.get("viewerPromise") or item.get("coreIdea"),
        "originalSourceEvidence": item.get("sourceEvidence"),
        "layout": item.get("layout"),
        "plannedCaptions": _timed_reference(item.get("captions") or []),
        "plannedVisualEvents": _timed_reference(
            [*(item.get("visualInserts") or []), *(item.get("callouts") or [])]
        ),
        "plannedSfxEvents": _timed_reference(item.get("sfxHits") or []),
        "restrictions": item.get("factualReviewReferences") or [],
    }
    return {
        "format": "YouTube Shorts",
        "language": transcript["language_code"],
        **reference,
        "acceptanceCriteria": [
            *_review_criteria(),
            "Verified candidate evidence and declared editorial plan, not English instruction text: "
            + json.dumps(reference, ensure_ascii=False, separators=(",", ":")),
            "Every response must match this JSON schema, including scorecard.criticalFailure and scorecard.notes: "
            + json.dumps(_review_response_schema(), separators=(",", ":")),
        ],
    }


def _timed_reference(events):
    fields = ("id", "startSec", "endSec", "kind", "label", "renderedText", "text")
    return [{key: event[key] for key in fields if key in event} for event in events]


def _review_criteria():
    return [
        "Judge the declared editorial promise against visible primary evidence and the verified candidate ASR transcript. English instructions and metadata do not establish the spoken language.",
        "Captions transcribe the creator's speech, not unrelated packaging text. Compare visible captions with candidateTranscript and plannedCaptions; graphic labels need not be verbatim speech.",
        "Assess only confirmed visible defects in the sampled frames. Do not infer audio quality, SFX audibility, lip sync, camera shake or continuous action from still images or different object positions across samples. Claim blur only when visible pixels establish it. State observational limits in scorecard.notes without inventing defects.",
        "Evaluate the current primary subject, product and essential UI. Decorative background shelves need not be sharply readable; report confirmed obstruction or illegibility of primary evidence.",
        "Declared splits and timed inserts are intentional. Consult each event's timing and labels. Do not demand unplanned inserts, gameplay or SFX, or penalize an effect for being absent outside its declared interval.",
        "Memes illustrate an opinion, not a survey. User ratings are not universal community opinion. Preserve version labels and supplied restrictions.",
        "Use the supplied reviewDateUTC as the current date and the supplied factual references as context. Do not call a date future merely because it follows your training knowledge. Raise confirmed factual conflicts or genuine unverified uncertainty explicitly.",
        "Do not dismiss confirmed defects or force a passing status. Score each dimension from evidence, explain uncertainty, and return fail or needs-human-judgment when warranted.",
    ]


def _review_response_schema():
    score_properties = {
        key: {"type": "integer", "minimum": 1, "maximum": 5} for key in SCORE_KEYS
    }
    score_properties.update(
        criticalFailure={"type": "boolean"}, notes={"type": "string"}
    )
    return {
        "type": "object",
        "required": ["status", "confidence", "findings", "scorecard"],
        "properties": {
            "status": {"enum": ["pass", "fail", "needs-human-judgment"]},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "findings": {"type": "array", "items": {"type": "object"}},
            "scorecard": {
                "type": "object",
                "required": list(score_properties),
                "properties": score_properties,
                "additionalProperties": False,
            },
        },
    }


def _output_profile(plan, row):
    output = dict(plan["output"])
    profile = row.get("renderProfile") or {}
    if profile.get("preview"):
        output.update(width=profile["width"], height=profile["height"])
    return output


def _review_one(plan, item, row, batch, pin, watch, transcriber, device):
    proof, artifacts = _current_proof(item, row)
    review_dir = batch / "review" / item["id"] / f"proof-v{proof['revision']:03d}"
    review_dir.mkdir(parents=True, exist_ok=True)
    lock, identity = _identity(plan, item, row, proof, artifacts)
    transcription = transcriber.transcribe(
        Path(proof["path"]), edit_dir=review_dir, device=device
    )
    if transcription.get("sourceSha256") != proof["hash"]:
        raise ValueError("transcription is not bound to exact proof")
    transcript_hash = shorts_media.sha256_file(Path(transcription["transcriptPath"]))
    identity["transcriptSha256"] = transcript_hash
    identity.pop("candidateIdentityHash")
    identity["candidateIdentityHash"] = shorts_contract.content_hash(identity)
    request = _watch_request(plan, item, pin, review_dir, lock, identity, transcription)
    vision = watch.review(Path(proof["path"]), **request)
    if (
        shorts_media.sha256_file(Path(transcription["transcriptPath"]))
        != transcript_hash
    ):
        raise ValueError("transcript changed during review")
    _verify_artifacts(artifacts)
    return _freeze_review(
        plan, item, row, proof, review_dir, lock, identity, transcription, vision
    )


def _freeze_review(
    plan, item, row, proof, directory, lock, identity, transcription, vision
):
    report_path = directory / "review-result.json"
    scorecard = _qwen_scorecard(vision)
    passed = (
        transcription.get("status") == "pass"
        and vision.get("status") in {"pass", "needs-human-judgment"}
        and scorecard["status"] == "pass"
    )
    qc = shorts_qc.qc_proof_artifact(
        item,
        proof,
        watch_reference=str(report_path) if passed else None,
        output=_output_profile(plan, row),
    )
    if not passed:
        qc["status"] = "failed"
        qc.setdefault("findings", []).append(
            {"severity": "error", "code": "automated-review-failed"}
        )
    report = {
        "identity": identity,
        "dependencyLock": lock,
        "transcription": transcription,
        "watch": vision,
        "qwenScorecard": scorecard,
        "qc": qc,
        "updatedAt": _now(),
        "humanApproval": False,
    }
    for name, payload in [
        ("candidate-identity.json", identity),
        ("dependency-lock.json", lock),
        ("transcription-result.json", transcription),
        ("review-result.json", report),
    ]:
        shorts_contract.atomic_write_json(directory / name, payload)
    _verify_artifacts(lock["artifacts"])
    reference = {
        "reference": str(report_path),
        "candidateHash": proof["hash"],
        "candidateIdentityHash": identity["candidateIdentityHash"],
        "dependencyLockSha256": identity["dependencyLockSha256"],
        "evidenceBundleSha256": shorts_media.sha256_file(report_path),
        "proofRevision": proof["revision"],
    }
    return {
        "qc": qc,
        "watchReview": reference,
        "watchReviewReference": str(report_path) if passed else None,
    }


def _qwen_scorecard(vision):
    try:
        passes = [
            _scorecard_response(ref) for ref in vision.get("rawArtifactRefs") or []
        ]
    except (OSError, KeyError, IndexError, TypeError, ValueError) as exc:
        return _failed_scorecard(str(exc))
    if not passes:
        return _failed_scorecard(
            "Qwen response did not contain the required scorecard."
        )
    return _aggregate_scorecard(passes)


def _aggregate_scorecard(passes):
    scores = {}
    for key in SCORE_KEYS:
        values = sorted(item["scores"][key] for item in passes)
        scores[key] = values[(len(values) - 1) // 2]
    critical = any(item["criticalFailure"] for item in passes)
    return {
        "status": "pass" if not critical and min(scores.values()) >= 3 else "failed",
        "scores": scores,
        "criticalFailure": critical,
        "notes": [item["notes"] for item in passes if item["notes"]],
        "passes": passes,
    }


def _failed_scorecard(reason):
    return {
        "status": "failed",
        "scores": {},
        "criticalFailure": True,
        "notes": reason,
        "passes": [],
    }


def _scorecard_response(ref):
    if not isinstance(ref, dict):
        raise TypeError("scorecard response reference must be an object")
    if ref.get("kind") != "endpoint-response":
        raise ValueError("scorecard requires a declared endpoint response")
    path = Path(ref["path"])
    data = path.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if digest != ref.get("sha256"):
        raise ValueError("scorecard response fingerprint mismatch")
    response = json.loads(data)
    content = response["choices"][0]["message"]["content"]
    card = _json_object(content)["scorecard"]
    scores = {key: _scorecard_integer(card[key]) for key in SCORE_KEYS}
    if type(card.get("criticalFailure")) is not bool:
        raise ValueError("scorecard requires an explicit boolean criticalFailure")
    return {
        "scores": scores,
        "criticalFailure": card["criticalFailure"],
        "notes": str(card.get("notes") or ""),
        "source": str(path),
        "sha256": digest,
    }


def _scorecard_integer(value):
    if type(value) is not int:
        raise ValueError("scorecard scores must be integers from 1 to 5")
    return min(5, max(1, value))


def _json_object(value):
    text = str(value).strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        raise ValueError("missing JSON object")
    return json.loads(text[start : end + 1])


def _load_batch(plan_path):
    plan = shorts_contract.load_document(plan_path, "plan")
    batch = Path(plan.get("batchRoot") or plan_path.parent.parent)
    status_path = batch / "plans" / "shorts.status.json"
    status = shorts_contract.load_document(status_path, "status")
    if (
        status["planHash"] != plan["planHash"]
        or shorts_contract.plan_hash(plan) != plan["planHash"]
    ):
        raise ValueError("review plan hash does not match current batch")
    return plan, batch, status_path, status


def _persist_item(status_path, plan, item, result):
    current = shorts_contract.load_document(status_path, "status")
    if current["planHash"] != plan["planHash"]:
        raise ValueError("batch plan changed during review")
    row = next(row for row in current["items"] if row["shortId"] == item["id"])
    proof, _ = _current_proof(item, row)
    if proof["hash"] != result["watchReview"]["candidateHash"]:
        raise ValueError("proof changed during review")
    row.update(result)
    shorts_contract.atomic_write_json(status_path, current)


def _summarize(status_path, plan):
    status = shorts_contract.load_document(status_path, "status")
    if status["planHash"] != plan["planHash"]:
        raise ValueError("batch plan changed during review")
    passed = [row["shortId"] for row in status["items"] if _automated_pass(row)]
    failed = [row["shortId"] for row in status["items"] if row["shortId"] not in passed]
    summary = {
        "stage": "proof",
        "passed": len(passed),
        "failed": len(failed),
        "selected": len(plan["items"]),
        "updatedAt": _now(),
    }
    status.update(
        batchQcSummary=summary,
        batchState="proof-review" if not failed else "proof-partial",
        updatedAt=_now(),
    )
    shorts_contract.atomic_write_json(status_path, status)
    return {
        "statusPath": str(status_path),
        "passed": passed,
        "failed": failed,
        "summary": summary,
    }


def _automated_pass(row):
    review = row.get("watchReview") or {}
    return (
        not row.get("dirty")
        and (row.get("qc") or {}).get("status") == "passed"
        and bool(row.get("watchReviewReference"))
        and review.get("proofRevision") == row.get("proofRevision")
        and _review_files_current(row, review)
    )


def _review_files_current(row, review):
    proof = next(
        (
            a
            for a in row["artifacts"]
            if a["kind"] == "proof" and a["revision"] == row["proofRevision"]
        ),
        None,
    )
    if not proof or proof["hash"] != review.get("candidateHash"):
        return False
    bindings = [
        (proof["path"], proof["hash"]),
        (review["reference"], review["evidenceBundleSha256"]),
    ]
    return all(
        Path(path).is_file() and shorts_media.sha256_file(Path(path)) == expected
        for path, expected in bindings
    )


def review_batch(
    plan_path,
    *,
    short_ids=None,
    watch_adapter=None,
    transcriber=None,
    asr_model="large-v3",
    device="cpu",
):
    """Review serially; never grant human approval or produce delivery masters."""
    if device != "cpu":
        raise ValueError(
            "Shorts review ASR must use CPU while the vision model is loaded"
        )
    plan, batch, status_path, status = _load_batch(Path(plan_path).resolve())
    _raw, pin = _model_pin(plan)
    selected = _selected_ids(plan, short_ids)
    watch = watch_adapter or WatchSkillAdapter()
    transcriber = transcriber or CandidateTranscriptionAdapter(model=asr_model)
    rows = {row["shortId"]: row for row in status["items"]}
    for item in plan["items"]:
        if item["id"] in selected:
            result = _review_one(
                plan, item, rows[item["id"]], batch, pin, watch, transcriber, device
            )
            _persist_item(status_path, plan, item, result)
    return _summarize(status_path, plan)


def _selected_ids(plan, short_ids):
    known = {item["id"] for item in plan["items"]}
    selected = set(short_ids or known)
    if selected - known:
        raise ValueError("unknown review short ID")
    return selected
