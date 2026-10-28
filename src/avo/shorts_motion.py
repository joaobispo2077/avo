"""Selected motion and already-generated alpha for the outer Shorts workflow."""

from __future__ import annotations

import json
from copy import deepcopy
from fractions import Fraction
from pathlib import Path
from typing import Any

from avo.motion import canonical_code_drawn_binding, validate_engine
from avo.timeline.generated_assets import GeneratedAssetService
from avo.timeline.workspace import TimelineWorkspace


def engine(value: dict[str, Any]) -> str:
    return validate_engine(value.get("motionEngine", "hyperframes"))


def workspace_from_paths(paths: Any) -> TimelineWorkspace:
    if paths is None:
        raise RuntimeError(
            "code-drawn Shorts require canonical workspace/batch context"
        )
    return TimelineWorkspace.from_project(Path(paths.raw_dir) / "avo.project.json")


def _manifest_path(workspace: Any, reference: dict) -> Path:
    value = Path(reference["path"])
    return (
        value.resolve()
        if value.is_absolute()
        else (Path(workspace.raw_dir) / value).resolve()
    )


def _require_binding_record(
    workspace: Any, binding: dict, record: dict
) -> tuple[Path, dict]:
    current = canonical_code_drawn_binding(workspace, binding["instanceId"])
    extension = record["parameters"]["codeDrawn"]
    manifest = _manifest_path(workspace, current["reference"]["manifestRef"])
    same_manifest = (
        manifest == _manifest_path(workspace, binding["manifestRef"]),
        binding["manifestRef"]["sha256"]
        == current["reference"]["manifestRef"]["sha256"],
        manifest == _manifest_path(workspace, extension["manifestRef"]),
    )
    if not all(same_manifest):
        raise RuntimeError("code-drawn Shorts manifest binding is stale")
    if current["canonicalInputLock"] != extension["canonicalInputLock"]:
        raise RuntimeError("code-drawn Shorts canonical binding is stale")
    if binding["inputLockRef"] != extension["inputLockRef"]:
        raise RuntimeError("code-drawn Shorts original input lock differs")
    return manifest, current


def _require_alpha_contract(record: dict, item: dict, output: dict) -> None:
    observed = record["parameters"]["codeDrawn"]["outputVerification"]
    rate = Fraction(str(output.get("frameRateRational") or output["fps"]))
    duration_frames = Fraction(str(item["editedDurationSec"])) * rate
    expected = (int(output["width"]), int(output["height"]), rate, duration_frames)
    actual = (
        observed["width"],
        observed["height"],
        Fraction(observed["frameRate"]["num"], observed["frameRate"]["den"]),
        observed["frameCount"],
    )
    if actual != expected or observed["alphaMode"] != "straight":
        raise RuntimeError(
            "code-drawn alpha must exactly match the Short dimensions, rate, duration and transparency"
        )
    if not observed["silent"]:
        raise RuntimeError("code-drawn Shorts alpha must be silent")


def preflight_alpha(
    spec: dict, workspace: Any, item: dict, output: dict
) -> tuple[GeneratedAssetService, dict, Path]:
    if workspace is None:
        raise RuntimeError("code-drawn Shorts require real canonical workspace context")
    binding = spec.get("codeDrawn")
    if not isinstance(binding, dict):
        raise RuntimeError(
            "code-drawn Shorts need a bound canonical generated alpha asset"
        )
    reference = binding["generatedAssetRef"]
    service = GeneratedAssetService(workspace)
    record = service.load(reference["assetId"])
    if record["recordHash"] != reference["recordHash"]:
        raise RuntimeError("code-drawn Shorts generated receipt is stale")
    receipt_path = Path(reference["locator"])
    if json.loads(receipt_path.read_text(encoding="utf-8")) != record:
        raise RuntimeError(
            "code-drawn Shorts receipt locator does not match its registered record"
        )
    manifest, current = _require_binding_record(workspace, binding, record)
    _require_caption_plan(
        current["manifest"], spec.get("captions") or item.get("captions") or []
    )
    _require_short_projection(workspace, current, item, output)
    _require_alpha_contract(record, item, output)
    service.validate_code_drawn_inputs(record["inputs"])
    return service, record, manifest


def admitted_alpha(
    spec: dict, workspace: Any, item: dict, output: dict
) -> tuple[Path, dict]:
    from avo.proof_composition import observe_code_drawn_environment

    service, expected, manifest = preflight_alpha(spec, workspace, item, output)
    observed = observe_code_drawn_environment(
        manifest,
        expected_evidence=expected["parameters"]["codeDrawn"]["captureEvidence"],
    )
    admitted = service.admit(expected["assetId"], code_drawn_environment=observed)
    if admitted["recordHash"] != expected["recordHash"]:
        raise RuntimeError(
            "code-drawn Shorts receipt changed during current observation"
        )
    return Path(admitted["output"]["locator"]), admitted


def receipt_lock(record: dict) -> dict[str, str]:
    extension = record["parameters"]["codeDrawn"]
    return {
        "generated:" + record["assetId"]: record["recordHash"],
        "input-lock:" + extension["instanceId"]: extension["inputLockHash"],
        "input-lock-file:" + extension["instanceId"]: extension["inputLockRef"][
            "sha256"
        ],
        "generator:code-drawn-executable": record["generator"]["executableSha256"],
        "generator:code-drawn-source": record["generator"]["sourceSha256"],
    }


