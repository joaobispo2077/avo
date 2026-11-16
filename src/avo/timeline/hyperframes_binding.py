"""Resolve source-only HyperFrames instances against current canonical authority."""

from __future__ import annotations

import json
import re
from copy import deepcopy
from fractions import Fraction
from pathlib import Path, PureWindowsPath
from typing import Any

from avo.motion import _canonical_drawing_heads, _drawing_region

from .component_instances import ComponentInstanceService
from .contracts import document_hash_excluding, file_fingerprint, fingerprint_stage
from .generated_assets import GeneratedAssetService
from .media_admission import require_media_admission
from .proof_validation_stage import in_proof_validation_batch


class HyperframesBindingError(ValueError):
    """A canonical declaration or its original source closure is unavailable."""


def _require(condition, message):
    if not condition:
        raise HyperframesBindingError(message)


def _integer(value, *, positive=False):
    return type(value) is int and value >= (1 if positive else 0)


def _inside(root, name, *, relative=False):
    path = Path(name)
    if relative:
        _require(
            not path.is_absolute()
            and not PureWindowsPath(str(name)).drive
            and ".." not in path.parts,
            "Project reference must be a relative project-owned path",
        )
    path = (root / path).resolve()
    _require(path.is_relative_to(root), f"Source path escaped project: {path}")
    return path


def _fingerprinted(root, item):
    _require(isinstance(item, dict), "Input fingerprint must be an object")
    _require(
        set(item) == {"locator", "sha256", "sizeBytes"}
        and isinstance(item["locator"], str)
        and bool(re.fullmatch(r"[a-f0-9]{64}", str(item["sha256"])))
        and _integer(item["sizeBytes"]),
        "Input requires exact locator, SHA256 and sizeBytes",
    )
    path = _inside(root, item["locator"])
    actual = file_fingerprint(path)
    _require(
        all(actual[key] == item[key] for key in ("sha256", "sizeBytes")),
        f"Input fingerprint changed: {path}",
    )
    return {**actual, "locator": str(path)}


def _render_contract(value):
    _require(
        isinstance(value, dict)
        and set(value) == {"width", "height", "frameRate", "frameCount"},
        "Render contract requires width, height, frameRate and frameCount",
    )
    _require(
        all(
            _integer(value[key], positive=True)
            for key in ("width", "height", "frameCount")
        ),
        "Render dimensions/count must be positive integers",
    )
    rate = value["frameRate"]
    _require(
        isinstance(rate, dict)
        and set(rate) == {"num", "den"}
        and all(_integer(rate[key], positive=True) for key in ("num", "den")),
        "Render frame rate requires positive integer numerator/denominator",
    )
    rational = Fraction(rate["num"], rate["den"])
    _require(
        (rational.numerator, rational.denominator) == (rate["num"], rate["den"]),
        "Render frame rate must be reduced",
    )
    return deepcopy(value)


def _cue_range(cue, rate):
    frames = []
    for key in ("start", "end"):
        value = cue[key]
        base = value["timebase"]
        _require(
            value.get("domain") == "cmap-output"
            and _integer(value["ticks"])
            and all(_integer(base[key], positive=True) for key in ("num", "den")),
            "BMap cue requires nonnegative exact output-clock timing",
        )
        frame = Fraction(value["ticks"] * base["num"], base["den"]) * rate
        _require(frame.denominator == 1, "BMap cue is not frame-aligned")
        frames.append(int(frame))
    return {"startFrame": frames[0], "endFrameExclusive": frames[1]}


def _generated_closure(service, references, lock, root):
    records, pending = (
        {},
        [
            item["artifactId"]
            for item in references
            if item["ancestryRole"] == "generated"
        ],
    )
    while pending:
        identity = pending.pop()
        if identity in records:
            continue
        record = service.admit(identity)
        params = record["parameters"].get("hyperframes", record["parameters"])
        ref = params.get("inputLockRef")
        _require(
            ref, f"Generated dependency requires a canonical input lock: {identity}"
        )
        path = _inside(root, ref["path"])
        _require(
            file_fingerprint(path)["sha256"] == ref["sha256"],
            "Generated input-lock bytes changed",
        )
        original = json.loads(path.read_text(encoding="utf-8"))
        _require(
            original.get("inputLockHash")
            == document_hash_excluding(original, "inputLockHash")
            and original.get("canonicalInputLock") == lock,
            f"Generated dependency canonical lock changed: {identity}",
        )
        records[identity] = record
        pending.extend(
            item["artifactId"]
            for item in record["inputs"]
            if item["ancestryRole"] == "generated"
        )
    return records


