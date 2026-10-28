"""Validate frozen generated picture inputs and compile alpha placement."""

from __future__ import annotations

import hashlib
import json
import subprocess
from copy import deepcopy
from fractions import Fraction
from pathlib import Path

from avo.timeline.contracts import (
    ContractError,
    document_hash_excluding,
    file_fingerprint,
    validate_document,
)
from avo.timeline.generated_assets import GeneratedAssetService


def _fingerprint(path, expected):
    path = Path(path)
    if not path.is_file():
        raise RuntimeError(f"Generated dependency is missing: {path}")
    actual = file_fingerprint(path)
    if any(
        actual[key] != expected[key]
        for key in ("sha256", "sizeBytes")
        if key in expected
    ):
        raise RuntimeError(f"Generated dependency changed: {path}")
    return actual


def _json(path):
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise RuntimeError(
            f"Cannot read generated dependency {path}: {error}"
        ) from error
    if not isinstance(value, dict):
        raise RuntimeError(f"Generated dependency must be an object: {path}")
    return value


def _closure(record, seen=None, *, admitted=False):
    seen = set() if seen is None else seen
    identity = record["recordHash"]
    if identity in seen:
        raise RuntimeError("Cyclic generated asset ancestry")
    seen.add(identity)
    for item in record["inputs"]:
        fingerprint = item["fingerprint"]
        locator = fingerprint.get("locator")
        if not locator:
            raise RuntimeError(
                f"Generated input has no retained locator: {item['artifactId']}"
            )
        _fingerprint(locator, fingerprint)
        if item["ancestryRole"] == "generated" and not admitted:
            ancestor = _json(locator)
            try:
                GeneratedAssetService._validate(ancestor)
            except RuntimeError as error:
                raise RuntimeError(
                    f"Invalid generated ancestor {locator}: {error}"
                ) from error
            _closure(ancestor, seen, admitted=admitted)
    seen.remove(identity)


def parameters(operation, refs, registry):
    kind = operation["kind"]
    implementation = registry.resolve(
        kind, implementation_id=operation["implementationId"]
    )
    if (
        implementation is None
        or refs.get(operation["implementationId"]) != implementation.proof_reference()
    ):
        raise RuntimeError(
            f"Generated implementation is unsupported or stale: {operation['operationId']}"
        )
    fragment = (
        "overlayVideoParameters"
        if kind == "overlay-video"
        else "generatedClipParameters"
    )
    try:
        validate_document(operation, "avo.proof-plan.schema.json#/$defs/operation")
        validate_document(
            operation["parameters"], "avo.proof-plan.schema.json#/$defs/" + fragment
        )
    except ContractError as error:
        raise RuntimeError(
            f"Invalid generated operation {operation['operationId']}: {error}"
        ) from error
    value = operation["parameters"]
    expected = ["generated:" + value["generatedAssetRef"]["assetId"]]
    if kind == "overlay-video":
        expected.insert(0, "program-picture")
    if operation["inputs"] != expected:
        raise RuntimeError(f"Unconsumed generated input: {operation['operationId']}")
    return value


def _record(operation, canonical_lock, validator):
    params = operation["parameters"]
    reference = params["generatedAssetRef"]
    record = _json(reference["locator"])
    try:
        GeneratedAssetService._validate(record)
    except RuntimeError as error:
        raise RuntimeError(
            f"Invalid generated record {reference['locator']}: {error}"
        ) from error
    if (
        record["assetId"] != reference["assetId"]
        or record["recordHash"] != reference["recordHash"]
    ):
        raise RuntimeError(
            f"Generated record identity mismatch: {reference['locator']}"
        )
    if canonical_lock.get("generated:" + record["assetId"]) != record["recordHash"]:
        raise RuntimeError(f"Generated asset lock mismatch: {reference['locator']}")
    if record["reproducibility"] == "unverified":
        raise RuntimeError(f"Generated asset is reference-only: {reference['locator']}")
    _current_admission(
        record, reference, params["inputLockRef"], canonical_lock, validator
    )
    if record["output"] != params["sourceFingerprint"]:
        raise RuntimeError(
            "Generated source fingerprint differs from its admitted record"
        )
    return record


def _current_admission(record, reference, input_lock_ref, canonical_lock, validator):
    if record["generator"]["adapterId"] == "code-drawn" and validator is None:
        raise RuntimeError(
            "Code-drawn generated asset requires current admission observations"
        )
    if validator is not None:
        admitted = validator(
            deepcopy(reference), deepcopy(input_lock_ref), dict(canonical_lock)
        )
        if admitted != record:
            raise RuntimeError("Current generated admission differs from frozen record")


