"""Executable AI-first review orchestration over candidate-bound ports."""

from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from math import isfinite
from pathlib import Path
from typing import Any

from .contracts import content_hash, dependency_lock_hash, file_fingerprint
from .ports import ToolError
from .review import (
    EVIDENCE_PROFILES,
    aggregate_watch_passes,
    candidate_identity,
    classify_findings,
    evaluate_gate,
    review_contract_hash,
    write_review_package,
)

_DETERMINISTIC_REVIEW_KINDS = {
    "sequentialDecode",
    "movement",
    "transcript",
    "waveform",
    "flash",
    "pacing",
}


def _merged_ranges(ranges: list[dict[str, Any]]) -> list[dict[str, float]]:
    ordered = sorted(
        (
            (float(item["start"]), float(item["end"]))
            for item in ranges
            if float(item["end"]) > float(item["start"])
        ),
        key=lambda item: item[0],
    )
    merged: list[list[float]] = []
    for start, end in ordered:
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return [{"start": start, "end": end} for start, end in merged]


def _range_seconds(ranges: list[dict[str, Any]]) -> float:
    return sum(item["end"] - item["start"] for item in _merged_ranges(ranges))


def _ranges_in_seconds(
    ranges: list[dict[str, Any]], frame_rate: dict[str, Any]
) -> list[dict[str, float]]:
    num = float(frame_rate.get("num") or 0)
    den = float(frame_rate.get("den") or 0)
    fps = num / den if num > 0 and den > 0 else 0
    normalized: list[dict[str, float]] = []
    for item in ranges:
        if "start" in item and "end" in item:
            normalized.append(
                {"start": float(item["start"]), "end": float(item["end"])}
            )
        elif fps and "startFrame" in item and "endFrameExclusive" in item:
            normalized.append(
                {
                    "start": float(item["startFrame"]) / fps,
                    "end": float(item["endFrameExclusive"]) / fps,
                }
            )
    return normalized


def actual_coverage(
    coverage: dict[str, Any], *, required_windows: list[dict[str, Any]]
) -> dict[str, Any]:
    """Compute coverage only from observed/decoded evidence, never nominal scope."""
    normalized = deepcopy(coverage)
    inspected = list(coverage.get("inspectedRanges") or coverage.get("windows") or [])
    partial = list(coverage.get("partiallyInspectedRanges") or [])
    deterministic = list(coverage.get("deterministicallyCheckedRanges") or [])
    duration = float(coverage.get("durationSeconds") or coverage.get("duration") or 0)
    frame_rate = coverage.get("frameRate") or {}
    inspected = _ranges_in_seconds(inspected, frame_rate)
    partial = _ranges_in_seconds(partial, frame_rate)
    deterministic = _ranges_in_seconds(deterministic, frame_rate)
    reviewed_ranges = _merged_ranges([*inspected, *partial])
    checked_ranges = _merged_ranges(deterministic)
    known_ranges = _merged_ranges([*reviewed_ranges, *checked_ranges])
    uninspected: list[dict[str, float]] = []
    cursor = 0.0
    for item in known_ranges:
        if item["start"] > cursor:
            uninspected.append({"start": cursor, "end": item["start"]})
        cursor = max(cursor, item["end"])
    if duration > cursor:
        uninspected.append({"start": cursor, "end": duration})
    observed_windows = coverage.get("observedWindows") or coverage.get("windows") or []
    normalized.update(
        {
            "durationSeconds": duration,
            "reviewedSeconds": _range_seconds(reviewed_ranges),
            "deterministicallyCheckedSeconds": _range_seconds(checked_ranges),
            "requiredWindows": len(required_windows),
            "reviewedWindows": len(observed_windows),
            "inspectedRanges": reviewed_ranges,
            "deterministicallyCheckedRanges": checked_ranges,
            "uninspectedRanges": uninspected,
        }
    )
    return normalized


