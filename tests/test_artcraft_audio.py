"""SoundCraft cue scope, source ownership and retained PCM evidence."""

import pytest

from avo import artcraft, init_project
from avo.timeline.contracts import file_fingerprint
from tests.artcraft_fixtures import request
from tests.test_artcraft_jobs import _prepare, job_spec


@pytest.fixture
def isolated_cue(tmp_path, monkeypatch):
    monkeypatch.setattr(init_project, "load_provider", lambda slug: {"slug": slug})
    source = tmp_path / "dry.wav"
    source.write_bytes(b"selected source fixture")
    brief = request(
        componentId="isolated-room-cue",
        required={
            "behavior": "editable-isolated-cue",
            "outputRole": "generated-audio",
            "editable": True,
        },
    )
    spec = job_spec(
        tmp_path,
        jobId="isolated-room-cue",
        readRoots=[str(tmp_path)],
        soundCue={"source": str(source), "effect": "room-reverb"},
        output={
            "role": "generated-audio",
            "format": "wav",
            "sampleRate": 48000,
            "sampleCount": 48000,
            "channels": 2,
        },
    )
    intent = artcraft.ArtCraftIntent("explicit", "soundcraft", ("isolated-cue",))
    return source, brief, spec, intent


@pytest.mark.parametrize(
    "output",
    [{"channels": 1}, {"sampleRate": 44100}, {"sampleCount": 480001}],
)
def test_soundcraft_refuses_unqualified_clock_before_app_access(isolated_cue, output):
    _, brief, spec, intent = isolated_cue
    spec["output"].update(output)
    with pytest.raises(artcraft.ArtCraftError, match="48 kHz stereo WAV"):
        _prepare(artcraft, brief, spec, None, intent=intent)


def test_soundcraft_refuses_a_cue_outside_selected_read_roots(isolated_cue):
    _, brief, spec, intent = isolated_cue
    spec["readRoots"] = []
    with pytest.raises(artcraft.ArtCraftError, match="outside"):
        _prepare(artcraft, brief, spec, None, intent=intent)


def test_soundcraft_generated_audio_refuses_relabelled_input_and_wrong_pcm(
    tmp_path, isolated_cue
):
    source, _, spec, _ = isolated_cue
    root = tmp_path / "isolated"
    dependency = root / "Audio Files" / "source.wav"
    dependency.parent.mkdir(parents=True)
    for path in (root / "component.scraft", root / "recipe.json", dependency):
        path.write_bytes(b"owned synthetic fixture")
    generated = root / "cue.wav"
    generated.write_bytes(source.read_bytes())
    output = spec["output"]
    job = {
        "output": output,
        "roots": {"write": [str(root)]},
        "inputs": [file_fingerprint(source)],
    }
    result = {
        "nativeSource": file_fingerprint(root / "component.scraft"),
        "recipe": file_fingerprint(root / "recipe.json"),
        "media": file_fingerprint(generated),
        "dependencies": [file_fingerprint(dependency)],
        "audioEvidence": {
            "codec": "pcm_s24le",
            "pcmSha256": "f" * 64,
            **{key: output[key] for key in ("sampleRate", "sampleCount", "channels")},
        },
    }
    with pytest.raises(artcraft.ArtCraftError, match="relabel"):
        artcraft._verify_sound_authoring_result(job, root, result)
    result["audioEvidence"]["sampleCount"] -= 1
    with pytest.raises(artcraft.ArtCraftError, match="output clock"):
        artcraft._verify_sound_authoring_result(job, root, result)
