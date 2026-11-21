"""Metadata-only canonical sound/proof bindings; encoded qualification is separate."""

from copy import deepcopy

import pytest

from avo.timeline.animation import AnimationService
from avo.timeline.contracts import document_hash_excluding, file_fingerprint
from avo.timeline.proof_plan import ProofPlanCompiler, ProofPlanError
from tests.test_proof_plan import proof_request, registry, regression_contract
from tests.test_sound_application import application
from tests.test_timeline_animation_service import strategy


def published_program(directory):
    workspace, _, service, _, request, _ = application(directory)
    applied = service.apply(request)
    sync = workspace.store("sync-map")
    if sync.load_index()["headRevisionId"] is None:
        sync.append_revision(
            snapshot={"fixture": "metadata-only clock"},
            actor="fixture",
            reason="Source clock fixture",
        )
    AnimationService(workspace).author(
        strategy(), actor="fixture", reason="Current independent motion metadata"
    )
    original = workspace.raw_dir / "raw.bin"
    source = {
        "locator": str(original),
        "sha256": file_fingerprint(original)["sha256"],
        "mediaClass": "source",
        "streamIndex": 0,
    }
    region = {"startSample": 0, "endSampleExclusive": 48000}
    value = proof_request(directory)
    value["sourceFingerprints"] = {"camera": source["sha256"]}
    value["output"]["frameRate"] = {"num": 24, "den": 1}
    value["videoGraph"]["operations"][0].update(
        inputs=["camera"], outputRange={"startFrame": 0, "endFrameExclusive": 24}
    )
    value["audioGraph"] = {
        "sampleRate": 48000,
        "singleFinalEncode": True,
        "nodes": [
            {
                "nodeId": "lead",
                "kind": "source",
                "sourceSampleRate": 48000,
                "targetSampleRate": 48000,
                "sourceLayout": "stereo",
                "targetLayout": "stereo",
                "channelMap": [0, 1],
                "latencyCompensationSamples": 0,
                "sourceRange": region,
                "outputRange": region,
            }
        ],
        "operations": [
            {
                "operationId": "lead-trim",
                "kind": "trim",
                "range": region,
                "parameters": {
                    "nodeId": "lead",
                    "sourceId": "camera",
                    "source": source,
                },
            },
            {
                "operationId": "lead-gain",
                "kind": "gain",
                "range": region,
                "parameters": {"nodeId": "lead", "gainDb": -1.5},
            },
            {
                "operationId": "program-encode",
                "kind": "encode",
                "range": region,
                "parameters": {},
            },
        ],
    }
    return workspace, ProofPlanCompiler(workspace, registry()), value, applied


@pytest.fixture(scope="module")
def selected_program(tmp_path_factory):
    return published_program(tmp_path_factory.mktemp("canonical-sound-proof"))


def test_normal_proof_derives_selected_sound_and_preserves_original_processing(
    selected_program,
):
    workspace, compiler, request, applied = selected_program
    original = deepcopy(request)
    plan = compiler.compile(request, regression_contract=regression_contract())
    nodes = [node for node in plan["audioGraph"]["nodes"] if node["kind"] == "sfx"]
    assert len(nodes) == 1
    assert plan["audioGraph"]["nodes"][0] == original["audioGraph"]["nodes"][0]
    assert plan["audioGraph"]["operations"][:3] == original["audioGraph"]["operations"]
    assert request == original
    chosen = applied["receipt"]["choices"][0]
    assert [event["eventId"] for event in plan["events"]] == [chosen["eventId"]]
    assert any(
        key.startswith("source:sound-source-") for key in plan["canonicalInputLock"]
    )
    assert compiler.compile(request, regression_contract=regression_contract()) == plan
    from avo.timeline.materialize import canonical_proof_media_inputs

    inputs = canonical_proof_media_inputs(workspace, plan)
    assert any(key.startswith("sound-source-") for key in inputs)
    assert (
        compiler.preflight(
            plan,
            media_inputs=inputs,
            tool_readiness={"ffmpeg": True, "proof-plan-executor": True},
        )["status"]
        == "pass"
    )


def test_cut_proof_remains_the_cmap_source_only_pass(selected_program):
    _, compiler, request, _ = selected_program
    request = {**request, "checkpoint": "cut-proof"}
    plan = compiler.compile(request, regression_contract=regression_contract())
    assert plan["audioGraph"] == request["audioGraph"]
    assert plan["events"] == []
    assert not any(
        key.startswith("source:sound-source-") for key in plan["canonicalInputLock"]
    )


