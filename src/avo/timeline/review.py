"""Candidate-bound AI review policy and deterministic human-gate projection."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from copy import deepcopy
from pathlib import Path
from typing import Any

from .contracts import (
    content_hash,
    file_fingerprint,
    validate_document,
)
from .store import atomic_write_json


def meaningful_change_summary(changes: list[dict[str, Any]]) -> dict[str, Any]:
    """Separate editorial intent changes from mechanically propagated shifts."""
    primary: list[dict[str, Any]] = []
    downstream: list[dict[str, Any]] = []
    mechanical_kinds = {"downstream-shift", "timing-shift", "reflow"}
    for change in changes:
        value = deepcopy(change)
        is_mechanical = (
            bool(value.get("mechanical")) or value.get("kind") in mechanical_kinds
        )
        (downstream if is_mechanical else primary).append(value)
    return {
        "primarySemanticChanges": primary,
        "mechanicalDownstreamShifts": downstream,
        "primaryCount": len(primary),
        "mechanicalCount": len(downstream),
    }


class GateError(RuntimeError):
    pass


def review_contract_hash(
    *,
    candidateHash: str,
    dependencyHashes: dict[str, str],
    policyHash: str,
    coveragePlanHash: str,
    requiredWindowHash: str,
    modelCapabilityHash: str,
    promptHash: str,
    transcriptHash: str,
    termsHash: str,
    adapterToolHash: str,
    estimatorHash: str,
) -> str:
    """Bind every input that can change a Watch observation or its coverage."""
    return content_hash(
        {
            "candidateHash": candidateHash,
            "dependencyHashes": dict(sorted(dependencyHashes.items())),
            "policyHash": policyHash,
            "coveragePlanHash": coveragePlanHash,
            "requiredWindowHash": requiredWindowHash,
            "modelCapabilityHash": modelCapabilityHash,
            "promptHash": promptHash,
            "transcriptHash": transcriptHash,
            "termsHash": termsHash,
            "adapterToolHash": adapterToolHash,
            "estimatorHash": estimatorHash,
        }
    )


def _finding_range(finding: dict[str, Any]) -> tuple[int, int] | None:
    value = finding.get("programRange")
    if not isinstance(value, dict):
        return None
    if "startFrame" not in value or "endFrameExclusive" not in value:
        return None
    return int(value["startFrame"]), int(value["endFrameExclusive"])


def _ranges_overlap(
    left: tuple[int, int] | None, right: tuple[int, int] | None
) -> bool:
    if left is None or right is None:
        return left == right
    return left[0] < right[1] and right[0] < left[1]


def _finding_semantics(finding: dict[str, Any]) -> tuple[str, ...]:
    return tuple(
        str(finding.get(key) or "").strip().casefold()
        for key in ("category", "observed", "expected", "message")
    )


def normalize_watch_findings(findings: list[dict[str, Any]]) -> dict[str, Any]:
    """Merge semantic duplicates while retaining overlapping contradictions."""
    normalized: list[dict[str, Any]] = []
    contradictions: list[dict[str, Any]] = []
    for source in findings:
        item = deepcopy(source)
        item.setdefault("findingId", f"finding-{content_hash(item)[:16]}")
        duplicate = next(
            (
                existing
                for existing in normalized
                if _finding_semantics(existing) == _finding_semantics(item)
                and _ranges_overlap(_finding_range(existing), _finding_range(item))
            ),
            None,
        )
        if duplicate is not None:
            left, right = _finding_range(duplicate), _finding_range(item)
            if left is not None and right is not None:
                duplicate["programRange"] = {
                    "startFrame": min(left[0], right[0]),
                    "endFrameExclusive": max(left[1], right[1]),
                }
            refs = [*(duplicate.get("evidenceRefs") or [])]
            for reference in item.get("evidenceRefs") or []:
                if reference not in refs:
                    refs.append(reference)
            duplicate["evidenceRefs"] = refs
            aliases = list(duplicate.get("aliases") or [])
            if (
                item["findingId"] != duplicate["findingId"]
                and item["findingId"] not in aliases
            ):
                aliases.append(item["findingId"])
            if aliases:
                duplicate["aliases"] = aliases
            continue
        for existing in normalized:
            if (
                str(existing.get("category")) == str(item.get("category"))
                and _ranges_overlap(_finding_range(existing), _finding_range(item))
                and _finding_semantics(existing) != _finding_semantics(item)
            ):
                contradictions.append(
                    {
                        "findingIds": [existing["findingId"], item["findingId"]],
                        "programRange": deepcopy(
                            item.get("programRange") or existing.get("programRange")
                        ),
                    }
                )
        normalized.append(item)
    normalized.sort(
        key=lambda item: (
            (_finding_range(item) or (2**63, 2**63))[0],
            str(item.get("category") or ""),
            str(item.get("findingId") or ""),
        )
    )
    return {"findings": normalized, "contradictions": contradictions}


def aggregate_watch_passes(
    pass_results: list[dict[str, Any]], *, required_pass_ids: list[str]
) -> dict[str, Any]:
    """Apply pass/finding precedence and emit one compatibility Watch record."""
    by_id = {str(item.get("passId")): item for item in pass_results}
    missing = [pass_id for pass_id in required_pass_ids if pass_id not in by_id]
    normalized = normalize_watch_findings(
        [finding for result in pass_results for finding in result.get("findings") or []]
    )
    statuses = {str(item.get("status") or "blocked") for item in pass_results}
    if missing or "blocked" in statuses:
        status = "blocked"
    elif "fail" in statuses or any(
        item.get("severity") == "blocking" and item.get("status") == "corroborated"
        for item in normalized["findings"]
    ):
        status = "fail"
    elif (
        "needs-human-judgment" in statuses
        or normalized["contradictions"]
        or any(item.get("requiresHuman") for item in normalized["findings"])
    ):
        status = "needs-human-judgment"
    else:
        status = "pass"
    return {
        "kind": "watch",
        "status": status,
        "findings": normalized["findings"],
        "contradictions": normalized["contradictions"],
        "passResults": deepcopy(pass_results),
        "missingPassIds": missing,
    }


def render_human_review_package(package: dict[str, Any]) -> str:
    """Render a structured Watch aggregate without promoting raw model prose."""
    findings = sorted(
        package.get("findings") or [],
        key=lambda item: (
            int((item.get("programRange") or {}).get("startFrame") or 0),
            str(item.get("findingId") or ""),
        ),
    )
    coverage = package.get("coverage") or {}
    lines = [
        "# Vision review package",
        "",
        "## Exact identities",
        "",
        f"- Candidate: `{package.get('candidateSha256', 'unknown')}`",
        f"- Proof plan: `{package.get('proofPlanHash', 'unknown')}`",
        f"- Transcript: `{package.get('transcriptHash', 'unknown')}`",
        f"- Model: `{package.get('modelIdentity', 'unknown')}`",
        f"- Review contract: `{package.get('reviewContractHash', 'unknown')}`",
        "",
        "## Status and blockers",
        "",
        f"- Status: **{package.get('status', 'blocked')}**",
    ]
    for blocker in package.get("blockers") or []:
        lines.append(f"- Blocker: {blocker}")
    lines.extend(
        [
            "",
            "## Truthful coverage",
            "",
            f"- Sampling: {coverage.get('samplingMode', 'unknown')}",
            f"- Requested samples: {coverage.get('requestedSamples', 0)}",
            f"- Observed samples: {coverage.get('observedSamples', 0)}",
            f"- Failed samples: {coverage.get('failedSamples', 0)}",
        ]
    )
    for hole in coverage.get("coverageHoles") or []:
        lines.append(
            f"- Coverage hole `{hole.get('windowId', 'unknown')}`: "
            f"{hole.get('reason', 'uninspected')}"
        )
    for frame_range in coverage.get("uninspectedRanges") or []:
        lines.append(
            "- Uninspected: "
            f"frames {frame_range.get('startFrame')}–"
            f"{frame_range.get('endFrameExclusive')}"
        )
    lines.extend(["", "## Regressions", ""])
    regressions = package.get("regressions") or []
    lines.extend(
        f"- `{item.get('obligationId', 'unknown')}`: {item.get('status', 'unresolved')}"
        for item in regressions
    )
    if not regressions:
        lines.append("- None reported.")
    lines.extend(["", "## Chronological findings by section", ""])
    for finding in findings:
        frame_range = finding.get("programRange") or {}
        lines.append(
            f"- [{finding.get('findingId', 'finding')}] "
            f"{finding.get('sectionId', 'unassigned')} "
            f"frames {frame_range.get('startFrame', '?')}–"
            f"{frame_range.get('endFrameExclusive', '?')}: "
            f"{finding.get('message', finding.get('observed', 'finding'))}"
        )
    if not findings:
        lines.append("- None.")
    lines.extend(["", "## Pacing by section purpose", ""])
    pacing = [item for item in findings if item.get("category") == "pacing"]
    lines.extend(
        f"- [{item.get('findingId')}] {item.get('sectionId', 'unassigned')}: "
        f"{item.get('message', item.get('observed'))}"
        for item in pacing
    )
    if not pacing:
        lines.append("- No pacing finding; deterministic metrics remain in evidence.")
    lines.extend(["", "## Contradictions and human questions", ""])
    for contradiction in package.get("contradictions") or []:
        lines.append(
            "- Contradiction: " + ", ".join(contradiction.get("findingIds") or [])
        )
    for question in package.get("humanQuestions") or []:
        lines.append(f"- Human judgment: {question}")
    if not (package.get("contradictions") or package.get("humanQuestions")):
        lines.append("- None.")
    lines.extend(["", "## Finding-linked actions", ""])
    actions = [item for item in findings if item.get("suggestedAction")]
    lines.extend(
        f"- [{item.get('findingId')}] {item['suggestedAction']}" for item in actions
    )
    if not actions:
        lines.append("- None; do not invent work without an evidence-linked finding.")
    return "\n".join(lines) + "\n"


def audio_editlog_entry(
    audio_graph: dict[str, Any],
    *,
    candidate_sha256: str,
    boundary_review: dict[str, Any],
    actor: str,
) -> dict[str, Any]:
    """Build the durable AUDIO-EDITLOG payload for one exact export."""
    return {
        "graphHash": audio_graph["graphHash"],
        "candidateSha256": candidate_sha256,
        "sampleRate": audio_graph["sampleRate"],
        "durationSamples": audio_graph["durationSamples"],
        "channelMappings": [
            {
                "nodeId": item["nodeId"],
                "channelMap": deepcopy(item.get("channelMap") or []),
            }
            for item in audio_graph.get("nodes") or []
        ],
        "latencyCompensation": [
            {"nodeId": item["nodeId"], "samples": int(item.get("latencySamples") or 0)}
            for item in audio_graph.get("nodes") or []
            if item.get("kind") == "source"
        ],
        "exactExportReview": deepcopy(boundary_review),
        "actor": actor,
    }


def write_audio_editlog_entry(path: Path, entry: dict[str, Any]) -> Path:
    """Append one compact exact-export audit without rewriting prior entries."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = (
        path.read_text(encoding="utf-8") if path.is_file() else "# AUDIO-EDITLOG\n"
    )
    findings = entry.get("exactExportReview", {}).get("findings") or []
    block = [
        "",
        f"## Candidate {entry['candidateSha256'][:12]}",
        "",
        f"- Audio graph: `{entry['graphHash']}`",
        f"- PCM: {entry['sampleRate']} Hz, {entry['durationSamples']} samples",
        f"- Boundary review: {entry['exactExportReview']['status']}",
        f"- Findings: {len(findings)}",
        f"- Actor: {entry['actor']}",
        "",
    ]
    path.write_text(existing.rstrip() + "\n" + "\n".join(block), encoding="utf-8")
    return path