def _input_lock(operation, record, canonical_lock):
    params = operation["parameters"]
    reference = params["inputLockRef"]
    _fingerprint(reference["path"], reference)
    lock = _json(reference["path"])
    if lock.get("inputLockHash") != document_hash_excluding(lock, "inputLockHash"):
        raise RuntimeError(f"Generated input lock hash mismatch: {reference['path']}")
    declared = record["parameters"].get("codeDrawn", record["parameters"])
    if declared.get("inputLockHash", lock["inputLockHash"]) != lock["inputLockHash"]:
        raise RuntimeError("Generated receipt refers to another input lock")
    instance = lock.get("instanceId")
    if (
        not instance
        or canonical_lock.get("input-lock:" + instance) != lock["inputLockHash"]
    ):
        raise RuntimeError(f"Generated input lock is not frozen: {reference['path']}")
    if any(
        canonical_lock.get(key) != value
        for key, value in lock.get("canonicalInputLock", {}).items()
    ):
        raise RuntimeError(f"Generated canonical inputs changed: {reference['path']}")
    if record["generator"]["adapterId"] == "code-drawn":
        _code_drawn_lock(operation, record, lock)
    return lock


def _code_drawn_lock(operation, record, lock):
    params = operation["parameters"]
    extension = record["parameters"]["codeDrawn"]
    if lock.get("bindingMode") != "canonical":
        raise RuntimeError(
            "Standalone code-drawn assets cannot become canonical proof sources"
        )
    if extension["inputLockHash"] != lock["inputLockHash"]:
        raise RuntimeError("Code-drawn receipt input lock mismatch")
    if lock["range"] != operation["outputRange"]:
        raise RuntimeError("Code-drawn output range differs from canonical placement")
    placement = lock["placement"]
    if operation["kind"] == "overlay-video":
        expected = {
            **params["placement"],
            "zOrder": params["zOrder"],
            "layerRole": params["layerRole"],
        }
        if placement != expected:
            raise RuntimeError(
                "Code-drawn placement differs from its canonical input lock"
            )
    elif placement["layerRole"] != "base" or placement["x"] or placement["y"]:
        raise RuntimeError(
            "Code-drawn base source requires canonical full-frame placement"
        )


def verify(operation, canonical_lock, validator, ancestry_validator):
    record = _record(operation, canonical_lock, validator)
    ancestry_validator(record)
    _closure(record, admitted=validator is not None)
    _input_lock(operation, record, canonical_lock)
    path = Path(record["output"]["locator"])
    _fingerprint(path, record["output"])
    return {"operation": deepcopy(operation), "record": record, "path": path}


def _capture(arguments, path):
    try:
        return subprocess.run(
            arguments, capture_output=True, text=True, check=True, timeout=300
        ).stdout
    except (OSError, subprocess.SubprocessError) as error:
        raise RuntimeError(
            f"Generated media inspection failed for {path}: {error}"
        ) from error


def _probe(path):
    streams = json.loads(
        _capture(
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
            path,
        )
    )["streams"]
    videos = [item for item in streams if item["codec_type"] == "video"]
    if len(videos) != 1 or any(item["codec_type"] == "audio" for item in streams):
        raise RuntimeError(
            f"Generated source must contain exactly one silent video: {path}"
        )
    return videos[0]


def _is_opaque(path, width, height, count):
    text = _capture(
        [
            "ffmpeg",
            "-v",
            "error",
            "-nostdin",
            "-i",
            str(path),
            "-map",
            "0:v:0",
            "-vf",
            "alphaextract",
            "-pix_fmt",
            "gray",
            "-f",
            "framemd5",
            "-",
        ],
        path,
    )
    rows = [line for line in text.splitlines() if line and not line.startswith("#")]
    if len(rows) != count:
        raise RuntimeError(f"Generated alpha decode count differs from picture: {path}")
    expected = hashlib.md5(
        bytes([255]) * width * height, usedforsecurity=False
    ).hexdigest()
    return all(row.rsplit(",", 1)[-1].strip() == expected for row in rows)


