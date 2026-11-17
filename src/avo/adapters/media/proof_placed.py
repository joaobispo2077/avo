"""Render canonical original-source placements on one absolute program clock."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
from fractions import Fraction
from math import ceil, floor
from pathlib import Path

from avo.capabilities import _PROOF_CODE_PATHS, default_proof_capability_registry
from avo.timeline.contracts import content_hash, file_fingerprint, fingerprint_stage
from avo.timeline.event_clock import sample_rate_boundary
from avo.timeline.import_layout import (
    picture_input_ids,
    picture_source_rate,
    validate_picture_operations,
    validate_privacy_masks,
)
from avo.timeline.proof_validation_stage import in_proof_validation_batch

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


def _layout_operation(execution):
    operations = execution["videoGraph"]["operations"]
    layouts = [op for op in operations if op["kind"] == "source-layout"]
    if len(layouts) != 1 or any(
        op["kind"] not in {"source-layout", "overlay-video"} for op in operations
    ):
        raise RuntimeError(
            "Placed proof requires one source-layout and only admitted overlays"
        )
    return layouts[0]


def _operation(execution):
    from . import proof_executor as native

    operation = _layout_operation(execution)
    _require_implementation(execution, operation)
    first, last = native._bounds(
        operation["outputRange"], "startFrame", "endFrameExclusive"
    )
    parameters = operation["parameters"]
    if (
        first
        or set(parameters) - {"privacyMasks"} != {"background", "placements"}
        or parameters["background"] != "black"
    ):
        raise RuntimeError("Source-layout requires an exact black program extent")
    if not isinstance(parameters["placements"], list):
        raise RuntimeError("Source-layout placements must be an explicit list")
    if operation["inputs"] != picture_input_ids(parameters["placements"]):
        raise RuntimeError("Source-layout has unconsumed or missing picture inputs")
    if "privacyMasks" in parameters:
        validate_privacy_masks(parameters["privacyMasks"], last)
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
    if item.get("mediaKind") == "title":
        required.update({"title", "fontSource"})
    if set(item) - {
        "pictureSampling",
        "pictureEndGapFrames",
        "pictureTransform",
        "pictureFade",
    } != required or item["mediaKind"] not in {
        "video",
        "still",
        "title",
    }:
        raise RuntimeError("Unsupported source-layout placement or treatment")
    try:
        picture_source_rate(item, Fraction(1))
    except ValueError as exc:
        raise RuntimeError("Unsupported source-layout picture sampling") from exc
    _placement_identity(item)


def _placement_identity(item):
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
    fps = picture_source_rate(item, fps)
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

    evidence = _verify_picture_clock(
        path, stream, cache, fps, end_gap_frames=item.get("pictureEndGapFrames", 0)
    )
    _, last = _source_frames(item, fps)
    if last > evidence.get("presentationFrameCount", evidence["packetCount"]):
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
        try:
            validate_picture_operations(item, end - start)
        except ValueError as exc:
            raise RuntimeError(str(exc)) from exc
        source_fps = picture_source_rate(item, fps)
        first, last = _source_frames(item, source_fps)
        if end > total or (
            item["mediaKind"] in {"video", "title"}
            and (last - first) * fps / source_fps != end - start
        ):
            raise RuntimeError(
                "Source-layout range contradicts normal-speed program extent"
            )
        if item["mediaKind"] == "still" and first != 0:
            raise RuntimeError(
                "Literal still placement must hold its original first frame"
            )
        if item["mediaKind"] == "title":
            from .proof_title import admit_title

            admitted.append(admit_title(item, execution))
            continue
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


def _scaled_transform(item, spec):
    value = item.get("pictureTransform")
    if value is None:
        return None
    if value["canvasWidth"] * spec["height"] != value["canvasHeight"] * spec["width"]:
        raise RuntimeError("Picture transform preview changes canonical aspect ratio")
    xrate = Fraction(spec["width"], value["canvasWidth"])
    yrate = Fraction(spec["height"], value["canvasHeight"])
    return {
        "x": round(value["x"] * xrate),
        "y": round(value["y"] * yrate),
        "width": max(1, round(value["width"] * xrate)),
        "height": max(1, round(value["height"] * yrate)),
    }


def _picture_fades(item, count):
    fade = item.get("pictureFade", {})
    first, last = fade.get("inFrames", 0), fade.get("outFrames", 0)
    return (f",fade=t=in:start_frame=0:nb_frames={first}:alpha=1" if first else "") + (
        f",fade=t=out:start_frame={count - last}:nb_frames={last}:alpha=1"
        if last
        else ""
    )


def _picture_arguments(source, spec, fps, *, start_frame=0, stop_frame=None):
    item = source["item"]
    region = item["outputRange"]
    offset = max(0, start_frame - region["startFrame"])
    original_count = region["endFrameExclusive"] - region["startFrame"]
    count = (
        original_count
        if stop_frame is None
        else min(original_count, stop_frame - region["startFrame"])
    )
    if count <= offset:
        raise RuntimeError("Source picture does not intersect the requested window")
    still = item["mediaKind"] == "still"
    arguments = ["-loop", "1", "-framerate", str(fps)] if still else []
    first, last = (0, count) if still else (source["first"], source["last"])
    source_fps = picture_source_rate(item, fps)
    last = min(last, first + -(-(count * source_fps) // fps))
    sampling = f"fps={fps}:start_time=0:round=near," if source_fps != fps else ""
    transform = _scaled_transform(item, spec)
    sizing = (
        f"scale={transform['width']}:{transform['height']}"
        if transform
        else f"scale={spec['width']}:{spec['height']}:force_original_aspect_ratio=decrease,"
        f"pad={spec['width']}:{spec['height']}:(ow-iw)/2:(oh-ih)/2:black"
    )
    filters = (
        (
            f"fps={source_fps}:start_time=0:round=near:eof_action=pass,"
            if item.get("pictureEndGapFrames")
            else ""
        )
        + f"trim=start_frame={first}:end_frame={last},"
        f"settb=expr={source_fps.denominator}/{source_fps.numerator},setpts=N,"
        f"{sampling}"
        f"settb=expr={fps.denominator}/{fps.numerator},setpts=N,trim=end_frame={count},"
        f"{sizing},setsar=1,format=rgba{_picture_fades(item, original_count)},format=bgra,"
        f"trim=start_frame={offset},setpts=PTS-STARTPTS"
    )
    return (
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
            "-frames:v",
            str(count - offset),
            "-r",
            str(fps),
            "-fps_mode",
            "cfr",
        ],
        count - offset,
    )


def _stage_picture(source, output, spec, fps, *, start_frame=0, stop_frame=None):
    from . import proof_executor as native

    if source["item"]["mediaKind"] == "title":
        from .proof_title import render_title

        item = source["item"]
        region = item["outputRange"]
        original_count = region["endFrameExclusive"] - region["startFrame"]
        count = (
            original_count
            if stop_frame is None
            else min(original_count, stop_frame - region["startFrame"])
        )
        offset = max(0, start_frame - region["startFrame"])
        render_title(
            source,
            output,
            spec,
            fps,
            count,
            _picture_fades(item, original_count),
            start_frame=offset,
        )
        _check_staged_picture(output, count - offset, fps)
        return
    arguments, count = _picture_arguments(
        source, spec, fps, start_frame=start_frame, stop_frame=stop_frame
    )
    native._run([*arguments, "-c:v", "ffv1", str(output)])
    _check_staged_picture(output, count, fps)


def _stage_cache_enabled(execution):
    lock = execution.get("canonicalInputLock") or {}
    hashes = [execution.get("proofPlanHash")]
    hashes.extend(
        lock.get(name) for name in ("cmap", "bmap", "tracks", "animation", "sync-map")
    )
    return all(
        isinstance(value, str) and re.fullmatch("[0-9a-f]{64}", value)
        for value in hashes
    )


def _stage_cache_fingerprints(source):
    from avo.timeline.proof_validation_stage import track_proof_dependency

    executables = [shutil.which(name) for name in ("ffmpeg", "ffprobe")]
    if any(path is None for path in executables):
        raise RuntimeError("Placed stage cache requires installed FFmpeg/FFprobe")
    paths = {
        Path(path).resolve()
        for path in [*executables, *_PROOF_CODE_PATHS, source["path"]]
    }
    fingerprints = [file_fingerprint(path) for path in sorted(paths)]
    for fingerprint in fingerprints:
        track_proof_dependency(fingerprint)
    if file_fingerprint(source["path"])["sha256"] != source["item"]["source"]["sha256"]:
        raise RuntimeError("Placed stage cache original source fingerprint changed")
    return fingerprints


def _stage_cache_capacity(source, parent, spec):
    region = source["item"]["outputRange"]
    transform = _scaled_transform(source["item"], spec) or spec
    width, height = (max(spec[key], transform[key]) for key in ("width", "height"))
    # Conservative uncompressed BGRA plus codec/container overhead and I/O buffers.
    budget = (region["endFrameExclusive"] - region["startFrame"]) * width * height * 4
    return shutil.disk_usage(parent).free >= budget * 11 // 10 + 256 * 1024**2


def _stage_cache_directory(parent, observations, resources):
    parent = parent.resolve()
    key = ("placed-video-stage-directory", str(parent))
    if key not in observations:
        directory = Path(tempfile.mkdtemp(prefix="placed-video-stages-", dir=parent))
        initial_root = directory.resolve()
        _checked_stage_cache_root(directory, initial_root, parent)
        resources.callback(
            _remove_stage_cache_directory, directory, initial_root, parent
        )
        observations[key] = directory
    return observations[key]


def _checked_stage_cache_root(directory, initial_root, parent):
    target = directory.resolve()
    if target != initial_root or target == parent or not target.is_relative_to(parent):
        raise RuntimeError(f"Unsafe placed stage cache cleanup target: {directory}")
    return target


def _remove_stage_cache_directory(directory, initial_root, parent):
    target = _checked_stage_cache_root(directory, initial_root, parent)
    # Owned stages are flat: never traverse an unexpected directory or reparse entry.
    for child in target.iterdir():
        attributes = getattr(child.lstat(), "st_file_attributes", 0)
        if (
            attributes & 0x400
            or child.is_symlink()
            or child.is_dir()
            or not child.resolve().is_relative_to(initial_root)
        ):
            raise RuntimeError(f"Unsafe placed stage cache descendant: {child}")
    shutil.rmtree(target)


def _stage_file_signature(path):
    stat = path.stat()
    return (stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns, stat.st_dev, stat.st_ino)


def _publish_stage_cache(source, directory, key, provenance, spec, fps):
    from avo.timeline.proof_validation_stage import track_proof_dependency
    from avo.timeline.store import write_immutable_json

    stage = directory / f"stage-{key}.mkv"
    _stage_picture(source, stage, spec, fps, start_frame=0, stop_frame=None)
    fingerprint = file_fingerprint(stage)
    receipt = directory / f"stage-{key}.json"
    write_immutable_json(
        receipt,
        {
            "kind": "original-placement-video-stage",
            "provenance": provenance,
            "output": fingerprint,
        },
    )
    files = [fingerprint, file_fingerprint(receipt)]
    for item in files:
        track_proof_dependency(item)
    return {
        "path": stage,
        "files": [
            (item, _stage_file_signature(Path(item["locator"]))) for item in files
        ],
    }


def _require_stage_cache_files(entry):
    for fingerprint, expected in entry["files"]:
        path = Path(fingerprint["locator"])
        if not path.is_file() or _stage_file_signature(path) != expected:
            raise RuntimeError(f"Placed stage cache file changed or missing: {path}")


def _cached_video_stage(execution, source, parent, spec, fps):
    from avo.timeline.proof_validation_stage import (
        proof_batch_resources,
        proof_pixel_observations,
    )

    observations, resources = proof_pixel_observations(), proof_batch_resources()
    if observations is None or resources is None or not _stage_cache_enabled(execution):
        return None
    provenance = {
        "proofPlanHash": execution["proofPlanHash"],
        "canonicalInputLock": execution["canonicalInputLock"],
        "placement": source["item"],
        "renderContract": spec,
        "frameRate": {"num": fps.numerator, "den": fps.denominator},
        "streamIndex": source["stream"],
        "sourceFirstFrame": source["first"],
        "sourceLastFrame": source["last"],
        "implementationRefs": execution["implementationRefs"],
        "sourceAndGeneratorInputs": _stage_cache_fingerprints(source),
    }
    key = ("placed-video-stage", content_hash(provenance))
    if key not in observations:
        if not _stage_cache_capacity(source, parent, spec):
            return (
                None  # Preserve bounded direct rendering when a full stage cannot fit.
            )
        directory = _stage_cache_directory(parent, observations, resources)
        observations[key] = _publish_stage_cache(
            source, directory, key[1], provenance, spec, fps
        )
    entry = observations[key]
    _require_stage_cache_files(entry)
    return entry["path"]


def _slice_cached_stage(source, cached, output, fps, window):
    from . import proof_executor as native

    region = source["item"]["outputRange"]
    first = max(0, window[0] - region["startFrame"])
    last = min(region["endFrameExclusive"], window[1]) - region["startFrame"]
    native._run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-nostdin",
            "-i",
            str(cached),
            "-map",
            "0:v:0",
            "-vf",
            f"trim=start_frame={first}:end_frame={last},settb=expr={fps.denominator}/{fps.numerator},setpts=N",
            "-an",
            "-c:v",
            "ffv1",
            "-pix_fmt",
            "bgra",
            "-frames:v",
            str(last - first),
            "-r",
            str(fps),
            "-fps_mode",
            "cfr",
            str(output),
        ]
    )
    _check_staged_picture(output, last - first, fps)


def _stage_window_picture(execution, source, output, spec, fps, window, cache_parent):
    cached = None
    if execution["window"] is not None and source["item"]["mediaKind"] == "video":
        cached = _cached_video_stage(execution, source, cache_parent, spec, fps)
    if cached is None:
        _stage_picture(
            source, output, spec, fps, start_frame=window[0], stop_frame=window[1]
        )
    else:
        _slice_cached_stage(source, cached, output, fps, window)


def _privacy_filters(value, current, filters, spec, *, frame_offset=0):
    if value is None:
        return current
    scale = Fraction(spec["width"], value["canvasWidth"])
    if scale != Fraction(spec["height"], value["canvasHeight"]):
        raise RuntimeError("Privacy mask preview changes canonical aspect ratio")
    for ordinal, region in enumerate(value["regions"]):
        x, y = floor(region["x"] * scale), floor(region["y"] * scale)
        width = ceil((region["x"] + region["width"]) * scale) - x
        height = ceil((region["y"] + region["height"]) * scale) - y
        target = f"privacy{ordinal}"
        filters.append(
            f"[{current}]drawbox=x={x}:y={y}:w={width}:h={height}:color=black:t=fill:"
            f"enable='gte(n+{frame_offset},{region['startFrame']})*lt(n+{frame_offset},{region['endFrameExclusive']})'[{target}]"
        )
        current = target
    return current


def _compose_picture(
    staged, output, spec, fps, window, privacy_masks=None, *, raw=False
):
    from . import proof_executor as native

    first, last = window
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
        f"[0:v]trim=end_frame={last - first},settb=expr={base},setpts=N,format=rgba[base]"
    ]
    current = "base"
    for ordinal, (item, path) in enumerate(staged, 1):
        region = item["outputRange"]
        start = region["startFrame"] - first
        if isinstance(path, dict):
            arguments.extend(
                [
                    "-f",
                    "rawvideo",
                    "-pixel_format",
                    "bgra",
                    "-video_size",
                    f"{path['width']}x{path['height']}",
                    "-framerate",
                    str(fps),
                    "-i",
                    str(path["path"]),
                ]
            )
        else:
            arguments.extend(["-i", str(path)])
        transform = _scaled_transform(item, spec) or {"x": 0, "y": 0}
        # Shifted PTS and finite input bound the layer; enable drops frames on FFmpeg 6.
        filters.extend(
            [
                f"[{ordinal}:v]settb=expr={base},setpts=N+{start},format=rgba[layer{ordinal}]",
                f"[{current}][layer{ordinal}]overlay={transform['x']}:{transform['y']}:format=rgb:eof_action=pass:repeatlast=0[picture{ordinal}]",
            ]
        )
        current = f"picture{ordinal}"
    current = _privacy_filters(
        privacy_masks, current, filters, spec, frame_offset=first
    )
    filters.append(
        f"[{current}]trim=end_frame={last - first},settb=expr={base},setpts=N,format=bgra[window]"
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
            "rawvideo" if raw else "ffv1",
            "-r",
            str(fps),
            "-fps_mode",
            "cfr",
            *(["-pix_fmt", "bgra", "-f", "rawvideo"] if raw else []),
            str(output),
        ]
    )
    if raw:
        if output.stat().st_size != (last - first) * spec["width"] * spec["height"] * 4:
            raise RuntimeError("Composed chunk violates its exact frame contract")
    else:
        _check_staged_picture(output, last - first, fps)


def _revalidate_sources(execution, items, generated, validator):
    from . import proof_executor as native

    source_execution = {
        **execution,
        "videoGraph": {
            "operations": [
                {"parameters": value}
                for item in items
                for value in [
                    item,
                    *([item["fontSource"]] if item["mediaKind"] == "title" else []),
                ]
            ]
        },
    }
    native._revalidate_inputs(source_execution, generated, validator)


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


def _render(
    execution,
    output,
    admitted,
    total,
    spec,
    fps,
    resolver,
    window,
    generated,
    generated_asset_validator,
):
    from . import proof_executor as native

    if execution["window"] is None:
        from .proof_bounded import render_bounded

        return render_bounded(
            execution,
            output,
            admitted,
            total,
            spec,
            fps,
            resolver,
            generated,
            generated_asset_validator,
        )

    overlays = native._proof_overlays(generated, total)
    if output.exists():
        raise RuntimeError(f"Refusing to replace existing proof: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    with (
        fingerprint_stage(reuse_current=in_proof_validation_batch()),
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
            item = source["item"]
            region = item["outputRange"]
            if (
                not item["enabled"]
                or region["endFrameExclusive"] <= window[0]
                or region["startFrame"] >= window[1]
            ):
                continue
            path = directory / f"picture-{len(staged):04d}.mkv"
            _stage_window_picture(
                execution, source, path, spec, fps, window, output.parent
            )
            staged.append(
                (
                    {
                        **item,
                        "outputRange": {
                            "startFrame": max(region["startFrame"], window[0]),
                            "endFrameExclusive": min(
                                region["endFrameExclusive"], window[1]
                            ),
                        },
                    },
                    path,
                )
            )
        picture = directory / "program.mkv"
        _compose_picture(
            staged,
            picture,
            spec,
            fps,
            window,
            _layout_operation(execution)["parameters"].get("privacyMasks"),
        )
        listing = directory / "concat.txt"
        listing.write_text("file 'program.mkv'\n", encoding="utf-8")
        mixed = directory / "mix.wav"
        sample_window = tuple(_sample_boundary(frame, fps) for frame in window)
        # The private mix is deleted here; its fingerprint must not outlive this job.
        with fingerprint_stage():
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
            listing, candidate, overlays, spec, fps, *window, mixed_audio=mixed
        )
        _revalidate_sources(
            execution,
            [source["item"] for source in admitted],
            generated,
            generated_asset_validator,
        )
        candidate.replace(output)
    return media, audio, metadata


def execute_placed_proof(
    execution,
    output,
    spec,
    fps,
    rate,
    *,
    generated_asset_validator=None,
):
    from . import proof_executor as native
    from . import proof_generated

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
    generated = native._generated_inputs(
        execution, spec, fps, generated_asset_validator
    )
    native._validate_events(execution, generated)
    media, audio, metadata = _render(
        execution,
        output,
        admitted,
        total,
        spec,
        fps,
        resolver,
        window,
        generated,
        generated_asset_validator,
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
        "generatedOperations": [
            proof_generated.operation_metadata(asset["operation"])
            for asset in generated.values()
        ],
        "overlayOperations": metadata,
    }
