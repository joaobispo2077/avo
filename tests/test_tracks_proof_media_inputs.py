"""Strict Tracks fingerprints own audio IDs through their locked trim descriptors."""

from copy import deepcopy
from types import SimpleNamespace

import pytest

from avo.timeline.contracts import file_fingerprint, validate_document
from avo.timeline.materialize import canonical_proof_media_inputs
from avo.timeline.proof_plan import ProofPlanCompiler
from tests.test_proof_plan import (
    proof_request,
    regression_contract,
    workspace_with_heads,
)


def _publish_tracks(case, *, strict=True):
    snapshot = {
        "basis": {
            "artifactType": "bmap",
            "artifactId": "video:bmap",
            "revisionId": "bmap-r0001",
            "sha256": case.ws.store("bmap").revision("bmap-r0001")["contentHash"],
            "state": "valid",
        },
        "audioTracks": {"layers": case.layers},
        "videoTracks": {"layers": case.video_layers},
    }
    if strict:
        validate_document(snapshot, "avo.tracks.schema.json#/$defs/tracksSnapshot")
    case.ws.store("tracks").append_revision(
        snapshot=snapshot, actor="test", reason="canonical source-only audio layers"
    )


@pytest.fixture
def case(tmp_path):
    ws = workspace_with_heads(tmp_path)
    camera = tmp_path / "camera.bin"
    camera.write_bytes(b"original camera")
    ws.store("cmap").append_revision(
        snapshot={
            "sources": [{"sourceId": "camera", "fingerprint": file_fingerprint(camera)}]
        },
        actor="test",
        reason="original CMap ownership",
    )
    audio = tmp_path / "assets" / "riser.wav"
    audio.parent.mkdir()
    audio.write_bytes(b"original shared riser")
    fingerprint = file_fingerprint(audio)
    layer = {
        "layerId": "riser-layer",
        "order": 1,
        "role": "sfx",
        "source": fingerprint,
        "channels": [0, 1],
        "gainDb": 0,
        "mute": False,
        "regions": [],
        "provenance": {"originalOnly": True},
    }
    request = proof_request(tmp_path)
    request["videoGraph"] = {"operations": []}
    request["sourceFingerprints"] = {
        "camera": file_fingerprint(camera)["sha256"],
        "riser-one": fingerprint["sha256"],
        "riser-two": fingerprint["sha256"],
    }
    request["audioGraph"]["operations"] = [
        {
            "operationId": source_id + "-trim",
            "kind": "trim",
            "range": {"startSample": 0, "endSampleExclusive": 4800},
            "parameters": {
                "sourceId": source_id,
                "source": {
                    "locator": str(audio),
                    "sha256": fingerprint["sha256"],
                    "mediaClass": "source",
                    "ancestry": [],
                    "streamIndex": 0,
                },
            },
        }
        for source_id in ("riser-one", "riser-two")
    ]
    value = SimpleNamespace(
        ws=ws,
        request=request,
        audio=audio,
        camera=camera,
        layers=[layer],
        video_layers=[],
    )
    _publish_tracks(value)
    return value


def _plan(case):
    return ProofPlanCompiler(case.ws).compile(
        case.request, regression_contract=regression_contract()
    )


def _resolve(case):
    return canonical_proof_media_inputs(case.ws, _plan(case))


def test_repeated_cue_ids_share_exact_owned_tracks_source_and_native_preflight(case):
    plan = _plan(case)
    inputs = canonical_proof_media_inputs(case.ws, plan)
    expected = {"path": case.audio.resolve(), "mediaClass": "source", "ancestry": []}
    assert inputs["riser-one"] == inputs["riser-two"] == expected
    assert inputs["camera"]["path"] == case.camera
    report = ProofPlanCompiler(case.ws).preflight(
        plan, media_inputs=inputs, tool_readiness={"proof-plan-executor": True}
    )
    assert report["status"] == "pass"


def test_tracks_and_trim_relative_locators_resolve_against_raw_dir(case):
    case.layers[0]["source"]["locator"] = "assets/riser.wav"
    _publish_tracks(case)
    for op in case.request["audioGraph"]["operations"]:
        op["parameters"]["source"]["locator"] = "assets/../assets/riser.wav"
    assert _resolve(case)["riser-one"]["path"] == case.audio.resolve()


@pytest.mark.parametrize(
    "change", ["hash", "path", "unowned", "path-only", "hash-only", "video-only"]
)
def test_source_requires_both_identity_fields_and_current_audio_track_ownership(
    case, change
):
    if change == "hash":
        case.layers[0]["source"]["sha256"] = "0" * 64
    elif change == "path":
        other = case.audio.with_name("copied.wav")
        other.write_bytes(case.audio.read_bytes())
        case.layers[0]["source"]["locator"] = str(other)
    elif change == "unowned":
        other = case.audio.with_name("unowned.wav")
        other.write_bytes(case.audio.read_bytes())
        for operation in case.request["audioGraph"]["operations"]:
            operation["parameters"]["source"]["locator"] = str(other)
    elif change == "video-only":
        case.video_layers = [
            {
                "layerId": "visual-layer",
                "order": 1,
                "role": "overlay",
                "source": deepcopy(case.layers[0]["source"]),
                "regions": [],
                "zOrder": 1,
            }
        ]
        case.layers = []
    else:
        key = "sha256" if change == "path-only" else "locator"
        for op in case.request["audioGraph"]["operations"]:
            del op["parameters"]["source"][key]
    _publish_tracks(case)
    inputs = _resolve(case)
    assert "riser-one" not in inputs and "riser-two" not in inputs


