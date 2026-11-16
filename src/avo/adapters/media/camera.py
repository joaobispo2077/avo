"""Sealed numeric source-picture resampling, before independent composition.

Only typed paths become FFmpeg expressions. This module neither opens sources
nor declares a proof implementation ready. Its caller must supply freshly
verified source bytes, measured stream metadata and an exact picture clock.
"""

from __future__ import annotations

import math
from copy import deepcopy
from fractions import Fraction
from itertools import pairwise

from avo.timeline.camera import MAX_SCHEDULE_FRAMES, display_size, evaluate_camera
from avo.timeline.contracts import content_hash, validate_document

_OUTPUT_BITS = {
    "yuv420p": 8,
    "yuv420p10le": 10,
    "yuv444p10le": 10,
    "gbrp16le": 16,
}
_SOURCE_BITS = {
    "rgb24": 8,
    "bgr24": 8,
    "gbrp": 8,
    "yuv420p": 8,
    "yuv422p": 8,
    "yuv444p": 8,
    **{
        f"{family}{bits}le": bits
        for family in ("gbrp", "yuv420p", "yuv422p", "yuv444p")
        for bits in (9, 10, 12, 14, 16)
    },
}
_ALPHA_SOURCE_BITS = {
    **dict.fromkeys(
        ("rgba", "bgra", "argb", "abgr", "gbrap", "yuva420p", "yuva444p"), 8
    ),
    **{
        f"{family}{bits}le": bits
        for family in ("gbrap", "yuva420p", "yuva422p", "yuva444p")
        for bits in (9, 10, 12, 16)
    },
}


class CameraRenderError(ValueError):
    """Source framing cannot be rendered by this explicitly bounded profile."""


def camera_input_arguments(stream):
    """Camera owns physical orientation; consume the copied stream marker too."""
    if type(stream) is not int or stream < 0:
        raise CameraRenderError("camera input requires its verified video stream index")
    return ["-noautorotate", f"-display_rotation:{stream}", "0"]


def camera_groups(execution, registry):
    """Bind typed camera operations to actual original-picture occurrences."""
    selected = [
        op
        for op in execution["videoGraph"]["operations"]
        if op["kind"] == "camera-transform"
    ]
    if not selected:
        return {}
    _require_camera_implementation(execution, registry)
    originals = _original_contributions(execution)
    groups = {}
    for operation in selected:
        source_id = operation.get("parameters", {}).get("sourceId")
        parameters = _validated_path(
            operation, execution["canonicalInputLock"].get(f"source:{source_id}")
        )
        target = originals.get(parameters["sourceOccurrenceId"])
        _matching_contribution(operation, target)
        groups.setdefault(target["operationId"], []).append(deepcopy(operation))
    return groups


def _original_contributions(execution):
    originals = {}
    for operation in execution["videoGraph"]["operations"]:
        if operation["kind"] == "trim":
            originals[operation["operationId"]] = operation
        elif operation["kind"] == "source-layout":
            for item in operation["parameters"]["placements"]:
                if item["enabled"] and item["mediaKind"] == "video":
                    originals[item["placementId"]] = {
                        "operationId": item["placementId"],
                        "outputRange": item["outputRange"],
                        "parameters": item,
                    }
    return originals


def _require_camera_implementation(execution, registry):
    if execution.get("schemaVersion") != "2.0.0" or execution.get(
        "requiredReaderCapabilities"
    ) != ["camera-transform-v1"]:
        raise CameraRenderError(
            "camera execution requires its explicit v2 reader contract"
        )
    implementation = registry.resolve(
        "camera-transform-v1", implementation_id="impl-camera-transform"
    )
    references = {
        item["implementationId"]: item for item in execution["implementationRefs"]
    }
    if (
        implementation is None
        or references.get("impl-camera-transform") != implementation.proof_reference()
    ):
        raise CameraRenderError(
            "camera implementation is unavailable or its frozen identity changed"
        )