def event_audit_entry(
    *,
    candidate_sha256: str,
    events: list[dict[str, Any]],
    exact_export_review: dict[str, Any],
) -> dict[str, Any]:
    """Persist the resolved event clock and exact-export waveform disposition."""
    matches = exact_export_review.get("transientMatches") or {}
    event_rows = []
    for event in events:
        expected_sample = int(event["resolvedImpactSample"])
        observed_matches = deepcopy(matches.get(str(event["eventId"])) or [])
        for match in observed_matches:
            if match.get("sample") is not None:
                match["offsetSamples"] = int(match["sample"]) - expected_sample
        event_rows.append(
            {
                "eventId": event["eventId"],
                "role": event.get("role"),
                "programFrame": event.get("programFrame"),
                "resolvedImpactSample": expected_sample,
                "scheduledAudioStartSample": event.get("scheduledAudioStartSample"),
                "expectedOccurrences": int(
                    (event.get("validation") or {}).get("expectedOccurrences") or 1
                ),
                "observedMatches": observed_matches,
            }
        )
    return {
        "candidateSha256": candidate_sha256,
        "events": event_rows,
        "exactExportReview": deepcopy(exact_export_review),
        "auditHash": content_hash(
            {
                "candidateSha256": candidate_sha256,
                "events": events,
                "review": exact_export_review,
            }
        ),
    }


