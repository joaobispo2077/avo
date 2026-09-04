"""Thin deterministic-QC adapter for canonical delivery fidelity evidence."""

from __future__ import annotations

from typing import Any

from avo.delivery_fidelity import (
    evaluate_delivery_fidelity,
)


def _video_stream(probe: dict[str, Any]) -> dict[str, Any]:
    return next(
        (
            stream
            for stream in probe.get("streams") or []
            if stream.get("codec_type") == "video"
        ),
        {},
    )


def _integer(value: Any) -> int:
    return int(value or 0)


def _probe_bit_rate(video: dict[str, Any], fmt: dict[str, Any], size: int) -> int:
    bit_rate = _integer(video.get("bit_rate") or fmt.get("bit_rate"))
    duration = float(fmt.get("duration") or 0)
    if bit_rate <= 0 and size > 0 and duration > 0:
        return int(size * 8 / duration)
    return bit_rate


def _probe_frame_rate(video: dict[str, Any]) -> float | None:
    value = video.get("avg_frame_rate") or video.get("r_frame_rate")
    if not isinstance(value, str) or "/" not in value:
        return None
    numerator, denominator = value.split("/", 1)
    if not float(denominator):
        return None
    return float(numerator) / float(denominator)


def media_from_probe(
    probe: dict[str, Any],
    *,
    locator: str = "",
    size_bytes: int = 0,
    sha256: str | None = None,
) -> dict[str, Any]:
    """Normalize probed candidate media without applying profile assumptions."""
    video = _video_stream(probe)
    fmt = probe.get("format") or {}
    duration = float(fmt.get("duration") or 0)
    size = _integer(fmt.get("size") or size_bytes)
    result = {
        "locator": locator,
        "width": _integer(video.get("width")),
        "height": _integer(video.get("height")),
        "durationSeconds": duration,
        "bitRate": _probe_bit_rate(video, fmt, size),
        "sizeBytes": size,
        "codec": str(video.get("codec_name") or "").lower(),
    }
    frame_rate = _probe_frame_rate(video)
    if frame_rate is not None:
        result["frameRate"] = frame_rate
    if sha256:
        result["sha256"] = sha256
    return result


def source_fidelity_evidence(
    *,
    checkpoint: str,
    candidate: dict[str, Any],
    materialization: dict[str, Any] | None,
    current_revision_hashes: dict[str, str] | None = None,
    materialization_path: str | None = None,
) -> dict[str, Any]:
    """Evaluate only canonical materialization, policy, and lineage inputs."""
    result = evaluate_delivery_fidelity(
        checkpoint=checkpoint,
        candidate=candidate,
        materialization=materialization,
        current_revision_hashes=current_revision_hashes,
    )
    if materialization_path:
        result.setdefault("details", {})["materializationPath"] = materialization_path
    return result
