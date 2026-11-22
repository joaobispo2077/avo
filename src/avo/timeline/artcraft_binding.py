"""Freeze an exact externally authored component against its owning video."""

from __future__ import annotations

import json
import re
from copy import deepcopy
from fractions import Fraction
from pathlib import Path

from avo.artcraft import (
    ArtCraftError,
    read_authoring_export,
    require_artcraft_export_environment,
    seal_record,
    validate_record,
)

from .contracts import (
    content_hash,
    document_hash_excluding,
    file_fingerprint,
    fingerprint_stage,
)

__all__ = [
    "build_artcraft_asset_record",
    "freeze_export_binding",
    "read_artcraft_binding",
    "require_artcraft_media_scope",
    "require_artcraft_operation_binding",
    "require_artcraft_output_geometry",
    "verify_artcraft_asset_record",
]


def require_artcraft_media_scope(workspace, job, media_name):
    request = job["request"]
    if request["provider"] != workspace.project.get("provider"):
        raise ValueError(f"{media_name} belongs to a different provider")
    context = request["context"]
    if context["kind"] == "video" and (
        context["videoId"] != workspace.video_id
        or Path(context["project"]) != Path(workspace.project_path)
        or Path(job["workspace"]) != workspace.raw_dir.resolve()
    ):
        raise ValueError(f"{media_name} belongs to a different video or project")


def freeze_export_binding(workspace, *, job_ref, expected_head):
    """Bind native source and rendered source frames to one current video scope."""
    with fingerprint_stage(reuse_current=True, verify_on_exit=True):
        job, event = read_authoring_export(job_ref, expected_head=expected_head)
        canonical = _canonical_export_scope(workspace, job)
        environment = require_artcraft_export_environment(job["observation"])
        artwork = job.get("artworkRef")
        source = {
            "nativeSource": event["saved"],
            "recipe": event["recipe"],
            "parameters": {
                **job.get("authoringParameters", {}),
                **({"artworkRef": artwork} if artwork else {}),
            },
            "requestHash": job["decision"]["requestHash"],
            "environmentHash": content_hash(environment),
        }
        if job["documentState"] == "saved":
            source["inputSources"] = job["inputs"]
            source["revisionCommandSchemaHash"] = event["revisionCommandSchemaHash"]
        if artwork:
            source["inputSources"] = job["inputs"]
        if job["observation"]["mode"] == "reuse":
            source["reusedExport"] = job["observation"]["reuseSource"]
        placement = _canonical_overlay(workspace, job, canonical["heads"])
        cue_binding = _pinned_kit_sound(workspace, job, placement, canonical["heads"])
        components = {
            "version": 1,
            "jobRef": file_fingerprint(Path(job_ref)),
            "jobHash": job["jobHash"],
            "exportHead": event["eventHash"],
            "canonical": canonical,
            "nativeRevisionHash": content_hash(source),
            "parameterHash": content_hash(source["parameters"]),
            "recipeHash": event["recipe"]["sha256"],
            "environment": environment,
            "outputContract": job["output"],
            "nativeByteBudget": job["budget"]["bytes"],
            "placement": placement,
            "frames": event["outputs"],
            **({"soundCue": cue_binding} if cue_binding else {}),
            **source,
        }
        return {**components, "bindingHash": content_hash(components)}


def _pinned_kit_sound(workspace, job, placement, heads):
    selection = job.get("artworkRef") or {}
    if "instanceId" not in selection:
        return None

    from .artcraft_audio import select_kit_sound
    from .artcraft_packages import _read_artwork_instance
    from .event_clock import frame_range_to_samples

    _, instance = _read_artwork_instance(workspace, selection, job["roots"]["read"])
    cue_binding = select_kit_sound(workspace, instance, job["output"])
    if cue_binding is None:
        return None
    rate = job["output"]["frameRate"]
    start, end = frame_range_to_samples(
        placement["range"]["startFrame"],
        placement["range"]["endFrameExclusive"],
        frame_rate_num=rate["numerator"],
        frame_rate_den=rate["denominator"],
    )
    if (
        cue_binding["tracksRevisionHash"] != heads.get("tracks")
        or cue_binding["cueId"] != placement["cueId"]
        or not start <= cue_binding["startSample"] < end
    ):
        raise ArtCraftError(
            "The provider kit sound cue must start during its BMap placement"
        )
    return cue_binding


