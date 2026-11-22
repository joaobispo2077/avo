"""Opt-in evidence from the installed SoundCraft release and media tools."""

import array
import json
import math
import os
import subprocess
import wave
from copy import deepcopy
from pathlib import Path

import numpy as np
import pytest
from tests.artcraft_fixtures import picture_output, request
from tests.integration.test_camera_proof_runtime import pixels
from tests.integration.test_canonical_sound_proof_runtime import recorded_program
from tests.integration.test_ffmpeg_proof_executor import _pcm
from tests.test_artcraft_audio import proof_cue_operation
from tests.test_artcraft_jobs import _prepare, job_spec
from tests.test_proof_plan import regression_contract
from tests.test_timeline_animation_service import strategy

from avo import artcraft, init_project
from avo.adapters.artcraft import SelectedArtCraftAdapter
from avo.adapters.media.proof_executor import execute_ffmpeg_proof
from avo.adapters.media.timeline_render import TimelineRenderAdapter
from avo.capabilities import default_proof_capability_registry
from avo.timeline.animation import AnimationService
from avo.timeline.bmap_service import BMapService
from avo.timeline.contracts import file_fingerprint
from avo.timeline.initial_cut import initial_cut_proof_request
from avo.timeline.materialize import canonical_proof_media_inputs
from avo.timeline.proof_plan import ProofPlanCompiler
from avo.timeline.tracks import TracksService

pytestmark = [pytest.mark.integration, pytest.mark.native_artcraft]


def _source_tone(path):
    samples = array.array(
        "h",
        (
            int(5000 * math.sin(index / 48000 * 750 * math.tau)) if index < 2400 else 0
            for index in range(48000)
        ),
    )
    with wave.open(str(path), "wb") as audio:
        audio.setparams((1, 2, 48000, 48000, "NONE", "not compressed"))
        audio.writeframes(samples.tobytes())


def _installed_cli():
    entry = os.environ.get("AVO_ARTCRAFT_SOUNDCRAFT_TEST_CLI")
    if not entry:
        pytest.skip("set AVO_ARTCRAFT_SOUNDCRAFT_TEST_CLI to the installed 0.20.1 CLI")
    return Path(entry).resolve(strict=True)


def _prepare_native_cue(tmp_path, monkeypatch, cli, *, provider):
    monkeypatch.setattr(init_project, "load_provider", lambda slug: {"slug": slug})

    def invoke(binary, roots, directory, arguments, *, env, timeout):
        assert binary["locator"] == str(cli)
        assert roots["write"] == [str(directory)]
        return subprocess.run(
            [str(cli), *map(str, arguments)],
            cwd=directory,
            env=env,
            capture_output=True,
            check=True,
            timeout=timeout,
        ).stdout

    source = tmp_path / "dry.wav"
    _source_tone(source)
    original = file_fingerprint(source)
    requested = {"sampleRate": 48000, "sampleCount": 48000, "channels": 2}
    spec = job_spec(
        tmp_path,
        jobId="isolated-room-cue",
        provider=provider,
        cliPath=str(cli),
        readRoots=[str(tmp_path)],
        soundCue={"source": str(source), "effect": "room-reverb"},
        output={"role": "generated-audio", "format": "wav", **requested},
        budget={"seconds": 45, "files": 16, "bytes": 8_000_000},
    )
    brief = request(
        provider=provider,
        componentId="isolated-room-cue",
        required={
            "behavior": "editable-isolated-cue",
            "outputRole": "generated-audio",
            "editable": True,
        },
    )
    adapter = SelectedArtCraftAdapter(
        observe_confinement=lambda _installed, roots: roots,
        run_confined=invoke,
    )
    intent = artcraft.ArtCraftIntent("explicit", "soundcraft", ("isolated-cue",))
    prepared = _prepare(artcraft, brief, spec, adapter, intent=intent)
    exported = artcraft.run_authoring(
        prepared["jobRef"], expected_head=prepared["head"], adapter=adapter
    )
    assert exported["state"] == "exported"
    return source, original, requested, prepared, exported


