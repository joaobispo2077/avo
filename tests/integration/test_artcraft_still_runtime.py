"""Opt-in native source, color and still evidence from installed VectorCraft."""

import os
import subprocess
from copy import deepcopy
from pathlib import Path

import numpy as np
import pytest
from tests.artcraft_fixtures import request
from tests.integration.test_camera_proof_runtime import pixels
from tests.integration.test_canonical_sound_proof_runtime import recorded_program
from tests.integration.test_ffmpeg_proof_executor import _pcm
from tests.test_artcraft_jobs import _prepare, job_spec
from tests.test_proof_plan import regression_contract
from tests.test_timeline_animation_service import strategy

from avo import artcraft, init_project
from avo.adapters.artcraft import SelectedArtCraftAdapter
from avo.adapters.artcraft_vectorcraft import observe_vector_card_png
from avo.adapters.media.proof_executor import execute_ffmpeg_proof
from avo.adapters.media.timeline_render import TimelineRenderAdapter
from avo.capabilities import default_proof_capability_registry
from avo.timeline.animation import AnimationService
from avo.timeline.initial_cut import initial_cut_proof_request
from avo.timeline.materialize import canonical_proof_media_inputs
from avo.timeline.proof_plan import ProofPlanCompiler
from avo.timeline.tracks import TracksService

pytestmark = [pytest.mark.integration, pytest.mark.native_artcraft]


def _installed_cli():
    entry = os.environ.get("AVO_ARTCRAFT_VECTORCRAFT_TEST_CLI")
    if not entry:
        pytest.skip("set AVO_ARTCRAFT_VECTORCRAFT_TEST_CLI to the installed 0.24.1 CLI")
    return Path(entry).resolve(strict=True)


def _prepare_card(path, monkeypatch, cli, *, provider):
    monkeypatch.setattr(init_project, "load_provider", lambda slug: {"slug": slug})

    def invoke(binary, roots, directory, arguments, *, env, timeout):
        assert binary["locator"] == str(cli)
        assert roots["write"] == [str(directory)]
        assert arguments[:2] == ("--safe-mode", "run")
        assert env["VECTORCRAFT_NO_PREFS"] == "1"
        return subprocess.run(
            [str(cli), *map(str, arguments)],
            cwd=directory,
            env=env,
            capture_output=True,
            check=True,
            timeout=timeout,
        ).stdout

    spec = job_spec(
        path,
        jobId="vector-card",
        provider=provider,
        cliPath=str(cli),
        authoringParameters={"primaryText": "$45 · Café", "font": "Arial"},
        output={
            "role": "generated-still",
            "format": "png",
            "width": 320,
            "height": 180,
            "alpha": "straight",
            "color": "srgb",
        },
    )
    intent = artcraft.ArtCraftIntent("explicit", "vectorcraft", ("vector-still",))
    brief = request(
        provider=provider,
        requestId="vector-card-request",
        componentId="vector-card",
        purpose="Introduce the selected example with an editable card.",
        required={
            "behavior": "editable-vector-card",
            "outputRole": "generated-still",
            "editable": True,
        },
    )
    adapter = SelectedArtCraftAdapter(
        observe_confinement=lambda _installed, roots: roots,
        run_confined=invoke,
    )
    prepared = _prepare(artcraft, brief, spec, adapter, intent=intent)
    exported = artcraft.run_authoring(
        prepared["jobRef"], expected_head=prepared["head"], adapter=adapter
    )
    assert exported["state"] == "exported"
    return spec, prepared, exported


def test_selected_vectorcraft_saves_and_reopens_an_editable_srgb_still(
    tmp_path, monkeypatch
):
    spec, prepared, exported = _prepare_card(
        tmp_path, monkeypatch, _installed_cli(), provider="neutral-channel"
    )
    _, event = artcraft.read_authoring_export(
        prepared["jobRef"], expected_head=exported["head"]
    )
    observed = observe_vector_card_png(
        Path(event["outputs"][0]["locator"]), spec["output"]
    )
    assert observed == event["stillEvidence"]
    assert observed["color"] == "srgb"
    assert observed["alpha"] == "straight"
    assert (observed["width"], observed["height"]) == (320, 180)
    native = Path(event["saved"]["locator"])
    assert native.suffix == ".vectorcraft"
    review = artcraft.describe_export_review(
        prepared["jobRef"], expected_head=exported["head"]
    )
    assert review["standalone"]["generatedStillRef"]["exportHead"] == exported["head"]
    assert review["standalone"]["still"] == event["outputs"][0]
    assert review["reviewState"] == "pending-creator"


