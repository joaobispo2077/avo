"""Code-drawn source identities at canonical schema and authoring boundaries."""

from __future__ import annotations

import copy
import json

import pytest

from avo.motion import MotionError, scaffold_code_drawn
from avo.timeline.animation import AnimationError, AnimationService
from avo.timeline.bmap_service import BMapService
from avo.timeline.contracts import (
    ContractError,
    canonical_json_bytes,
    file_fingerprint,
    validate_document,
)
from avo.timeline.tracks import TracksService
from tests.test_timeline_animation_service import strategy
from tests.test_timeline_bmap_service import approved_workspace, cue
from tests.test_timeline_tracks_service import canonical_tracks
from tests.test_video_animation_schema import strategy_document

SHA = "a" * 64


def canonical_drawing_reference(workspace, instance_id="drawing-one"):
    destination = (
        workspace.raw_dir
        / "edit"
        / "derived"
        / "components"
        / instance_id
        / "source-r0001"
    )
    scaffold_code_drawn(
        destination,
        route="canvas",
        width=128,
        height=96,
        fps="30/1",
        frames=9,
        background="transparent",
    )
    composition = destination / "composition.json"
    return {
        "engine": "code-drawn",
        "instanceId": instance_id,
        "manifestRef": {
            "path": composition.relative_to(workspace.raw_dir).as_posix(),
            "sha256": file_fingerprint(composition)["sha256"],
        },
    }


def code_drawn_strategy(reference):
    value = strategy()
    value["framework"] = "code-drawn"
    component = value["components"][0]
    component.pop("providerPatternRef")
    component["extensions"] = {
        "codeDrawn": {
            "instanceId": reference["instanceId"],
            "manifestRef": copy.deepcopy(reference["manifestRef"]),
        }
    }
    return value


def _schema_strategy():
    document = strategy_document()
    value = document["revisions"][0]["strategy"]
    value["framework"] = "code-drawn"
    component = value["components"][0]
    component.pop("providerPatternRef")
    component["extensions"] = {
        "codeDrawn": {
            "instanceId": "drawing-one",
            "manifestRef": {
                "path": "edit/derived/components/drawing-one/source-r0001/composition.json",
                "sha256": SHA,
            },
        }
    }
    return document, value, component["extensions"]["codeDrawn"]


def test_canonical_animation_ref_has_no_output_or_timing_authority():
    document, value, reference = _schema_strategy()
    validate_document(document, "avo.animation.schema.json")
    assert set(reference) == {"instanceId", "manifestRef"}
    assert set(reference["manifestRef"]) == {"path", "sha256"}
    assert not {"start", "end", "startTicks", "endTicks", "generatedAssetRef"} & set(
        value
    )


@pytest.mark.parametrize(
    "missing", ["extensions", "codeDrawn", "instanceId", "manifestRef"]
)
def test_code_drawn_strategy_requires_its_source_reference(missing):
    document, value, reference = _schema_strategy()
    component = value["components"][0]
    if missing == "extensions":
        component.pop("extensions")
    elif missing == "codeDrawn":
        component["extensions"].pop("codeDrawn")
    else:
        reference.pop(missing)
    with pytest.raises(ContractError):
        validate_document(document, "avo.animation.schema.json")


@pytest.mark.parametrize(
    ("key", "invalid"),
    [
        ("instanceId", ""),
        ("instanceId", "Wrong-ID"),
        ("instanceId", "../drawing-one"),
        ("manifestRef", None),
        (
            "manifestRef",
            {"path": "edit/derived/components/drawing-one/composition.json"},
        ),
        (
            "manifestRef",
            {
                "path": "edit/derived/components/drawing-one/composition.json",
                "sha256": "not-a-hash",
            },
        ),
        ("manifestRef", {"path": "", "sha256": SHA}),
        ("manifestRef", {"path": "../composition.json", "sha256": SHA}),
        ("manifestRef", {"path": "/external/composition.json", "sha256": SHA}),
        ("manifestRef", {"path": "C:/external/composition.json", "sha256": SHA}),
        (
            "manifestRef",
            {"path": "edit/derived/components/../composition.json", "sha256": SHA},
        ),
    ],
)
def test_canonical_strategy_reference_is_typed_local_and_fingerprinted(key, invalid):
    document, _, reference = _schema_strategy()
    reference[key] = invalid
    with pytest.raises(ContractError):
        validate_document(document, "avo.animation.schema.json")


@pytest.mark.parametrize(
    "field",
    ["start", "end", "startTicks", "endTicks", "outputHash", "generatedAssetRef"],
)
def test_logical_code_drawn_reference_rejects_timing_and_future_output_fields(field):
    document, _, reference = _schema_strategy()
    reference[field] = SHA
    with pytest.raises(ContractError):
        validate_document(document, "avo.animation.schema.json")


