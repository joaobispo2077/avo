"""SoundCraft cue scope, source ownership and retained PCM evidence."""

from copy import deepcopy
from types import SimpleNamespace

import pytest

from avo import artcraft, init_project
from avo.timeline import artcraft_audio
from avo.timeline.contracts import content_hash, file_fingerprint
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


def proof_cue_operation(review, *, start=0, count=48000):
    evidence = review["standalone"]
    clip = evidence["audio"]
    region = {"startSample": start, "endSampleExclusive": start + count}
    node = {
        "nodeId": "generated-room-cue",
        "kind": "sfx",
        "sourceSampleRate": 48000,
        "targetSampleRate": 48000,
        "sourceLayout": "stereo",
        "targetLayout": "stereo",
        "channelMap": [0, 1],
        "latencyCompensationSamples": 0,
        "sourceRange": {"startSample": 0, "endSampleExclusive": count},
        "outputRange": region,
    }
    trim = {
        "operationId": "generated-room-cue-trim",
        "kind": "trim",
        "range": region,
        "parameters": {
            "nodeId": node["nodeId"],
            "sourceId": evidence["sourceId"],
            "generatedAudioRef": evidence["generatedAudioRef"],
            "source": {
                "locator": clip["locator"],
                "sha256": clip["sha256"],
                "mediaClass": "generated-asset",
                "streamIndex": 0,
                "ancestry": [],
            },
        },
    }
    return node, trim


def test_generated_cue_proof_locks_exact_selected_placement_once(tmp_path, monkeypatch):
    source = {
        "locator": str(tmp_path / "cue.wav"),
        "sha256": "3" * 64,
        "sizeBytes": 100,
    }
    reference = {
        "job": {
            "locator": str(tmp_path / "job.json"),
            "sha256": "2" * 64,
            "sizeBytes": 12,
        },
        "exportHead": "1" * 64,
    }
    source_id = "artcraft-audio-" + content_hash(reference)[:24]
    node, trim = proof_cue_operation(
        {
            "standalone": {
                "audio": source,
                "sourceId": source_id,
                "generatedAudioRef": reference,
            }
        },
    )
    layer = {
        "generatedAudioRef": reference,
        "source": source,
        "role": "sfx",
        "regions": [{"startTicks": 0, "endTicks": 24}],
    }
    tracks = SimpleNamespace(
        load_index=lambda: {"headRevisionId": "tracks-one"},
        revision=lambda _: {"snapshot": {"audioTracks": {"layers": [layer]}}},
    )
    workspace = SimpleNamespace(
        store=lambda _: tracks,
        raw_dir=tmp_path,
        project_path=tmp_path / "avo.project.json",
        video_id="current-video",
        timeline_dir=tmp_path / "edit" / "timeline",
        project={"provider": "neutral-channel"},
    )
    event = {"outputs": [source], "audioEvidence": {"sampleCount": 48000}}
    job = {
        "request": {
            "provider": "neutral-channel",
            "context": {"kind": "provider-only"},
        },
        "workspace": str(tmp_path),
        "inputs": [source],
    }
    monkeypatch.setattr(
        artcraft_audio, "resolve_generated_audio", lambda _: (job, event)
    )
    plan = {
        "canonicalInputLock": {"tracks": "a" * 64},
        "audioGraph": {"nodes": [node], "operations": [trim]},
        "output": {"frameRate": {"num": 24, "den": 1}},
    }
    frozen = artcraft_audio.lock_generated_audio(workspace, plan, require_applied=False)
    assert frozen["canonicalInputLock"]["source:" + source_id] == source["sha256"]
    assert frozen["audioGraph"] == {"nodes": [node], "operations": [trim]}
    assert frozen["canonicalInputLock"]["generated-audio:" + source_id] == content_hash(
        reference
    )
    assert (
        artcraft_audio.lock_generated_audio(workspace, frozen, require_applied=True)
        == frozen
    )
    request_context = {
        "kind": "video",
        "videoId": workspace.video_id,
        "project": str(workspace.project_path),
    }
    job["request"]["context"] = request_context
    assert (
        artcraft_audio.lock_generated_audio(workspace, frozen, require_applied=True)
        == frozen
    )
    for change in (
        {"videoId": "other-video"},
        {"project": str(tmp_path / "other.project.json")},
    ):
        job["request"]["context"] = {**request_context, **change}
        with pytest.raises(ValueError, match="different video"):
            artcraft_audio.lock_generated_audio(
                workspace, frozen, require_applied=False
            )
    job["request"]["context"] = {"kind": "provider-only"}
    unlocked = deepcopy(frozen)
    unlocked["canonicalInputLock"].pop("generated-audio:" + source_id)
    with pytest.raises(ValueError, match="receipt lock changed"):
        artcraft_audio.lock_generated_audio(workspace, unlocked, require_applied=True)
    doubled = deepcopy(frozen)
    doubled["audioGraph"]["operations"].append(deepcopy(trim))
    with pytest.raises(ValueError, match="duplicated"):
        artcraft_audio.lock_generated_audio(workspace, doubled, require_applied=False)
    relabelled = deepcopy(frozen)
    del relabelled["audioGraph"]["operations"][0]["parameters"]["generatedAudioRef"]
    with pytest.raises(ValueError, match="relabel"):
        artcraft_audio.lock_generated_audio(
            workspace, relabelled, require_applied=False
        )
    layer["regions"].append({"startTicks": 1, "endTicks": 12})
    with pytest.raises(ValueError, match="overlapping"):
        artcraft_audio.lock_generated_audio(workspace, frozen, require_applied=False)