def historical_review_requirements(
    ledger: dict[str, Any], regression_contract: dict[str, Any]
) -> dict[str, Any]:
    """Project complete ledger history into exact windows and evidence inputs."""
    if regression_contract.get("ledgerHash") != ledger.get("ledgerHash"):
        raise GateError("regression contract is bound to another iteration ledger")
    evidence: dict[tuple[str, str], dict[str, Any]] = {}
    for decision in ledger.get("decisions") or []:
        for item in decision.get("evidenceRefs") or []:
            key = (str(item.get("evidenceId")), str(item.get("sha256")))
            evidence[key] = deepcopy(item)
    return {
        "ledgerHash": ledger["ledgerHash"],
        "contractHash": regression_contract["contractHash"],
        "requiredWindows": deepcopy(
            regression_contract.get("historicalRiskWindows") or []
        ),
        "sourceEvidenceRefs": [evidence[key] for key in sorted(evidence)],
    }


EVIDENCE_PROFILES = {
    "raw-inventory": "raw-sync",
    "sync": "raw-sync",
    "rights": "source-rights",
    "source-usage": "source-rights",
}

CHECKPOINT_POLICIES = {
    "sync-ready": {
        "version": "1.0.0",
        "required": {"raw-inventory", "sync"},
        "fullWatch": False,
        "allowNotApplicable": {"sync"},
    },
    "cut-proof": {
        "version": "1.0.0",
        "required": {"lineage", "technical-qc", "sync", "transcript-analysis", "watch"},
        "fullWatch": True,
        "allowNotApplicable": set(),
    },
    "motion-proof": {
        "version": "1.0.0",
        "required": {
            "lineage",
            "technical-qc",
            "transcript-analysis",
            "watch",
            "bmap",
            "tracks",
            "animation",
            "visual-qc",
            "audio-qc",
            "rights",
        },
        "fullWatch": True,
        "allowNotApplicable": {"animation"},
    },
    "pre-master": {
        "version": "1.0.0",
        "required": {
            "lineage",
            "technical-qc",
            "transcript-analysis",
            "watch",
            "sync",
            "audio-qc",
            "visual-qc",
            "source-fidelity",
            "accessibility",
            "rights",
        },
        "fullWatch": True,
        "allowNotApplicable": set(),
    },
    "deliver": {
        "version": "1.0.0",
        "required": {
            "lineage",
            "technical-qc",
            "transcript-analysis",
            "watch",
            "audio-qc",
            "visual-qc",
            "source-fidelity",
            "accessibility",
            "rights",
            "final-transcript",
        },
        "fullWatch": True,
        "allowNotApplicable": set(),
    },
}
GATE_REQUIREMENTS = {
    name: set(policy["required"]) for name, policy in CHECKPOINT_POLICIES.items()
}