def _tracks_with_card(workspace, review, placement):
    store = workspace.store("tracks")
    snapshot = deepcopy(
        store.revision(store.load_index()["headRevisionId"])["snapshot"]
    )
    card = review["standalone"]
    snapshot["videoTracks"]["layers"].append(
        {
            "layerId": "vector-card-overlay",
            "order": 2,
            "role": "overlay",
            "source": card["still"],
            "generatedStillRef": card["generatedStillRef"],
            "placement": placement,
            "zOrder": 2,
            "regions": [
                {
                    "regionId": "vector-card-region",
                    "cueIds": ["cue-one"],
                    "startTicks": 0,
                    "endTicks": 24,
                    "timebase": {"num": 1, "den": 24},
                }
            ],
        }
    )
    return snapshot


def _with_card_operation(request, review, placement):
    value = deepcopy(request)
    card = review["standalone"]
    value["videoGraph"]["operations"].append(
        {
            "operationId": "vector-card-overlay",
            "kind": "overlay-image",
            "inputs": ["program-picture", "generated-still:vector-card-overlay"],
            "outputRange": {"startFrame": 0, "endFrameExclusive": 24},
            "parameters": {
                "layerId": "vector-card-overlay",
                "generatedStillRef": card["generatedStillRef"],
                "sourceFingerprint": card["still"],
                "placement": placement,
                "zOrder": 2,
                "layerRole": "overlay",
            },
        }
    )
    return value


def test_vectorcraft_still_stays_static_in_an_original_footage_proof(
    tmp_path, monkeypatch
):
    cli = _installed_cli()
    workspace = recorded_program(tmp_path)
    native_workspace = tmp_path / "native"
    native_workspace.mkdir()
    _, prepared, exported = _prepare_card(
        native_workspace, monkeypatch, cli, provider=workspace.project["provider"]
    )
    review = artcraft.describe_export_review(
        prepared["jobRef"], expected_head=exported["head"]
    )
    base = initial_cut_proof_request(
        workspace,
        iteration_id="iteration-0001",
        output=workspace.raw_dir / "edit" / "normal.mkv",
        frame_rate={"num": 24, "den": 1},
        width=640,
        height=360,
    )
    base["checkpoint"] = "motion-proof"
    base["output"].update(conformance=True, videoCodec="ffv1", audioCodec="pcm_s32le")
    compiler = ProofPlanCompiler(workspace, default_proof_capability_registry())
    renderer = TimelineRenderAdapter(proof_executor=execute_ffmpeg_proof)

    def render(value, name, window=None):
        plan = compiler.compile(value, regression_contract=regression_contract())
        result = compiler.preflight(
            plan,
            media_inputs=canonical_proof_media_inputs(workspace, plan),
            tool_readiness={"ffmpeg": True, "proof-plan-executor": True},
        )
        assert result["status"] == "pass", result["blockers"]
        path = tmp_path / name
        renderer.render_proof_plan(plan, path, window=window)
        return path

    original = render(base, "original.mkv")
    placement = {"x": 160, "y": 90, "width": 320, "height": 180}
    TracksService(workspace).author(
        _tracks_with_card(workspace, review, placement),
        actor="fixture",
        reason="Select the exact synthetic vector card",
    )
    AnimationService(workspace).author(
        strategy(), actor="fixture", reason="Current tracks"
    )
    configured = _with_card_operation(base, review, placement)
    mixed = render(configured, "with-card.mkv")
    clean, result = pixels(original, 640, 360), pixels(mixed, 640, 360)
    assert clean.shape == result.shape == (24, 360, 640, 3)
    np.testing.assert_array_equal(result[:, :130], clean[:, :130])
    assert np.any(result[:, 160:200, 180:440] != clean[:, 160:200, 180:440])
    expected_fill = np.array([0x10, 0x2C, 0x48], dtype=np.uint16) * 257
    np.testing.assert_allclose(
        result[:, 155, 195], np.tile(expected_fill, (24, 1)), atol=257
    )
    np.testing.assert_array_equal(_pcm(original), _pcm(mixed))
    window = render(
        configured, "card-window.mkv", {"startFrame": 7, "endFrameExclusive": 15}
    )
    np.testing.assert_array_equal(pixels(window, 640, 360), result[7:15])
