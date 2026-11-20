"""Opt-in evidence from the installed SoundCraft release and media tools."""

import array
import math
import os
import subprocess
import wave
from pathlib import Path

import pytest
from tests.artcraft_fixtures import request
from tests.test_artcraft_jobs import _prepare, job_spec

from avo import artcraft, init_project
from avo.adapters.artcraft import SelectedArtCraftAdapter
from avo.timeline.contracts import file_fingerprint

pytestmark = pytest.mark.integration


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


def test_installed_soundcraft_saved_cue_reopens_with_exact_stereo_pcm(
    tmp_path, monkeypatch
):
    entry = os.environ.get("AVO_ARTCRAFT_SOUNDCRAFT_TEST_CLI")
    if not entry:
        pytest.skip("set AVO_ARTCRAFT_SOUNDCRAFT_TEST_CLI to the installed 0.20.1 CLI")
    cli = Path(entry).resolve(strict=True)
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
        cliPath=str(cli),
        readRoots=[str(tmp_path)],
        soundCue={"source": str(source), "effect": "room-reverb"},
        output={"role": "generated-audio", "format": "wav", **requested},
        budget={"seconds": 45, "files": 16, "bytes": 8_000_000},
    )
    brief = request(
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