def inspect(asset, spec, fps):
    operation = asset["operation"]
    params = operation["parameters"]
    video = _probe(asset["path"])
    if video["codec_name"] != "ffv1" or video["pix_fmt"] != "bgra":
        raise RuntimeError(
            f"Generated asset requires lossless FFV1/BGRA alpha pixels: {asset['path']}"
        )
    if Fraction(video["r_frame_rate"]) != fps:
        raise RuntimeError("Generated asset frame rate differs from ProofPlan")
    count = int(video.get("nb_read_frames") or 0)
    source = params["sourceRange"]
    duration = _frame_count(operation["outputRange"])
    _frame_count(source)
    if (
        source["endFrameExclusive"] - source["startFrame"] != duration
        or source["endFrameExclusive"] > count
    ):
        raise RuntimeError(
            "Generated source frame range differs from output duration or available frames"
        )
    width, height = video["width"], video["height"]
    opaque = _is_opaque(asset["path"], width, height, count)
    if operation["kind"] == "generated-clip":
        if not opaque or (width, height) != (spec["width"], spec["height"]):
            raise RuntimeError(
                "Generated base must be opaque and match output dimensions"
            )
    else:
        _placement(params["placement"], spec)
    asset["video"] = video
    asset["opaque"] = opaque
    return asset


def _frame_count(region):
    start, end = region["startFrame"], region["endFrameExclusive"]
    if type(start) is not int or type(end) is not int or start < 0 or end <= start:
        raise RuntimeError(
            "Generated operations require nonempty half-open frame ranges"
        )
    return end - start


def validate_layers(assets):
    overlays = [
        asset["operation"]["parameters"]
        for asset in assets
        if asset["operation"]["kind"] == "overlay-video"
    ]
    captions = [item["zOrder"] for item in overlays if item["layerRole"] == "caption"]
    graphics = [item["zOrder"] for item in overlays if item["layerRole"] != "caption"]
    if captions and graphics and min(captions) <= max(graphics):
        raise RuntimeError("Frozen caption layers must composite after other graphics")


def _placement(placement, spec):
    if any(type(value) is not int for value in placement.values()):
        raise RuntimeError("Overlay placement requires integer pixel coordinates")
    if (
        placement["x"] < 0
        or placement["y"] < 0
        or placement["width"] <= 0
        or placement["height"] <= 0
        or placement["x"] + placement["width"] > spec["width"]
        or placement["y"] + placement["height"] > spec["height"]
    ):
        raise RuntimeError("Overlay placement exceeds the frozen output canvas")


def overlay_filters(assets, fps, wstart, wend, *, conformance):
    arguments, filters, metadata = [], [], []
    current = "picture"
    timebase = f"{fps.denominator}/{fps.numerator}"
    for asset in sorted(assets, key=_overlay_order):
        operation = asset["operation"]
        params = operation["parameters"]
        region = operation["outputRange"]
        left, right = (
            max(region["startFrame"], wstart),
            min(region["endFrameExclusive"], wend),
        )
        item = operation_metadata(operation)
        item["appliedRange"] = (
            {"startFrame": left, "endFrameExclusive": right} if left < right else None
        )
        metadata.append(item)
        if left >= right:
            continue
        index = len(arguments) // 2 + 1
        arguments += ["-i", str(asset["path"])]
        local = params["sourceRange"]["startFrame"] + left - region["startFrame"]
        offset = left - wstart
        p = params["placement"]
        filters.append(
            f"[{index}:v:0]trim=start_frame={local}:end_frame={local + right - left},"
            f"settb=expr={timebase},setpts=N+{offset},scale={p['width']}:{p['height']},"
            f"format=rgba[alpha{index}]"
        )
        filters.append(
            f"[{current}][alpha{index}]overlay=x={p['x']}:y={p['y']}:format=rgb:"
            f"alpha=straight:eof_action=pass:repeatlast=0:"
            f"enable='gte(n,{offset})*lt(n,{offset + right - left})'[picture{index}]"
        )
        current = f"picture{index}"
    filters.append(f"[{current}]format={'bgra' if conformance else 'yuv420p'}[v]")
    return arguments, filters, metadata


def _overlay_order(asset):
    operation = asset["operation"]
    params = operation["parameters"]
    return (params["zOrder"], operation["operationId"])


def operation_metadata(operation):
    params = operation["parameters"]
    keys = (
        "generatedAssetRef",
        "inputLockRef",
        "sourceRange",
        "placement",
        "zOrder",
        "layerRole",
        "alphaMode",
    )
    return {
        "operationId": operation["operationId"],
        "kind": operation["kind"],
        "outputRange": deepcopy(operation["outputRange"]),
        **{key: deepcopy(params[key]) for key in keys if key in params},
    }