@pytest.mark.parametrize(
    "field,value", [("mediaClass", "proof"), ("ancestry", [{"mediaClass": "preview"}])]
)
@pytest.mark.parametrize("owner", ["descriptor", "tracks"])
def test_origin_metadata_cannot_be_changed_to_claim_an_original(
    case, field, value, owner
):
    if owner == "descriptor":
        for op in case.request["audioGraph"]["operations"]:
            op["parameters"]["source"][field] = value
    else:
        case.layers[0]["provenance"][field] = value
        _publish_tracks(case)
    assert "riser-one" not in _resolve(case)


def test_identical_duplicate_layers_do_not_make_source_ownership_ambiguous(case):
    duplicate = deepcopy(case.layers[0])
    duplicate.update(layerId="another-riser", order=2)
    case.layers.append(duplicate)
    _publish_tracks(case)
    assert _resolve(case)["riser-one"]["path"] == case.audio.resolve()


@pytest.mark.parametrize(
    "field,value",
    [("mediaClass", "proof"), ("ancestry", [{"mediaClass": "preview"}])],
)
def test_duplicate_path_and_hash_with_different_origin_is_rejected(case, field, value):
    duplicate = deepcopy(case.layers[0])
    duplicate.update(layerId="another-riser", order=2)
    duplicate["provenance"][field] = value
    case.layers.append(duplicate)
    _publish_tracks(case)
    with pytest.raises(ValueError, match="ambiguous|origin"):
        _resolve(case)


@pytest.mark.parametrize("change", ["file", "class", "ancestry"])
def test_same_audio_source_id_cannot_describe_different_origins(case, change):
    duplicate = deepcopy(case.request["audioGraph"]["operations"][0])
    duplicate["operationId"] = "conflicting-trim"
    other = case.audio.with_name("renamed.wav")
    other.write_bytes(case.audio.read_bytes())
    if change == "file":
        duplicate["parameters"]["source"]["locator"] = str(other)
    elif change == "class":
        duplicate["parameters"]["source"]["mediaClass"] = "proof"
    else:
        duplicate["parameters"]["source"]["ancestry"] = [{"mediaClass": "preview"}]
    case.request["audioGraph"]["operations"].append(duplicate)
    with pytest.raises(ValueError, match="conflicting|source ID"):
        _resolve(case)


def test_audio_descriptor_must_match_its_locked_source_hash(case):
    case.request["audioGraph"]["operations"][0]["parameters"]["source"]["sha256"] = (
        "0" * 64
    )
    with pytest.raises(ValueError, match="lock|source ID"):
        _resolve(case)


def test_cmap_source_id_cannot_be_rebound_by_an_audio_trim(case):
    camera_hash = file_fingerprint(case.camera)["sha256"]
    other = case.audio.with_name("camera-copy.bin")
    other.write_bytes(case.camera.read_bytes())
    case.layers[0]["source"] = file_fingerprint(other)
    _publish_tracks(case)
    op = case.request["audioGraph"]["operations"][0]
    op["parameters"]["sourceId"] = "camera"
    op["parameters"]["source"].update(locator=str(other), sha256=camera_hash)
    with pytest.raises(ValueError, match="conflicting|source ID|canonical"):
        _resolve(case)


def test_same_source_id_can_select_different_streams_of_the_same_original(case):
    first = case.request["audioGraph"]["operations"][0]
    duplicate = deepcopy(first)
    duplicate["operationId"] = "another-stream-trim"
    duplicate["parameters"]["source"]["streamIndex"] = 2
    case.request["audioGraph"]["operations"].append(duplicate)
    assert _resolve(case)["riser-one"]["path"] == case.audio.resolve()


def test_resolution_does_not_admit_changed_source_bytes(case):
    plan = _plan(case)
    case.audio.write_bytes(b"changed source bytes")
    inputs = canonical_proof_media_inputs(case.ws, plan)
    report = ProofPlanCompiler(case.ws).preflight(
        plan, media_inputs=inputs, tool_readiness={"proof-plan-executor": True}
    )
    assert report["status"] != "pass"
    assert any("source" in str(item).lower() for item in report["blockers"])


def test_audio_source_id_requires_its_own_lock_even_when_another_id_reuses_asset(case):
    plan = _plan(case)
    del plan["canonicalInputLock"]["source:riser-one"]
    inputs = canonical_proof_media_inputs(case.ws, plan)
    assert "riser-one" not in inputs
    assert inputs["riser-two"]["path"] == case.audio.resolve()


@pytest.mark.parametrize("operation_kind", ["gain", "video-trim"])
def test_only_audio_trim_descriptors_can_bind_missing_tracks_ids(case, operation_kind):
    operation = case.request["audioGraph"]["operations"].pop(0)
    if operation_kind == "gain":
        operation["kind"] = "gain"
        case.request["audioGraph"]["operations"].append(operation)
    else:
        operation = {
            "operationId": "video-trim",
            "kind": "trim",
            "inputs": ["riser-one"],
            "outputRange": {"startFrame": 0, "endFrameExclusive": 1},
            "parameters": operation["parameters"],
        }
        case.request["videoGraph"]["operations"].append(operation)
    assert "riser-one" not in _resolve(case)


def test_explicit_nonoriginal_track_provenance_is_not_guessed(case):
    case.layers[0]["provenance"]["originalOnly"] = False
    _publish_tracks(case)
    assert "riser-one" not in _resolve(case)


@pytest.mark.parametrize("field", ["sourceId", "assetId"])
def test_explicit_legacy_tracks_ids_keep_their_existing_resolution(case, field):
    case.layers[0]["source"][field] = "legacy-audio"
    _publish_tracks(case, strict=False)
    case.request["sourceFingerprints"]["legacy-audio"] = file_fingerprint(case.audio)[
        "sha256"
    ]
    assert _resolve(case)["legacy-audio"] == {
        "path": case.audio,
        "mediaClass": "source",
        "ancestry": [],
    }
