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
    ):
        self.review_root = Path(review_root)
        self.transcription = transcription
        self.watch = watch
        self.deterministic_qc = deterministic_qc
        self.fix_executor = fix_executor
        self.workspace = workspace
        self.clock = clock
        self.max_tool_attempts = max_tool_attempts
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
        }

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
            ),
            attempts,
        )
        review_windows = list(risk_windows)
        for window in qc.get("requiredWindows") or []:
            if window not in review_windows:
                review_windows.append(window)
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
        watch = self._call(
            "watch",
            lambda: self.watch.review(
                candidate,
                checkpoint=checkpoint,
                scope="full",
                windows=review_windows,
                transcript_ref=transcript.get("transcriptPath") or None,
                artifact_dir=self.review_root
                / checkpoint
                / identity["sha256"][:12]
                / "watch",
            ),
            attempts,
        )
        evidence = []
        for item in qc.get("evidence") or []:
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
                    windows=review_windows,
                    coverage={**(qc.get("coverage") or {}), "windows": review_windows},
                    findings=item.get("findings") or [],
                )
            )
        evidence.append(
            self._evidence(
                kind="transcript-analysis",
                status=transcript.get("status") or "pass",
                tool_name=transcript.get("engine") or "transcription",
                tool_version=transcript.get("engineVersion") or "unknown",
                model=transcript.get("model"),
                identity=identity,
                lock_hash=lock_hash,
                scope_mode="full",
                windows=review_windows,
                coverage={
                    "durationSeconds": qc.get("duration") or 0,
                    "windows": review_windows,
                },
                findings=transcript.get("findings") or [],
                artifacts=self._artifact_refs(
                    [transcript.get("transcriptPath")]
                    if transcript.get("transcriptPath")
                    else []
                ),
            )
        )
        watch_coverage = watch.get("coverage") or {}
        if watch_coverage.get("mode") not in {"full", "whole"}:
            raise ToolError(
                "WATCH_SCOPE_INSUFFICIENT",
                "full Watch evidence required",
                False,
                "rerun full Watch",
            )
        reviewed_windows = watch_coverage.get("windows") or []
        if review_windows and len(reviewed_windows) < len(review_windows):
            raise ToolError(
                "WATCH_SCOPE_INSUFFICIENT",
                "Watch did not cover every required join/changed/privacy/risk window",
                False,
                "rerun Watch with all required windows",
            )
        evidence.append(
            self._evidence(
                kind="watch",
                status=watch.get("status") or "pass",
                tool_name=watch.get("tool") or "watch",
                tool_version=watch.get("toolVersion") or "unknown",
                model=watch.get("model"),
                identity=identity,
                lock_hash=lock_hash,
                scope_mode="full",
                windows=review_windows,
                coverage={**watch_coverage, "durationSeconds": qc.get("duration") or 0},
                findings=watch.get("findings") or [],
                artifacts=self._artifact_refs(watch.get("artifacts") or []),
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
    ) -> dict[str, Any]:
        candidate = Path(candidate)
        windows = list(risk_windows or [])
        attempts: list[dict[str, Any]] = []
        current_candidate = candidate
        current_dependencies = dict(sorted(dependencies.items()))
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
                )
            except ToolError as error:
                return self._write(
                    checkpoint=checkpoint,
                    identity=last_identity,
                    evidence=last_evidence,
                    attempts=attempts,
                    state="blocked",
                    findings=last_findings,
                    blocker=str(error),
                )
            last_identity, last_evidence, last_findings = identity, evidence, findings
            state = classify_findings(findings)
            if state == "ai-passed":
                try:
                    evaluate_gate(
                        checkpoint,
                        identity["sha256"],
                        identity["dependencies"],
                        evidence,
                        candidate_identity_hash=identity["identityHash"],
                        dependency_lock_sha256=dependency_lock_hash(
                            identity["dependencies"]
                        ),
                    )
                except Exception as error:
                    return self._write(
                        checkpoint=checkpoint,
                        identity=identity,
                        evidence=evidence,
                        attempts=attempts,
                        state="blocked",
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
            if state == "needs-human-judgment":
                return self._write(
                    checkpoint=checkpoint,
                    identity=identity,
                    evidence=evidence,
                    attempts=attempts,
                    state=state,
                    findings=findings,
                )
            if self.fix_executor is None:
                return self._write(
                    checkpoint=checkpoint,
                    identity=identity,
                    evidence=evidence,
                    attempts=attempts,
                    state="blocked",
                    findings=findings,
                    blocker="safe findings require an owning-stage fix executor",
                )
            if fix_number >= self.max_fix_attempts:
                return self._write(
                    checkpoint=checkpoint,
                    identity=identity,
                    evidence=evidence,
                    attempts=attempts,
                    state="blocked",
                    findings=findings,
                    blocker="maximum safe-fix attempts reached",
                )
            result = self.fix_executor.apply_fix(
                findings,
                checkpoint=checkpoint,
                candidate=current_candidate,
                dependencies=current_dependencies,
            )
            next_candidate = Path(result.get("candidate") or current_candidate)
            next_dependencies = dict(
                sorted((result.get("dependencies") or current_dependencies).items())
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
                return self._write(
                    checkpoint=checkpoint,
                    identity=identity,
                    evidence=evidence,
                    attempts=attempts,
                    state="blocked",
                    findings=findings,
                    blocker="safe fix produced no candidate or dependency identity change",
                )
            current_candidate = next_candidate
            current_dependencies = next_dependencies
            last_identity = next_identity

        raise AssertionError("unreachable")
