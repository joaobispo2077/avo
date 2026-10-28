"""Thin deterministic-QC adapter for canonical delivery fidelity evidence."""

from __future__ import annotations

import json
import subprocess
from fractions import Fraction
from pathlib import Path
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
    workspace: Any = None,
) -> dict[str, Any]:
    """Evaluate only canonical materialization, policy, and lineage inputs."""
    if (
        materialization
        and materialization.get("kind") == "proof-plan"
        and checkpoint in {"pre-master", "deliver"}
    ):
        return _native_fidelity(
            candidate, materialization, materialization_path, workspace
        )
    result = evaluate_delivery_fidelity(
        checkpoint=checkpoint,
        candidate=candidate,
        materialization=materialization,
        current_revision_hashes=current_revision_hashes,
    )
    if materialization_path:
        result.setdefault("details", {})["materializationPath"] = materialization_path
    return result


def _native_probe(path: Path, *, count_frames: bool = False) -> dict:
    command = ["ffprobe", "-v", "error"]
    if count_frames:
        command.append("-count_frames")
    result = subprocess.run(
        [*command, "-show_streams", "-show_format", "-of", "json", str(path)],
        check=True,
        capture_output=True,
        text=True,
        timeout=120,
    )
    return json.loads(result.stdout)


def _native_sdr_tags(video: dict) -> None:
    primaries = video.get("color_primaries", "unknown")
    transfer = video.get("color_transfer", "unknown")
    if primaries not in {
        "unknown",
        "unspecified",
        "bt709",
        "bt470bg",
        "bt470m",
        "smpte170m",
        "smpte240m",
    }:
        raise ValueError("Unsupported native wide-gamut/HDR source or output")
    if transfer not in {
        "unknown",
        "unspecified",
        "bt709",
        "iec61966-2-1",
        "bt470bg",
        "smpte170m",
        "smpte240m",
        "gamma22",
        "gamma28",
    }:
        raise ValueError("Unsupported native HDR transfer function")
    _native_picture_metadata(video)


def _native_picture_metadata(video: dict) -> None:
    for item in video.get("side_data_list") or []:
        name = str(item.get("side_data_type") or "").lower()
        if any(
            token in name
            for token in ("mastering", "content light", "dovi", "dolby", "hdr")
        ):
            raise ValueError("Unsupported native HDR metadata")
        if item.get("rotation", 0):
            raise ValueError("Unsupported native rotated picture metadata")
    if (video.get("tags") or {}).get("rotate") not in (None, "0", 0):
        raise ValueError("Unsupported native rotated picture metadata")


def _native_sdr_video(video: dict) -> None:
    formats = {
        "yuv420p",
        "yuv422p",
        "yuv444p",
        "yuvj420p",
        "yuvj422p",
        "yuvj444p",
        "nv12",
        "rgb24",
        "bgr24",
        "rgba",
        "bgra",
        "argb",
        "abgr",
        "0rgb",
        "rgb0",
        "0bgr",
        "bgr0",
        "gray",
        "gray8",
    }
    if video.get("pix_fmt") not in formats or str(
        video.get("bits_per_raw_sample") or "0"
    ) not in {"0", "8"}:
        raise ValueError(
            "Unsupported native bit depth; only 8-bit SDR picture is verified"
        )
    if video.get("field_order") not in (None, "unknown", "progressive"):
        raise ValueError("Unsupported native interlaced picture")
    _native_sdr_tags(video)


def _native_video_sources(segments, generated):
    pictures = {segment[2] for segment in segments}
    pictures.update(
        (asset["path"], asset["video"]["index"]) for asset in generated.values()
    )
    for path, index in pictures:
        probe = _native_probe(Path(path))
        video = next(
            item
            for item in probe["streams"]
            if item["index"] == index and item["codec_type"] == "video"
        )
        _native_sdr_video(video)


def _native_graph_contract(plan, workspace):
    from avo.adapters.media import proof_executor as executor
    from avo.proof_composition import create_generated_asset_validator

    execution = {**plan, "window": None}
    spec, fps, rate = executor._output_settings(execution)
    executor._validate_events(execution)
    nodes = execution["audioGraph"]["nodes"]
    by_range = executor._audio_nodes(nodes, rate)
    executor._validate_resampling(execution["audioGraph"], nodes, rate)
    trims, encodes = executor._audio_operations(execution["audioGraph"])
    generated = executor._generated_inputs(
        execution, spec, fps, create_generated_asset_validator(workspace)
    )
    frames, segments = executor._segments(
        execution, by_range, trims, fps, rate, nodes, generated
    )
    executor._proof_window(execution, frames, encodes, fps, rate)
    executor._proof_overlays(generated, frames)
    _native_video_sources(segments, generated)
    return spec, fps, rate, frames


def _native_candidate_streams(probe):
    video = [item for item in probe["streams"] if item["codec_type"] == "video"]
    audio = [item for item in probe["streams"] if item["codec_type"] == "audio"]
    if len(video) != 1 or len(audio) != 1 or len(probe["streams"]) != 2:
        raise ValueError(
            "Unsupported native stream structure; one picture and stereo audio required"
        )
    _native_sdr_video(video[0])
    return video[0], audio[0]