def pinned_fields(item: dict) -> dict:
    return {
        key: deepcopy(item[key]) for key in ("motionEngine", "codeDrawn") if key in item
    }


def _clock(value: dict) -> Fraction:
    base = value.get("timebase") or {"num": 1, "den": 1000}
    return Fraction(value["ticks"] * base["num"], base["den"])


def _short_segment(item: dict) -> dict:
    segments = item.get("sourceSegments") or []
    if len(segments) != 1 or Fraction(str(item.get("speed", 1))) != 1:
        raise RuntimeError(
            "code-drawn Shorts currently require one contiguous segment at speed 1"
        )
    return segments[0]


def _canonical_source_interval(
    workspace: Any, binding: dict, rate: Fraction
) -> tuple[dict, Fraction, Fraction]:
    index = workspace.require_active("cmap")
    cmap = workspace.store("cmap").revision(index["headRevisionId"])["snapshot"]
    start = Fraction(binding["range"]["startFrame"], 1) / rate
    end = Fraction(binding["range"]["endFrameExclusive"], 1) / rate
    offset = Fraction(0)
    for segment in cmap["segments"]:
        duration = _clock(segment["out"]) - _clock(segment["in"])
        if offset <= start and end <= offset + duration:
            source = next(
                value
                for value in cmap["sources"]
                if value["sourceId"] == segment["sourceId"]
            )
            return (
                source,
                _clock(segment["in"]) + start - offset,
                _clock(segment["in"]) + end - offset,
            )
        offset += duration
    raise RuntimeError(
        "code-drawn Shorts cannot restart an offset or cut-spanning canonical drawing"
    )


def _require_short_projection(
    workspace: Any, binding: dict, item: dict, output: dict
) -> None:
    segment = _short_segment(item)
    rate = Fraction(str(output.get("frameRateRational") or output["fps"]))
    source, start, end = _canonical_source_interval(workspace, binding, rate)
    expected = (source["fingerprint"]["sha256"], start, end)
    actual = (
        segment["sourceFingerprint"],
        Fraction(str(segment["startSec"])),
        Fraction(str(segment["endSec"])),
    )
    if actual != expected:
        raise RuntimeError(
            "code-drawn Shorts range does not project the same selected canonical content"
        )
    placement = binding["placement"]
    full_frame = (0, 0, int(output["width"]), int(output["height"]))
    if tuple(placement[key] for key in ("x", "y", "width", "height")) != full_frame:
        raise RuntimeError(
            "code-drawn Shorts currently require a full-canvas alpha placement"
        )


def require_proof(item: dict, output: dict, paths: Any) -> Any:
    selected = engine(item)
    if selected == "hyperframes":
        return None
    if selected != "code-drawn":
        raise RuntimeError(
            "Remotion Shorts rendering is unsupported; select a supported motion engine explicitly"
        )
    if output.get("pixelFormat") != "yuv420p10le":
        raise RuntimeError(
            "code-drawn Shorts require the original-picture source-fidelity output profile"
        )
    unsupported = [
        key
        for key in ("callouts", "graphics", "punchIns", "visualInserts")
        if item.get(key)
    ]
    if unsupported or item["layout"]["mode"] != "full-frame":
        raise RuntimeError(
            "code-drawn Shorts do not port HyperFrames treatments: "
            + ", ".join(unsupported or ["split layout"])
        )
    workspace = workspace_from_paths(paths)
    preflight_alpha(item, workspace, item, output)
    return workspace


def composition_spec(
    *,
    batch_id: str,
    item: dict,
    output: dict,
    assets: dict,
    proof_revision: int,
    expected_output_path: Path,
    provider_tokens=None,
) -> dict:
    from avo import shorts_contract

    spec = {
        "version": "1.2",
        "batchId": batch_id,
        "shortId": str(item["id"]),
        "proofRevision": proof_revision,
        "width": int(output["width"]),
        "height": int(output["height"]),
        "fps": float(output["fps"]),
        "durationSec": float(item["editedDurationSec"]),
        "assets": dict(assets),
        "layout": {
            "mode": "full-frame",
            "captionAnchor": item["layout"]["captionAnchor"],
            "baseRegion": {"x": 0, "y": 0, "width": 1, "height": 1},
        },
        "captions": deepcopy(item.get("captions") or []),
        "providerTokens": dict(provider_tokens or {}),
        "templateVersion": "code-drawn-admitted-alpha-v1",
        "expectedOutputPath": str(expected_output_path),
        "provenanceReferences": list(item.get("factualReviewReferences") or []),
        **pinned_fields(item),
    }
    shorts_contract.validate_document(spec, "composition")
    return spec


def _require_caption_plan(manifest: dict, captions: list) -> None:
    from avo.shorts_contract import content_hash

    if not captions:
        return
    authored = manifest.get("extensions", {}).get("shortsCaptionPlanHash")
    if authored != content_hash(captions):
        raise RuntimeError(
            "code-drawn caption plan is not declared in the authored source; author the exact caption plan, reseal source/manifest/input lock and regenerate the alpha before proof"
        )


def revalidate_alpha(
    spec: dict, workspace: Any, item: dict, output: dict, expected: dict
) -> None:
    _, current = admitted_alpha(spec, workspace, item, output)
    if current["recordHash"] != expected["recordHash"]:
        raise RuntimeError(
            "code-drawn alpha changed while the Short proof was rendering"
        )
