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


class GateError(RuntimeError):
    pass


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
    if classes & {"tool-error", "missing-watch", "missing-transcript"}:
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
    return json_path, markdown
