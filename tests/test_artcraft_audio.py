"""SoundCraft cue scope, source ownership and retained PCM evidence."""

from copy import deepcopy
from types import SimpleNamespace

import pytest

from avo import artcraft, init_project
from avo.breath_control import resolve_control
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


def _existing_mix(tmp_path, cue_node, cue_trim):
    layers, nodes, operations = [], [], []
    region = cue_node["outputRange"]
    for index, role in enumerate(("dialogue", "music", "sfx", "ambience"), start=4):
        name = "existing-" + role
        source = {"locator": str(tmp_path / f"{name}.wav"), "sha256": str(index) * 64}
        layer = {"layerId": name, "role": role, "source": source, "gainDb": -index}
        if role == "dialogue":
            layer["breathControl"] = {"enabled": False}
        layers.append(layer)
        nodes.append(
            {
                **deepcopy(cue_node),
                "nodeId": name,
                "kind": "source" if role == "dialogue" else role,
            }
        )
        operations.extend(
            [
                {
                    "operationId": name + "-trim",
                    "kind": "trim",
                    "range": region,
                    "parameters": {"nodeId": name, "sourceId": name, "source": source},
                },
                {
                    "operationId": name + "-gain",
                    "kind": "gain",
                    "range": region,
                    "parameters": {"nodeId": name, "gainDb": layer["gainDb"]},
                },
            ]
        )
    nodes.append(cue_node)
    operations.extend(
        [
            cue_trim,
            {
                "operationId": "program-mix",
                "kind": "mix",
                "range": region,
                "parameters": {"nodeIds": [node["nodeId"] for node in nodes]},
            },
        ]
    )
    return layers, {"nodes": nodes, "operations": operations}


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
    unrelated, graph = _existing_mix(tmp_path, node, trim)
    snapshot = {"audioTracks": {"layers": [*unrelated, layer]}}
    original_tracks = deepcopy(snapshot)
    tracks = SimpleNamespace(
        load_index=lambda: {"headRevisionId": "tracks-one"},
        revision=lambda _: {"snapshot": snapshot},
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
        "audioGraph": graph,
        "output": {"frameRate": {"num": 24, "den": 1}},
    }
    original_graph = deepcopy(graph)
    frozen = artcraft_audio.lock_generated_audio(workspace, plan, require_applied=False)
    assert frozen["canonicalInputLock"]["source:" + source_id] == source["sha256"]
    assert frozen["audioGraph"] == original_graph
    assert snapshot == original_tracks
    assert all(
        resolve_control(item.get("breathControl"), role=item["role"]) is None
        for item in unrelated
    )
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
    relabelled_cue = next(
        op
        for op in relabelled["audioGraph"]["operations"]
        if op["operationId"] == trim["operationId"]
    )
    del relabelled_cue["parameters"]["generatedAudioRef"]
    with pytest.raises(ValueError, match="relabel"):
        artcraft_audio.lock_generated_audio(
            workspace, relabelled, require_applied=False
        )
    for item in unrelated:
        if item["role"] == "sfx":
            continue
        with pytest.raises(ValueError, match="own SFX layer"):
            artcraft_audio.require_generated_audio_layer(
                {**layer, "role": item["role"]}
            )
    layer["regions"].append({"startTicks": 1, "endTicks": 12})
    with pytest.raises(ValueError, match="overlapping"):
        artcraft_audio.lock_generated_audio(workspace, frozen, require_applied=False)
