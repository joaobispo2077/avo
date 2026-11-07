"""Render canonical original-source placements on one absolute program clock."""

from __future__ import annotations

import json
import subprocess
import tempfile
from fractions import Fraction
from pathlib import Path

from avo.capabilities import default_proof_capability_registry
from avo.timeline.contracts import file_fingerprint, fingerprint_stage
from avo.timeline.event_clock import sample_rate_boundary

from .local_source import local_source_arguments
from .proof_audio_mix import render_proof_audio_mix, validate_proof_audio_mix


def _require_implementation(execution, operation):
    implementation = default_proof_capability_registry().resolve(
        "source-layout", implementation_id=operation["implementationId"]
    )
    refs = {item["implementationId"]: item for item in execution["implementationRefs"]}
    if (
        implementation is None
        or refs.get(operation["implementationId"]) != implementation.proof_reference()
    ):
        raise RuntimeError(
            "ProofPlan source-layout implementation is unsupported or stale"
        )


def _operation(execution):
    from . import proof_executor as native

    operations = execution["videoGraph"]["operations"]
    if len(operations) != 1 or operations[0]["kind"] != "source-layout":
        raise RuntimeError("Placed proof requires exactly one source-layout operation")
    operation = operations[0]
    _require_implementation(execution, operation)
    first, last = native._bounds(
        operation["outputRange"], "startFrame", "endFrameExclusive"
    )
    parameters = operation["parameters"]
    if (
        first
        or set(parameters) != {"background", "placements"}
        or parameters["background"] != "black"
    ):
        raise RuntimeError("Source-layout requires an exact black program extent")
    if not isinstance(parameters["placements"], list):
        raise RuntimeError("Source-layout placements must be an explicit list")
    if operation["inputs"] != sorted(
        {item["sourceId"] for item in parameters["placements"]}
    ):
        raise RuntimeError("Source-layout has unconsumed or missing picture inputs")
    return parameters["placements"], last


def _placement_fields(item):
    required = {
        "placementId",
        "trackId",
        "sourceId",
        "mediaKind",
        "source",
        "sourceRange",
        "outputRange",
        "zOrder",
        "enabled",
    }
    if set(item) != required or item["mediaKind"] not in {"video", "still"}:
        raise RuntimeError("Unsupported source-layout placement or treatment")
    if (
        type(item["enabled"]) is not bool
        or type(item["zOrder"]) is not int
        or item["zOrder"] < 0
    ):
        raise RuntimeError(
            "Source-layout requires explicit enabled state and layer order"
        )
    if any(
        not isinstance(item[key], str) or not item[key]
        for key in ("placementId", "trackId", "sourceId")
    ):
        raise RuntimeError("Source-layout requires nonempty stable identities")


def _source_frames(item, fps):
    from . import proof_executor as native

    value = item["sourceRange"]
    if set(value) != {"startTicks", "endTicks", "timebase"}:
        raise RuntimeError("Source-layout requires an exact raw source range")
    first, last = native._bounds(value, "startTicks", "endTicks")
    base = value["timebase"]
    if set(base) != {"num", "den"} or any(
        type(base[key]) is not int or base[key] <= 0 for key in ("num", "den")
    ):
        raise RuntimeError("Source-layout source timebase must be positive")
    frames = [
        Fraction(ticks * base["num"], base["den"]) * fps for ticks in (first, last)
    ]
    if any(frame.denominator != 1 for frame in frames):
        raise RuntimeError("Source-layout trims must use exact source frame boundaries")
    return tuple(frame.numerator for frame in frames)


def _require_square_pixels(metadata):
    value = metadata.get("sample_aspect_ratio")
    if value in (None, "", "N/A", "0:1", "0/1"):
        return
    try:
        ratio = Fraction(str(value).replace(":", "/"))
    except (ValueError, ZeroDivisionError) as exc:
        raise RuntimeError(
            "Source-layout has an unsupported source sample aspect ratio"
        ) from exc
    if ratio != 1:
        raise RuntimeError("Source-layout requires square source sample aspect ratio")


def _actual_picture_clock(item, path, stream, cache, fps):
    metadata = next(
        value
        for value in cache[str(path.resolve())]["streams"]
        if value["index"] == stream
    )
    _require_square_pixels(metadata)
    if item["mediaKind"] == "still":
        return
    try:
        rates = [Fraction(metadata[key]) for key in ("r_frame_rate", "avg_frame_rate")]
    except (KeyError, ValueError, ZeroDivisionError) as exc:
        raise RuntimeError(
            "Source-layout requires verified constant-rate source picture"
        ) from exc
    if any(rate != fps for rate in rates):
        raise RuntimeError(
            "Source-layout picture frame rate differs from program clock"
        )
    from .proof_executor import _verify_picture_clock

    evidence = _verify_picture_clock(path, stream, cache, fps)
    _, last = _source_frames(item, fps)
    if last > evidence["packetCount"]:
        raise RuntimeError("Source-layout exceeds verified available picture frames")


