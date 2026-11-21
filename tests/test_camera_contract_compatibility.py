"""Advanced camera intent cannot be published where a v1 reader can ignore it."""

import json
from copy import deepcopy
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, ValidationError

from avo.timeline.contracts import ContractError, content_hash, validate_document
from avo.timeline.motion_review import MotionReviewService
from avo.timeline.store import ArtifactStore, StoreError, atomic_write_json
from avo.timeline.workspace import TimelineWorkspace
from tests.test_timeline_animation_service import strategy


def advanced(framework="hyperframes"):
    value = strategy()
    value.update(
        strategyContractVersion="2.0.0",
        framework=framework,
        dependencies={name: "a" * 64 for name in ("cmap", "bmap", "tracks")},
    )
    component = value["components"][0]
    component.pop("providerPatternRef")
    component["extensions"] = {
        "editingCraft": {
            "camera": {
                "contractVersion": "1.0.0",
                "targetLayerId": "presenter",
                "sourceId": "camera-main",
                "nodes": [
                    {
                        "phase": 0,
                        "scale": 1,
                        "center": {"x": 0.5, "y": 0.5},
                        "curve": "linear",
                    },
                    {
                        "phase": 1,
                        "scale": 1.2,
                        "center": {"x": 0.5, "y": 0.5},
                        "curve": "linear",
                    },
                ],
            }
        }
    }
    return value


def camera_store(tmp_path):
    store = ArtifactStore(tmp_path / "animation.json")
    store.initialize(
        artifact_type="animation",
        artifact_id="camera:animation",
        video_id="camera",
        provider="example",
        timeline_domain="cmap-output",
    )
    return store


def test_legacy_reads_and_preparation_do_not_upgrade_the_index(tmp_path):
    store = camera_store(tmp_path)
    before = store.path.read_bytes()
    store.prepare_revision(
        snapshot={"legacy": "opaque"}, actor="creator", reason="Legacy preparation"
    )
    assert store.load_index()["schemaVersion"] == "1.0.0"
    assert store.path.read_bytes() == before


@pytest.mark.parametrize("framework", ["hyperframes", "remotion", "code-drawn"])
def test_native_camera_strategy_is_strict_and_engine_independent(framework):
    value = advanced(framework)
    validate_document(value, "avo.animation.schema.json#/$defs/videoStrategy")


def test_preparation_is_pure_and_publication_atomically_fences_the_new_reader(
    tmp_path, monkeypatch
):
    from avo.timeline import store as store_module

    store = camera_store(tmp_path)
    before = store.path.read_bytes()
    prepared = store.prepare_revision(
        snapshot=advanced(), actor="creator", reason="Selected move"
    )
    assert store.path.read_bytes() == before
    original, writes = store_module.atomic_write_json, []

    def record(path, value):
        if path == store.path:
            writes.append(deepcopy(value))
            assert value["schemaVersion"] == "2.0.0"
            assert set(value["requiredReaderCapabilities"]) == {
                "animation-strategy-v2",
                "camera-behavior-v1",
            }
            assert value["headRevisionId"] == prepared["revisionId"]
        return original(path, value)

    monkeypatch.setattr(store_module, "atomic_write_json", record)
    published = store.append_prepared_revision(prepared, expected_head_hash=None)
    assert len(writes) == 1
    assert published["contentHash"] == prepared["contentSha256"]
    assert store.load_index()["schemaVersion"] == "2.0.0"


@pytest.mark.parametrize(
    "mutation",
    ["unmarked", "null", "unknown", "bad-camera", "reserved-field", "nested-timing"],
)
def test_generic_store_preparation_cannot_bypass_camera_contracts(tmp_path, mutation):
    store = camera_store(tmp_path)
    value = advanced()
    wrapper = value["components"][0]["extensions"]["editingCraft"]
    if mutation == "unmarked":
        value.pop("strategyContractVersion")
    elif mutation == "null":
        value["strategyContractVersion"] = None
    elif mutation == "unknown":
        value["strategyContractVersion"] = "99.0.0"
    elif mutation == "bad-camera":
        wrapper["camera"]["nodes"][1]["scale"] = 0
    elif mutation == "reserved-field":
        wrapper["expression"] = "arbitrary code"
    else:
        value["extensions"] = {"nested": {"startFrame": 12}}
    before = store.path.read_bytes()
    with pytest.raises(
        (StoreError, ContractError),
        match="camera|strategy|contract|timing|animation|immutable revision",
    ):
        store.prepare_revision(
            snapshot=value, actor="creator", reason="Invalid advanced intent"
        )
    assert store.path.read_bytes() == before


