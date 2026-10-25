from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from avo import shorts_contract, shorts_media, shorts_review


@pytest.mark.parametrize("failed,expected_exit", [([], 0), (["02"], 2)])
def test_cli_dispatches_native_serial_review(
    monkeypatch, capsys, failed, expected_exit
):
    from avo import shorts

    calls = []

    def review(plan, **options):
        calls.append((plan, options))
        return {"failed": failed, "passed": ["01"]}

    monkeypatch.setattr(shorts_review, "review_batch", review)
    result = shorts.main(
        ["review", "plan.json", "--short", "01", "--short", "02", "--device", "cpu"]
    )
    assert result == expected_exit
    assert calls == [
        (Path("plan.json").resolve(), {"short_ids": ["01", "02"], "device": "cpu"})
    ]
    assert json.loads(capsys.readouterr().out)["failed"] == failed


def test_status_schema_accepts_source_fidelity_artifact():
    schema = shorts_contract.load_schema("status")["$defs"]["artifact"]
    Draft202012Validator(schema).validate(
        {
            "kind": "source-fidelity",
            "path": "source-fidelity.json",
            "hash": "a" * 64,
            "revision": 7,
        }
    )


@pytest.fixture
def batch(tmp_path, monkeypatch):
    raw = tmp_path / "raw"
    raw.mkdir()
    pin = {
        "id": "qwen3.5-4b",
        "source": {
            "kind": "endpoint",
            "endpoint": {
                "baseUrl": "http://127.0.0.1:1234/v1",
                "servedName": "qwen3.5-4b",
            },
        },
    }
    (raw / "avo.project.json").write_text(json.dumps({"models": {"understand": pin}}))
    root = raw / "edit/shorts/batch"
    (root / "plans").mkdir(parents=True)
    proof = root / "candidate.mp4"
    proof.write_bytes(b"exact candidate")
    item = {
        "id": "01",
        "inputFingerprint": "a" * 64,
        "editedDurationSec": 10,
        "sourceEvidence": "Original words",
        "viewerPromise": "Demonstrate a manual",
        "visualInserts": [
            {"id": "image", "startSec": 2, "endSec": 7, "label": "Illustration"}
        ],
    }
    plan = {
        "version": "1.2",
        "batchId": "batch",
        "batchRoot": str(root),
        "source": {"masterPath": str(raw / "original.mp4")},
        "output": {"width": 1728, "height": 3072, "pixelFormat": "yuv420p10le"},
        "items": [item],
    }
    plan["planHash"] = shorts_contract.plan_hash(plan)
    row = {
        "shortId": "01",
        "inputFingerprint": item["inputFingerprint"],
        "dirty": False,
        "state": "proof-ready",
        "proofRevision": 7,
        "proofArtifactRevision": 7,
        "artifacts": [
            {
                "kind": "proof",
                "path": str(proof),
                "hash": shorts_media.sha256_file(proof),
                "revision": 7,
            }
        ],
        "renderProfile": {"preview": True, "width": 720, "height": 1280},
    }
    status = {"planHash": plan["planHash"], "items": [row], "batchApprovals": []}
    plan_path = root / "plans/shorts.plan-v007.json"
    shorts_contract.atomic_write_json(plan_path, plan)
    shorts_contract.atomic_write_json(root / "plans/shorts.status.json", status)
    monkeypatch.setattr(
        shorts_contract, "load_document", lambda path, kind: shorts_review._read(path)
    )
    monkeypatch.setattr(
        shorts_review,
        "_qwen_scorecard",
        lambda vision: {
            "status": "pass",
            "scores": {key: 5 for key in shorts_review.SCORE_KEYS},
            "criticalFailure": False,
            "notes": [],
            "passes": [],
        },
    )
    return plan_path, proof, status


def test_qwen_scorecard_lower_median_blocks_two_pass_score_below_three(tmp_path):
    refs = []
    for index, score in enumerate((5, 2), 1):
        path = tmp_path / f"pass-{index}.json"
        card = {
            "scorecard": {
                **{key: score for key in shorts_review.SCORE_KEYS},
                "criticalFailure": False,
                "notes": f"pass {index}",
            }
        }
        path.write_text(
            json.dumps({"choices": [{"message": {"content": json.dumps(card)}}]}),
            encoding="utf-8",
        )
        refs.append(
            {
                "path": str(path),
                "kind": "endpoint-response",
                "sha256": shorts_media.sha256_file(path),
            }
        )

    result = shorts_review._qwen_scorecard({"rawArtifactRefs": refs})

    assert result["status"] == "failed"
    assert result["scores"] == {key: 2 for key in shorts_review.SCORE_KEYS}
    assert result["criticalFailure"] is False