def _logical_component_layer(snapshots, instance_id):
    strategy = snapshots["animation"]
    components = [
        item
        for item in strategy.get("components", [])
        if item.get("extensions", {}).get("hyperframes", {}).get("instanceId")
        == instance_id
    ]
    layers = [
        item
        for item in snapshots["tracks"].get("videoTracks", {}).get("layers", [])
        if item.get("generator", {}).get("instanceId") == instance_id
    ]
    _require(
        len(components) == len(layers) == 1,
        "Exactly one Animation component and Tracks layer are required",
    )
    component, layer = components[0], layers[0]
    return component, layer


def _validate_logical_layer(component, layer, pair):
    _require(
        component["extensions"]["hyperframes"] == pair,
        "Animation instance identity changed",
    )
    _require(
        layer.get("generator") == {"adapterId": "hyperframes", **pair},
        "Tracks instance identity changed",
    )
    _require(
        layer.get("animationRef") == component["componentId"],
        "Tracks animationRef differs from component",
    )
    _require(
        layer.get("role") == "overlay"
        and "source" not in layer
        and "generatedSourceRef" not in layer,
        "HyperFrames binding must be a logical overlay without output sources",
    )
    _require(
        not any(
            key in layer
            for key in ("generatedAssetId", "generatedAssetRef", "output", "outputHash")
        ),
        "Tracks must not bind future generated outputs",
    )
    _require(
        _integer(layer.get("order"))
        and layer.get("zOrder", layer["order"]) == layer["order"],
        "Tracks order/zOrder must agree",
    )


def _source_project(root, instance):
    params = instance["parameters"]
    _require(
        set(params) == {"projectRef", "renderContract", "mediaInputs"},
        "Instance parameters require only projectRef, renderContract and mediaInputs",
    )
    contract = _render_contract(params["renderContract"])
    project_ref = params["projectRef"]
    _require(
        isinstance(project_ref, dict) and set(project_ref) == {"path"},
        "Invalid projectRef",
    )
    project = _inside(root, project_ref["path"], relative=True)
    _require(project.is_dir(), "HyperFrames source project is missing")
    return params, contract, project


def _canonical_cue(snapshots, component, layer, contract):
    region = _drawing_region(layer, contract)
    one = layer["regions"][0]
    _require(
        isinstance(one.get("cueIds"), list) and len(one["cueIds"]) == 1,
        "Exactly one BMap cue is required",
    )
    cues = [
        item
        for item in snapshots["bmap"].get("cues", [])
        if item["cueId"] == one["cueIds"][0]
    ]
    _require(len(cues) == 1, "BMap cue identity is missing or ambiguous")
    cue = cues[0]
    _require(
        cue.get("targetLayerId") == layer["layerId"]
        and cue.get("componentRef") == component["componentId"]
        and isinstance(cue.get("intent"), str)
        and bool(cue["intent"].strip())
        and isinstance(cue.get("reason"), str)
        and bool(cue["reason"].strip()),
        "BMap component, layer or editorial intent does not match",
    )
    rate = Fraction(contract["frameRate"]["num"], contract["frameRate"]["den"])
    _require(
        _cue_range(cue, rate) == region, "Tracks range must exactly equal its BMap cue"
    )
    return region, cue


def _canonical_canvas(snapshots, contract):
    canvas = snapshots["cmap"].get("importOutput") or {}
    _require(
        all(_integer(canvas.get(key), positive=True) for key in ("width", "height"))
        and canvas.get("frameRate") == contract["frameRate"],
        "Canonical imported canvas and exact render clock are required",
    )
    canonical_canvas = {key: canvas[key] for key in ("width", "height")}
    _require(
        contract["width"] * canvas["height"] == contract["height"] * canvas["width"],
        "Component must preserve canonical canvas aspect ratio",
    )
    return canonical_canvas