def _native_contract_findings(probe, spec, fps, rate, frames):
    video, audio = _native_candidate_streams(probe)
    codec = {"libx264": "h264", "h264_nvenc": "h264", "ffv1": "ffv1"}[
        spec["videoCodec"]
    ]
    checks = {
        "width": (video["width"], spec["width"]),
        "height": (video["height"], spec["height"]),
        "frame-rate": (
            Fraction(video.get("avg_frame_rate") or video["r_frame_rate"]),
            fps,
        ),
        "frame-count": (int(video["nb_read_frames"]), frames),
        "video-codec": (video["codec_name"], codec),
        "pixel-format": (
            video["pix_fmt"],
            "bgra" if spec.get("conformance") is True else "yuv420p",
        ),
        "audio-codec": (audio["codec_name"], spec["audioCodec"]),
        "audio-rate": (int(audio["sample_rate"]), rate),
        "audio-channels": (audio["channels"], 2),
        "audio-layout": (audio.get("channel_layout") or "stereo", "stereo"),
        "sample-aspect-ratio": (video.get("sample_aspect_ratio") or "1:1", "1:1"),
    }
    findings = [
        {
            "id": "native-" + key,
            "classification": "technical",
            "message": f"Frozen native {key} differs: observed {actual}, expected {expected}",
        }
        for key, (actual, expected) in checks.items()
        if actual != expected
    ]
    findings.extend(_native_duration_findings(probe, audio, spec, fps, rate, frames))
    return findings


def _native_stream_duration(stream):
    if stream.get("duration") is not None:
        return float(stream["duration"])
    value = (stream.get("tags") or {}).get("DURATION")
    if not isinstance(value, str):
        raise ValueError("Native audio duration could not be observed")
    hours, minutes, seconds = value.split(":")
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def _native_duration_findings(probe, audio, spec, fps, rate, frames):
    expected = float(frames / fps)
    checks = {
        "duration": (float(probe["format"]["duration"]), float(1 / fps)),
        "audio-duration": (
            _native_stream_duration(audio),
            (1024 / rate if spec["audioCodec"] == "aac" else 1 / rate) + 0.001,
        ),
    }
    return [
        {
            "id": "native-" + key,
            "classification": "technical",
            "message": f"Native {key} differs from frozen frame range (tolerance {tolerance}s)",
        }
        for key, (actual, tolerance) in checks.items()
        if abs(actual - expected) > tolerance
    ]


def _native_fidelity_binding(
    candidate, materialization, materialization_path, workspace
):
    from avo.timeline.approval_service import require_native_proof_materialization
    from avo.timeline.proof_plan import ProofPlanCompiler

    if workspace is None or materialization_path is None:
        raise ValueError(
            "Native fidelity requires project and persisted materialization context"
        )
    persisted = json.loads(Path(materialization_path).read_text(encoding="utf-8"))
    if persisted != materialization:
        raise ValueError(
            "Native persisted materialization differs from the supplied record"
        )
    path = Path(candidate["locator"]).resolve()
    dependencies = require_native_proof_materialization(
        workspace, materialization, path
    )
    if candidate.get("sha256") != materialization["output"]["sha256"]:
        raise ValueError("Native candidate fingerprint differs from materialization")
    if materialization.get("producer") != {
        "name": "avo.ffmpeg-proof-plan",
        "version": "1",
    }:
        raise ValueError("Unsupported native materialization producer")
    compiler = ProofPlanCompiler(workspace)
    plan = compiler.load(compiler.path(materialization["proofPlanId"]))
    return path, plan, dependencies


def _native_fidelity(candidate, materialization, materialization_path, workspace):
    details = {
        "basis": "native-proof-plan",
        "materializationPath": str(materialization_path),
    }
    try:
        path, plan, dependencies = _native_fidelity_binding(
            candidate, materialization, materialization_path, workspace
        )
        spec, fps, rate, frames = _native_graph_contract(plan, workspace)
        probe = _native_probe(path, count_frames=True)
        findings = _native_contract_findings(probe, spec, fps, rate, frames)
        details["nativeBasis"] = {
            "scope": "8-bit-sdr-native",
            "proofPlanId": plan["proofPlanId"],
            "proofPlanHash": plan["proofPlanHash"],
            "materializationHash": materialization["materializationHash"],
            "preflightHash": materialization["preflightHash"],
            "microproofGateHash": materialization["microproofGateHash"],
            "canonicalInputLock": plan["canonicalInputLock"],
            "dependencies": dependencies,
            "renderProfile": plan["renderProfile"],
            "renderContract": spec,
            "frameCount": frames,
            "observedStreams": probe["streams"],
            "observedFormat": probe["format"],
            "untaggedSourceInterpretation": "8-bit SDR; HDR/wide-gamut inputs rejected",
        }
    except (
        OSError,
        ValueError,
        RuntimeError,
        KeyError,
        TypeError,
        StopIteration,
        ZeroDivisionError,
        subprocess.SubprocessError,
    ) as error:
        return {
            "kind": "source-fidelity",
            "status": "error",
            "disposition": "blocked",
            "findings": [
                {
                    "id": "native-fidelity-prerequisite",
                    "classification": "prerequisite",
                    "message": str(error),
                }
            ],
            "details": details,
        }
    status = "fail" if findings else "pass"
    return {
        "kind": "source-fidelity",
        "status": status,
        "disposition": status,
        "findings": findings,
        "details": details,
    }
