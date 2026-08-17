"""Deterministic cut-proof lineage, decode, duration, and risk-window checks."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from avo.timeline.contracts import file_fingerprint
from avo.timeline.projection import ProjectionError, verify_projection


def _seconds(value: dict[str, Any]) -> float:
    timebase = value["timebase"]
    return float(value["ticks"]) * float(timebase["num"]) / float(timebase["den"])


def _join_windows(workspace: Any) -> list[dict[str, Any]]:
    if workspace is None:
        return []
    store = workspace.store("cmap")
    index = store.load_index()
    if not index["headRevisionId"]:
        return []
    revision = store.revision(index["headRevisionId"])
    elapsed = 0.0
    windows = []
    segments = revision["snapshot"].get("segments") or []
    for ordinal, segment in enumerate(segments):
        elapsed += _seconds(segment["out"]) - _seconds(segment["in"])
        if ordinal < len(segments) - 1:
            windows.append(
                {
                    "start": max(0.0, elapsed - 0.25),
                    "end": elapsed + 0.25,
                    "reason": f"join:{segment['segmentId']}->{segments[ordinal + 1]['segmentId']}",
                }
            )
    return windows


class CutProofQcAdapter:
    def check(self, candidate: Path, **request: Any) -> dict[str, Any]:
        candidate = Path(candidate)
        findings: list[dict[str, Any]] = []
        duration = 0.0
        try:
            probe = json.loads(
                subprocess.run(
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
                ).stdout
            )
            duration = float((probe.get("format") or {}).get("duration") or 0)
            if duration <= 0:
                findings.append(
                    {
                        "id": "duration",
                        "classification": "technical",
                        "message": "candidate duration is invalid",
                    }
                )
            if not any(
                item.get("codec_type") == "video" for item in probe.get("streams") or []
            ):
                findings.append(
                    {
                        "id": "video-stream",
                        "classification": "technical",
                        "message": "video stream missing",
                    }
                )
            subprocess.run(
                ["ffmpeg", "-v", "error", "-i", str(candidate), "-f", "null", "-"],
                check=True,
                capture_output=True,
            )
        except Exception as error:
            findings.append(
                {"id": "decode", "classification": "technical", "message": str(error)}
            )

        workspace = request.get("workspace")
        dependencies = request.get("dependencies") or {}
        try:
            if workspace is None:
                raise ProjectionError("canonical workspace is required")
            verify_projection(workspace)
            cmap_store = workspace.store("cmap")
            cmap_index = cmap_store.load_index()
            cmap_ref = next(
                item
                for item in cmap_index["revisionRefs"]
                if item["revisionId"] == cmap_index["headRevisionId"]
            )
            if dependencies.get("cmap") != cmap_ref["contentSha256"]:
                raise ProjectionError("candidate CMap dependency is not current")
            sync_event = workspace.store("sync-map").effective_approval()
            if sync_event is None:
                raise ProjectionError("current approved Sync/N/A is missing")
            if dependencies.get("sync-map") != sync_event["subject"]["contentSha256"]:
                raise ProjectionError("candidate Sync dependency is not current")
            candidate_hash = file_fingerprint(candidate)["sha256"]
            if (
                dependencies.get("cutOutput")
                and dependencies["cutOutput"] != candidate_hash
            ):
                raise ProjectionError(
                    "cut-output dependency does not match candidate bytes"
                )
        except (ProjectionError, StopIteration, KeyError, ValueError) as error:
            findings.append(
                {"id": "lineage", "classification": "lineage", "message": str(error)}
            )

        if not dependencies or any(
            len(str(value)) != 64 for value in dependencies.values()
        ):
            findings.append(
                {
                    "id": "dependency-lock",
                    "classification": "lineage",
                    "message": "exact dependency lock missing",
                }
            )

        required_windows = list(request.get("risk_windows") or [])
        for window in _join_windows(workspace):
            if window not in required_windows:
                required_windows.append(window)
        lineage_findings = [
            item for item in findings if item["classification"] == "lineage"
        ]
        technical_findings = [
            item for item in findings if item["classification"] == "technical"
        ]
        sync_findings = [
            item for item in lineage_findings if "Sync" in item.get("message", "")
        ]
        return {
            "status": "pass" if not findings else "fail",
            "evidence": [
                {
                    "kind": "lineage",
                    "status": "pass" if not lineage_findings else "fail",
                    "findings": lineage_findings,
                },
                {
                    "kind": "technical-qc",
                    "status": "pass" if not technical_findings else "fail",
                    "findings": technical_findings,
                },
                {
                    "kind": "sync",
                    "status": "pass" if not sync_findings else "fail",
                    "findings": sync_findings,
                },
            ],
            "duration": duration,
            "candidate": file_fingerprint(candidate),
            "requiredWindows": required_windows,
            "coverage": {"mode": "full", "windows": required_windows},
            "findings": findings,
            "tool": "avo-cut-qc",
            "toolVersion": "1.0.0",
        }