def _full_frame_placement(layer, canonical_canvas):
    placement = layer.get("placement")
    _require(
        isinstance(placement, dict)
        and set(placement) == {"x", "y", "width", "height"}
        and all(_integer(placement[key]) for key in ("x", "y"))
        and all(_integer(placement[key], positive=True) for key in ("width", "height"))
        and placement == {"x": 0, "y": 0, **canonical_canvas},
        "Placement must exactly cover the canonical imported canvas",
    )
    return placement


def _authoring_inputs(root, project, instance):
    inputs, files = [], set()
    for item in instance["generatedFiles"]:
        path = _inside(root, item["path"])
        _require(
            path.is_relative_to(project), "Authoring file is outside the source project"
        )
        _require(
            path.suffix.lower()
            not in {".gif", ".mp4", ".mkv", ".mov", ".png", ".jpg", ".wav", ".mp3"},
            "Media must be declared as mediaInputs, never authoring files",
        )
        _require(path not in files, "Duplicate authoring file")
        files.add(path)
        inputs.append(
            {
                "artifactId": "hyperframes-source:"
                + path.relative_to(project).as_posix(),
                "fingerprint": file_fingerprint(path),
                "ancestryRole": "dependency",
            }
        )
    _require(
        (project / "index.html").resolve() in files, "Source index.html must be frozen"
    )
    return inputs, files


def _media_reference(root, item, identities):
    _require(
        isinstance(item, dict)
        and set(item) == {"artifactId", "fingerprint", "ancestryRole"},
        "Invalid media input contract",
    )
    identity, role = item["artifactId"], item["ancestryRole"]
    _require(
        isinstance(identity, str) and identity and identity not in identities,
        "Media input identities must be unique",
    )
    identities.add(identity)
    _require(
        role in {"original", "generated", "dependency"},
        "Media ancestry must be original, generated or dependency",
    )
    fingerprint = _fingerprinted(root, item["fingerprint"])
    path = Path(fingerprint["locator"])
    _require(
        not (
            role == "dependency"
            and path.suffix.lower()
            in {".gif", ".mp4", ".mkv", ".mov", ".png", ".jpg", ".wav", ".mp3"}
        ),
        "Picture/audio media cannot be disguised as a dependency",
    )
    reference = {
        "artifactId": identity,
        "fingerprint": fingerprint,
        "ancestryRole": "source" if role == "original" else role,
    }
    return reference, path, role


def _media_inputs(root, project, params, inputs, files):
    media = params["mediaInputs"]
    _require(isinstance(media, list), "mediaInputs must be an explicit list")
    identities = set()
    originals = []
    for item in media:
        reference, path, role = _media_reference(root, item, identities)
        inputs.append(reference)
        if role == "original":
            originals.append(reference)
        if path.is_relative_to(project):
            files.add(path)
    return identities, originals


def _validate_source_closure(
    root, project, instance, cue, inputs, files, identities, originals
):
    actual_files = {path.resolve() for path in project.rglob("*") if path.is_file()}
    _require(
        actual_files == files,
        "Source project contains untracked or missing closure files",
    )
    expected_gifs = cue.get("contentRef", {}).get("originalGifAssets", [])
    _require(
        all(
            any(
                all(
                    ref["fingerprint"][key] == expected[key]
                    for key in ("sha256", "sizeBytes")
                )
                and Path(ref["fingerprint"]["locator"]).resolve()
                == _inside(root, expected["locator"])
                for ref in originals
            )
            for expected in expected_gifs
        ),
        "BMap original GIF closure is incomplete",
    )
    bound_hashes = {item["sha256"] for item in instance["assetBindings"]}
    _require(
        bound_hashes
        == {
            item["fingerprint"]["sha256"]
            for item in inputs
            if item["artifactId"] in identities
        },
        "Component assetBindings and mediaInputs differ",
    )


