from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from importlib import metadata
from pathlib import Path

import pytest

from avo.adapters.media import otio_reader
from avo.timeline.otio_import import ImportError

FIXTURE = Path(__file__).parent / "fixtures/otio/clip-v1.otio"


def test_missing_extra_is_actionable_without_installing(monkeypatch):
    def absent(_):
        raise metadata.PackageNotFoundError("opentimelineio")

    monkeypatch.setattr(otio_reader.metadata, "version", absent)
    with pytest.raises(ImportError) as error:
        otio_reader.read_otio(FIXTURE.read_bytes())
    assert error.value.code == "OTIO_RUNTIME_UNAVAILABLE"
    assert "resolve-import" in str(error.value)


def test_worker_environment_disables_plugins_and_startup_paths(monkeypatch):
    monkeypatch.setenv("OTIO_PLUGIN_MANIFEST_PATH", "malicious.json")
    monkeypatch.setenv("PYTHONPATH", "untrusted")
    env = otio_reader.worker_environment()
    assert env["OTIO_PLUGIN_MANIFEST_PATH"] == ""
    assert env["OTIO_DISABLE_ENTRYPOINTS_PLUGINS"] == "1"
    assert "PYTHONPATH" not in env


@pytest.mark.parametrize("frozen", [False, True])
def test_reader_uses_qualified_worker_route_without_host_plugin_paths(
    monkeypatch, frozen
):
    monkeypatch.setattr(sys, "frozen", frozen, raising=False)
    monkeypatch.setattr(otio_reader.metadata, "version", lambda _: "0.18.1")
    monkeypatch.setenv("OTIO_PLUGIN_MANIFEST_PATH", "untrusted/plugins.json")
    monkeypatch.setenv("OTIO_DISABLE_ENTRYPOINTS_PLUGINS", "0")
    monkeypatch.setenv("PYTHONPATH", "untrusted")
    monkeypatch.setenv("PYTHONSTARTUP", "untrusted/startup.py")
    calls = []

    def invoke(argv, **kwargs):
        calls.append((argv, kwargs))
        payload = {"nativeVersion": "0.18.1", "document": {}, "timelines": []}
        return subprocess.CompletedProcess(argv, 0, json.dumps(payload).encode(), b"")

    monkeypatch.setattr(otio_reader.subprocess, "run", invoke)
    result = otio_reader.read_otio(FIXTURE.read_bytes())
    assert result["nativeVersion"] == "0.18.1"
    argv, options = calls[0]
    assert argv == (
        [sys.executable, "otio-worker", "--worker"]
        if frozen
        else [sys.executable, "-I", "-m", "avo.adapters.media.otio_reader", "--worker"]
    )
    assert options["input"] == FIXTURE.read_bytes()
    assert options["timeout"] == 60 and options["shell"] is False
    assert options["env"]["OTIO_PLUGIN_MANIFEST_PATH"] == ""
    assert options["env"]["OTIO_DISABLE_ENTRYPOINTS_PLUGINS"] == "1"
    assert "PYTHONPATH" not in options["env"]
    assert "PYTHONSTARTUP" not in options["env"]


