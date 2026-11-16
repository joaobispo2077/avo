"""Explicit high-precision placed-picture composition, sharing native layer clocks."""

from __future__ import annotations

from . import proof_generated


def picture_format(spec, *, layer=False):
    if "pixelFormat" in spec:
        return "gbrap16le" if layer else "gbrp16le"
    return "bgra"


def picture_bytes(spec, *, layer=False):
    if "pixelFormat" in spec:
        return 8 if layer else 6
    return 4


def opaque_alpha_filter(chain):
    # Plane copies avoid libswscale's RGB-to-RGBA matrix round trip, which can
    # change 16-bit RGB values even when geometry and bit depth stay identical.
    return (
        chain + ",split=2[opaque-color][opaque-mask];"
        "[opaque-mask]extractplanes=g,geq=lum=65535[opaque-alpha];"
        "[opaque-color][opaque-alpha]mergeplanes="
        "map0s=0:map0p=0:map1s=0:map1p=1:map2s=0:map2p=2:map3s=1:map3p=0:format=gbrap16le"
    )


def source_pixel_filter(source, spec, fades):
    if "pixelFormat" not in spec:
        return f"format=rgba{fades},format=bgra"
    if source.get("precisionOpaque"):
        return opaque_alpha_filter("scale=iw:ih:flags=bilinear,format=gbrp16le") + fades
    if source.get("precisionDepth") == 8:
        return (
            proof_generated._promote_alpha8("format=gbrap", "sourcepromotion") + fades
        )
    return f"scale=iw:ih:flags=bilinear,format=gbrap16le{fades}"


def admit_camera_placements(execution, admitted, cache, spec, fps):
    from . import proof_executor as native
    from .camera import (
        _SOURCE_BITS,
        _fidelity,
        _source_depth,
        bind_camera_source,
        camera_groups,
    )
    from .proof_placed import _scaled_transform

    groups = camera_groups(execution, native.default_proof_capability_registry())
    for source in admitted:
        item = source["item"]
        if item["mediaKind"] == "title":
            continue
        path, stream = source["path"], source["stream"]
        observed = cache[str(path.resolve())]
        metadata = next(
            value for value in observed["streams"] if value["index"] == stream
        )
        _fidelity(metadata, spec, allow_alpha=True)
        source["precisionOpaque"] = metadata["pix_fmt"] in _SOURCE_BITS
        source["precisionDepth"] = _source_depth(metadata, True)
        operations = groups.get(item["placementId"])
        if not operations:
            continue
        target = _scaled_transform(item, spec) or spec
        output = {**spec, "width": target["width"], "height": target["height"]}
        extent = item["outputRange"]
        source["camera"] = bind_camera_source(
            operations,
            metadata=metadata,
            output=output,
            source_sha256=observed["sha256"],
            first_frame=extent["startFrame"],
            end_frame=extent["endFrameExclusive"],
        )
        source["camera"]["output"] = output


def camera_picture_arguments(source, spec, fps, *, start_frame, stop_frame):
    from .camera import camera_filter, camera_input_arguments

    region = source["item"]["outputRange"]
    first = max(region["startFrame"], start_frame)
    last = min(region["endFrameExclusive"], stop_frame or region["endFrameExclusive"])
    if first >= last:
        raise RuntimeError("Camera placement does not intersect the requested window")
    binding = source["camera"]
    chain = camera_filter(
        binding["operations"],
        metadata=binding["metadata"],
        output=binding["output"],
        source_sha256=binding["sourceSha256"],
        first_frame=first,
        end_frame=last,
    )
    left = source["first"] + first - region["startFrame"]
    base = f"{fps.denominator}/{fps.numerator}"
    filters = opaque_alpha_filter(
        f"trim=start_frame={left}:end_frame={left + last - first},settb=expr={base},setpts=N,"
        f"{chain}"
    )
    return [
        "ffmpeg",
        "-v",
        "error",
        "-nostdin",
        *camera_input_arguments(source["stream"]),
        "-i",
        str(source["path"]),
        "-map",
        f"0:{source['stream']}",
        "-vf",
        filters,
        "-an",
        "-frames:v",
        str(last - first),
        "-r",
        str(fps),
        "-fps_mode",
        "cfr",
    ], last - first


def compose_picture(staged, output, spec, fps, window, *, raw):
    from . import proof_executor as native
    from .proof_placed import _check_staged_picture, _scaled_transform

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
        f"[0:v]trim=end_frame={last - first},settb=expr={base},setpts=N,format=gbrp16le[base]"
    ]
    current = "base"
    for ordinal, (item, path) in enumerate(staged, 1):
        if isinstance(path, dict):
            arguments.extend(
                [
                    "-f",
                    "rawvideo",
                    "-pixel_format",
                    picture_format(spec, layer=True),
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
        transform = _scaled_transform(item, spec) or {"x": 0, "y": 0, **spec}
        operation = {
            "outputRange": item["outputRange"],
            "parameters": {
                "sourceRange": {"startFrame": 0},
                "placement": {
                    key: transform[key] for key in ("x", "y", "width", "height")
                },
            },
        }
        filters.extend(
            proof_generated._precision_overlay_planes(
                operation,
                ordinal,
                fps,
                first,
                last,
                item["outputRange"]["startFrame"],
                item["outputRange"]["endFrameExclusive"],
                (spec["width"], spec["height"]),
                alpha8=False,
            )
        )
        target = f"picture{ordinal}"
        filters.append(
            f"[{current}][color{ordinal}][mask{ordinal}]maskedmerge=planes=7[{target}]"
        )
        current = target
    filters.append(
        f"[{current}]trim=end_frame={last - first},settb=expr={base},setpts=N,format=gbrp16le[window]"
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
            "-pix_fmt",
            "gbrp16le",
            "-r",
            str(fps),
            "-fps_mode",
            "cfr",
            *(["-f", "rawvideo"] if raw else []),
            str(output),
        ]
    )
    if raw:
        if output.stat().st_size != (last - first) * spec["width"] * spec[
            "height"
        ] * picture_bytes(spec):
            raise RuntimeError(
                "Precision composition violates its exact frame contract"
            )
    else:
        _check_staged_picture(output, last - first, fps)