def _canonical_overlay(workspace, job, expected_heads):
    from avo.motion import _canonical_drawing_heads

    from .hyperframes_binding import _canonical_cue

    snapshots, heads = _canonical_drawing_heads(workspace)
    if any(expected_heads.get(key) != value for key, value in heads.items()):
        raise ArtCraftError("ArtCraft placement changed after authoring began")
    component_id = job["request"]["componentId"]
    component, layer = _selected_overlay(snapshots, component_id)
    output = job["output"]
    rate = output["frameRate"]
    contract = {
        **output,
        "frameRate": {"num": rate["numerator"], "den": rate["denominator"]},
    }
    canvas = _artcraft_canvas(snapshots["cmap"], layer, contract)
    region, cue = _canonical_cue(snapshots, component, layer, contract)
    if layer.get("placement") != {"x": 0, "y": 0, **canvas}:
        raise ArtCraftError("ArtCraft lower third must cover the canonical canvas")
    return {
        "componentId": component_id,
        "layerId": layer["layerId"],
        "cueId": cue["cueId"],
        "range": region,
        "canvas": canvas,
        "zOrder": layer["zOrder"],
    }


def _artcraft_canvas(cmap, layer, contract):
    """Use the declared program canvas, or the complete Tracks canvas for raw cuts."""
    selected = (
        cmap.get("importOutput")
        or cmap.get("renderOutput")
        or layer.get("placement", {})
    )
    width, height = selected.get("width"), selected.get("height")
    if not all(type(value) is int and value > 0 for value in (width, height)):
        raise ArtCraftError("ArtCraft needs exact positive canonical canvas dimensions")
    if selected.get("frameRate", contract["frameRate"]) != contract["frameRate"]:
        raise ArtCraftError("ArtCraft needs the exact canonical canvas frame rate")
    if width * contract["height"] != height * contract["width"]:
        raise ArtCraftError("ArtCraft must preserve the canonical canvas aspect ratio")
    return {"width": width, "height": height}


def _selected_overlay(snapshots, component_id):
    components = [
        value
        for value in snapshots["animation"].get("components", [])
        if value["componentId"] == component_id
    ]
    generator = {"adapterId": "artcraft.anicraft", "componentId": component_id}
    layers = [
        layer
        for layer in snapshots["tracks"].get("videoTracks", {}).get("layers", [])
        if layer.get("generator") == generator
    ]
    if (len(components), len(layers)) != (1, 1):
        raise ArtCraftError(
            "Select exactly one Animation component and ArtCraft Tracks layer"
        )
    layer = layers[0]
    expected = {
        "animationRef": component_id,
        "role": "overlay",
        "order": layer.get("zOrder"),
    }
    if (
        any(layer.get(key) != value for key, value in expected.items())
        or type(layer.get("zOrder")) is not int
        or {"source", "generatedSourceRef", "crop"}.intersection(layer)
    ):
        raise ArtCraftError("ArtCraft requires an uncropped logical overlay on Tracks")
    return components[0], layer


def _canonical_export_scope(workspace, job):
    current = workspace.active_dependency_snapshot()
    context = job["request"]["context"]
    canonical = {
        "project": file_fingerprint(Path(workspace.project_path)),
        "provider": workspace.project.get("provider"),
        "videoId": workspace.video_id,
        "heads": current,
    }
    if (
        context["kind"] != "video"
        or Path(job["workspace"]) != workspace.raw_dir.resolve()
    ):
        raise ArtCraftError(
            "ArtCraft export belongs to a different video workspace",
            code="ARTCRAFT_SCOPE_CHANGED",
        )
    selected = {
        "project": job["projectFingerprint"],
        "provider": job["request"]["provider"],
        "videoId": context["videoId"],
        "heads": job["canonicalHeads"],
    }
    if "cmap" not in current or canonical != selected:
        raise ArtCraftError(
            "ArtCraft canonical export scope is incomplete or stale",
            code="ARTCRAFT_SCOPE_CHANGED",
        )
    return canonical