def _admit_binding_inputs(
    workspace, root, instance_id, registry, inputs, originals, lock
):
    instance_path = registry.path(instance_id)
    inputs.append(
        {
            "artifactId": "component-instance:" + instance_id,
            "fingerprint": file_fingerprint(instance_path),
            "ancestryRole": "dependency",
        }
    )
    service = GeneratedAssetService(workspace)
    assets = _generated_closure(service, inputs, lock, root)
    contributors = [
        {
            **item,
            **(
                {"kind": "generated", "assetId": item["artifactId"]}
                if item["ancestryRole"] == "generated"
                else {}
            ),
        }
        for item in inputs
    ]
    require_media_admission(
        contributors,
        registered_originals=[*service._current_originals(), *originals],
        generated_assets=assets,
        known_outputs=service._known_outputs(),
    )


def _component_contract(component, contract, files, project):
    component_contract = deepcopy(component)
    component_contract["renderContract"] = deepcopy(contract)
    component_contract["runtimeDependencies"] = [
        {
            "path": path.relative_to(project).as_posix(),
            "sha256": file_fingerprint(path)["sha256"],
        }
        for path in sorted(files)
        if path.is_relative_to(project / "lib") and path.suffix.lower() == ".js"
    ]
    return component_contract


def _resolve(workspace, instance_id):
    _require(
        bool(re.fullmatch(r"[a-z][a-z0-9-]{2,63}", instance_id)),
        "Invalid component instance ID",
    )
    root = Path(workspace.raw_dir).resolve()
    snapshots, lock = _canonical_drawing_heads(workspace)
    strategy = snapshots["animation"]
    _require(
        strategy.get("framework") == "hyperframes",
        "Recorded animation engine is not HyperFrames",
    )
    registry = ComponentInstanceService(workspace)
    instance = registry.load(instance_id)
    registry.implementation_reference(instance_id, adapter_id="hyperframes")
    pair = {"instanceId": instance_id, "instanceHash": instance["instanceHash"]}
    component, layer = _logical_component_layer(snapshots, instance_id)
    _validate_logical_layer(component, layer, pair)
    params, contract, project = _source_project(root, instance)
    region, cue = _canonical_cue(snapshots, component, layer, contract)
    canonical_canvas = _canonical_canvas(snapshots, contract)
    placement = _full_frame_placement(layer, canonical_canvas)
    inputs, files = _authoring_inputs(root, project, instance)
    identities, originals = _media_inputs(root, project, params, inputs, files)
    _validate_source_closure(
        root, project, instance, cue, inputs, files, identities, originals
    )
    _admit_binding_inputs(
        workspace, root, instance_id, registry, inputs, originals, lock
    )
    component_contract = _component_contract(component, contract, files, project)
    return {
        "instanceId": instance_id,
        "instanceHash": instance["instanceHash"],
        "componentRef": component["componentId"],
        "bmapCueId": cue["cueId"],
        "layerId": layer["layerId"],
        "intent": cue["intent"],
        "reason": cue["reason"],
        "canonicalInputLock": lock,
        "range": region,
        "placement": {**placement, "zOrder": layer["order"], "layerRole": "overlay"},
        "componentContract": component_contract,
        "inputs": sorted(inputs, key=lambda item: item["artifactId"]),
        "project": str(project),
        "renderContract": contract,
        "canonicalCanvas": canonical_canvas,
    }


def resolve_binding(workspace: Any, instance_id: str) -> dict[str, Any]:
    """Resolve current canonical authority and verify the entire local source closure."""
    try:
        with fingerprint_stage(reuse_current=in_proof_validation_batch()):
            return _resolve(workspace, instance_id)
    except HyperframesBindingError:
        raise
    except (KeyError, TypeError, ValueError, RuntimeError, OSError) as error:
        raise HyperframesBindingError(
            f"HyperFrames canonical binding failed: {error}"
        ) from error


def verify_binding(workspace: Any, frozen_binding: dict[str, Any]) -> dict[str, Any]:
    """Never trust a supplied snapshot as authority; resolve every field again."""
    _require(
        isinstance(frozen_binding, dict)
        and isinstance(frozen_binding.get("instanceId"), str),
        "Frozen binding requires an instance identity",
    )
    current = resolve_binding(workspace, frozen_binding["instanceId"])
    _require(
        current == frozen_binding,
        "HyperFrames canonical binding or source closure changed",
    )
    return current