def _admit_picture(execution, items, total, fps, cache):
    from . import proof_executor as native
    from .still_probe import verify_literal_still

    admitted = []
    for item in items:
        _placement_fields(item)
        start, end = native._bounds(
            item["outputRange"], "startFrame", "endFrameExclusive"
        )
        first, last = _source_frames(item, fps)
        if end > total or (
            item["mediaKind"] == "video" and last - first != end - start
        ):
            raise RuntimeError(
                "Source-layout range contradicts normal-speed program extent"
            )
        if item["mediaKind"] == "still" and first != 0:
            raise RuntimeError(
                "Literal still placement must hold its original first frame"
            )
        still = item["mediaKind"] == "still"
        if still:
            native._source_identity(item, execution["canonicalInputLock"])
            verify_literal_still(Path(item["source"]["locator"]))
        path, stream = native._source(
            item, execution["canonicalInputLock"], cache, literal_still=still
        )
        _actual_picture_clock(item, path, stream, cache, fps)
        admitted.append(
            {"item": item, "path": path, "stream": stream, "first": first, "last": last}
        )
    _validate_layers(items)
    return admitted


def _validate_layers(items):
    ids, tracks, intervals = set(), {}, {}
    for item in items:
        if item["placementId"] in ids:
            raise RuntimeError("Source-layout placement IDs must be unique")
        ids.add(item["placementId"])
        if tracks.setdefault(item["trackId"], item["zOrder"]) != item["zOrder"]:
            raise RuntimeError("Source-layout track order is inconsistent")
        region = item["outputRange"]
        intervals.setdefault(item["trackId"], []).append(
            (region["startFrame"], region["endFrameExclusive"])
        )
    if len(set(tracks.values())) != len(tracks):
        raise RuntimeError("Source-layout tracks require unique layer order")
    for values in intervals.values():
        previous = 0
        for first, last in sorted(values):
            if first < previous:
                raise RuntimeError("Source-layout placements overlap on one track")
            previous = last


def _check_staged_picture(path, expected, fps):
    probe = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-count_frames",
            "-show_streams",
            "-of",
            "json",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    metadata = json.loads(probe.stdout)["streams"][0]
    count = int(metadata.get("nb_read_frames") or 0)
    if count != expected or Fraction(metadata["r_frame_rate"]) != fps:
        raise RuntimeError(
            "Source-layout trim exceeds decoded EOF or exact frame contract: "
            f"frames={count}/{expected}, rate={metadata['r_frame_rate']}/{fps}"
        )


def _stage_picture(source, output, spec, fps):
    from . import proof_executor as native

    item = source["item"]
    region = item["outputRange"]
    count = region["endFrameExclusive"] - region["startFrame"]
    still = item["mediaKind"] == "still"
    arguments = ["-loop", "1", "-framerate", str(fps)] if still else []
    first, last = (0, count) if still else (source["first"], source["last"])
    filters = (
        f"trim=start_frame={first}:end_frame={last},"
        f"settb=expr={fps.denominator}/{fps.numerator},setpts=N,"
        f"scale={spec['width']}:{spec['height']}:force_original_aspect_ratio=decrease,"
        f"pad={spec['width']}:{spec['height']}:(ow-iw)/2:(oh-ih)/2:black,setsar=1,format=bgra"
    )
    native._run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-nostdin",
            *local_source_arguments(source["path"], literal_still=still),
            *arguments,
            "-i",
            str(source["path"]),
            "-map",
            f"0:{source['stream']}",
            "-vf",
            filters,
            "-an",
            "-c:v",
            "ffv1",
            "-r",
            str(fps),
            "-fps_mode",
            "cfr",
            str(output),
        ]
    )
    _check_staged_picture(output, count, fps)


def _compose_picture(staged, output, total, spec, fps, window):
    from . import proof_executor as native

    arguments = [
        "ffmpeg",
        "-v",
        "error",
        "-nostdin",
        "-filter_complex_threads",
        "1",
        "-f",
        "lavfi",
        "-i",
        f"color=black:s={spec['width']}x{spec['height']}:r={fps}",
    ]
    base = f"{fps.denominator}/{fps.numerator}"
    filters = [
        f"[0:v]trim=end_frame={total},settb=expr={base},setpts=N,format=rgba[base]"
    ]
    current = "base"
    for ordinal, (item, path) in enumerate(staged, 1):
        region = item["outputRange"]
        start = region["startFrame"]
        arguments.extend(["-i", str(path)])
        # Shifted PTS and finite input bound the layer; enable drops frames on FFmpeg 6.
        filters.extend(
            [
                f"[{ordinal}:v]settb=expr={base},setpts=N+{start},format=rgba[layer{ordinal}]",
                f"[{current}][layer{ordinal}]overlay=0:0:format=rgb:eof_action=pass:repeatlast=0[picture{ordinal}]",
            ]
        )
        current = f"picture{ordinal}"
    first, last = window
    filters.append(
        f"[{current}]trim=start_frame={first}:end_frame={last},settb=expr={base},setpts=N,format=bgra[window]"
    )
    native._run(
        [
            *arguments,
            "-filter_complex",
            ";".join(filters),
            "-map",
            "[window]",
            "-an",
            "-c:v",
            "ffv1",
            "-r",
            str(fps),
            "-fps_mode",
            "cfr",
            str(output),
        ]
    )
    _check_staged_picture(output, last - first, fps)