@pytest.mark.parametrize(
    "change", ["omit", "gain", "event", "source-lock", "duplicate-source"]
)
def test_resealed_proof_cannot_change_its_canonical_sound_contribution(
    selected_program, change
):
    workspace, compiler, request, applied = selected_program
    plan = compiler.compile(request, regression_contract=regression_contract())
    assert any(node["kind"] == "sfx" for node in plan["audioGraph"]["nodes"])
    if change == "omit":
        plan["audioGraph"] = deepcopy(request["audioGraph"])
        plan["events"] = []
        plan["canonicalInputLock"] = {
            key: value
            for key, value in plan["canonicalInputLock"].items()
            if not key.startswith("source:sound-source-")
        }
    elif change == "gain":
        operation = next(
            op
            for op in plan["audioGraph"]["operations"]
            if op["kind"] == "gain" and op["parameters"]["nodeId"] != "lead"
        )
        operation["parameters"]["gainDb"] = -18
    elif change == "event":
        plan["events"][0]["resolvedImpactSample"] += 1
    elif change == "source-lock":
        key = next(
            key
            for key in plan["canonicalInputLock"]
            if key.startswith("source:sound-source-")
        )
        plan["canonicalInputLock"][key] = "f" * 64
    else:
        from avo.timeline.sound_compilation import append_selected_sound

        node = deepcopy(
            next(node for node in plan["audioGraph"]["nodes"] if node["kind"] == "sfx")
        )
        original_id = node["nodeId"]
        node["nodeId"] = "duplicate-effect"
        original_event = deepcopy(plan["events"][0])
        original_event.update(
            eventId="duplicate-event", audio={"nodeId": node["nodeId"]}
        )
        graph = deepcopy(request["audioGraph"])
        graph["nodes"].append(node)
        for operation in plan["audioGraph"]["operations"]:
            if operation["parameters"].get("nodeId") == original_id:
                duplicate = deepcopy(operation)
                duplicate["operationId"] += "-duplicate"
                duplicate["parameters"]["nodeId"] = node["nodeId"]
                graph["operations"].append(duplicate)
        plan = append_selected_sound(
            {**plan, "audioGraph": graph, "events": [original_event]},
            applied["receipt"]["choices"],
            source_refs=applied["receipt"]["sourceRefs"],
        )
    plan["proofPlanHash"] = document_hash_excluding(plan, "proofPlanHash")
    inputs = {"camera": workspace.raw_dir / "raw.bin"}
    for operation in plan["audioGraph"]["operations"]:
        if operation["kind"] == "trim":
            inputs[operation["parameters"]["sourceId"]] = operation["parameters"][
                "source"
            ]
    report = compiler.preflight(
        plan,
        media_inputs=inputs,
        tool_readiness={"ffmpeg": True, "proof-plan-executor": True},
    )
    assert "PROOF_SOUND_INVALID" in {blocker["code"] for blocker in report["blockers"]}


def test_generic_tracks_cannot_claim_an_unpublished_sound_recipe(tmp_path):
    from avo.timeline.bmap_service import BMapService
    from avo.timeline.tracks import TracksService

    workspace, compiler, request, _ = published_program(tmp_path)
    tracks = workspace.store("tracks").load()["revisions"][-1]["snapshot"]
    selected = tracks["audioTracks"]["layers"][0]["provenance"]["soundSelection"]
    selected["applicationRef"] = {
        "path": f"edit/motion/sound/requests/{'f' * 64}.json",
        "sha256": "f" * 64,
    }
    bmap = workspace.store("bmap").load()["revisions"][-1]["snapshot"]
    cue = next(cue for cue in bmap["cues"] if cue["cueId"] == selected["cueId"])
    cue["contentRef"]["applicationRef"] = selected["applicationRef"]
    BMapService(workspace).author(bmap, actor="fixture", reason="Unpublished claim")
    TracksService(workspace).author(tracks, actor="fixture", reason="Unpublished claim")
    AnimationService(workspace).author(
        strategy(), actor="fixture", reason="Current motion metadata"
    )
    with pytest.raises(ProofPlanError) as failure:
        compiler.compile(request, regression_contract=regression_contract())
    assert failure.value.code == "PROOF_SOUND_INVALID"
    assert not list(compiler.directory.glob("*.json"))


def test_explicitly_muted_selection_does_not_need_its_library_source_to_preview(
    tmp_path,
):
    from avo.timeline.tracks import TracksService

    workspace, compiler, request, _ = published_program(tmp_path)
    tracks = workspace.store("tracks").load()["revisions"][-1]["snapshot"]
    layer = tracks["audioTracks"]["layers"][0]
    layer["mute"] = True
    TracksService(workspace).author(tracks, actor="fixture", reason="Explicit mute")
    AnimationService(workspace).author(
        strategy(), actor="fixture", reason="Current motion metadata"
    )
    from pathlib import Path

    Path(layer["source"]["locator"]).write_bytes(
        b"source unavailable for muted preview"
    )
    plan = compiler.compile(request, regression_contract=regression_contract())
    assert plan["audioGraph"] == request["audioGraph"]
    assert plan["events"] == []
