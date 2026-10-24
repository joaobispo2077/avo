"""Deterministic cut-proof lineage, decode, duration, and risk-window checks."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from avo.timeline.contracts import content_hash, file_fingerprint, validate_document
from avo.timeline.lineage import (
    lineage_from_materialization,
    validate_audiovisual_lineage,
)
from avo.timeline.projection import ProjectionError, verify_projection

from .source_fidelity import media_from_probe, source_fidelity_evidence


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


def _require_assembly_dependencies(workspace, materialization, dependencies):
    lock = materialization["canonicalInputLock"]
    expected = {
        "materialization": materialization["materializationHash"],
        "assembly-output": materialization["output"]["sha256"],
        "picture-lineage": materialization["pictureLineageHash"],
        "delivery-fidelity-policy": materialization["deliveryFidelityPolicyHash"],
        "raw": content_hash(lock["rawFingerprints"]),
    }
    for name, prefix in (
        ("cmap", "cmap"),
        ("sync-map", "sync"),
        ("bmap", "bmap"),
        ("tracks", "tracks"),
    ):
        index = workspace.require_active(name)
        head = next(
            item
            for item in index["revisionRefs"]
            if item["revisionId"] == index["headRevisionId"]
        )
        if (
            lock[f"{prefix}RevisionId"] != head["revisionId"]
            or lock[f"{prefix}RevisionHash"] != head["contentSha256"]
        ):
            raise ProjectionError(f"assembly {name} dependency is not current")
        expected[name] = head["contentSha256"]
    if any(dependencies.get(key) != value for key, value in expected.items()):
        raise ProjectionError("assembly review dependencies are not exact")
    sync = workspace.store("sync-map").effective_approval()
    if sync is None or sync["subject"]["contentSha256"] != expected["sync-map"]:
        raise ProjectionError("current approved Sync/N/A is missing or stale")


def _require_assembly_lineage(
    workspace, materialization, candidate, dependencies, materialization_path, probe
):
    if materialization_path is None:
        raise ProjectionError("persisted assembly materialization is required")
    persisted = json.loads(Path(materialization_path).read_text(encoding="utf-8"))
    if persisted != materialization:
        raise ProjectionError("persisted assembly materialization differs")
    validate_document(materialization, "avo.materialization.schema.json")
    actual = file_fingerprint(candidate)
    output = materialization["output"]
    if (
        actual["sha256"] != output["sha256"]
        or actual["sizeBytes"] != output["sizeBytes"]
        or Path(output["locator"]).resolve() != candidate.resolve()
    ):
        raise ProjectionError("assembly candidate differs from materialization")
    _require_assembly_dependencies(workspace, materialization, dependencies)
    _require_assembly_graph(materialization, candidate, actual)
    result = source_fidelity_evidence(
        checkpoint="pre-master",
        candidate=media_from_probe(
            probe or {},
            locator=str(candidate),
            size_bytes=actual["sizeBytes"],
            sha256=actual["sha256"],
        ),
        materialization=materialization,
    )
    if result["status"] != "pass":
        raise ProjectionError(
            f"assembly fidelity validation failed: {result['findings']}"
        )


def _require_assembly_graph(materialization, candidate, actual):
    graphs = [materialization["pictureLineage"]]
    if "audiovisualLineage" in materialization:
        graph = lineage_from_materialization(materialization)
        if graph["lineageHash"] != materialization.get("audiovisualLineageHash"):
            raise ProjectionError("assembly audiovisual lineage hash differs")
        graphs.append(graph)
    for graph in graphs:
        validate_audiovisual_lineage(graph)
        if (
            graph["canonicalInputLock"] != materialization["canonicalInputLock"]
            or graph["projectionHash"] != materialization["projectionHash"]
        ):
            raise ProjectionError("assembly lineage canonical binding differs")
        for node in graph["nodes"]:
            if node["nodeId"] in graph["rootIds"] and (
                node["sha256"] != actual["sha256"]
                or Path(node["locator"]).resolve() != candidate.resolve()
            ):
                raise ProjectionError("assembly lineage output differs from candidate")


def _require_cut_lineage(
    workspace,
    materialization,
    candidate,
    dependencies,
    *,
    materialization_path=None,
    probe=None,
):
    if workspace is None:
        raise ProjectionError("canonical workspace is required")
    if materialization and materialization.get("kind") == "assembly":
        _require_assembly_lineage(
            workspace,
            materialization,
            Path(candidate),
            dependencies,
            materialization_path,
            probe,
        )
        return
    if materialization and materialization.get("kind") == "proof-plan":
        from avo.timeline.approval_service import require_native_cut_materialization

        expected = require_native_cut_materialization(
            workspace, materialization, candidate
        )
        if any(dependencies.get(key) != value for key, value in expected.items()):
            raise ProjectionError("candidate native cut dependencies are not exact")
    else:
        verify_projection(workspace)
    _require_current_cut_heads(workspace, candidate, dependencies)


def _require_current_cut_heads(workspace, candidate, dependencies):
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
    if dependencies.get("cutOutput") and dependencies["cutOutput"] != candidate_hash:
        raise ProjectionError("cut-output dependency does not match candidate bytes")


class CutProofQcAdapter:
    def check(self, candidate: Path, **request: Any) -> dict[str, Any]:
        candidate = Path(candidate)
        findings: list[dict[str, Any]] = []
        duration = 0.0
        probe: dict[str, Any] = {}
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
            _require_cut_lineage(
                workspace,
                request.get("materialization"),
                candidate,
                dependencies,
                materialization_path=request.get("materialization_path"),
                probe=probe,
            )
        except (
            OSError,
            ProjectionError,
            StopIteration,
            KeyError,
            ValueError,
            RuntimeError,
        ) as error:
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