def candidate_identity(
    path: Path, dependencies: dict[str, str], render_profile: str
) -> dict[str, Any]:
    fingerprint = file_fingerprint(path)
    normalized = dict(sorted(dependencies.items()))
    identity = {
        "sha256": fingerprint["sha256"],
        "byteSize": fingerprint["sizeBytes"],
        "path": str(path),
        "dependencies": normalized,
        "renderProfile": render_profile,
    }
    identity["identityHash"] = content_hash(
        {
            "candidate": identity["sha256"],
            "byteSize": identity["byteSize"],
            "dependencies": normalized,
            "renderProfile": render_profile,
        }
    )
    return identity


def evidence_is_fresh(
    evidence: dict[str, Any],
    candidate_hash: str,
    dependencies: dict[str, str],
    *,
    candidate_identity_hash: str | None = None,
    dependency_lock_sha256: str | None = None,
    review_contract_sha256: str | None = None,
) -> bool:
    profile = str(
        evidence.get("dependencyProfile")
        or EVIDENCE_PROFILES.get(str(evidence.get("kind")), "exact-candidate")
    )
    recorded = evidence.get("dependencyHashes") or {}
    current = dict(sorted(dependencies.items()))
    if profile == "exact-candidate":
        if evidence.get("candidateHash") != candidate_hash:
            return False
        if recorded != current:
            return False
        if (
            candidate_identity_hash is not None
            and evidence.get("candidateIdentityHash") != candidate_identity_hash
        ):
            return False
        if (
            dependency_lock_sha256 is not None
            and evidence.get("dependencyLockSha256") != dependency_lock_sha256
        ):
            return False
        recorded_contract = evidence.get("reviewContractHash") or (
            evidence.get("policy") or {}
        ).get("reviewContractHash")
        if (
            review_contract_sha256 is not None
            and recorded_contract != review_contract_sha256
        ):
            return False
    elif profile == "raw-sync":
        keys = [
            key
            for key in ("raw", "rawInventory", "sync-map", "syncMap")
            if key in recorded
        ]
        if not keys or any(current.get(key) != recorded.get(key) for key in keys):
            return False
    elif profile == "source-rights":
        keys = [
            key
            for key in ("raw", "rawInventory", "sourceUsage", "rightsPolicy")
            if key in recorded
        ]
        if not keys or any(current.get(key) != recorded.get(key) for key in keys):
            return False
    else:
        return False
    return evidence.get("status") not in {"stale", "error"}


def stale_evidence(
    items: list[dict[str, Any]],
    candidate_hash: str,
    dependencies: dict[str, str],
    *,
    candidate_identity_hash: str | None = None,
    dependency_lock_sha256: str | None = None,
) -> list[dict[str, Any]]:
    result = []
    for evidence in items:
        item = deepcopy(evidence)
        if not evidence_is_fresh(
            item,
            candidate_hash,
            dependencies,
            candidate_identity_hash=candidate_identity_hash,
            dependency_lock_sha256=dependency_lock_sha256,
        ):
            item["status"] = "stale"
        result.append(item)
    return result


def evaluate_gate(
    checkpoint: str,
    candidate_hash: str,
    dependencies: dict[str, str],
    evidence: list[dict[str, Any]],
    *,
    candidate_identity_hash: str | None = None,
    dependency_lock_sha256: str | None = None,
) -> str:
    policy = CHECKPOINT_POLICIES.get(checkpoint)
    if policy is None:
        raise GateError(f"unknown checkpoint: {checkpoint}")
    current = [
        item
        for item in evidence
        if evidence_is_fresh(
            item,
            candidate_hash,
            dependencies,
            candidate_identity_hash=candidate_identity_hash,
            dependency_lock_sha256=dependency_lock_sha256,
        )
    ]
    counts = Counter(item.get("kind") for item in current)
    duplicates = sorted(kind for kind, count in counts.items() if count > 1)
    if duplicates:
        raise GateError(
            "human gate blocked; duplicate current evidence: " + ", ".join(duplicates)
        )
    passing = set()
    for item in current:
        kind = item.get("kind")
        coverage = item.get("coverage") or {}
        required_windows = int(coverage.get("requiredWindows") or 0)
        reviewed_windows = int(coverage.get("reviewedWindows") or 0)
        if reviewed_windows < required_windows:
            continue
        if (
            kind == "watch"
            and policy["fullWatch"]
            and (item.get("scope") or {}).get("mode") != "full"
        ):
            continue
        if item.get("status") == "pass":
            passing.add(kind)
        elif (
            item.get("status") == "not-applicable"
            and kind in policy["allowNotApplicable"]
        ):
            waiver = item.get("notApplicable") or {}
            actor = waiver.get("actor") or {}
            if (
                waiver.get("policy")
                and waiver.get("rationale")
                and actor.get("id")
                and waiver.get("basisSha256")
            ):
                passing.add(kind)
    missing = set(policy["required"]) - passing
    if missing:
        raise GateError(
            "human gate blocked; missing current evidence: "
            + ", ".join(sorted(missing))
        )
    return "ai-passed"


def _fresh_evidence(
    evidence: list[dict[str, Any]],
    candidate_hash: str,
    dependencies: dict[str, str],
    *,
    candidate_identity_hash: str | None,
    dependency_lock_sha256: str | None,
) -> list[dict[str, Any]]:
    return [
        item
        for item in evidence
        if evidence_is_fresh(
            item,
            candidate_hash,
            dependencies,
            candidate_identity_hash=candidate_identity_hash,
            dependency_lock_sha256=dependency_lock_sha256,
        )
    ]