def test_installed_soundcraft_saved_cue_reopens_with_exact_stereo_pcm(
    tmp_path, monkeypatch
):
    source, original, requested, prepared, exported = _prepare_native_cue(
        tmp_path, monkeypatch, _installed_cli(), provider="neutral-channel"
    )
    job, event = artcraft.read_authoring_export(
        prepared["jobRef"], expected_head=exported["head"]
    )
    target = (tmp_path / job["document"]).parent
    assert job["inputs"] == [original]
    assert file_fingerprint(source) == original
    assert event["saved"] == file_fingerprint(target / "component.scraft")
    assert event["dependencies"] == [
        file_fingerprint(target / "Audio Files" / "source.wav")
    ]
    assert event["outputs"] == [file_fingerprint(target / "cue.wav")]
    assert event["audioEvidence"]["codec"] == "pcm_s24le"
    assert {key: event["audioEvidence"][key] for key in requested} == requested
    rendered = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            event["outputs"][0]["locator"],
            "-f",
            "f32le",
            "pipe:1",
        ],
        capture_output=True,
        check=True,
        timeout=8,
    ).stdout
    signal = array.array("f", rendered)
    assert 0.05 < max(map(abs, signal)) < 0.2
    assert 0.001 < max(map(abs, signal[19_200:43_200])) < 0.02
    review = artcraft.describe_export_review(
        prepared["jobRef"], expected_head=exported["head"]
    )
    assert review["standalone"]["audio"] == event["outputs"][0]
    assert review["reviewState"] == "pending-creator"
    assert (
        artcraft.run_authoring(
            prepared["jobRef"], expected_head=exported["head"], adapter=None
        )
        == exported
    )
    retained = target / "Audio Files" / "source.wav"
    with retained.open("ab") as stream:
        stream.write(b"changed owned fixture")
    inspection = artcraft.inspect_authoring(
        prepared["jobRef"], expected_head=exported["head"]
    )
    assert inspection["status"] == "stale"
    assert inspection["checks"]["outputs"] == "changed"


def _tracks_with_generated_cue(workspace, review, *, start_frame=0):
    store = workspace.store("tracks")
    tracks = deepcopy(store.revision(store.load_index()["headRevisionId"])["snapshot"])
    evidence = review["standalone"]
    tracks["audioTracks"]["layers"].append(
        {
            "layerId": "soundcraft-room-cue",
            "order": 1,
            "role": "sfx",
            "source": evidence["audio"],
            "generatedAudioRef": evidence["generatedAudioRef"],
            "regions": [
                {
                    "regionId": "soundcraft-room-region",
                    "cueIds": [] if start_frame else ["cue-one"],
                    "startTicks": start_frame,
                    "endTicks": 24,
                    "timebase": {"num": 1, "den": 24},
                }
            ],
        }
    )
    return tracks