@pytest.mark.parametrize("location", ["component", "strategy"])
def test_code_drawn_cannot_retain_a_hyperframes_provider_pattern(location):
    document, value, _ = _schema_strategy()
    if location == "component":
        value["components"][0]["providerPatternRef"] = "c01-c02"
    else:
        value["providerPatternRefs"] = ["c01-c02"]
    with pytest.raises(ContractError):
        validate_document(document, "avo.animation.schema.json")


@pytest.fixture
def canonical_authoring(tmp_path):
    workspace, _, _ = approved_workspace(tmp_path)
    BMapService(workspace).author(
        {"cues": [cue()]}, actor="avo", reason="approved-cut cue"
    )
    TracksService(workspace).author(
        canonical_tracks(workspace, workspace.raw_dir / "raw.bin"),
        actor="avo",
        reason="canonical placement",
    )
    reference = canonical_drawing_reference(workspace)
    return workspace, reference


def test_animation_author_preserves_logical_manifest_identity(canonical_authoring):
    workspace, reference = canonical_authoring
    supplied = code_drawn_strategy(reference)
    before = canonical_json_bytes(supplied)
    revision = AnimationService(workspace).author(
        supplied, actor="avo", reason="code-drawn source revision"
    )
    actual = revision["snapshot"]
    assert actual["framework"] == "code-drawn"
    assert actual["components"] == supplied["components"]
    assert set(actual["dependencies"]) == {"cmap", "bmap", "tracks"}
    assert canonical_json_bytes(supplied) == before


@pytest.mark.parametrize(
    "mutation",
    [
        "path-instance",
        "manifest-hash",
        "missing-manifest",
        "changed-source",
        "duplicate-component",
        "duplicate-instance",
        "provider-pattern",
    ],
)
def test_animation_author_rejects_invalid_code_drawn_identity_before_revision(
    canonical_authoring, mutation
):
    workspace, reference = canonical_authoring
    value = code_drawn_strategy(reference)
    component = value["components"][0]
    binding = component["extensions"]["codeDrawn"]
    composition = workspace.raw_dir / reference["manifestRef"]["path"]
    if mutation == "path-instance":
        binding["instanceId"] = "different-instance"
    elif mutation == "manifest-hash":
        binding["manifestRef"]["sha256"] = "b" * 64
    elif mutation == "missing-manifest":
        composition.unlink()
    elif mutation == "changed-source":
        manifest = json.loads(composition.read_text(encoding="utf-8"))
        (composition.parent / manifest["entry"]).write_text(
            "changed drawing", encoding="utf-8"
        )
    elif mutation == "duplicate-component":
        duplicate = copy.deepcopy(component)
        other = canonical_drawing_reference(workspace, "drawing-two")
        duplicate["extensions"]["codeDrawn"] = {
            "instanceId": other["instanceId"],
            "manifestRef": other["manifestRef"],
        }
        value["components"].append(duplicate)
    elif mutation == "duplicate-instance":
        duplicate = copy.deepcopy(component)
        duplicate["componentId"] = "different-component"
        value["components"].append(duplicate)
    else:
        component["providerPatternRef"] = "c01-c02"
    store = workspace.store("animation")
    before = canonical_json_bytes(store.load_index())
    with pytest.raises((AnimationError, MotionError, ContractError)):
        AnimationService(workspace).author(
            value, actor="avo", reason="invalid identity"
        )
    assert canonical_json_bytes(store.load_index()) == before


@pytest.mark.parametrize(
    "field",
    ["start", "end", "startTicks", "endTicks", "timestamp", "timestamps", "timing"],
)
def test_animation_extensions_cannot_introduce_nested_cue_timing(
    canonical_authoring, field
):
    workspace, reference = canonical_authoring
    value = code_drawn_strategy(reference)
    value["extensions"] = {"review": [{"nested": {field: 100}}]}
    with pytest.raises(AnimationError, match="timing"):
        AnimationService(workspace).author(
            value, actor="avo", reason="invalid clock owner"
        )


def test_new_code_drawn_authoring_does_not_rewrite_historical_hyperframes_revision(
    canonical_authoring,
):
    workspace, reference = canonical_authoring
    service = AnimationService(workspace)
    old = service.author(
        strategy(), actor="avo", reason="historical HyperFrames strategy"
    )
    before = canonical_json_bytes(
        workspace.store("animation").revision(old["revisionId"])
    )
    service.author(
        code_drawn_strategy(reference), actor="avo", reason="new code-drawn strategy"
    )
    assert (
        canonical_json_bytes(workspace.store("animation").revision(old["revisionId"]))
        == before
    )