def _require_unique_required(
    current: list[dict[str, Any]], policy: dict[str, Any]
) -> None:
    counts = Counter(item.get("kind") for item in current)
    duplicates = sorted(kind for kind, count in counts.items() if count > 1)
    if duplicates:
        raise GateError(
            "human gate blocked; duplicate current evidence: " + ", ".join(duplicates)
        )
    missing = set(policy["required"]) - {item.get("kind") for item in current}
    if missing:
        raise GateError(
            "human gate blocked; missing current evidence: "
            + ", ".join(sorted(missing))
        )


def _require_coverage_complete(
    current: list[dict[str, Any]], policy: dict[str, Any]
) -> None:
    for item in current:
        coverage = item.get("coverage") or {}
        required_windows = int(coverage.get("requiredWindows") or 0)
        reviewed_windows = int(coverage.get("reviewedWindows") or 0)
        if reviewed_windows < required_windows:
            raise GateError(
                "human gate blocked; incomplete coverage for " + str(item.get("kind"))
            )
        if (
            item.get("kind") == "watch"
            and policy["fullWatch"]
            and (item.get("scope") or {}).get("mode") != "full"
        ):
            raise GateError("human gate blocked; full Watch evidence required")


def validate_evidence_integrity(
    checkpoint: str,
    candidate_hash: str,
    dependencies: dict[str, str],
    evidence: list[dict[str, Any]],
    *,
    candidate_identity_hash: str | None = None,
    dependency_lock_sha256: str | None = None,
) -> None:
    """Require fresh, unique, coverage-complete evidence regardless of AI pass/fail."""
    policy = CHECKPOINT_POLICIES.get(checkpoint)
    if policy is None:
        raise GateError(f"unknown checkpoint: {checkpoint}")
    current = _fresh_evidence(
        evidence,
        candidate_hash,
        dependencies,
        candidate_identity_hash=candidate_identity_hash,
        dependency_lock_sha256=dependency_lock_sha256,
    )
    _require_unique_required(current, policy)
    _require_coverage_complete(current, policy)


def approval_is_current(
    approval: dict[str, Any] | None,
    *,
    checkpoint: str,
    candidate_identity_hash: str,
    candidate_sha256: str,
    dependency_lock_sha256: str,
) -> bool:
    if not approval:
        return False
    return (
        approval.get("checkpoint") == checkpoint
        and approval.get("candidateIdentityHash") == candidate_identity_hash
        and approval.get("candidateSha256") == candidate_sha256
        and approval.get("dependencyLockSha256") == dependency_lock_sha256
        and approval.get("decision") == "approved"
    )


def classify_findings(findings: list[dict[str, Any]]) -> str:
    if any(
        finding.get("requiresHuman") is True or finding.get("status") == "needs-human"
        for finding in findings
    ):
        return "needs-human-judgment"
    classes = {str(finding.get("classification")) for finding in findings}
    if classes & {
        "meaning",
        "rights",
        "privacy",
        "policy",
        "safety",
        "factual",
        "ambiguous-rebase",
    }:
        return "needs-human-judgment"
    if classes & {
        "tool-error",
        "missing-watch",
        "missing-transcript",
        "prerequisite",
    }:
        return "blocked"
    return "fixing" if findings else "ai-passed"


def run_fix_loop(
    inspect: Callable[[], list[dict[str, Any]]],
    fix: Callable[[list[dict[str, Any]]], str | None],
    *,
    max_attempts: int = 3,
) -> dict[str, Any]:
    attempts = []
    previous = None
    for number in range(1, max_attempts + 1):
        findings = inspect()
        state = classify_findings(findings)
        if state in {"ai-passed", "needs-human-judgment", "blocked"}:
            return {"state": state, "attempts": attempts, "findings": findings}
        signature = content_hash(findings)
        if signature == previous:
            return {
                "state": "blocked",
                "attempts": attempts,
                "findings": findings,
                "blocker": "no candidate diff/convergence",
            }
        previous = signature
        revision = fix(findings)
        attempts.append(
            {"attempt": number, "findingHash": signature, "fixRevision": revision}
        )
        if not revision:
            return {
                "state": "blocked",
                "attempts": attempts,
                "findings": findings,
                "blocker": "safe fix produced no revision",
            }
    return {
        "state": "blocked",
        "attempts": attempts,
        "findings": inspect(),
        "blocker": "maximum attempts reached",
    }


