"""Bind full-canvas generated alpha to a source-preserving validation example."""

from fractions import Fraction
from pathlib import Path

from .contracts import file_fingerprint
from .editor_layout import rational
from .proof_plan import ProofPlanCompiler


def load_alpha_plan(workspace, reference):
    compiler = ProofPlanCompiler(workspace)
    path = compiler.path(reference["id"])
    if path.is_symlink() or path.resolve() != (
        Path(workspace.timeline_dir).resolve() / "proof-plans" / path.name
    ):
        raise ValueError("Select an owned immutable proof plan for generated alpha")
    file_fingerprint(path)
    plan = compiler.load(path)
    if (plan["proofPlanId"], plan["proofPlanHash"]) != (
        reference["id"],
        reference["sha256"],
    ):
        raise ValueError("Generated alpha proof plan identity changed")
    return compiler, path, plan


def _selected_plan(workspace, reference, canvas, fps):
    compiler, _, plan = load_alpha_plan(workspace, reference)
    output = plan["output"]
    rate = output["frameRate"]
    if (output["width"], output["height"], Fraction(rate["num"], rate["den"])) != (
        canvas["width"],
        canvas["height"],
        fps,
    ):
        raise ValueError(
            "Generated alpha proof plan differs from the editor canvas or clock"
        )
    if compiler._canonical_preflight(plan):
        raise ValueError(
            "Generated alpha proof plan must still match the active timeline"
        )
    return plan


def _scope(operation, window):
    extent = operation["outputRange"]
    return {
        "startFrame": max(extent["startFrame"], window["startFrame"]),
        "endFrameExclusive": min(
            extent["endFrameExclusive"], window["endFrameExclusive"]
        ),
    }


def _loss(operation, scope, reason):
    return {"field": operation["operationId"], "scope": scope, "reason": reason}


def _candidate_operations(plan, canvas, window):
    candidates, losses = [], []
    placement = {"x": 0, "y": 0, "width": canvas["width"], "height": canvas["height"]}
    for operation in plan["videoGraph"]["operations"]:
        if operation["kind"] not in {"overlay-video", "generated-clip"}:
            continue
        span = _scope(operation, window)
        if span["startFrame"] >= span["endFrameExclusive"]:
            continue
        params = operation["parameters"]
        if operation["kind"] != "overlay-video" or (
            params["alphaMode"],
            params["placement"],
        ) != ("straight", placement):
            losses.append(
                _loss(operation, span, "Generated placement needs manual finishing")
            )
            continue
        candidates.append(operation)
    return candidates, losses


def _source_path(workspace, operation, roots):
    locator = operation["parameters"]["sourceFingerprint"]["locator"]
    path = Path(locator)
    if not path.is_absolute() or locator.replace("\\", "/").startswith("//"):
        raise ValueError("Generated alpha must use an absolute local path")
    path = path.resolve()
    if not path.is_relative_to(
        (workspace.raw_dir / "edit/derived").resolve()
    ) or not any(path.is_relative_to(root) and path != root for root in roots):
        raise ValueError(
            "Generated alpha is outside the admitted project output folders"
        )


def is_full_canvas_alpha(asset, canvas):
    video = asset["video"]
    return (
        not asset["opaque"]
        and video.get("sample_aspect_ratio") in (None, "1:1")
        and (video.get("width"), video.get("height"), video.get("start_pts"))
        == (canvas["width"], canvas["height"], 0)
    )


def _occurrence(asset, fps, window):
    operation, record, video = (asset[key] for key in ("operation", "record", "video"))
    scope = _scope(operation, window)
    first, end = scope["startFrame"], scope["endFrameExclusive"]
    offset = operation["parameters"]["sourceRange"]["startFrame"]
    source_first = offset + first - operation["outputRange"]["startFrame"]
    frames = {
        "start": first - window["startFrame"],
        "end": end - window["startFrame"],
        "in": source_first,
        "out": source_first + end - first,
    }
    identity = "avo-generated-" + operation["operationId"]
    source_id = "avo-generated-" + record["assetId"]
    source = {
        "sourceId": source_id,
        "kind": "generated-alpha",
        "generatedAsset": {
            "id": record["assetId"],
            "sha256": record["recordHash"],
            "original": {
                key: record["output"][key] for key in ("locator", "sizeBytes", "sha256")
            },
        },
        **asset["editorSource"],
    }
    file = {
        "locator": source["locator"],
        "rate": fps,
        "duration": int(video["nb_read_frames"]),
        "originFrame": 0,
        "pictureFormat": {
            "width": video["width"],
            "height": video["height"],
            "pixelAspectRatio": "square",
        },
    }
    clip = {
        **frames,
        "id": identity,
        "name": operation["operationId"],
        "fileId": source_id,
        "rate": fps,
    }
    occurrence = {
        "id": identity,
        "placementId": operation["operationId"],
        "sourceId": source_id,
        "streamIndex": video["index"],
        "sourceOriginTicks": 0,
        "laneId": identity,
        "exactFrames": {key: rational(point) for key, point in frames.items()},
        "serializedFrames": frames,
    }
    return (
        source,
        file,
        {"kind": "video", "outputChannel": None, "clips": [clip]},
        occurrence,
    )


def generated_alpha(workspace, reference, inspect, canvas, fps, window, roots):
    plan = _selected_plan(workspace, reference, canvas, fps)
    operations, losses = _candidate_operations(plan, canvas, window)
    for operation in operations:
        _source_path(workspace, operation, roots)
    selected = {**plan, "videoGraph": {**plan["videoGraph"], "operations": operations}}
    assets = inspect(selected, fps)
    results = []
    for operation in sorted(
        operations, key=lambda row: (row["parameters"]["zOrder"], row["operationId"])
    ):
        asset = assets[operation["operationId"]]
        if "editorSource" in asset:
            results.append(_occurrence(asset, fps, window))
        else:
            losses.append(
                _loss(
                    operation,
                    _scope(operation, window),
                    "Generated alpha geometry or clock needs manual finishing",
                )
            )
    return results, losses