def test_qwen_scorecard_uses_lower_median_across_partial_passes():
    passes = []
    for score in (2, 3, 3, 4, 5, 5):
        passes.append(
            {
                "scores": {key: score for key in shorts_review.SCORE_KEYS},
                "criticalFailure": False,
                "notes": "",
            }
        )
    result = shorts_review._aggregate_scorecard(passes)
    assert result["status"] == "pass"
    assert result["scores"] == {key: 3 for key in shorts_review.SCORE_KEYS}


@pytest.mark.parametrize(("reported", "normalized"), [(0, 1), (6, 5)])
def test_scorecard_clamps_out_of_range_integer_scores(reported, normalized):
    assert shorts_review._scorecard_integer(reported) == normalized


@pytest.mark.parametrize(
    "invalid",
    [
        "missing-card",
        "float",
        "boolean-score",
        "string-score",
        "missing-critical",
        "string-critical",
        "bad-hash",
        "missing-file",
    ],
)
def test_scorecard_rejects_any_invalid_pass_even_beside_valid_pass(tmp_path, invalid):
    refs = []
    for index in range(2):
        card = {
            **{key: 5 for key in shorts_review.SCORE_KEYS},
            "criticalFailure": False,
        }
        if index == 1:
            _invalidate_card(card, invalid)
        payload = (
            {} if index == 1 and invalid == "missing-card" else {"scorecard": card}
        )
        path = tmp_path / f"response-{index}.json"
        path.write_text(
            json.dumps({"choices": [{"message": {"content": json.dumps(payload)}}]})
        )
        ref = {
            "path": str(path),
            "kind": "endpoint-response",
            "sha256": shorts_media.sha256_file(path),
        }
        if index == 1 and invalid == "bad-hash":
            ref["sha256"] = "0" * 64
        if index == 1 and invalid == "missing-file":
            path.unlink()
        refs.append(ref)
    result = shorts_review._qwen_scorecard({"rawArtifactRefs": refs})
    assert result["status"] == "failed"
    assert result["criticalFailure"] is True


def _invalidate_card(card, invalid):
    score_values = {"float": 4.5, "boolean-score": True, "string-score": "5"}
    if invalid in score_values:
        card[shorts_review.SCORE_KEYS[0]] = score_values[invalid]
    if invalid == "missing-critical":
        card.pop("criticalFailure")
    if invalid == "string-critical":
        card["criticalFailure"] = "false"


class Transcriber:
    def transcribe(self, candidate, **options):
        assert options["device"] == "cpu"
        path = options["edit_dir"] / "transcripts/exact.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "text": "Aqui está o manual colorido.",
                    "language_code": "pt",
                    "sourceSha256": shorts_media.sha256_file(candidate),
                    "words": [],
                }
            ),
            encoding="utf-8",
        )
        return {
            "status": "pass",
            "sourceSha256": shorts_media.sha256_file(candidate),
            "transcriptPath": str(path),
        }


class Watch:
    def __init__(self, status="pass", mutate=False):
        self.status, self.mutate = status, mutate
        self.requests = []

    def review(self, candidate, **request):
        self.requests.append(request)
        if self.mutate:
            candidate.write_bytes(b"replaced")
        return {"status": self.status, "model": request["model_pin"]["id"]}


def test_review_binds_exact_candidate_without_human_approval(batch, monkeypatch):
    path, proof, _status = batch
    watch = Watch()
    calls = []

    def qc(item, artifact, **options):
        calls.append(options)
        return {"status": "passed", "findings": []}

    monkeypatch.setattr(shorts_review.shorts_qc, "qc_proof_artifact", qc)
    result = shorts_review.review_batch(
        path, watch_adapter=watch, transcriber=Transcriber()
    )
    assert result["passed"] == ["01"]
    assert calls[0]["output"]["width"] == 720
    assert calls[0]["output"]["pixelFormat"] == "yuv420p10le"
    request = watch.requests[0]
    assert request["policy"]["effective"]["operatorManagedLifecycle"] is True
    assert request["contract_context"]["candidateHash"] == shorts_media.sha256_file(
        proof
    )
    status = shorts_review._read(path.parent / "shorts.status.json")
    assert status["batchState"] == "proof-review"
    assert status["batchApprovals"] == []
    assert status["items"][0]["state"] == "proof-ready"
    report = shorts_review._read(Path(status["items"][0]["watchReviewReference"]))
    assert report["humanApproval"] is False


def test_native_prompt_contains_verified_portuguese_and_editorial_references(
    batch, monkeypatch
):
    from avo.adapters.understand.watch_policy import build_watch_prompt

    monkeypatch.setattr(
        shorts_review.shorts_qc,
        "qc_proof_artifact",
        lambda *a, **k: {"status": "passed", "findings": []},
    )
    watch = Watch()
    shorts_review.review_batch(batch[0], watch_adapter=watch, transcriber=Transcriber())
    request = watch.requests[0]
    prompt = build_watch_prompt(
        checkpoint=request["checkpoint"],
        scope=request["scope"],
        windows=request["windows"],
        context=request["context"],
        transcript_ref=request["transcript_ref"],
    )
    assert "Aqui está o manual colorido." in prompt
    assert '"language_code":"pt"' in prompt
    assert "Demonstrate a manual" in prompt
    assert '"plannedVisualEvents"' in prompt
    assert '"plannedCaptions"' in prompt
    assert '"plannedSfxEvents"' in prompt
    assert '"criticalFailure":{"type":"boolean"}' in prompt
    assert '"notes":{"type":"string"}' in prompt
    assert request["policy"]["effective"]["maxOutputTokens"] == 1536
    assert "neutral score 3" not in prompt