def write_review_package(
    directory: Path, manifest: dict[str, Any]
) -> tuple[Path, Path | None]:
    directory.mkdir(parents=True, exist_ok=True)
    validate_document(manifest, "avo.review-evidence.schema.json")
    json_path = atomic_write_json(directory / "review.json", manifest)
    if manifest["state"] not in {"ai-passed", "needs-human-judgment"}:
        (directory / "approval-gate.md").unlink(missing_ok=True)
        return json_path, None

    candidate = manifest["candidate"]
    change_summary = manifest.get("changeSummary") or {
        "headline": "Candidate bytes and exact canonical dependency snapshot.",
        "items": [],
        "windows": [],
        "staleDependencies": [],
    }
    lines = [
        "# Approval gate",
        "",
        f"Checkpoint: {manifest['checkpoint']}",
        f"Candidate SHA-256: {candidate['sha256']}",
        f"Candidate identity: {candidate['identityHash']}",
        f"Dependency lock: {manifest['dependencyLockSha256']}",
        f"AI state: {manifest['state']}",
        "",
        "## What changed",
        "",
        f"- {change_summary['headline']}",
    ]
    for item in change_summary.get("items") or []:
        operations = ", ".join(
            f"{name}={count}"
            for name, count in (item.get("operationCounts") or {}).items()
        )
        targets = ", ".join(item.get("targets") or [])
        truncated = int(item.get("truncatedTargets") or 0)
        target_note = f"; targets={targets}" if targets else ""
        if truncated:
            target_note += f" (+{truncated} more)"
        lines.append(
            f"- {item['artifactType']} {item['revisionId']}: {operations}; "
            f"reason={item['reason']}{target_note}"
        )
    lines.extend(["", "## Where and why", ""])
    windows = list(change_summary.get("windows") or [])
    if not windows:
        for item in manifest.get("evidence") or []:
            for window in (item.get("scope") or {}).get("windows") or []:
                if window not in windows:
                    windows.append(window)
    if windows:
        for window in windows:
            lines.append(
                f"- {window['start']:.3f}-{window['end']:.3f}s: {window['reason']}"
            )
    else:
        lines.append("- Full-program checkpoint review; no isolated changed window.")
    lines.extend(["", "## Evidence matrix", ""])
    for item in manifest.get("evidence") or []:
        scope = item.get("scope") or {}
        lines.append(
            f"- {item['kind']}: {item['status']} "
            f"(scope={scope.get('mode')}; candidate={item['candidateHash'][:12]})"
        )
    lines.extend(["", "## Stale dependencies", ""])
    stale = list(change_summary.get("staleDependencies") or [])
    for item in manifest.get("evidence") or []:
        if item.get("status") == "stale" and item["kind"] not in stale:
            stale.append(item["kind"])
    lines.append("- " + (", ".join(stale) if stale else "None."))
    lines.extend(["", "## Unresolved risks", ""])
    risks = manifest.get("unresolvedRisks") or []
    if risks:
        for risk in risks:
            lines.append(
                f"- {risk.get('classification', 'risk')}: {risk.get('message', risk.get('id', 'unresolved'))}"
            )
    else:
        lines.append("- None reported by the current evidence bundle.")
    if manifest["state"] == "ai-passed":
        question = (
            f"Do you approve this exact {manifest['checkpoint']} candidate "
            f"{candidate['sha256']} with dependency lock "
            f"{manifest['dependencyLockSha256']}?"
        )
    else:
        question = (
            f"Creator judgment required for this exact {manifest['checkpoint']} "
            f"candidate {candidate['sha256']} with dependency lock "
            f"{manifest['dependencyLockSha256']}. Resolve the risks above; "
            "this package cannot authorize approval until they are resolved "
            "and affected AI checks are current."
        )
    lines.extend(["", "## Exact decision question", "", question, ""])
    markdown = directory / "approval-gate.md"
    markdown.write_text("\n".join(lines), encoding="utf-8")
    _notify_editlog_from_review_dir(directory)
    return json_path, markdown


def _notify_editlog_from_review_dir(directory: Path) -> None:
    raw_dir = directory.parent.parent.parent
    if not (raw_dir / "edit").is_dir():
        return
    from avo.editlog import after_canonical_write

    after_canonical_write(raw_dir)


def _code_drawn_review_header(package: dict[str, Any]) -> None:
    from .contracts import document_hash_excluding

    fields = {
        "schemaVersion",
        "kind",
        "packagePath",
        "candidate",
        "dependencyLockSha256",
        "candidateContract",
        "sources",
        "sampleFrames",
        "transitionRanges",
        "loopRequested",
        "artifacts",
        "findings",
        "state",
        "approval",
        "createdAt",
        "reviewHash",
    }
    if not isinstance(package, dict) or set(package) != fields:
        raise GateError("Incomplete code-drawn review package.")
    if package["schemaVersion"] != "1.0.0" or package["kind"] != "code-drawn-review":
        raise GateError("Unsupported code-drawn review package.")
    if type(package["loopRequested"]) is not bool:
        raise GateError("Code-drawn loop request must be a boolean.")
    if package["approval"] is not None or package["state"] != "needs-human-judgment":
        raise GateError("A prepared code-drawn review cannot grant creator approval.")
    if package["reviewHash"] != document_hash_excluding(package, "reviewHash"):
        raise GateError("Code-drawn review seal changed.")


def _code_drawn_review_binding(
    package, *, candidate, dependencies, render_profile
) -> None:
    from avo.motion import _code_drawn_review_sources, _review_candidate_contract

    from .contracts import dependency_lock_hash

    identity = candidate_identity(Path(candidate), dependencies, render_profile)
    keys = ("sha256", "byteSize", "dependencies", "renderProfile", "identityHash")
    if any(package["candidate"].get(key) != identity[key] for key in keys):
        raise GateError("Code-drawn review candidate/dependency identity is stale.")
    if package["dependencyLockSha256"] != dependency_lock_hash(dependencies):
        raise GateError("Code-drawn review dependency lock changed.")
    if not isinstance(render_profile, str) or not render_profile:
        raise GateError("Code-drawn review requires a render profile.")
    validate_document(
        dependencies,
        "avo.review-evidence.schema.json#/$defs/evidence/properties/dependencyHashes",
    )
    _review_candidate_contract(package["candidateContract"])
    paths = [Path(source["receiptRef"]["path"]) for source in package["sources"]]
    if _code_drawn_review_sources(paths, dependencies) != package["sources"]:
        raise GateError("Code-drawn review source/lock/runtime identity changed.")


