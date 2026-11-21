"""Opt-in evidence from the installed SoundCraft release and media tools."""

import array
import math
import os
import subprocess
import wave
from copy import deepcopy
from pathlib import Path

import numpy as np
import pytest
from tests.artcraft_fixtures import request
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


def _tracks_with_generated_cue(workspace, review):
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
                    "cueIds": ["cue-one"],
                    "startTicks": 0,
                    "endTicks": 24,
                    "timebase": {"num": 1, "den": 24},
                }
            ],
        }
    )
    return tracks


def _with_cue_graph(original, review):
    value = deepcopy(original)
    graph = value["audioGraph"]
    node, trim = proof_cue_operation(review)
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
            "programFrame": 0,
            "visibleRange": None,
            "sourceRange": node["sourceRange"],
            "audio": {"nodeId": node["nodeId"]},
            "transientOffset": None,
            "resolvedImpactSample": 0,
            "entryEffectIds": [],
            "validation": {"required": True},
        }
    )
    return value


def test_native_soundcraft_cue_mixes_once_under_original_dialogue(
    tmp_path, monkeypatch
):
    cli = _installed_cli()
    workspace = recorded_program(tmp_path)
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
        width=128,
        height=72,
    )
    base["checkpoint"] = "motion-proof"
    base["output"].update(conformance=True, videoCodec="ffv1", audioCodec="pcm_s32le")
    compiler = ProofPlanCompiler(workspace, default_proof_capability_registry())
    renderer = TimelineRenderAdapter(proof_executor=execute_ffmpeg_proof)

    def render(value, filename, window=None):
        plan = compiler.compile(value, regression_contract=regression_contract())
        result = compiler.preflight(
            plan,
            media_inputs=canonical_proof_media_inputs(workspace, plan),
            tool_readiness={"ffmpeg": True, "proof-plan-executor": True},
        )
        assert result["status"] == "pass", result["blockers"]
        path = tmp_path / filename
        renderer.render_proof_plan(plan, path, window=window)
        return path

    clean = render(base, "dialogue.mkv")
    TracksService(workspace).author(
        _tracks_with_generated_cue(workspace, review),
        actor="fixture",
        reason="Select the exact synthetic effect at picture start",
    )
    AnimationService(workspace).author(
        strategy(), actor="fixture", reason="Current tracks"
    )
    request = _with_cue_graph(base, review)
    mixed = render(request, "with-cue.mkv")
    cue = _pcm(Path(review["standalone"]["audio"]["locator"]))
    original, result = _pcm(clean), _pcm(mixed)
    assert original.shape == result.shape == cue.shape == (48000, 2)
    assert np.max(np.abs(original)) > 0.05
    np.testing.assert_allclose(result - original, cue, atol=3e-7)
    np.testing.assert_array_equal(pixels(clean, 128, 72), pixels(mixed, 128, 72))
    window = render(
        request, "with-cue-window.mkv", {"startFrame": 4, "endFrameExclusive": 16}
    )
    np.testing.assert_allclose(_pcm(window), result[8000:32000], atol=3e-7)