def test_candidate_transcript_content_requires_candidate_hash(tmp_path):
    path = tmp_path / "wrong.json"
    path.write_text(
        json.dumps({"text": "Português", "sourceSha256": "0" * 64}), encoding="utf-8"
    )
    with pytest.raises(ValueError, match="not bound"):
        shorts_review._candidate_transcript(
            {"transcriptPath": str(path), "sourceSha256": "a" * 64}, "a" * 64
        )


@pytest.mark.parametrize("vision,physical", [("fail", "passed"), ("pass", "failed")])
def test_model_pass_cannot_override_physical_qc(batch, monkeypatch, vision, physical):
    monkeypatch.setattr(
        shorts_review.shorts_qc,
        "qc_proof_artifact",
        lambda *a, **k: {"status": physical, "findings": []},
    )
    result = shorts_review.review_batch(
        batch[0], watch_adapter=Watch(vision), transcriber=Transcriber()
    )
    assert result["failed"] == ["01"]
    status = shorts_review._read(batch[0].parent / "shorts.status.json")
    assert status["batchState"] == "proof-partial"


def test_needs_human_vision_can_pass_automation_when_scorecard_and_qc_pass(
    batch, monkeypatch
):
    monkeypatch.setattr(
        shorts_review.shorts_qc,
        "qc_proof_artifact",
        lambda *a, **k: {"status": "passed", "findings": []},
    )
    result = shorts_review.review_batch(
        batch[0], watch_adapter=Watch("needs-human-judgment"), transcriber=Transcriber()
    )
    assert result["passed"] == ["01"]


def test_changed_proof_cannot_freeze_review(batch, monkeypatch):
    monkeypatch.setattr(
        shorts_review.shorts_qc,
        "qc_proof_artifact",
        lambda *a, **k: {"status": "passed"},
    )
    with pytest.raises(ValueError, match="dependency hash mismatch"):
        shorts_review.review_batch(
            batch[0], watch_adapter=Watch(mutate=True), transcriber=Transcriber()
        )


def test_dirty_proof_is_rejected_before_asr(batch):
    path, _proof, status = batch
    status["items"][0]["dirty"] = True
    shorts_contract.atomic_write_json(path.parent / "shorts.status.json", status)
    with pytest.raises(ValueError, match="dirty or noncurrent"):
        shorts_review.review_batch(
            path, watch_adapter=Watch(), transcriber=Transcriber()
        )


def test_stale_plan_hash_is_rejected(batch):
    path, _proof, status = batch
    status["planHash"] = "0" * 64
    shorts_contract.atomic_write_json(path.parent / "shorts.status.json", status)
    with pytest.raises(ValueError, match="plan hash"):
        shorts_review.review_batch(
            path, watch_adapter=Watch(), transcriber=Transcriber()
        )


@pytest.mark.parametrize(
    "model,url",
    [("bonsai", "http://127.0.0.1:1234/v1"), ("qwen3.5-4b", "https://example.com/v1")],
)
def test_review_never_substitutes_model_or_cloud_endpoint(batch, model, url):
    path = batch[0]
    plan = shorts_review._read(path)
    raw = Path(plan["source"]["masterPath"]).parent
    project = {
        "models": {
            "understand": {
                "id": model,
                "source": {
                    "kind": "endpoint",
                    "endpoint": {"baseUrl": url, "servedName": model},
                },
            }
        }
    }
    (raw / "avo.project.json").write_text(json.dumps(project))
    with pytest.raises(ValueError, match="project-pinned local Qwen"):
        shorts_review.review_batch(
            path, watch_adapter=Watch(), transcriber=Transcriber()
        )


def test_windows_cover_all_events_and_joins_with_bounded_count():
    item = {
        "editedDurationSec": 60,
        "sourceSegments": [{}, {"outputStartSec": 30}],
        "callouts": [
            {"id": str(i), "startSec": i * 2, "endSec": i * 2 + 0.5} for i in range(29)
        ],
    }
    windows = shorts_review.review_windows(item)
    assert len(windows) <= 20
    assert windows[0]["start"] == 0
    assert windows[-1]["end"] == 60
    assert any(w["start"] <= 30 <= w["end"] for w in windows)
    for event in item["callouts"]:
        assert any(w["start"] <= event["startSec"] <= w["end"] for w in windows)