def _code_drawn_artifact_family(package: dict, kind: str) -> list[dict]:
    return [item for item in package["artifacts"] if item["kind"] == kind]


def _code_drawn_artifact_coverage(package: dict) -> None:
    samples = set(package["sampleFrames"])
    for kind in ("frame", "small-display"):
        covered = {
            item.get("frame") for item in _code_drawn_artifact_family(package, kind)
        }
        if not samples <= covered:
            raise GateError(f"Code-drawn review lacks required {kind} evidence.")
    if not _code_drawn_artifact_family(package, "contact-sheet"):
        raise GateError("Code-drawn review lacks its contact sheet.")
    strips = _code_drawn_artifact_family(package, "transition-strip")
    if any(
        not any(item.get("range") == bounds for item in strips)
        for bounds in package["transitionRanges"]
    ):
        raise GateError("Code-drawn review lacks a requested transition strip.")
    loops = _code_drawn_artifact_family(package, "loop-strip")
    if bool(loops) != package["loopRequested"]:
        raise GateError("Loop-strip evidence must match the explicit loop request.")


def _code_drawn_artifact_fields(item: dict, count: int) -> None:
    from avo.motion import _review_transition_range

    allowed = {"kind", "path", "sha256", "sizeBytes", "frame", "range", "frames"}
    kinds = {
        "frame",
        "small-display",
        "contact-sheet",
        "transition-strip",
        "loop-strip",
    }
    if set(item) - allowed or item.get("kind") not in kinds:
        raise GateError("Code-drawn review contains an unsupported preview artifact.")
    if "frame" in item and (
        type(item["frame"]) is not int or not 0 <= item["frame"] < count
    ):
        raise GateError("Code-drawn review artifact frame is invalid.")
    if "range" in item:
        _review_transition_range(item["range"], count)


def _code_drawn_review_artifacts(package: dict) -> None:
    from avo.motion import _review_artifacts, _review_sample_plan

    count = package["candidateContract"]["frameCount"]
    frames, transitions = _review_sample_plan(
        count, package["sampleFrames"], package["transitionRanges"]
    )
    if frames != package["sampleFrames"] or transitions != package["transitionRanges"]:
        raise GateError("Code-drawn review frame plan changed.")
    for item in package["artifacts"]:
        _code_drawn_artifact_fields(item, count)
    directory = Path(package["packagePath"]).resolve().parent
    if _review_artifacts(package["artifacts"], directory) != package["artifacts"]:
        raise GateError("Code-drawn review preview artifact changed.")
    _code_drawn_artifact_coverage(package)


def _code_drawn_review_time(value: str):
    from datetime import datetime

    try:
        stamp = datetime.fromisoformat(value)
    except (AttributeError, TypeError, ValueError) as error:
        raise GateError("Code-drawn finding requires an actual timestamp.") from error
    if stamp.tzinfo is None:
        raise GateError("Code-drawn finding timestamp must identify its timezone.")
    return stamp


def _code_drawn_recheck_clock(entry: dict, recheck: dict) -> None:
    fixed = _code_drawn_review_time(entry.get("fixedAt"))
    if not entry.get("fixRevisionRef") or fixed < _code_drawn_review_time(
        entry["observedAt"]
    ):
        raise GateError(
            "Code-drawn recheck requires its recorded fix revision and chronology."
        )
    if _code_drawn_review_time(recheck["observedAt"]) < fixed:
        raise GateError("Code-drawn recheck predates its fix.")
    if entry["finding"]["status"] == "resolved" and recheck["status"] != "pass":
        raise GateError("A failed code-drawn recheck cannot resolve a finding.")


def _code_drawn_recheck_evidence(entry: dict, recheck: dict, package: dict) -> None:
    from avo.motion import _review_transition_range

    bounds, original = recheck["programRange"], entry["finding"].get("programRange")
    _review_transition_range(bounds, package["candidateContract"]["frameCount"])
    if original and not (
        bounds["startFrame"] <= original["startFrame"]
        and bounds["endFrameExclusive"] >= original["endFrameExclusive"]
    ):
        raise GateError("Code-drawn recheck does not cover its finding range.")
    known = {(item["path"], item["sha256"]) for item in package["artifacts"]}
    if not recheck["evidenceRefs"] or any(
        (item.get("path"), item.get("sha256")) not in known
        for item in recheck["evidenceRefs"]
    ):
        raise GateError("Code-drawn recheck lacks current hashed preview evidence.")


def _code_drawn_recheck(entry: dict, package: dict) -> None:
    recheck = entry.get("recheck") or {}
    required = {
        "candidateSha256",
        "dependencyLockSha256",
        "observedAt",
        "programRange",
        "evidenceRefs",
        "status",
    }
    if set(recheck) != required or recheck["status"] not in {"pass", "fail"}:
        raise GateError("Code-drawn finding requires a complete current recheck.")
    if (
        recheck["candidateSha256"] != package["candidate"]["sha256"]
        or recheck["dependencyLockSha256"] != package["dependencyLockSha256"]
    ):
        raise GateError(
            "Code-drawn finding recheck belongs to another candidate/dependency lock."
        )
    _code_drawn_recheck_clock(entry, recheck)
    _code_drawn_recheck_evidence(entry, recheck, package)