def _matching_contribution(operation, contribution):
    parameters, region = operation["parameters"], operation["outputRange"]
    if (
        contribution is None
        or contribution["parameters"]["sourceId"] != parameters["sourceId"]
    ):
        raise CameraRenderError(
            "camera must target an exact original-source picture occurrence"
        )
    source, extent = contribution["parameters"], contribution["outputRange"]
    if (
        source["source"].get("mediaClass") != "source"
        or source.get("videoTailPolicy")
        or source.get("pictureSampling")
        or source.get("pictureEndGapFrames")
        or source.get("pictureFade")
        or source.get("trackId", parameters["targetLayerId"])
        != parameters["targetLayerId"]
    ):
        raise CameraRenderError(
            "camera source ancestry or padded-picture profile is not qualified"
        )
    if (
        not extent["startFrame"]
        <= region["startFrame"]
        < region["endFrameExclusive"]
        <= extent["endFrameExclusive"]
    ):
        raise CameraRenderError(
            "camera interval exceeds its original source occurrence"
        )


def bind_camera_source(
    operations, *, metadata, output, source_sha256, first_frame, end_frame
):
    """Prevalidate the complete contribution before any output directory exists."""
    camera_filter(
        operations,
        metadata=metadata,
        output=output,
        source_sha256=source_sha256,
        first_frame=first_frame,
        end_frame=end_frame,
    )
    return {
        "operations": deepcopy(operations),
        "metadata": deepcopy(metadata),
        "sourceSha256": source_sha256,
    }


def _number(value):
    result = float(value)
    if not math.isfinite(result):
        raise CameraRenderError("camera filter requires finite numeric values")
    return format(result, ".17g")


def _rotation(metadata):
    observed = [
        item["rotation"]
        for item in metadata.get("side_data_list", [])
        if "rotation" in item
    ]
    if "rotate" in metadata.get("tags", {}):
        observed.append(metadata["tags"]["rotate"])
    rotations = set()
    for value in observed or [0]:
        actual = float(value)
        if not math.isfinite(actual) or abs(actual / 90 - round(actual / 90)) > 1e-6:
            raise CameraRenderError("source rotation is not a qualified right angle")
        rotations.add(round(actual / 90) * 90 % 360)
    if len(rotations) != 1:
        raise CameraRenderError("source rotation metadata conflicts")
    return rotations.pop()


def _measured_geometry(geometry, metadata):
    try:
        aspect = Fraction(metadata["sample_aspect_ratio"].replace(":", "/"))
        expected = geometry["sampleAspectRatio"]
        matches = (
            metadata["width"] == geometry["codedWidth"]
            and metadata["height"] == geometry["codedHeight"]
            and aspect == Fraction(expected["num"], expected["den"])
            and _rotation(metadata) == geometry["rotationDegrees"] % 360
        )
    except (KeyError, TypeError, ValueError, ZeroDivisionError) as error:
        raise CameraRenderError(
            "measured source display geometry is unavailable"
        ) from error
    if not matches:
        raise CameraRenderError(
            "measured source geometry differs from the frozen camera source"
        )


def _source_depth(metadata, allow_alpha):
    depth = _SOURCE_BITS.get(metadata.get("pix_fmt"))
    if depth is None and allow_alpha:
        depth = _ALPHA_SOURCE_BITS.get(metadata.get("pix_fmt"))
    return depth


def _fidelity(metadata, output, *, allow_alpha=False):
    depth = _source_depth(metadata, allow_alpha)
    target = _OUTPUT_BITS.get(output.get("pixelFormat"))
    if depth is None or target is None:
        raise CameraRenderError(
            "source/output pixel format is not qualified for camera resampling"
        )
    if target < depth:
        raise CameraRenderError(
            "selected camera output would reduce original source bit depth"
        )
    if (
        metadata.get("color_transfer") in {"smpte2084", "arib-std-b67"}
        or metadata.get("color_space") in {"bt2020nc", "bt2020c", "ictcp"}
        or metadata.get("color_primaries") in {"bt2020", "smpte431", "smpte432"}
    ):
        raise CameraRenderError("HDR/wide-gamut camera resampling is not qualified")
    if any(
        type(output.get(key)) is not int or not 1 <= output[key] <= 8192
        for key in ("width", "height")
    ):
        raise CameraRenderError(
            "camera output dimensions exceed the qualified 1..8192 pixel range"
        )