def _with_cue_graph(original, review, *, start_frame=0):
    value = deepcopy(original)
    graph = value["audioGraph"]
    start_sample = start_frame * (48000 // 24)
    node, trim = proof_cue_operation(
        review, start=start_sample, count=48000 - start_sample
    )
    graph["nodes"].append(node)
    graph["operations"].append(trim)
    encode = next(item for item in graph["operations"] if item["kind"] == "encode")
    graph["operations"].append(
        {
            "operationId": "program-mix",
            "kind": "mix",
            "range": encode["range"],
            "parameters": {"nodeIds": [item["nodeId"] for item in graph["nodes"]]},
        }
    )
    value["events"].append(
        {
            "eventId": "soundcraft-room-event",
            "role": "sfx",
            "programFrame": start_frame,
            "visibleRange": None,
            "sourceRange": node["sourceRange"],
            "audio": {"nodeId": node["nodeId"]},
            "transientOffset": None,
            "resolvedImpactSample": start_sample,
            "entryEffectIds": [],
            "validation": {"required": True},
        }
    )
    return value


def _select_lower_third_on_current_timeline(workspace, tracks, animation):
    from tests.test_artcraft_jobs import _overlay_snapshots

    selected = _overlay_snapshots(width=640, height=360, start_frame=0, frame_count=24)
    store = workspace.store("bmap")
    bmap = store.revision(store.load_index()["headRevisionId"])["snapshot"]
    original_cue = bmap["cues"][0]
    label_cue = {**original_cue, **selected["bmap"]["cues"][0]}
    BMapService(workspace).author(
        {"cues": [original_cue, label_cue]},
        actor="fixture",
        reason="Selected label appearance",
    )
    layer = selected["tracks"]["videoTracks"]["layers"][0]
    layer["regions"][0]["regionId"] = "speaker-label-region"
    tracks["videoTracks"]["layers"].append(layer)
    animation["components"][0]["componentId"] = "speaker-label"


def _add_selected_anicraft_hold(value, workspace, cli):
    from tests.integration.test_code_drawn_proof_executor import _add_generated

    from avo.proof_composition import register_artcraft_export
    from avo.timeline.generated_assets import GeneratedAssetService

    def invoke(binary, roots, directory, arguments, *, env, timeout):
        assert binary["locator"] == str(cli)
        assert directory.is_relative_to(Path(roots["write"][0]))
        return subprocess.run(
            [str(cli), *map(str, arguments)],
            cwd=directory,
            env=env,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            check=True,
            timeout=timeout,
        ).stdout

    adapter = SelectedArtCraftAdapter(
        observe_confinement=lambda _tool, roots: roots, run_confined=invoke
    )
    brief = request(
        provider=workspace.project["provider"],
        context={
            "kind": "video",
            "project": str(workspace.project_path),
            "videoId": workspace.video_id,
        },
    )
    spec = job_spec(
        workspace.raw_dir,
        provider=workspace.project["provider"],
        cliPath=str(cli),
        output=picture_output(
            width=640,
            height=360,
            frameCount=24,
            frameRate={"numerator": 24, "denominator": 1},
        ),
        authoringParameters={
            "primaryText": "Presenter",
            "font": "Arial",
            "motion": "hold",
        },
        budget={"seconds": 60, "files": 128, "bytes": 16_000_000},
    )
    prepared = _prepare(artcraft, brief, spec, adapter)
    exported = artcraft.run_authoring(
        prepared["jobRef"], expected_head=prepared["head"], adapter=adapter
    )
    derived = workspace.raw_dir / "edit" / "derived"
    derived.mkdir(exist_ok=True)
    record = register_artcraft_export(
        workspace,
        job_ref=prepared["jobRef"],
        expected_head=exported["head"],
        output=derived / "signed-label.mkv",
        asset_id="synchronized-label",
    )
    receipt = record["parameters"]["artcraft"]
    operation = _add_generated(
        {
            "videoGraph": value["videoGraph"],
            "implementationRefs": [],
            "canonicalInputLock": {},
        },
        {
            "record": record,
            "receipt": GeneratedAssetService(workspace).path(record["assetId"]),
            "lock_path": Path(receipt["bindingRef"]["locator"]),
            "lock": {"inputLockHash": receipt["bindingHash"]},
        },
        kind="overlay-video",
        start=0,
        end=24,
        local_start=0,
        z_order=2,
    )
    operation["parameters"]["placement"] = {"x": 0, "y": 0, "width": 640, "height": 360}


@pytest.mark.parametrize(
    "with_picture", [False, True], ids=["cue-only", "lower-third-with-cue"]
)
def test_native_soundcraft_cue_mixes_once_under_original_dialogue(
    tmp_path, monkeypatch, with_picture
):
    from avo.proof_composition import create_generated_asset_validator

    cli = _installed_cli()
    ani = os.environ.get("AVO_ARTCRAFT_ANICRAFT_TEST_CLI")
    if with_picture and not ani:
        pytest.skip("Select the installed AniCraft 0.2.1 CLI for the two-app fixture")
    width, height = (640, 360) if with_picture else (128, 72)
    start_frame = 3 if with_picture else 0
    workspace = recorded_program(tmp_path)
    if with_picture:
        workspace.project["videoId"] = workspace.video_id
        workspace.project_path.write_text(
            json.dumps(workspace.project), encoding="utf-8"
        )
    native_workspace = tmp_path / "native"
    native_workspace.mkdir()
    _, _, _, prepared, exported = _prepare_native_cue(
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
        width=width,
        height=height,
    )
    base["checkpoint"] = "motion-proof"
    base["output"].update(conformance=True, videoCodec="ffv1", audioCodec="pcm_s32le")
    compiler = ProofPlanCompiler(workspace, default_proof_capability_registry())
    renderer = TimelineRenderAdapter(
        proof_executor=execute_ffmpeg_proof,
        generated_asset_validator=create_generated_asset_validator(workspace),
    )

    def render(value, filename, window=None):
        plan = compiler.compile(value, regression_contract=regression_contract())
        result = compiler.preflight(
            plan,
            media_inputs=canonical_proof_media_inputs(workspace, plan),
            tool_readiness={
                "ffmpeg": True,
                "proof-plan-executor": True,
                **renderer.proof_tool_readiness(plan),
            },
        )
        assert result["status"] == "pass", result["blockers"]
        path = tmp_path / filename
        renderer.render_proof_plan(plan, path, window=window)
        return path

    clean = render(base, "dialogue.mkv")
    tracks = _tracks_with_generated_cue(workspace, review, start_frame=start_frame)
    animation = strategy()
    if with_picture:
        _select_lower_third_on_current_timeline(workspace, tracks, animation)
    TracksService(workspace).author(
        tracks,
        actor="fixture",
        reason="Select the exact synthetic effect at picture start",
    )
    AnimationService(workspace).author(
        animation, actor="fixture", reason="Current tracks"
    )
    request = _with_cue_graph(base, review, start_frame=start_frame)
    if with_picture:
        _add_selected_anicraft_hold(request, workspace, Path(ani).resolve(strict=True))
    mixed = render(request, "with-cue.mkv")
    cue = _pcm(Path(review["standalone"]["audio"]["locator"]))
    original, result = _pcm(clean), _pcm(mixed)
    assert original.shape == result.shape == cue.shape == (48000, 2)
    assert np.max(np.abs(original)) > 0.05
    onset = start_frame * (48000 // 24)
    np.testing.assert_array_equal(result[:onset], original[:onset])
    np.testing.assert_allclose(
        result[onset:] - original[onset:], cue[: 48000 - onset], atol=3e-7
    )
    baseline, combined = pixels(clean, width, height), pixels(mixed, width, height)
    if with_picture:
        np.testing.assert_array_equal(baseline[:3], combined[:3])
        assert not np.array_equal(baseline[3], combined[3])
        np.testing.assert_array_equal(baseline[-1], combined[-1])
    else:
        np.testing.assert_array_equal(baseline, combined)
    window = render(
        request, "with-cue-window.mkv", {"startFrame": 4, "endFrameExclusive": 16}
    )
    np.testing.assert_allclose(_pcm(window), result[8000:32000], atol=3e-7)