def build_artcraft_asset_record(binding, binding_ref, observed, *, asset_id):
    """Construct the generated-media record from independent encoded observations."""
    contract = binding["outputContract"]
    hashes = observed["rgbaFrameHashes"]
    _require_encoded_observations(contract, observed, hashes)
    files = [
        binding["nativeSource"],
        binding["recipe"],
        binding["jobRef"],
        binding_ref,
        *binding.get("inputSources", []),
        *binding["frames"],
    ]
    environment = binding["environment"]
    receipt = seal_record(
        "receipt",
        {
            "version": 1,
            "artifactState": "admitted",
            "app": environment["app"],
            "requestHash": binding["requestHash"],
            "nativeRevisionHash": binding["nativeRevisionHash"],
            "parameterHash": binding["parameterHash"],
            "recipeHash": binding["recipeHash"],
            "environmentHash": binding["environmentHash"],
            "bindingHash": binding["bindingHash"],
            "bindingRef": binding_ref,
            "inputs": files,
            "output": contract,
            "observed": [observed["fingerprint"]],
            "rebuildEvidenceHash": content_hash(hashes),
        },
    )
    return {
        "assetId": asset_id,
        "role": "overlay",
        "generator": {
            "adapterId": f"artcraft.{environment['app']}",
            "version": environment["release"],
            "executableSha256": environment["executable"]["sha256"],
            "sourceSha256": binding["nativeRevisionHash"],
        },
        "parameters": {"artcraft": receipt},
        "sourceFree": False,
        "environment": {
            "platform": environment["platform"],
            "dependencies": {
                "artcraft-command-schema": environment["commandSchemaHash"]
            },
        },
        "inputs": [
            {
                "artifactId": f"{asset_id}:native-{index:05d}",
                "fingerprint": item,
                "ancestryRole": "dependency",
            }
            for index, item in enumerate(files)
        ],
        "output": observed["fingerprint"],
        "reproducibility": "verified",
        "approvalReference": None,
    }


def _require_encoded_observations(contract, observed, hashes):
    if (
        contract["role"] != "overlay-video"
        or observed["frameRate"] != contract["frameRate"]
    ):
        raise ArtCraftError(
            "ArtCraft encoded output does not match its selected role and frame rate"
        )
    if len(hashes) != contract["frameCount"] or not all(
        isinstance(value, str) and re.fullmatch(r"[a-f0-9]{64}", value)
        for value in hashes
    ):
        raise ArtCraftError(
            "ArtCraft requires complete independent output frame observations"
        )


def read_artcraft_binding(workspace, reference):
    """Recompute the binding from its retained source and current project."""
    locator = _owned_derived_path(workspace, reference["locator"])
    if file_fingerprint(locator) != reference:
        raise ArtCraftError(
            "ArtCraft input lock file changed", code="ARTCRAFT_SCOPE_CHANGED"
        )
    stored = json.loads(locator.read_text(encoding="utf-8"))
    if not isinstance(stored, dict) or not {"jobRef", "exportHead"} <= stored.keys():
        raise ArtCraftError("ArtCraft input lock identity is incomplete")
    current = freeze_export_binding(
        workspace,
        job_ref=stored["jobRef"]["locator"],
        expected_head=stored["exportHead"],
    )
    if stored != current:
        raise ArtCraftError(
            "ArtCraft input lock is stale or belongs to another scope",
            code="ARTCRAFT_SCOPE_CHANGED",
        )
    return current