def _validated_path(operation, source_sha256):
    validate_document(operation, "avo.proof-plan.v2.schema.json#/$defs/cameraOperation")
    parameters = operation["parameters"]
    behavior, geometry = parameters["behavior"], parameters["geometry"]
    if (
        parameters["sourceSha256"] != source_sha256
        or operation["inputs"] != [parameters["sourceId"]]
        or behavior.get("sourceId") != parameters["sourceId"]
        or behavior["targetLayerId"] != parameters["targetLayerId"]
    ):
        raise CameraRenderError(
            "camera source/layer identity differs from the verified original"
        )
    if parameters["pathHash"] != content_hash(
        {"behavior": behavior, "geometry": geometry}
    ):
        raise CameraRenderError(
            "camera path hash differs from its typed numeric intent"
        )
    interval = parameters["originalFrameRange"]
    initial = evaluate_camera(
        behavior, frame=interval["firstFrame"], frame_range=interval, geometry=geometry
    )
    if parameters["entryState"] != initial:
        raise CameraRenderError("camera entry state differs from its original path")
    return parameters


def _validated_operations(operations, source_sha256, metadata):
    if len(operations) > 512:
        raise CameraRenderError("camera source occurrence exceeds its operation budget")
    identity, geometry = None, None
    selected = []
    for operation in operations:
        parameters = _validated_path(operation, source_sha256)
        actual = tuple(
            parameters[key]
            for key in ("sourceId", "sourceOccurrenceId", "targetLayerId")
        )
        if identity is not None and (
            actual != identity or geometry != parameters["geometry"]
        ):
            raise CameraRenderError(
                "camera filter mixes different source occurrences or baselines"
            )
        identity, geometry = actual, parameters["geometry"]
        selected.append(operation)
    _measured_geometry(geometry, metadata)
    selected.sort(key=lambda operation: operation["outputRange"]["startFrame"])
    for previous, current in pairwise(selected):
        if (
            previous["outputRange"]["endFrameExclusive"]
            > current["outputRange"]["startFrame"]
        ):
            raise CameraRenderError("camera source has overlapping property owners")
    return selected, geometry


def _validate_window(operations, first, end):
    if (
        type(first) is not int
        or type(end) is not int
        or not 0 <= first < end
        or end - first > MAX_SCHEDULE_FRAMES
    ):
        raise CameraRenderError(
            "camera render window requires a bounded exact frame interval"
        )
    earliest = operations[0]["outputRange"]["startFrame"]
    for frame in range(max(first, earliest), end):
        active = next(
            (
                operation
                for operation in operations
                if operation["outputRange"]["startFrame"]
                <= frame
                < operation["outputRange"]["endFrameExclusive"]
            ),
            None,
        )
        if active is None:
            raise CameraRenderError(
                "camera occurrence has an unresolved hold or uncovered frame"
            )
        parameters = active["parameters"]
        evaluate_camera(
            parameters["behavior"],
            frame=frame,
            frame_range=parameters["originalFrameRange"],
            geometry=parameters["geometry"],
        )


def _eased(curve, phase):
    formulas = {
        "hold": "0",
        "linear": phase,
        "quadratic-in": f"pow({phase},2)",
        "quadratic-out": f"1-pow(1-({phase}),2)",
        "quadratic-in-out": f"if(lt({phase},0.5),2*pow({phase},2),1-2*pow(1-({phase}),2))",
        "quartic-in": f"pow({phase},4)",
        "exponential-out": f"1-pow(2,-10*({phase}))",
    }
    return f"if(gte({phase},1),1,if(lte({phase},0),0,{formulas[curve]}))"


def _node_value(node, field):
    return node["scale"] if field == "scale" else node["center"][field]