def _receipt_envelope(record, environment):
    GeneratedAssetService._validate(record)
    GeneratedAssetService._output(record)
    _require(
        record["generator"]["adapterId"] == "hyperframes",
        "Receipt generator is not HyperFrames",
    )
    extension = record["parameters"]["hyperframes"]
    _require(
        set(extension)
        == {
            "instanceId",
            "instanceHash",
            "inputLockRef",
            "canonicalInputLock",
            "renderContract",
            "seekEvidence",
            "outputVerification",
        },
        "Invalid canonical HyperFrames receipt extension",
    )
    _require(
        isinstance(environment, dict)
        and set(environment)
        == {
            "toolEnvironment",
            "toolInputs",
            "captureEvidence",
            "encodedVerification",
        },
        "Fresh HyperFrames environment observations are required",
    )
    return extension


def _receipt_lock(workspace, extension):
    root = Path(workspace.raw_dir).resolve()
    reference = extension["inputLockRef"]
    _require(
        isinstance(reference, dict) and set(reference) == {"path", "sha256"},
        "Invalid receipt input-lock reference",
    )
    lock_path = _inside(root, reference["path"])
    lock_fingerprint = file_fingerprint(lock_path)
    _require(
        lock_fingerprint["sha256"] == reference["sha256"],
        "HyperFrames input-lock file changed",
    )
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    _require(
        set(lock) == {"instanceId", "binding", "environment", "inputLockHash"}
        and lock["inputLockHash"] == document_hash_excluding(lock, "inputLockHash"),
        "HyperFrames input-lock hash is invalid",
    )
    return lock, lock_fingerprint


def _receipt_binding(workspace, extension, lock):
    binding = verify_binding(workspace, lock["binding"])
    _require(
        lock["instanceId"] == extension["instanceId"] == binding["instanceId"]
        and extension["instanceHash"] == binding["instanceHash"]
        and extension["canonicalInputLock"] == binding["canonicalInputLock"]
        and extension["renderContract"] == binding["renderContract"],
        "HyperFrames receipt canonical binding changed",
    )
    return binding


def _receipt_tool_environment(record, environment, lock):
    tool_environment = environment["toolEnvironment"]
    tool_hash = tool_environment["hash"]
    _require(
        tool_hash == document_hash_excluding(tool_environment, "hash"),
        "Observed tool environment hash is invalid",
    )
    _require(
        bool(re.fullmatch(r"[a-f0-9]{64}", tool_hash)), "Invalid observed tool hash"
    )
    _require(
        lock["environment"] == tool_environment
        and record["generator"]["executableSha256"] == tool_hash
        and record["environment"]["dependencies"].get("toolEnvironment") == tool_hash,
        "HyperFrames tool environment changed",
    )
    return tool_environment


def _receipt_tool_inputs(environment, tool_environment):
    tools = environment["toolInputs"]
    _require(
        isinstance(tools, list) and tools, "Observed tool input closure is required"
    )
    _require(
        sorted(tool_environment["files"], key=lambda item: item["locator"])
        == sorted(
            [item["fingerprint"] for item in tools],
            key=lambda item: item["locator"],
        ),
        "Tool input closure differs from observed environment",
    )
    for item in tools:
        _require(
            set(item) == {"artifactId", "fingerprint", "ancestryRole"}
            and item["ancestryRole"] == "dependency",
            "Tools must be fingerprinted dependencies",
        )
        expected = item["fingerprint"]
        _require(
            set(expected) == {"locator", "sha256", "sizeBytes"},
            "Tool fingerprint is incomplete",
        )
        actual = file_fingerprint(Path(expected["locator"]).resolve())
        _require(
            all(actual[key] == expected[key] for key in ("sha256", "sizeBytes")),
            "Observed tool input changed",
        )
    return tools


