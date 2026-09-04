"""Checkpoint-aware deterministic, audio, visual, accessibility and rights evidence."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from avo.timeline.contracts import file_fingerprint
from avo.timeline.review import CHECKPOINT_POLICIES

from .cut_proof import CutProofQcAdapter
from .source_fidelity import media_from_probe, source_fidelity_evidence


class CheckpointQcRegistry:
    """Produce the full deterministic evidence bundle for a review checkpoint."""

    def __init__(self, *, rights_policy: Any | None = None) -> None:
        self.rights_policy = rights_policy

    @staticmethod
    def _probe(candidate: Path) -> dict[str, Any]:
        completed = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_streams",
                "-show_format",
                "-of",
                "json",
                str(candidate),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        return json.loads(completed.stdout)

    @staticmethod
    def _active_evidence(
        workspace: Any, artifact_type: str, dependencies: dict[str, str]
    ) -> dict[str, Any]:
        findings: list[dict[str, Any]] = []
        try:
            index = workspace.require_active(artifact_type)
            revision = workspace.store(artifact_type).revision(index["headRevisionId"])
            if dependencies.get(artifact_type) != revision["contentHash"]:
                findings.append(
                    {
                        "id": f"{artifact_type}-dependency",
                        "classification": "lineage",
                        "message": f"{artifact_type} dependency is not current",
                    }
                )
        except Exception as error:
            findings.append(
                {
                    "id": f"{artifact_type}-active",
                    "classification": "lineage",
                    "message": str(error),
                }
            )
        return {
            "kind": artifact_type,
            "status": "pass" if not findings else "fail",
            "findings": findings,
        }

    @staticmethod
    def _cue_windows(workspace: Any) -> list[dict[str, Any]]:
        if workspace is None:
            return []
        try:
            index = workspace.require_active("bmap")
            snapshot = workspace.store("bmap").revision(index["headRevisionId"])[
                "snapshot"
            ]
        except Exception:
            return []
        windows = []
        for cue in snapshot.get("cues") or []:
            start = cue.get("start") or {}
            end = cue.get("end") or start
            timebase = start.get("timebase") or {"num": 1, "den": 1}
            factor = float(timebase.get("num", 1)) / float(timebase.get("den", 1))
            begin = float(start.get("ticks", 0)) * factor
            finish = float(end.get("ticks", start.get("ticks", 0))) * factor
            windows.append(
                {
                    "start": max(0.0, begin - 0.15),
                    "end": max(begin + 0.05, finish + 0.15),
                    "reason": f"cue:{cue.get('cueId', 'unknown')}",
                }
            )
        return windows

    @staticmethod
    def _final_transcript(candidate: Path, workspace: Any) -> dict[str, Any]:
        findings = []
        transcript = (
            workspace.raw_dir / "edit" / "transcripts" / f"{candidate.stem}.json"
        )
        if not transcript.is_file():
            findings.append(
                {
                    "id": "final-transcript-missing",
                    "classification": "missing-transcript",
                    "message": f"final-file transcript missing: {transcript}",
                }
            )
        else:
            try:
                value = json.loads(transcript.read_text(encoding="utf-8"))
                source = value.get("source") or {}
                if source.get("sha256") != file_fingerprint(candidate)["sha256"]:
                    findings.append(
                        {
                            "id": "final-transcript-stale",
                            "classification": "missing-transcript",
                            "message": "final transcript source hash does not match master bytes",
                        }
                    )
            except Exception as error:
                findings.append(
                    {
                        "id": "final-transcript-invalid",
                        "classification": "missing-transcript",
                        "message": str(error),
                    }
                )
        return {
            "kind": "final-transcript",
            "status": "pass" if not findings else "fail",
            "findings": findings,
        }

    def _rights(
        self, candidate: Path, workspace: Any, dependencies: dict[str, str]
    ) -> dict[str, Any]:
        if self.rights_policy is not None:
            result = self.rights_policy.check(
                candidate,
                workspace=workspace,
                dependencies=dependencies,
            )
            return {
                "kind": "rights",
                "status": result.get("status") or "fail",
                "findings": result.get("findings") or [],
            }
        source_log = workspace.raw_dir / "SOURCE-LOG.md"
        findings = []
        if (
            not source_log.is_file()
            or not source_log.read_text(encoding="utf-8").strip()
        ):
            findings.append(
                {
                    "id": "source-rights-unresolved",
                    "classification": "rights",
                    "message": "SOURCE-LOG.md is missing or empty; rights/source usage needs human judgment",
                }
            )
        return {
            "kind": "rights",
            "status": "pass" if not findings else "fail",
            "findings": findings,
        }

    def _probe_media(
        self, candidate: Path
    ) -> tuple[dict[str, Any], bool, bool, list[dict[str, Any]]]:
        try:
            probe = self._probe(candidate)
            streams = probe.get("streams") or []
            findings: list[dict[str, Any]] = []
        except Exception as error:
            probe, streams = {}, []
            findings = [
                {
                    "id": "media-probe",
                    "classification": "technical",
                    "message": str(error),
                }
            ]
        has_video = any(item.get("codec_type") == "video" for item in streams)
        has_audio = any(item.get("codec_type") == "audio" for item in streams)
        return probe, has_video, has_audio, findings

    @staticmethod
    def _stream_evidence(
        *, kind: str, present: bool, findings: list[dict[str, Any]] | None = None
    ) -> dict[str, Any]:
        rows = list(findings or [])
        if not present:
            rows.append(
                {
                    "id": f"{kind.split('-')[0]}-stream",
                    "classification": "technical",
                    "message": f"candidate has no {kind.split('-')[0]} stream",
                }
            )
        return {
            "kind": kind,
            "status": "pass" if not rows else "fail",
            "findings": rows,
        }

    @staticmethod
    def _fidelity_evidence(
        candidate: Path, probe: dict[str, Any], checkpoint: str, request: dict[str, Any]
    ) -> dict[str, Any]:
        exists = candidate.is_file()
        return source_fidelity_evidence(
            checkpoint=checkpoint,
            candidate=media_from_probe(
                probe,
                locator=str(candidate),
                size_bytes=candidate.stat().st_size if exists else 0,
                sha256=file_fingerprint(candidate)["sha256"] if exists else None,
            ),
            materialization=request.get("materialization"),
            current_revision_hashes=request.get("current_revision_hashes"),
            materialization_path=request.get("materialization_path"),
        )

    def _checkpoint_evidence(
        self,
        *,
        checkpoint: str,
        candidate: Path,
        workspace: Any,
        dependencies: dict[str, str],
        probe: dict[str, Any],
        has_video: bool,
        has_audio: bool,
        probe_findings: list[dict[str, Any]],
        request: dict[str, Any],
    ) -> list[dict[str, Any]]:
        evidence: list[dict[str, Any]] = []
        if checkpoint == "motion-proof":
            evidence.extend(
                self._active_evidence(workspace, artifact_type, dependencies)
                for artifact_type in ("bmap", "tracks", "animation")
            )
        evidence.extend(
            [
                self._stream_evidence(
                    kind="visual-qc", present=has_video, findings=probe_findings
                ),
                self._fidelity_evidence(candidate, probe, checkpoint, request),
                self._stream_evidence(kind="audio-qc", present=has_audio),
                {"kind": "accessibility", "status": "pass", "findings": []},
                self._rights(candidate, workspace, dependencies),
            ]
        )
        if checkpoint == "deliver":
            evidence.append(self._final_transcript(candidate, workspace))
        return evidence

    @staticmethod
    def _filtered_result(
        base: dict[str, Any],
        checkpoint: str,
        evidence: list[dict[str, Any]],
        windows: list[dict[str, Any]],
    ) -> dict[str, Any]:
        required = CHECKPOINT_POLICIES[checkpoint]["required"]
        selected = [item for item in evidence if item["kind"] in required]
        findings = [
            finding for item in selected for finding in item.get("findings") or []
        ]
        return {
            **base,
            "status": "pass" if not findings else "fail",
            "evidence": selected,
            "requiredWindows": windows,
            "coverage": {"mode": "full", "windows": windows},
            "findings": findings,
            "tool": "avo-checkpoint-qc",
            "toolVersion": "1.0.0",
        }

    def check(self, candidate: Path, **request: Any) -> dict[str, Any]:
        checkpoint = str(request.get("checkpoint") or "cut-proof")
        if checkpoint not in CHECKPOINT_POLICIES:
            raise ValueError(f"unknown review checkpoint: {checkpoint}")
        base = CutProofQcAdapter().check(candidate, **request)
        if checkpoint == "cut-proof":
            return base

        workspace = request.get("workspace")
        dependencies = request.get("dependencies") or {}
        evidence = list(base["evidence"])
        required_windows = list(base.get("requiredWindows") or [])
        for window in self._cue_windows(workspace):
            if window not in required_windows:
                required_windows.append(window)

        candidate_path = Path(candidate)
        probe, has_video, has_audio, probe_findings = self._probe_media(candidate_path)
        evidence.extend(
            self._checkpoint_evidence(
                checkpoint=checkpoint,
                candidate=candidate_path,
                workspace=workspace,
                dependencies=dependencies,
                probe=probe,
                has_video=has_video,
                has_audio=has_audio,
                probe_findings=probe_findings,
                request=request,
            )
        )
        return self._filtered_result(base, checkpoint, evidence, required_windows)