def _path_value(parameters, field):
    interval = parameters["originalFrameRange"]
    count = interval["endFrameExclusive"] - interval["firstFrame"]
    nodes = parameters["behavior"]["nodes"]
    if count == 1:
        return _number(_node_value(nodes[0], field))
    phase = f"clip((ld(0)-{interval['firstFrame']})/{count - 1},0,1)"
    result = _number(_node_value(nodes[-1], field))
    for left, right in reversed(list(pairwise(nodes))):
        start, stop = Fraction(str(left["phase"])), Fraction(str(right["phase"]))
        local = f"clip((({phase})-{_number(start)})/{_number(stop - start)},0,1)"
        beginning = _node_value(left, field)
        delta = _node_value(right, field) - beginning
        value = f"({_number(beginning)}+({_number(delta)})*({_eased(left['curve'], local)}))"
        result = f"if(lte({phase},{_number(stop)}),{value},{result})"
    return result


def _selected_value(operations, field):
    result = "1" if field == "scale" else "0.5"
    for operation in reversed(operations):
        region = operation["outputRange"]
        value = _path_value(operation["parameters"], field)
        result = f"if(between(ld(0),{region['startFrame']},{region['endFrameExclusive'] - 1}),{value},{result})"
    return result


def _resample_expression(operations, geometry, first):
    baseline = geometry["baselineCrop"]
    width, height = display_size(geometry)
    prefix = (
        f"st(0,N+{first});"
        + ";".join(
            f"st({index},{_selected_value(operations, field)})"
            for index, field in enumerate(("scale", "x", "y"), 1)
        )
        + ";"
    )
    x = f"(({_number(baseline['x'])}+{_number(baseline['width'])}*ld(2)-{_number(baseline['width'])}/(2*ld(1)))*(W-1)/{_number(width)}+X*{_number(baseline['width'])}/(ld(1)*{_number(width)}))"
    y = f"(({_number(baseline['y'])}+{_number(baseline['height'])}*ld(3)-{_number(baseline['height'])}/(2*ld(1)))*(H-1)/{_number(height)}+Y*{_number(baseline['height'])}/(ld(1)*{_number(height)}))"
    # Every expression initializes its own registers at every pixel and frame.
    # No stored value survives as a clock or as mutable camera state.
    return ":".join(
        f"{channel}='{prefix}{channel}({x},{y})'" for channel in ("r", "g", "b")
    )


def camera_filter(
    operations, *, metadata, output, source_sha256, first_frame, end_frame
):
    """Produce only sealed numeric filters for one verified source occurrence.

    N starts at zero in a window; the original global frame offset is explicit.
    Internal RGB samples remain 16-bit. Unsupported source/fidelity profiles fail
    instead of negotiating a hidden 8-bit intermediate.
    """
    if not operations:
        return None
    try:
        operations, geometry = _validated_operations(
            operations, source_sha256, metadata
        )
        _fidelity(metadata, output)
        _validate_window(operations, first_frame, end_frame)
        expression = _resample_expression(operations, geometry, first_frame)
        if len(expression) > 2 * 1024 * 1024:
            raise CameraRenderError(
                "camera expression exceeds its explicit render budget"
            )
        orientation = {
            0: "",
            90: "transpose=cclock,",
            180: "hflip,vflip,",
            270: "transpose=clock,",
        }[geometry["rotationDegrees"] % 360]
        # Older geq bilinear readers clamp to W-2/H-2. An exact replicated
        # edge gives them the same final real pixel and subpixel boundary as
        # newer readers. Expressions use the original dimensions; the private
        # extra row/column are removed before output resampling.
        return (
            orientation + "sidedata=mode=delete:type=DISPLAYMATRIX,"
            "scale=iw:ih:flags=bilinear,format=gbrp16le,"
            "pad=iw+1:ih+1:0:0:color=black,fillborders=right=1:bottom=1:mode=smear,geq="
            + expression
            + ":interpolation=bilinear,crop=w=iw-1:h=ih-1:x=0:y=0:exact=1,"
            f"scale={output['width']}:{output['height']}:flags=bilinear,setsar=1,format={output['pixelFormat']}"
        )
    except (ValueError, TypeError, KeyError, OverflowError, RecursionError) as error:
        if isinstance(error, CameraRenderError):
            raise
        raise CameraRenderError(f"camera source framing is invalid: {error}") from error