def _verify_receipt_inputs(workspace, record, binding, lock_fingerprint, tools):
    lock_input = {
        "artifactId": "hyperframes-input-lock:" + binding["instanceId"],
        "fingerprint": lock_fingerprint,
        "ancestryRole": "dependency",
    }
    expected_inputs = [*binding["inputs"], lock_input, *tools]
    _require(
        all(isinstance(item.get("artifactId"), str) for item in expected_inputs),
        "Input identities must be strings",
    )
    _require(
        len({item["artifactId"] for item in expected_inputs}) == len(expected_inputs),
        "Receipt input identities must be unique",
    )
    _require(
        sorted(record["inputs"], key=lambda item: item["artifactId"])
        == sorted(expected_inputs, key=lambda item: item["artifactId"]),
        "HyperFrames receipt source closure differs from its binding",
    )
    service = GeneratedAssetService(workspace)
    require_media_admission(
        [lock_input, *tools], known_outputs=service._known_outputs()
    )


def _verify_encoded_contract(encoded, contract):
    _require(
        set(encoded)
        == {
            "silent",
            "width",
            "height",
            "frameRate",
            "frameCount",
            "codec",
            "pixelFormat",
            "frameHashes",
        },
        "Encoded verification contract is incomplete",
    )
    _require(
        encoded["silent"] is True
        and encoded["codec"] == "ffv1"
        and encoded["pixelFormat"] == "bgra"
        and all(
            encoded[key] == contract[key]
            for key in ("width", "height", "frameRate", "frameCount")
        ),
        "HyperFrames encoded output violates its silent lossless contract",
    )


def _encoded_frame_hashes(encoded, contract):
    hashes = encoded["frameHashes"]
    _require(
        isinstance(hashes, list)
        and len(hashes) == contract["frameCount"]
        and all(
            isinstance(value, str) and re.fullmatch(r"[a-f0-9]{64}", value)
            for value in hashes
        ),
        "Every encoded RGBA frame requires a fingerprint",
    )
    return hashes


def _seek_frame_indices(capture, contract, hashes):
    frames = capture["frames"]
    _require(
        isinstance(frames, list)
        and len(frames) >= min(3, contract["frameCount"])
        and all(_integer(index) and index < len(hashes) for index in frames)
        and len(set(frames)) == len(frames)
        and 0 in frames
        and len(hashes) - 1 in frames,
        "Seek verification must cover valid distinct frames and both endpoints",
    )
    return frames


def _verify_capture_evidence(capture, contract, hashes):
    _require(
        set(capture) == {"frames", "rgbaSha256"},
        "Seek verification contract is incomplete",
    )
    frames = _seek_frame_indices(capture, contract, hashes)
    _require(
        set(capture["rgbaSha256"]) == {str(index) for index in frames}
        and all(capture["rgbaSha256"][str(index)] == hashes[index] for index in frames),
        "Seek pixels differ from encoded frames",
    )


def verify_generated_record(workspace, record, environment):
    """Validate an observed HyperFrames receipt against fresh canonical authority."""
    try:
        extension = _receipt_envelope(record, environment)
        lock, lock_fingerprint = _receipt_lock(workspace, extension)
        binding = _receipt_binding(workspace, extension, lock)
        tool_environment = _receipt_tool_environment(record, environment, lock)
        tools = _receipt_tool_inputs(environment, tool_environment)
        _verify_receipt_inputs(workspace, record, binding, lock_fingerprint, tools)
        encoded, capture = (
            environment["encodedVerification"],
            environment["captureEvidence"],
        )
        contract = binding["renderContract"]
        _verify_encoded_contract(encoded, contract)
        hashes = _encoded_frame_hashes(encoded, contract)
        _verify_capture_evidence(capture, contract, hashes)
        _require(
            extension["seekEvidence"] == capture
            and extension["outputVerification"] == encoded,
            "Receipt capture evidence differs from fresh observations",
        )
        return deepcopy(record)
    except HyperframesBindingError:
        raise
    except (KeyError, TypeError, ValueError, RuntimeError, OSError) as error:
        raise HyperframesBindingError(
            f"HyperFrames receipt verification failed: {error}"
        ) from error