def fuse_review_evidence(
    *,
    watch_findings: list[dict[str, Any]],
    deterministic: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Fuse visual observations with six deterministic evidence families."""
    missing = sorted(_DETERMINISTIC_REVIEW_KINDS - deterministic.keys())
    if missing:
        return {
            "status": "blocked",
            "findings": deepcopy(watch_findings),
            "humanReviewWindows": [],
            "missingEvidence": missing,
        }
    findings = deepcopy(watch_findings)
    windows: list[dict[str, Any]] = []
    statuses = {str(item.get("status") or "blocked") for item in deterministic.values()}
    for kind, result in deterministic.items():
        for finding in result.get("findings") or []:
            findings.append({**deepcopy(finding), "evidenceKind": kind})
        windows.extend(deepcopy(result.get("listeningWindows") or []))
    movement_passed = deterministic["movement"].get("status") == "pass"
    for finding in watch_findings:
        if (
            finding.get("category") == "movement"
            and finding.get("status") == "corroborated"
            and movement_passed
        ):
            frame_range = finding.get("programRange")
            if frame_range:
                windows.append(deepcopy(frame_range))
            statuses.add("needs-human-judgment")
    if "blocked" in statuses:
        status = "blocked"
    elif "fail" in statuses:
        status = "fail"
    elif "needs-human-judgment" in statuses:
        status = "needs-human-judgment"
    else:
        status = "pass"
    unique_windows = []
    for window in windows:
        if window not in unique_windows:
            unique_windows.append(window)
    return {
        "status": status,
        "findings": findings,
        "humanReviewWindows": unique_windows,
        "missingEvidence": [],
    }


def select_microproof_windows(proof_plan: dict[str, Any]) -> list[dict[str, Any]]:
    """Select deterministic changed-operation and historical-risk windows."""
    selected: dict[tuple[int, int], dict[str, Any]] = {}

    def add(
        window: dict[str, Any], *, reason: str, operation_id: str | None = None
    ) -> None:
        start = int(window["startFrame"])
        end = int(window["endFrameExclusive"])
        if start < 0 or end <= start:
            raise ValueError("microproof window must be a positive half-open range")
        key = (start, end)
        item = selected.setdefault(
            key,
            {
                "startFrame": start,
                "endFrameExclusive": end,
                "reasons": [],
                "operationIds": [],
            },
        )
        if reason not in item["reasons"]:
            item["reasons"].append(reason)
        if operation_id and operation_id not in item["operationIds"]:
            item["operationIds"].append(operation_id)

    for window in (proof_plan.get("validationPlan") or {}).get("microproof") or []:
        add(window, reason="declared-microproof")
    for window in (proof_plan.get("regressionContract") or {}).get(
        "historicalRiskWindows"
    ) or []:
        add(window, reason="historical-risk")
    seen_kinds: set[str] = set()
    for operation in (proof_plan.get("videoGraph") or {}).get("operations") or []:
        kind = str(operation.get("kind") or "")
        if kind in seen_kinds:
            continue
        seen_kinds.add(kind)
        add(
            operation["outputRange"],
            reason=f"changed-operation:{kind}",
            operation_id=str(operation["operationId"]),
        )
    return [selected[key] for key in sorted(selected)]


def _review_windows(
    risk_windows: list[dict[str, Any]], qc: dict[str, Any]
) -> list[dict[str, Any]]:
    windows = list(risk_windows)
    for window in qc.get("requiredWindows") or []:
        if window not in windows:
            windows.append(window)
    return windows


def _watch_policy_values(
    policy: Any | None,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    if policy is None:
        return None, {}
    return policy.payload(), dict(getattr(policy, "context", {}))


def _understand_model_pin(workspace: Any | None) -> dict[str, Any]:
    project = getattr(workspace, "project", None)
    if not isinstance(project, dict):
        return {}
    models = project.get("models")
    if not isinstance(models, dict):
        return {}
    pin = models.get("understand")
    return dict(pin) if isinstance(pin, dict) else {}


def _validate_watch_coverage(
    coverage: dict[str, Any], required_windows: list[dict[str, Any]]
) -> None:
    if coverage.get("mode") not in {"full", "whole"}:
        raise ToolError(
            "WATCH_SCOPE_INSUFFICIENT",
            "full Watch evidence required",
            False,
            "rerun full Watch",
        )
    reviewed_windows = coverage.get("observedWindows") or coverage.get("windows") or []
    if required_windows and len(reviewed_windows) < len(required_windows):
        raise ToolError(
            "WATCH_SCOPE_INSUFFICIENT",
            "Watch did not cover every required join/changed/privacy/risk window",
            False,
            "rerun Watch with all required windows",
        )


def _materialization_dependencies(
    materialization: dict[str, Any] | None,
) -> dict[str, str]:
    if materialization is None:
        return {}
    fields = {
        "materializationHash": "materialization",
        "deliveryFidelityPolicyHash": "delivery-fidelity-policy",
        "pictureLineageHash": "picture-lineage",
    }
    return {
        dependency: str(materialization[field])
        for field, dependency in fields.items()
        if materialization.get(field)
    }


def _active_revision_hashes(
    workspace: Any | None, materialization: dict[str, Any] | None
) -> dict[str, str] | None:
    if materialization is None or workspace is None:
        return None
    if not hasattr(workspace, "active_dependency_snapshot"):
        return None
    active = workspace.active_dependency_snapshot()
    return {
        "cmapRevisionHash": str(active.get("cmap") or ""),
        "syncRevisionHash": str(active.get("sync-map") or ""),
        "bmapRevisionHash": str(active.get("bmap") or ""),
        "tracksRevisionHash": str(active.get("tracks") or ""),
    }


def _normalized_watch_status(watch: dict[str, Any]) -> str:
    status = str(watch.get("status") or "pass")
    if status == "needs-human-judgment":
        return "fail"
    if status == "blocked":
        return "error"
    return status


def _watch_extra(watch: dict[str, Any]) -> dict[str, Any]:
    fields = (
        "outcomeKind",
        "policy",
        "reviewContext",
        "promptSha256",
        "attempts",
        "visionCoverageManifest",
        "disposition",
    )
    return {key: watch[key] for key in fields if key in watch}


def _automated_review_status(evidence: list[dict[str, Any]]) -> str | None:
    watch = next((item for item in evidence if item.get("kind") == "watch"), None)
    if watch is None:
        return None
    manifest = watch.get("visionCoverageManifest") or {}
    return str(manifest.get("aggregateStatus") or "blocked")


def _resolved_review_state(
    evidence: list[dict[str, Any]], findings: list[dict[str, Any]]
) -> str:
    automated = _automated_review_status(evidence)
    if automated in {"fail", "blocked", "needs-human-judgment"}:
        return automated
    return classify_findings(findings)


def _resolved_review_contract_hash(
    watch: dict[str, Any], computed_contract_hash: str
) -> str:
    contract_hash = str(watch.get("reviewContractHash") or computed_contract_hash)
    valid = len(contract_hash) == 64 and all(
        character in "0123456789abcdef" for character in contract_hash
    )
    if not valid:
        raise ToolError(
            "WATCH_CONTRACT_INVALID",
            "native review returned an invalid review contract hash",
            False,
            "rerun native structured review for the exact candidate",
        )
    return contract_hash


def _bind_manifest_contract(extra: dict[str, Any], contract_hash: str) -> None:
    manifest = extra.get("visionCoverageManifest")
    if isinstance(manifest, dict):
        extra["visionCoverageManifest"] = {
            **manifest,
            "reviewContractHash": contract_hash,
        }


def _normalized_words(transcript: dict[str, Any]) -> list[str]:
    return [
        str(item.get("word") or item.get("text") or "").strip().casefold()
        for item in transcript.get("words") or []
        if str(item.get("word") or item.get("text") or "").strip()
    ]


def _valid_word_clock(first, last):
    return (
        all(
            not isinstance(value, bool)
            and isinstance(value, (int, float))
            and isfinite(value)
            for value in (first, last)
        )
        and 0 <= first < last
    )


def _local_candidate_words(
    transcript: dict[str, Any], candidate_range: Any
) -> list[str] | None:
    """Return words in the exact mapped occurrence; invalid clocks are unknown."""
    if not isinstance(candidate_range, dict):
        return None
    start, end = candidate_range.get("start"), candidate_range.get("end")
    if not _valid_word_clock(start, end):
        return None
    local = []
    for word in transcript.get("words") or []:
        first, last = word.get("start"), word.get("end")
        if not _valid_word_clock(first, last):
            return None
        if first < end and last > start:
            local.append(word)
    return _normalized_words({"words": local})


def _contains_local_phrase(words: list[str], expected: str) -> bool:
    punctuation = ".,!?;:\"'()[]"
    tokens = [word.strip(punctuation) for word in words]
    phrase = [word.strip(punctuation) for word in expected.split()]
    return bool(phrase) and any(
        tokens[index : index + len(phrase)] == phrase
        for index in range(len(tokens) - len(phrase) + 1)
    )


def _boundary_word_match(
    boundary, transcript, candidate_words, candidate_text, expected
):
    if "candidateRange" not in boundary:
        return candidate_words, False, expected in candidate_text
    words = _local_candidate_words(transcript, boundary["candidateRange"])
    return words, words is None, _contains_local_phrase(words or [], expected)


def _boundary_regression(kind, expected, phrase_present, local_unknown, check):
    missing = not local_unknown and kind == "phrase" and expected and not phrase_present
    return missing or check.get("complete") is False


def _boundary_needs_listening(local_unknown, confidence, check):
    return local_unknown or confidence < 0.5 or check.get("complete") is None


def compare_protected_boundaries(
    source_transcript: dict[str, Any],
    candidate_transcript: dict[str, Any],
    *,
    protected_boundaries: list[dict[str, Any]],
    acoustic_checks: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Fuse exact-candidate words with local acoustic boundary evidence."""
    source_words = _normalized_words(source_transcript)
    candidate_words = _normalized_words(candidate_transcript)
    candidate_text = " ".join(candidate_words)
    findings: list[dict[str, Any]] = []
    for boundary in protected_boundaries:
        boundary_id = str(boundary.get("boundaryId") or "")
        check = acoustic_checks.get(boundary_id) or {}
        confidence = float(check.get("confidence") or 0)
        kind = str(boundary.get("kind") or "phrase")
        expected = str(boundary.get("text") or "").strip().casefold()
        boundary_words, local_unknown, phrase_present = _boundary_word_match(
            boundary, candidate_transcript, candidate_words, candidate_text, expected
        )
        if _boundary_regression(kind, expected, phrase_present, local_unknown, check):
            findings.append(
                {
                    "code": "protected-speech-regression",
                    "classification": "meaning",
                    "boundaryId": boundary_id,
                    "expected": expected,
                    "sourceWords": source_words,
                    "candidateWords": boundary_words or [],
                    "confidence": confidence,
                    "range": {
                        "start": boundary.get("start"),
                        "end": boundary.get("end"),
                    },
                }
            )
        elif _boundary_needs_listening(local_unknown, confidence, check):
            findings.append(
                {
                    "code": "acoustic-boundary-needs-human",
                    "classification": "ambiguous-rebase",
                    "boundaryId": boundary_id,
                    "confidence": confidence,
                    "listeningWindow": {
                        "start": boundary.get("start"),
                        "end": boundary.get("end"),
                    },
                }
            )
    if any(item["code"] == "protected-speech-regression" for item in findings):
        status = "fail"
    elif findings:
        status = "needs-human-judgment"
    else:
        status = "pass"
    return {
        "status": status,
        "findings": findings,
        "checkedBoundaryIds": [
            str(item.get("boundaryId")) for item in protected_boundaries
        ],
    }


def verify_exact_export_events(
    events: list[dict[str, Any]],
    *,
    transient_result: dict[str, Any],
    movement_results: list[dict[str, Any]],
) -> dict[str, Any]:
    """Fuse exported waveform and movement checks without upgrading ambiguity."""
    del events  # identities already bind the supplied result records
    findings = [*(transient_result.get("findings") or [])]
    for result in movement_results:
        if result.get("status") != "pass":
            findings.append(
                {
                    "code": "moving-media-" + str(result.get("status")),
                    "layerId": result.get("layerId"),
                    "confidence": result.get("confidence"),
                    "variationCount": result.get("variationCount"),
                }
            )
    statuses = {
        str(transient_result.get("status")),
        *(str(item.get("status")) for item in movement_results),
    }
    if "fail" in statuses:
        status = "fail"
    elif "needs-human-judgment" in statuses:
        status = "needs-human-judgment"
    else:
        status = "pass"
    return {
        "status": status,
        "findings": findings,
        "listeningWindows": deepcopy(transient_result.get("listeningWindows") or []),
        "transientMatches": deepcopy(transient_result.get("matches") or {}),
    }


class ReviewRunner:
    def __init__(
        self,
        *,
        review_root: Path,
        transcription: Any,
        watch: Any,
        deterministic_qc: Any,
        fix_executor: Any | None = None,
        workspace: Any | None = None,
        clock: Callable[[], str],
        max_tool_attempts: int = 3,
        max_fix_attempts: int = 3,
        watch_policy: Any | None = None,
    ):
        self.review_root = Path(review_root)
        self.transcription = transcription
        self.watch = watch
        self.deterministic_qc = deterministic_qc
        self.fix_executor = fix_executor
        self.workspace = workspace
        self.clock = clock
        self.watch_policy = watch_policy
        self.max_tool_attempts = int(
            getattr(watch_policy, "tool_attempts", max_tool_attempts)
        )
        self.max_fix_attempts = max_fix_attempts

    def _call(
        self,
        producer: str,
        operation: Callable[[], dict[str, Any]],
        attempts: list[dict[str, Any]],
    ) -> dict[str, Any]:
        for number in range(1, self.max_tool_attempts + 1):
            try:
                result = operation()
                attempts.append(
                    {
                        "producer": producer,
                        "attempt": number,
                        "status": "pass",
                        "runAt": self.clock(),
                    }
                )
                return result
            except ToolError as error:
                attempts.append(
                    {
                        "producer": producer,
                        "attempt": number,
                        "status": "error",
                        "runAt": self.clock(),
                        "error": error.to_dict(),
                    }
                )
                if not error.retryable or number == self.max_tool_attempts:
                    raise
        raise AssertionError("unreachable")

    @staticmethod
    def _artifact_refs(paths: list[str]) -> list[dict[str, str]]:
        result = []
        for value in paths:
            path = Path(value)
            if path.is_file():
                fingerprint = file_fingerprint(path)
                result.append({"path": str(path), "sha256": fingerprint["sha256"]})
        return result

    def _evidence(
        self,
        *,
        kind: str,
        status: str,
        tool_name: str,
        tool_version: str,
        model: str | None,
        identity: dict[str, Any],
        lock_hash: str,
        scope_mode: str,
        windows: list[dict[str, Any]],
        coverage: dict[str, Any],
        findings: list[dict[str, Any]],
        artifacts: list[dict[str, str]] | None = None,
        attempt: int = 1,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        normalized_coverage = actual_coverage(coverage, required_windows=windows)
        return {
            "evidenceId": f"{kind}-{identity['sha256'][:12]}-{attempt:02d}",
            "kind": kind,
            "tool": {
                "name": tool_name,
                "version": tool_version or "unknown",
                "model": model,
            },
            "runAt": self.clock(),
            "candidateHash": identity["sha256"],
            "candidateIdentityHash": identity["identityHash"],
            "dependencyLockSha256": lock_hash,
            "dependencyHashes": identity["dependencies"],
            "dependencyProfile": EVIDENCE_PROFILES.get(kind, "exact-candidate"),
            "scope": {
                "mode": scope_mode,
                "windows": windows,
                "rationale": f"{kind} required by checkpoint",
            },
            "coverage": normalized_coverage,
            "status": status,
            "findings": findings,
            "artifacts": artifacts or [],
            "attempt": attempt,
            **(extra or {}),
        }

    def _qc_evidence(
        self,
        qc: dict[str, Any],
        identity: dict[str, Any],
        lock_hash: str,
        windows: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        evidence = []
        for item in qc.get("evidence") or []:
            extra = {}
            if "disposition" in item:
                extra["disposition"] = item["disposition"]
            if "details" in item:
                extra["fidelityDetails"] = item["details"]
            evidence.append(
                self._evidence(
                    kind=item["kind"],
                    status=item.get("status") or "pass",
                    tool_name=qc.get("tool") or "deterministic-qc",
                    tool_version=qc.get("toolVersion") or "unknown",
                    model=None,
                    identity=identity,
                    lock_hash=lock_hash,
                    scope_mode="full",
                    windows=windows,
                    coverage={**(qc.get("coverage") or {}), "windows": windows},
                    findings=item.get("findings") or [],
                    extra=extra,
                )
            )
        return evidence

    def _transcript_evidence(
        self,
        transcript: dict[str, Any],
        qc: dict[str, Any],
        identity: dict[str, Any],
        lock_hash: str,
        windows: list[dict[str, Any]],
    ) -> dict[str, Any]:
        transcript_path = transcript.get("transcriptPath")
        return self._evidence(
            kind="transcript-analysis",
            status=transcript.get("status") or "pass",
            tool_name=transcript.get("engine") or "transcription",
            tool_version=transcript.get("engineVersion") or "unknown",
            model=transcript.get("model"),
            identity=identity,
            lock_hash=lock_hash,
            scope_mode="full",
            windows=windows,
            coverage={"durationSeconds": qc.get("duration") or 0, "windows": windows},
            findings=transcript.get("findings") or [],
            artifacts=self._artifact_refs([transcript_path] if transcript_path else []),
        )

    def _watch_evidence(
        self,
        watch: dict[str, Any],
        qc: dict[str, Any],
        identity: dict[str, Any],
        lock_hash: str,
        windows: list[dict[str, Any]],
        transcript: dict[str, Any],
        terms: list[str],
        names: list[str],
    ) -> dict[str, Any]:
        coverage = watch.get("coverage") or {}
        _validate_watch_coverage(coverage, windows)
        findings = list(watch.get("findings") or [])
        status = str(watch.get("status") or "pass")
        contradictions: list[dict[str, Any]] = []
        if watch.get("passResults"):
            aggregate = aggregate_watch_passes(
                list(watch["passResults"]),
                required_pass_ids=list(
                    watch.get("requiredPassIds")
                    or [item["passId"] for item in watch["passResults"]]
                ),
            )
            findings = aggregate["findings"]
            status = aggregate["status"]
            contradictions = aggregate["contradictions"]
        deterministic = watch.get("deterministicEvidence") or qc.get(
            "deterministicEvidence"
        )
        fusion: dict[str, Any] | None = None
        if isinstance(deterministic, dict):
            fusion = fuse_review_evidence(
                watch_findings=findings,
                deterministic=deterministic,
            )
            findings = fusion["findings"]
            precedence = {
                "pass": 0,
                "needs-human-judgment": 1,
                "fail": 2,
                "blocked": 3,
            }
            status = max(
                (status, fusion["status"]),
                key=lambda value: precedence.get(value, 3),
            )
        computed_contract_hash = review_contract_hash(
            candidateHash=identity["sha256"],
            dependencyHashes=identity["dependencies"],
            policyHash=str(
                (watch.get("policy") or {}).get("policyHash") or "unconfigured"
            ),
            coveragePlanHash=str(
                watch.get("coveragePlanHash") or content_hash(coverage)
            ),
            requiredWindowHash=content_hash(windows),
            modelCapabilityHash=str(
                watch.get("capabilityIdentityHash")
                or content_hash({"model": watch.get("model")})
            ),
            promptHash=str(watch.get("promptSha256") or content_hash("unavailable")),
            transcriptHash=content_hash(transcript),
            termsHash=content_hash({"terms": terms, "names": names}),
            adapterToolHash=content_hash(
                {
                    "tool": watch.get("tool") or "watch",
                    "version": watch.get("toolVersion") or "unknown",
                }
            ),
            estimatorHash=str(
                watch.get("estimatorHash") or content_hash({"estimator": "unavailable"})
            ),
        )
        contract_hash = _resolved_review_contract_hash(watch, computed_contract_hash)
        extra = _watch_extra(watch)
        _bind_manifest_contract(extra, contract_hash)
        policy = dict(extra.get("policy") or {})
        policy["reviewContractHash"] = contract_hash
        extra["policy"] = policy
        if contradictions:
            context = dict(extra.get("reviewContext") or {})
            context["contradictions"] = contradictions
            extra["reviewContext"] = context
        if fusion is not None:
            context = dict(extra.get("reviewContext") or {})
            context["humanReviewWindows"] = fusion["humanReviewWindows"]
            context["missingDeterministicEvidence"] = fusion["missingEvidence"]
            extra["reviewContext"] = context
        normalized_watch = {**watch, "status": status}
        return self._evidence(
            kind="watch",
            status=_normalized_watch_status(normalized_watch),
            tool_name=watch.get("tool") or "watch",
            tool_version=watch.get("toolVersion") or "unknown",
            model=watch.get("model"),
            identity=identity,
            lock_hash=lock_hash,
            scope_mode=(
                "full" if coverage.get("mode") in {"full", "whole"} else "windows"
            ),
            windows=windows,
            coverage={**coverage, "durationSeconds": qc.get("duration") or 0},
            findings=findings,
            artifacts=self._artifact_refs(watch.get("artifacts") or []),
            extra=extra,
        )

    def _inspect_once(
        self,
        *,
        checkpoint: str,
        candidate: Path,
        dependencies: dict[str, str],
        render_profile: str,
        risk_windows: list[dict[str, Any]],
        terms: list[str],
        names: list[str],
        attempts: list[dict[str, Any]],
        materialization: dict[str, Any] | None,
        materialization_path: Path | None,
        current_revision_hashes: dict[str, str] | None,
    ) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
        identity = candidate_identity(candidate, dependencies, render_profile)
        lock_hash = dependency_lock_hash(identity["dependencies"])
        qc = self._call(
            "deterministic-qc",
            lambda: self.deterministic_qc.check(
                candidate,
                dependencies=identity["dependencies"],
                risk_windows=risk_windows,
                workspace=self.workspace,
                checkpoint=checkpoint,
                materialization=materialization,
                materialization_path=(
                    str(materialization_path) if materialization_path else None
                ),
                current_revision_hashes=current_revision_hashes,
            ),
            attempts,
        )
        review_windows = _review_windows(risk_windows, qc)
        transcript = self._call(
            "transcription",
            lambda: self.transcription.transcribe(
                candidate,
                risk_windows=review_windows,
                terms=terms,
                names=names,
                edit_dir=self.review_root.parent,
            ),
            attempts,
        )
        protected = qc.get("protectedBoundaries") or []
        if protected:
            boundary_review = compare_protected_boundaries(
                qc.get("sourceTranscript") or {},
                transcript,
                protected_boundaries=protected,
                acoustic_checks=qc.get("acousticBoundaryChecks") or {},
            )
            transcript = dict(transcript)
            transcript["findings"] = [
                *(transcript.get("findings") or []),
                *boundary_review["findings"],
            ]
            if boundary_review["status"] != "pass":
                transcript["status"] = boundary_review["status"]
        policy_payload, policy_context = _watch_policy_values(self.watch_policy)
        model_pin = _understand_model_pin(self.workspace)
        watch = self._call(
            "watch",
            lambda: self.watch.review(
                candidate,
                checkpoint=checkpoint,
                scope="full",
                windows=review_windows,
                transcript_ref=transcript.get("transcriptPath") or None,
                terms=terms,
                names=names,
                policy=policy_payload,
                context=policy_context,
                option_id=model_pin.get("id") or None,
                model_pin=model_pin or None,
                contract_context={
                    "candidateIdentityHash": identity["identityHash"],
                    "dependencies": identity["dependencies"],
                },
                root=getattr(self.watch_policy, "working_directory", None),
                artifact_dir=self.review_root
                / checkpoint
                / identity["sha256"][:12]
                / "watch",
            ),
            attempts,
        )
        evidence = self._qc_evidence(qc, identity, lock_hash, review_windows)
        evidence.append(
            self._transcript_evidence(
                transcript, qc, identity, lock_hash, review_windows
            )
        )
        evidence.append(
            self._watch_evidence(
                watch,
                qc,
                identity,
                lock_hash,
                review_windows,
                transcript,
                terms,
                names,
            )
        )
        findings = [
            finding for item in evidence for finding in item.get("findings") or []
        ]
        findings.extend(qc.get("findings") or [])
        return identity, evidence, findings

    def _change_summary(
        self,
        identity: dict[str, Any],
        evidence: list[dict[str, Any]],
    ) -> dict[str, Any]:
        windows: list[dict[str, Any]] = []
        for item in evidence:
            for window in (item.get("scope") or {}).get("windows") or []:
                normalized = {
                    "start": float(window["start"]),
                    "end": float(window["end"]),
                    "reason": str(window["reason"]),
                }
                if normalized not in windows:
                    windows.append(normalized)
        if self.workspace is not None and hasattr(
            self.workspace, "review_change_summary"
        ):
            return self.workspace.review_change_summary(
                identity["dependencies"],
                windows=windows,
            )
        keys = sorted(identity["dependencies"])
        return {
            "headline": f"Candidate materialized from {len(keys)} exact dependency revisions",
            "items": [
                {
                    "artifactType": "candidate",
                    "revisionId": "dependency-lock",
                    "reason": "materialized from the exact declared dependency snapshot",
                    "operationCounts": {"materialize": 1},
                    "targets": keys[:6],
                    "truncatedTargets": max(0, len(keys) - 6),
                }
            ],
            "windows": windows,
            "staleDependencies": [],
        }

    def _write(
        self,
        *,
        checkpoint: str,
        identity: dict[str, Any],
        evidence: list[dict[str, Any]],
        attempts: list[dict[str, Any]],
        state: str,
        findings: list[dict[str, Any]],
        blocker: str | None = None,
    ) -> dict[str, Any]:
        manifest = {
            "schemaVersion": "1.0.0",
            "checkpoint": checkpoint,
            "candidate": identity,
            "dependencyLockSha256": dependency_lock_hash(identity["dependencies"]),
            "changeSummary": self._change_summary(identity, evidence),
            "state": state,
            "evidence": evidence
            or [
                self._evidence(
                    kind="review-runtime",
                    status="error",
                    tool_name="avo-review",
                    tool_version="1.0.0",
                    model=None,
                    identity=identity,
                    lock_hash=dependency_lock_hash(identity["dependencies"]),
                    scope_mode="full",
                    windows=[],
                    coverage={},
                    findings=[
                        {
                            "classification": "tool-error",
                            "message": blocker or "review failed",
                        }
                    ],
                )
            ],
            "attempts": attempts,
            "unresolvedRisks": findings if state == "needs-human-judgment" else [],
            "approval": None,
        }
        if blocker:
            manifest["blocker"] = blocker
        directory = self.review_root / checkpoint / identity["sha256"][:12]
        review_path, gate_path = write_review_package(directory, manifest)
        return {**manifest, "reviewPath": review_path, "approvalGatePath": gate_path}

    def _blocked(
        self,
        *,
        checkpoint: str,
        identity: dict[str, Any],
        evidence: list[dict[str, Any]],
        attempts: list[dict[str, Any]],
        findings: list[dict[str, Any]],
        blocker: str,
    ) -> dict[str, Any]:
        return self._write(
            checkpoint=checkpoint,
            identity=identity,
            evidence=evidence,
            attempts=attempts,
            state="blocked",
            findings=findings,
            blocker=blocker,
        )

    def _terminal_result(
        self,
        *,
        checkpoint: str,
        state: str,
        identity: dict[str, Any],
        evidence: list[dict[str, Any]],
        attempts: list[dict[str, Any]],
        findings: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        if state in {"needs-human-judgment", "fail"}:
            return self._write(
                checkpoint=checkpoint,
                identity=identity,
                evidence=evidence,
                attempts=attempts,
                state=state,
                findings=findings,
            )
        if state != "ai-passed":
            return None
        try:
            evaluate_gate(
                checkpoint,
                identity["sha256"],
                identity["dependencies"],
                evidence,
                candidate_identity_hash=identity["identityHash"],
                dependency_lock_sha256=dependency_lock_hash(identity["dependencies"]),
            )
        except Exception as error:
            return self._blocked(
                checkpoint=checkpoint,
                identity=identity,
                evidence=evidence,
                attempts=attempts,
                findings=findings,
                blocker=str(error),
            )
        return self._write(
            checkpoint=checkpoint,
            identity=identity,
            evidence=evidence,
            attempts=attempts,
            state="ai-passed",
            findings=findings,
        )

    def _advance_safe_fix(
        self,
        *,
        checkpoint: str,
        fix_number: int,
        candidate: Path,
        dependencies: dict[str, str],
        render_profile: str,
        identity: dict[str, Any],
        evidence: list[dict[str, Any]],
        attempts: list[dict[str, Any]],
        findings: list[dict[str, Any]],
    ) -> dict[str, Any]:
        blocker = None
        if self.fix_executor is None:
            blocker = "safe findings require an owning-stage fix executor"
        elif fix_number >= self.max_fix_attempts:
            blocker = "maximum safe-fix attempts reached"
        if blocker:
            return {
                "result": self._blocked(
                    checkpoint=checkpoint,
                    identity=identity,
                    evidence=evidence,
                    attempts=attempts,
                    findings=findings,
                    blocker=blocker,
                )
            }
        result = self.fix_executor.apply_fix(
            findings,
            checkpoint=checkpoint,
            candidate=candidate,
            dependencies=dependencies,
        )
        next_candidate = Path(result.get("candidate") or candidate)
        next_dependencies = dict(
            sorted((result.get("dependencies") or dependencies).items())
        )
        next_identity = candidate_identity(
            next_candidate, next_dependencies, render_profile
        )
        attempts.append(
            {
                "producer": "safe-fix",
                "attempt": fix_number + 1,
                "status": "pass",
                "runAt": self.clock(),
                "revisionId": result.get("revisionId"),
                "beforeIdentityHash": identity["identityHash"],
                "afterIdentityHash": next_identity["identityHash"],
            }
        )
        if next_identity["identityHash"] == identity["identityHash"]:
            return {
                "result": self._blocked(
                    checkpoint=checkpoint,
                    identity=identity,
                    evidence=evidence,
                    attempts=attempts,
                    findings=findings,
                    blocker="safe fix produced no candidate or dependency identity change",
                )
            }
        return {
            "candidate": next_candidate,
            "dependencies": next_dependencies,
            "identity": next_identity,
        }

    def run(
        self,
        *,
        checkpoint: str,
        candidate: Path,
        dependencies: dict[str, str],
        render_profile: str,
        risk_windows: list[dict[str, Any]] | None = None,
        terms: list[str] | None = None,
        names: list[str] | None = None,
        materialization: dict[str, Any] | None = None,
        materialization_path: Path | None = None,
    ) -> dict[str, Any]:
        candidate = Path(candidate)
        windows = list(risk_windows or [])
        attempts: list[dict[str, Any]] = []
        current_candidate = candidate
        current_dependencies = dict(dependencies)
        if self.watch_policy is not None:
            current_dependencies["watch-policy"] = str(self.watch_policy.policy_hash)
        current_dependencies.update(_materialization_dependencies(materialization))
        current_revision_hashes = _active_revision_hashes(
            self.workspace, materialization
        )
        current_dependencies = dict(sorted(current_dependencies.items()))
        last_identity = candidate_identity(
            current_candidate, current_dependencies, render_profile
        )
        last_evidence: list[dict[str, Any]] = []
        last_findings: list[dict[str, Any]] = []

        for fix_number in range(self.max_fix_attempts + 1):
            try:
                identity, evidence, findings = self._inspect_once(
                    checkpoint=checkpoint,
                    candidate=current_candidate,
                    dependencies=current_dependencies,
                    render_profile=render_profile,
                    risk_windows=windows,
                    terms=list(terms or []),
                    names=list(names or []),
                    attempts=attempts,
                    materialization=materialization,
                    materialization_path=materialization_path,
                    current_revision_hashes=current_revision_hashes,
                )
            except ToolError as error:
                return self._blocked(
                    checkpoint=checkpoint,
                    identity=last_identity,
                    evidence=last_evidence,
                    attempts=attempts,
                    findings=last_findings,
                    blocker=str(error),
                )
            last_identity, last_evidence, last_findings = identity, evidence, findings
            state = _resolved_review_state(evidence, findings)
            terminal = self._terminal_result(
                checkpoint=checkpoint,
                state=state,
                identity=identity,
                evidence=evidence,
                attempts=attempts,
                findings=findings,
            )
            if terminal is not None:
                return terminal
            advanced = self._advance_safe_fix(
                checkpoint=checkpoint,
                fix_number=fix_number,
                candidate=current_candidate,
                dependencies=current_dependencies,
                render_profile=render_profile,
                identity=identity,
                evidence=evidence,
                attempts=attempts,
                findings=findings,
            )
            if "result" in advanced:
                return advanced["result"]
            current_candidate = advanced["candidate"]
            current_dependencies = advanced["dependencies"]
            last_identity = advanced["identity"]

        raise AssertionError("unreachable")
