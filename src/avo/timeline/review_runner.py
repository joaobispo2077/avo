"""Executable AI-first review orchestration over candidate-bound ports."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from .contracts import dependency_lock_hash, file_fingerprint
from .ports import ToolError
from .review import (
    EVIDENCE_PROFILES,
    candidate_identity,
    classify_findings,
    evaluate_gate,
    write_review_package,
)


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
    reviewed_windows = coverage.get("windows") or []
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
    return "fail" if status == "needs-human-judgment" else status


def _watch_extra(watch: dict[str, Any]) -> dict[str, Any]:
    fields = ("outcomeKind", "policy", "reviewContext", "promptSha256", "attempts")
    return {key: watch[key] for key in fields if key in watch}


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
        duration = float(
            coverage.get("durationSeconds") or coverage.get("duration") or 0
        )
        reviewed = float(
            coverage.get("reviewedSeconds")
            or (
                duration
                if scope_mode == "full"
                else sum(max(0.0, float(w["end"]) - float(w["start"])) for w in windows)
            )
        )
        normalized_coverage = dict(coverage)
        normalized_coverage.update(
            {
                "durationSeconds": duration,
                "reviewedSeconds": reviewed,
                "requiredWindows": len(windows),
                "reviewedWindows": len(coverage.get("windows") or windows),
            }
        )
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
    ) -> dict[str, Any]:
        coverage = watch.get("coverage") or {}
        _validate_watch_coverage(coverage, windows)
        return self._evidence(
            kind="watch",
            status=_normalized_watch_status(watch),
            tool_name=watch.get("tool") or "watch",
            tool_version=watch.get("toolVersion") or "unknown",
            model=watch.get("model"),
            identity=identity,
            lock_hash=lock_hash,
            scope_mode="full",
            windows=windows,
            coverage={**coverage, "durationSeconds": qc.get("duration") or 0},
            findings=watch.get("findings") or [],
            artifacts=self._artifact_refs(watch.get("artifacts") or []),
            extra=_watch_extra(watch),
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
                edit_dir=self.review_root.parent / "transcripts",
            ),
            attempts,
        )
        policy_payload, policy_context = _watch_policy_values(self.watch_policy)
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
            self._watch_evidence(watch, qc, identity, lock_hash, review_windows)
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
        if state == "needs-human-judgment":
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
            state = classify_findings(findings)
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