def test_frozen_missing_extra_checks_metadata_and_never_spawns_worker(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    looked_up = []

    def absent(name):
        looked_up.append(name)
        raise metadata.PackageNotFoundError(name)

    monkeypatch.setattr(otio_reader.metadata, "version", absent)
    monkeypatch.setattr(
        otio_reader.subprocess,
        "run",
        lambda *_, **__: pytest.fail("Missing native core spawned a worker"),
    )
    with pytest.raises(ImportError) as error:
        otio_reader.read_otio(FIXTURE.read_bytes())
    assert looked_up == ["opentimelineio"]
    assert error.value.code == "OTIO_RUNTIME_UNAVAILABLE"
    assert "resolve-import" in str(error.value) and "engine" in str(error.value)


@pytest.mark.parametrize("version", ["0.17.0", "0.18.2"])
def test_frozen_native_core_must_match_the_qualified_version(monkeypatch, version):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(otio_reader.metadata, "version", lambda _: version)
    with pytest.raises(ImportError) as error:
        otio_reader.read_otio(FIXTURE.read_bytes())
    assert error.value.code == "OTIO_RUNTIME_UNAVAILABLE"
    assert "0.18.1" in str(error.value)


@pytest.mark.parametrize("arguments", [[], ["--help"], ["--worker", "--extra"], ["-I"]])
def test_private_worker_dispatch_rejects_unrelated_arguments(monkeypatch, arguments):
    monkeypatch.setattr(
        otio_reader,
        "_worker_main",
        lambda: pytest.fail("Invalid private arguments reached worker"),
    )
    with pytest.raises(SystemExit, match="internal OTIO reader worker"):
        otio_reader.main(arguments)


def test_private_worker_dispatch_accepts_only_explicit_worker_request(monkeypatch):
    calls = []
    monkeypatch.setattr(
        otio_reader, "_worker_main", lambda: calls.append("worker") or 3
    )
    assert otio_reader.main(["--worker"]) == 3
    assert calls == ["worker"]


def test_native_timeout_is_scoped(monkeypatch):
    monkeypatch.setattr(otio_reader.metadata, "version", lambda _: "0.18.1")

    def timeout(*args, **kwargs):
        assert kwargs["timeout"] == 60
        assert kwargs["shell"] is False
        raise subprocess.TimeoutExpired(args[0], 60)

    monkeypatch.setattr(otio_reader.subprocess, "run", timeout)
    with pytest.raises(ImportError) as error:
        otio_reader.read_otio(FIXTURE.read_bytes())
    assert error.value.code == "OTIO_INPUT_LIMIT"


def test_worker_bad_json_is_scoped(monkeypatch):
    monkeypatch.setattr(otio_reader.metadata, "version", lambda _: "0.18.1")
    monkeypatch.setattr(
        otio_reader.subprocess,
        "run",
        lambda *_, **__: subprocess.CompletedProcess([], 0, b"invalid", b""),
    )
    with pytest.raises(ImportError) as error:
        otio_reader.read_otio(FIXTURE.read_bytes())
    assert error.value.code == "OTIO_INPUT_INVALID"


def test_oversized_worker_output_blocks(monkeypatch):
    monkeypatch.setattr(otio_reader.metadata, "version", lambda _: "0.18.1")
    monkeypatch.setattr(otio_reader, "MAX_OUTPUT_BYTES", 10)
    monkeypatch.setattr(
        otio_reader.subprocess,
        "run",
        lambda *_, **__: subprocess.CompletedProcess([], 0, b"x" * 11, b""),
    )
    with pytest.raises(ImportError) as error:
        otio_reader.read_otio(FIXTURE.read_bytes())
    assert error.value.code == "OTIO_INPUT_LIMIT"


@pytest.mark.skipif(
    importlib.util.find_spec("opentimelineio") is None,
    reason="Optional pinned native reader required",
)
def test_native_core_roundtrip_ignores_hostile_plugin_manifest(tmp_path, monkeypatch):
    marker = tmp_path / "executed"
    plugin = tmp_path / "plugin.py"
    plugin.write_text(
        f"from pathlib import Path\nPath({str(marker)!r}).write_text('executed')\n"
    )
    manifest = tmp_path / "plugins.json"
    manifest.write_text(
        json.dumps(
            {
                "OTIO_SCHEMA": "PluginManifest.1",
                "schemadefs": [
                    {
                        "OTIO_SCHEMA": "SchemaDef.1",
                        "name": "malicious",
                        "filepath": str(plugin),
                    }
                ],
            }
        )
    )
    monkeypatch.setenv("OTIO_PLUGIN_MANIFEST_PATH", str(manifest))
    result = otio_reader.read_otio(FIXTURE.read_bytes())
    assert result["nativeVersion"] == "0.18.1"
    assert result["document"]["OTIO_SCHEMA"] == "Timeline.1"
    assert not marker.exists()


@pytest.mark.skipif(
    importlib.util.find_spec("opentimelineio") is None,
    reason="Optional pinned native reader required",
)
def test_unknown_schema_survival_is_not_capability_support():
    raw = json.loads(FIXTURE.read_text())
    raw["metadata"] = {
        "unknown": {"OTIO_SCHEMA": "VendorThing.99", "value": "retained"}
    }
    result = otio_reader.read_otio(json.dumps(raw).encode())
    assert "VendorThing" in json.dumps(result)
    assert "activationAllowed" not in result


@pytest.mark.skipif(
    importlib.util.find_spec("opentimelineio") is None,
    reason="Optional pinned native reader required",
)
def test_native_ranges_keep_media_origin_separate_from_program_origin():
    result = otio_reader.read_otio(FIXTURE.read_bytes())
    timeline = result["timelines"][0]
    assert timeline["pointer"] == ""
    assert float(timeline["globalStart"]["value"]) == 86400
    assert float(timeline["duration"]["value"]) == 48
    track = timeline["tracks"][0]
    clip = track["children"][0]
    assert track["pointer"] == "/tracks/children/0"
    assert track["kind"] == "Video"
    assert clip["schema"] == "Clip.1"
    assert clip["nativeSchema"] == "Clip.2"
    assert clip["referencePointer"] == clip["pointer"] + "/media_reference"
    assert float(clip["sourceRange"]["start"]["value"]) == 240
    assert float(clip["trimmedSourceRange"]["start"]["value"]) == 240
    assert float(clip["availableRange"]["start"]["value"]) == 240
    assert float(clip["fileRelativeSourceRange"]["start"]["value"]) == 0
    assert float(clip["parentRange"]["start"]["value"]) == 0
    assert float(clip["programRange"]["start"]["value"]) == 0
    assert clip["enabled"] is True
    assert clip["effectsCount"] == 0
    assert track["parentTrim"] is False
    assert clip["nativeRangeError"] == []


@pytest.mark.skipif(
    importlib.util.find_spec("opentimelineio") is None,
    reason="Optional pinned native reader required",
)
def test_native_clip2_uses_active_raw_reference_and_repeated_source_range():
    path = FIXTURE.with_name("clip-v2.otio")
    result = otio_reader.read_otio(path.read_bytes())
    clips = result["timelines"][0]["tracks"][0]["children"]
    assert clips[0]["activeReferenceKey"] == "camera"
    assert clips[0]["targetUrl"] == "file:///originals/take.mov"
    assert (
        clips[0]["referencePointer"] == clips[0]["pointer"] + "/media_references/camera"
    )
    assert float(clips[1]["sourceRange"]["start"]["value"]) == 60
    assert float(clips[1]["programRange"]["start"]["value"]) == 30
    assert clips[1]["availableRange"] is None
    assert clips[1]["fileRelativeSourceRange"] is None


@pytest.mark.skipif(
    importlib.util.find_spec("opentimelineio") is None,
    reason="Optional pinned native reader required",
)
def test_native_collection_facts_retain_structural_timeline_pointers():
    one = json.loads(FIXTURE.read_text())
    two = json.loads(FIXTURE.with_name("clip-v2.otio").read_text())
    raw = {
        "OTIO_SCHEMA": "SerializableCollection.1",
        "children": [
            one,
            {"OTIO_SCHEMA": "SerializableCollection.1", "children": [two]},
        ],
    }
    result = otio_reader.read_otio(json.dumps(raw).encode())
    assert [item["pointer"] for item in result["timelines"]] == [
        "/children/0",
        "/children/1/children/0",
    ]
    assert result["timelines"][1]["tracks"][0]["pointer"].startswith(
        "/children/1/children/0/tracks/"
    )


@pytest.mark.skipif(
    importlib.util.find_spec("opentimelineio") is None,
    reason="Optional pinned native reader required",
)
def test_native_nested_composition_is_reported_without_flattening():
    raw = json.loads(FIXTURE.read_text())
    track = raw["tracks"]["children"][0]
    nested_track = json.loads(json.dumps(track))
    track["children"] = [{"OTIO_SCHEMA": "Stack.1", "children": [nested_track]}]
    track["source_range"] = {
        "OTIO_SCHEMA": "TimeRange.1",
        "start_time": {"OTIO_SCHEMA": "RationalTime.1", "value": 0, "rate": 24},
        "duration": {"OTIO_SCHEMA": "RationalTime.1", "value": 48, "rate": 24},
    }
    result = otio_reader.read_otio(json.dumps(raw).encode())
    track_facts = result["timelines"][0]["tracks"][0]
    assert track_facts["parentTrim"] is True
    assert len(track_facts["children"]) == 1
    child = track_facts["children"][0]
    assert child["schema"] == "Stack.1"
    assert child["nestedComposition"] is True
    assert "children" not in child


@pytest.mark.skipif(
    importlib.util.find_spec("opentimelineio") is None,
    reason="Optional pinned native reader required",
)
def test_native_unavailable_ranges_are_scoped_facts_not_a_flattened_guess():
    raw = json.loads(FIXTURE.read_text())
    clip = raw["tracks"]["children"][0]["children"][0]
    clip.pop("source_range")
    clip["media_reference"].pop("available_range")
    result = otio_reader.read_otio(json.dumps(raw).encode())
    facts = result["timelines"][0]["tracks"][0]["children"][0]
    assert facts["trimmedSourceRange"] is None
    assert facts["programRange"] is None
    assert facts["nativeRangeError"]
    assert all(
        error["scope"] == facts["pointer"] for error in facts["nativeRangeError"]
    )


@pytest.mark.skipif(
    importlib.util.find_spec("opentimelineio") is None,
    reason="Optional pinned native reader required",
)
def test_transition_range_limitations_remain_scoped_facts():
    raw = json.loads(FIXTURE.read_text())
    clips = raw["tracks"]["children"][0]["children"]
    second = json.loads(json.dumps(clips[0]))
    transition = {
        "OTIO_SCHEMA": "Transition.1",
        "transition_type": "SMPTE_Dissolve",
        "in_offset": {"OTIO_SCHEMA": "RationalTime.1", "value": 12, "rate": 24},
        "out_offset": {"OTIO_SCHEMA": "RationalTime.1", "value": 12, "rate": 24},
    }
    clips.extend([transition, second])
    result = otio_reader.read_otio(json.dumps(raw).encode())
    facts = result["timelines"][0]["tracks"][0]["children"][1]
    assert facts["schema"] == "Transition.1"
    assert facts["trimmedSourceRange"] is None
    assert facts["nativeRangeError"]
    assert all(
        error["scope"] == facts["pointer"] for error in facts["nativeRangeError"]
    )


@pytest.mark.skipif(
    importlib.util.find_spec("opentimelineio") is None,
    reason="Optional pinned native reader required",
)
def test_active_reference_pointer_escapes_original_key():
    raw = json.loads(FIXTURE.with_name("clip-v2.otio").read_text())
    first = raw["tracks"]["children"][0]["children"][0]
    first["media_references"]["camera/a~b"] = first["media_references"].pop("camera")
    first["active_media_reference_key"] = "camera/a~b"
    result = otio_reader.read_otio(json.dumps(raw).encode())
    facts = result["timelines"][0]["tracks"][0]["children"][0]
    assert facts["referencePointer"].endswith("/media_references/camera~1a~0b")


@pytest.mark.skipif(
    importlib.util.find_spec("opentimelineio") is None,
    reason="Optional pinned native reader required",
)
def test_native_enabled_and_effect_facts_preserve_each_level():
    raw = json.loads(FIXTURE.read_text())
    raw["tracks"]["enabled"] = False
    track = raw["tracks"]["children"][0]
    track["effects"] = [
        {"OTIO_SCHEMA": "Effect.1", "name": "declared", "effect_name": "test"}
    ]
    track["children"][0]["enabled"] = False
    result = otio_reader.read_otio(json.dumps(raw).encode())
    timeline = result["timelines"][0]
    assert timeline["enabled"] is False
    assert timeline["tracks"][0]["effectsCount"] == 1
    assert timeline["tracks"][0]["children"][0]["enabled"] is False