def _code_drawn_finding_binding(entry: dict, package: dict, known: set[str]) -> dict:
    from avo.motion import _review_transition_range

    from .vision_review import validate_vision_finding

    finding = validate_vision_finding(entry["finding"])
    _code_drawn_review_time(entry["observedAt"])
    if finding["programRange"] is not None:
        _review_transition_range(
            finding["programRange"], package["candidateContract"]["frameCount"]
        )
    if any(ref["sha256"] not in known for ref in finding["evidenceRefs"]):
        raise GateError("Code-drawn finding lacks its exact preview evidence.")
    if entry["candidateSha256"] != package["candidate"]["sha256"] and not entry.get(
        "recheck"
    ):
        raise GateError(
            "Code-drawn finding belongs to an old candidate without a current recheck."
        )
    disposition = finding.get("humanDisposition")
    if (
        disposition
        and disposition.get("candidateSha256") != package["candidate"]["sha256"]
    ):
        raise GateError("Code-drawn finding disposition belongs to another candidate.")
    return finding


def _code_drawn_review_findings(package: dict) -> tuple[list[dict], list[str]]:
    findings, fixes, seen = [], [], set()
    known = {item["sha256"] for item in package["artifacts"]}
    for entry in package["findings"]:
        finding = _code_drawn_finding_binding(entry, package, known)
        if finding["findingId"] in seen:
            raise GateError("Code-drawn finding IDs must be unique.")
        seen.add(finding["findingId"])
        if finding["status"] == "resolved" or entry.get("recheck"):
            _code_drawn_recheck(entry, package)
            fixes.append(entry["fixRevisionRef"])
        findings.append(finding)
    return findings, sorted(set(fixes))


def _validate_code_drawn_package(
    package: dict, *, candidate: Path, dependencies: dict[str, str], render_profile: str
) -> tuple[list[dict], list[str]]:
    from avo.motion import MotionError

    from .contracts import ContractError

    try:
        _code_drawn_review_header(package)
        _code_drawn_review_binding(
            package,
            candidate=candidate,
            dependencies=dependencies,
            render_profile=render_profile,
        )
        _code_drawn_review_artifacts(package)
        return _code_drawn_review_findings(package)
    except (
        MotionError,
        ContractError,
        OSError,
        KeyError,
        TypeError,
        ValueError,
    ) as error:
        if isinstance(error, GateError):
            raise
        raise GateError(
            f"Invalid or stale code-drawn review evidence: {error}"
        ) from error


def validate_code_drawn_review(
    package: dict, *, candidate: Path, dependencies: dict[str, str], render_profile: str
) -> dict[str, Any]:
    """Bind prepared previews to existing visual-QC evidence, never approval."""
    from avo.motion import _review_json

    from .vision_review import aggregate_finding_status

    findings, fixes = _validate_code_drawn_package(
        package,
        candidate=candidate,
        dependencies=dependencies,
        render_profile=render_profile,
    )
    path = Path(package["packagePath"])
    if _review_json(path) != package:
        raise GateError("Saved code-drawn review package changed.")
    reference = {
        "path": str(path),
        "sha256": file_fingerprint(path)["sha256"],
        "reviewHash": package["reviewHash"],
        "state": package["state"],
        "approval": None,
    }
    contract = package["candidateContract"]
    seconds = contract["frameRate"]["den"] / contract["frameRate"]["num"]
    windows = [
        {
            "start": frame * seconds,
            "end": (frame + 1) * seconds,
            "reason": "code-drawn frame",
        }
        for frame in package["sampleFrames"]
    ]
    windows.extend(
        {
            "start": bounds["startFrame"] * seconds,
            "end": bounds["endFrameExclusive"] * seconds,
            "reason": "code-drawn transition",
        }
        for bounds in package["transitionRanges"]
    )
    status = aggregate_finding_status(findings, required_passes_complete=True)
    evidence = {
        "evidenceId": "code-drawn-review-" + package["reviewHash"][:16],
        "kind": "visual-qc",
        "tool": {"name": "avo-code-drawn-review", "version": "1"},
        "runAt": package["createdAt"],
        "candidateHash": package["candidate"]["sha256"],
        "candidateIdentityHash": package["candidate"]["identityHash"],
        "dependencyLockSha256": package["dependencyLockSha256"],
        "dependencyHashes": deepcopy(dependencies),
        "dependencyProfile": "exact-candidate",
        "scope": {
            "mode": "windows",
            "windows": windows,
            "rationale": "Prepared previews require visual judgment; they do not replace full Watch/transcript review.",
        },
        "coverage": {
            "durationSeconds": contract["frameCount"] * seconds,
            "reviewedSeconds": 0,
            "requiredWindows": len(windows),
            "reviewedWindows": 0,
            "requestedFrames": package["sampleFrames"],
            "decodedFrames": package["sampleFrames"],
            "inspectedFrames": [],
            "loopRequested": package["loopRequested"],
        },
        "status": "fail" if status == "fail" else "pending",
        "findings": findings,
        "fixRevisionRefs": fixes,
        "artifacts": [
            {key: item[key] for key in ("kind", "path", "sha256")}
            for item in package["artifacts"]
        ],
        "attempt": 1,
        "reviewContext": {"codeDrawnReview": reference},
    }
    validate_document(evidence, "avo.review-evidence.schema.json#/$defs/evidence")
    return evidence