def _receipt():
    return {
        "schemaVersion": "1.0.0",
        "assetId": "drawing-one-output",
        "role": "overlay",
        "generator": {
            "adapterId": "code-drawn",
            "version": "1.0.0",
            "executableSha256": SHA,
            "sourceSha256": SHA,
        },
        "parameters": {
            "codeDrawn": {
                "instanceId": "drawing-one",
                "drawingRoute": "canvas",
                "manifestRef": {
                    "path": "C:/project/source/composition.json",
                    "sha256": SHA,
                },
                "sourceRevision": "source-r0001",
                "inputLockRef": {
                    "path": "C:/project/source/input-lock.json",
                    "sha256": SHA,
                },
                "inputLockHash": SHA,
                "renderContractHash": SHA,
                "inputsHash": SHA,
                "captureEvidence": {"frames": [0], "rgbaSha256": [SHA]},
                "outputVerification": {"rgbaRoundTrip": "exact"},
            }
        },
        "inputs": [],
        "sourceFree": True,
        "environment": {"platform": "test", "dependencies": {}},
        "output": {
            "locator": "C:/project/output/asset.mkv",
            "sha256": SHA,
            "sizeBytes": 1,
        },
        "reproducibility": "verified",
        "approvalReference": None,
        "recordHash": SHA,
    }


def test_generated_asset_receipt_accepts_actual_code_drawn_extension_shape():
    validate_document(_receipt(), "avo.generated-asset.schema.json")


@pytest.mark.parametrize(
    "field",
    [
        "instanceId",
        "drawingRoute",
        "manifestRef",
        "sourceRevision",
        "inputLockRef",
        "inputLockHash",
        "renderContractHash",
        "inputsHash",
        "captureEvidence",
        "outputVerification",
    ],
)
def test_code_drawn_receipt_requires_complete_render_identity(field):
    record = _receipt()
    record["parameters"]["codeDrawn"].pop(field)
    with pytest.raises(ContractError):
        validate_document(record, "avo.generated-asset.schema.json")


@pytest.mark.parametrize("value", [None, {}, "code-drawn"])
def test_known_code_drawn_generator_cannot_omit_typed_receipt_extension(value):
    record = _receipt()
    if value is None:
        record["parameters"].pop("codeDrawn")
    else:
        record["parameters"]["codeDrawn"] = value
    with pytest.raises(ContractError):
        validate_document(record, "avo.generated-asset.schema.json")


@pytest.mark.parametrize("field", ["manifestRef", "inputLockRef"])
@pytest.mark.parametrize(
    "invalid",
    [
        {"path": "file.json"},
        {"sha256": SHA},
        {"path": "file.json", "sha256": "bad"},
        {"path": "file.json", "sha256": SHA, "outputHash": SHA},
    ],
)
def test_receipt_input_file_references_are_strict_path_and_byte_hash(field, invalid):
    record = _receipt()
    record["parameters"]["codeDrawn"][field] = invalid
    with pytest.raises(ContractError):
        validate_document(record, "avo.generated-asset.schema.json")


def test_historical_other_generator_receipt_requires_no_code_drawn_metadata():
    record = _receipt()
    record["generator"]["adapterId"] = "hyperframes"
    record["parameters"] = {"title": "Historical title"}
    before = canonical_json_bytes(record)
    validate_document(record, "avo.generated-asset.schema.json")
    assert canonical_json_bytes(record) == before


@pytest.mark.parametrize(
    ("field", "invalid"),
    [
        ("drawingRoute", "p5-brush"),
        ("inputLockHash", "not-a-hash"),
        ("inputsHash", None),
        ("renderContractHash", ""),
        ("captureEvidence", []),
        ("outputVerification", "passed"),
    ],
)
def test_code_drawn_receipt_identity_fields_have_exact_types(field, invalid):
    record = _receipt()
    record["parameters"]["codeDrawn"][field] = invalid
    with pytest.raises(ContractError):
        validate_document(record, "avo.generated-asset.schema.json")


def test_current_cut_approval_output_must_match_the_drawing_bmap_basis(tmp_path):
    from avo import motion
    from tests.code_drawn_asset_fixture import canonical_asset

    asset = canonical_asset(tmp_path)
    store = asset.workspace.store("cmap")
    index = store.load_index()
    revision = store.revision(index["headRevisionId"])
    store.approve(
        revision["revisionId"],
        revision_hash=revision["contentHash"],
        candidate_hash="f" * 64,
    )
    with pytest.raises(MotionError, match="approved|basis|cut"):
        motion.freeze_code_drawn_lock(
            asset.composition,
            workspace=asset.workspace,
            instance_id=asset.reference["instanceId"],
            environment=asset.environment,
        )