@pytest.mark.parametrize("downgrade", ["v1", "missing", "unknown"])
def test_loaded_advanced_history_requires_a_truthful_reader_guard(tmp_path, downgrade):
    store = camera_store(tmp_path)
    store.append_revision(snapshot=advanced(), actor="creator", reason="Selected move")
    index = store.load_index()
    if downgrade == "v1":
        index["schemaVersion"] = "1.0.0"
        index.pop("requiredReaderCapabilities", None)
    elif downgrade == "missing":
        index["requiredReaderCapabilities"] = ["animation-strategy-v2"]
    else:
        index["requiredReaderCapabilities"].append("unknown-reader")
    atomic_write_json(store.path, index)
    with pytest.raises(
        (StoreError, ContractError), match="reader|capabilit|index|camera"
    ):
        store.load_index()


def test_v2_guard_survives_a_later_legacy_head_and_real_v1_reader_rejects_it(tmp_path):
    store = camera_store(tmp_path)
    legacy_schema = json.loads(
        (
            Path(__file__).parent / "fixtures/camera/timeline-index-v1.schema.json"
        ).read_text(encoding="utf-8")
    )
    reader = Draft202012Validator(legacy_schema)
    reader.validate(store.load_index())
    store.append_revision(snapshot=advanced(), actor="creator", reason="Selected move")
    store.append_revision(
        snapshot={"legacy": "historical"}, actor="creator", reason="Legacy head"
    )
    index = store.load_index()
    assert index["schemaVersion"] == "2.0.0"
    with pytest.raises(ValidationError):
        reader.validate(index)


@pytest.mark.parametrize("after_replace", [False, True])
def test_interrupted_guard_publication_keeps_a_consistent_index_and_sidecar(
    tmp_path, monkeypatch, after_replace
):
    from avo.timeline import store as store_module

    store = camera_store(tmp_path)
    before = store.path.read_bytes()
    original = store_module.atomic_write_json

    def fail(path, value):
        if path == store.path:
            if after_replace:
                original(path, value)
            raise OSError("Injected publication interruption")
        return original(path, value)

    monkeypatch.setattr(store_module, "atomic_write_json", fail)
    with pytest.raises(OSError, match="Injected"):
        store.append_revision(
            snapshot=advanced(), actor="creator", reason="Selected move"
        )
    if after_replace:
        index = store.load_index()
        assert index["schemaVersion"] == "2.0.0"
        assert (store.timeline_dir / index["revisionRefs"][0]["path"]).is_file()
    else:
        assert store.path.read_bytes() == before
        assert store.load_index()["revisionRefs"] == []


def test_advanced_projection_is_a_pure_selected_head_read(tmp_path):
    project = {"provider": "example", "videoId": "camera", "rawDir": str(tmp_path)}
    path = tmp_path / "avo.project.json"
    path.write_text(json.dumps(project), encoding="utf-8")
    workspace = TimelineWorkspace.from_project(path)
    workspace.initialize()
    store = workspace.store("animation")
    revision = store.append_revision(
        snapshot=advanced(), actor="creator", reason="Selected move"
    )
    before = {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    snapshot = MotionReviewService(workspace).project()
    assert snapshot["basisHeads"]["animation"]["sha256"] == revision["contentHash"]
    assert snapshot["basisHeads"]["animation"].get("availability") != "unavailable"
    assert {path: path.read_bytes() for path in before} == before


def test_changed_advanced_body_is_still_bound_to_its_canonical_hash(tmp_path):
    store = camera_store(tmp_path)
    result = store.append_revision(
        snapshot=advanced(), actor="creator", reason="Selected move"
    )
    index = store.load_index()
    path = store.timeline_dir / index["revisionRefs"][0]["path"]
    body = json.loads(path.read_text(encoding="utf-8"))
    body["snapshot"]["components"][0]["extensions"]["editingCraft"]["camera"]["nodes"][
        1
    ]["scale"] = 1.5
    assert (
        content_hash(
            {key: value for key, value in body.items() if key != "contentSha256"}
        )
        != result["contentHash"]
    )
    atomic_write_json(path, body)
    with pytest.raises(StoreError, match="hash"):
        store.load_index()


def test_advanced_camera_cannot_silently_compile_as_v1(tmp_path):
    from avo.timeline.proof_plan import ProofPlanCompiler, ProofPlanError
    from tests.test_proof_plan import (
        proof_request,
        registry,
        regression_contract,
        workspace_with_heads,
    )

    workspace = workspace_with_heads(tmp_path)
    workspace.store("animation").append_revision(
        snapshot=advanced(), actor="creator", reason="Selected camera intent"
    )
    with pytest.raises(ProofPlanError) as failure:
        ProofPlanCompiler(workspace, registry()).compile(
            proof_request(tmp_path), regression_contract=regression_contract()
        )
    assert failure.value.code == "PROOF_CAMERA_UNAVAILABLE"