def require_artcraft_operation_binding(operation, record, binding, canonical_lock=None):
    """Check phase, order and source identity against the original video binding."""
    receipt = record["parameters"]["artcraft"]
    reference = receipt["bindingRef"]
    parameters = operation["parameters"]
    if (
        parameters["inputLockRef"]
        != {"path": reference["locator"], "sha256": reference["sha256"]}
        or binding.get("bindingHash") != receipt["bindingHash"]
        or document_hash_excluding(binding, "bindingHash") != receipt["bindingHash"]
    ):
        raise ArtCraftError("ArtCraft operation uses a different input binding")
    placement = binding["placement"]
    contract = binding["outputContract"]
    expected = {
        "sourceRange": {"startFrame": 0, "endFrameExclusive": contract["frameCount"]},
        "zOrder": placement["zOrder"],
        "layerRole": "overlay",
        "alphaMode": contract["alpha"],
    }
    if (
        operation["kind"] != "overlay-video"
        or operation["outputRange"] != placement["range"]
        or any(parameters.get(key) != value for key, value in expected.items())
    ):
        raise ArtCraftError(
            "ArtCraft operation differs from its canonical overlay and phases"
        )
    if canonical_lock is not None:
        _require_frozen_proof_inputs(record, binding, canonical_lock)
    return binding


def _require_frozen_proof_inputs(record, binding, canonical_lock):
    if canonical_lock.get("input-lock:" + record["assetId"]) != binding["bindingHash"]:
        raise ArtCraftError("ArtCraft source binding is missing from the proof lock")
    heads = binding["canonical"]["heads"]
    for key in ("cmap", "bmap", "tracks", "animation", "sync-map"):
        if key not in heads or canonical_lock.get(key) != heads[key]:
            raise ArtCraftError(
                "ArtCraft canonical inputs differ from the frozen proof plan"
            )


def require_artcraft_output_geometry(operation, contract, output):
    """Allow only a full canvas placement at its canonical aspect and exact clock."""
    rate = contract["frameRate"]
    if Fraction(output["frameRate"]["num"], output["frameRate"]["den"]) != Fraction(
        rate["numerator"], rate["denominator"]
    ):
        raise ArtCraftError("ArtCraft proof changes the selected native frame rate")
    canvas = {key: output[key] for key in ("width", "height")}
    if canvas["width"] * contract["height"] != canvas["height"] * contract[
        "width"
    ] or operation["parameters"]["placement"] != {"x": 0, "y": 0, **canvas}:
        raise ArtCraftError("ArtCraft proof changes the selected full canvas geometry")


def _owned_derived_path(workspace, locator):
    path = Path(locator)
    directory = workspace.raw_dir.resolve() / "edit" / "derived"
    if (
        not path.is_absolute()
        or path.resolve() != path
        or not path.is_relative_to(directory)
        or path.stat().st_nlink != 1
        or not path.is_file()
    ):
        raise ArtCraftError(
            "ArtCraft generated evidence must be an owned file under edit/derived"
        )
    return path


def verify_artcraft_asset_record(workspace, record, observed):
    """Reject receipt claims that differ from current native and encoded evidence."""
    with fingerprint_stage(reuse_current=True, verify_on_exit=True):
        receipt = validate_record("receipt", record["parameters"]["artcraft"])
        reference = receipt["bindingRef"]
        binding = read_artcraft_binding(workspace, reference)
        output = _owned_derived_path(workspace, observed["fingerprint"]["locator"])
        if file_fingerprint(output) != observed["fingerprint"]:
            raise ArtCraftError(
                "ArtCraft encoded observation is stale", code="ARTCRAFT_SCOPE_CHANGED"
            )
        expected = build_artcraft_asset_record(
            binding, reference, observed, asset_id=record["assetId"]
        )
        body = {
            key: value
            for key, value in record.items()
            if key not in {"schemaVersion", "recordHash"}
        }
        if body != expected:
            raise ArtCraftError(
                "ArtCraft receipt differs from its frozen source and output evidence",
                code="ARTCRAFT_SCOPE_CHANGED",
            )
        return deepcopy(record)