def _revalidate_sources(execution, items):
    from . import proof_executor as native

    source_execution = {
        **execution,
        "videoGraph": {"operations": [{"parameters": item} for item in items]},
    }
    native._revalidate_inputs(source_execution, {}, None)


def _sample_boundary(frame, fps):
    seconds = Fraction(frame, 1) / fps
    return sample_rate_boundary(
        seconds.numerator, source_rate=seconds.denominator, target_rate=48000
    )


def _window(execution, total, fps):
    from . import proof_executor as native

    extent = {"startSample": 0, "endSampleExclusive": _sample_boundary(total, fps)}
    operations = execution["audioGraph"]["operations"]
    encodes = [op for op in operations if op["kind"] == "encode"]
    if len(encodes) != 1 or any(
        op["parameters"] or op["range"] != extent
        for op in operations
        if op["kind"] in {"mix", "encode"}
    ):
        raise RuntimeError(
            "Placed mix and one final encode must cover the exact program"
        )
    window = execution["window"]
    first, last = (
        (0, total)
        if window is None
        else native._bounds(window, "startFrame", "endFrameExclusive")
    )
    if last > total:
        raise RuntimeError("Microproof window exceeds placed program")
    return first, last


def _render(execution, output, admitted, total, spec, fps, resolver, window):
    from . import proof_executor as native

    if output.exists():
        raise RuntimeError(f"Refusing to replace existing proof: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    with (
        fingerprint_stage(),
        tempfile.TemporaryDirectory(
            prefix="proof-placed-", dir=output.parent
        ) as folder,
    ):
        directory = Path(folder)
        staged = []
        ordered = sorted(
            admitted,
            key=lambda value: (value["item"]["zOrder"], value["item"]["placementId"]),
        )
        for source in ordered:
            if not source["item"]["enabled"]:
                continue
            path = directory / f"picture-{len(staged):04d}.mkv"
            _stage_picture(source, path, spec, fps)
            staged.append((source["item"], path))
        picture = directory / "program.mkv"
        _compose_picture(staged, picture, total, spec, fps, window)
        listing = directory / "concat.txt"
        listing.write_text("file 'program.mkv'\n", encoding="utf-8")
        mixed = directory / "mix.wav"
        sample_window = tuple(_sample_boundary(frame, fps) for frame in window)
        audio = render_proof_audio_mix(
            execution["audioGraph"],
            mixed,
            source_resolver=resolver,
            window=sample_window,
        )
        candidate = directory / (
            "candidate.mkv" if spec.get("conformance") is True else "candidate.mp4"
        )
        media, metadata = native._render_final(
            listing, candidate, [], spec, fps, *window, mixed_audio=mixed
        )
        _revalidate_sources(execution, [source["item"] for source in admitted])
        candidate.replace(output)
    return media, audio, metadata


def execute_placed_proof(execution, output, spec, fps, rate):
    from . import proof_executor as native

    if rate != 48000:
        raise RuntimeError("Placed source assembly requires 48000 Hz audio")
    items, total = _operation(execution)
    cache = {}
    admitted = _admit_picture(execution, items, total, fps, cache)

    def resolver(node, parameters):
        return native._source(
            parameters, execution["canonicalInputLock"], cache, audio_node=node
        )

    native._validate_resampling(
        execution["audioGraph"], execution["audioGraph"]["nodes"], rate
    )
    compiled = validate_proof_audio_mix(
        execution["audioGraph"], source_resolver=resolver
    )
    if compiled["durationSamples"] != _sample_boundary(total, fps):
        raise RuntimeError("Placed audio graph contradicts exact program duration")
    window = _window(execution, total, fps)
    native._validate_events(execution, {})
    media, audio, metadata = _render(
        execution, output, admitted, total, spec, fps, resolver, window
    )
    return {
        "status": "pass",
        "output": file_fingerprint(output),
        "path": str(output),
        "audioEncodeCount": 1,
        "audioMix": audio,
        "producer": {"name": "avo.ffmpeg-proof-plan", "version": "1"},
        "media": media,
        "sourceVideoTailPolicies": [],
        "sourceDialogueNoisePolicies": [],
        "sourceDialogueTreatmentPolicies": [],
        "generatedOperations": [],
        "overlayOperations": metadata,
    }
