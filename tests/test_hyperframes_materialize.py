"""Materialization guards with a fake browser and real tiny lossless FFmpeg media."""

import hashlib
import json
import shutil
import struct
import subprocess
import zlib
from copy import deepcopy
from fractions import Fraction
from pathlib import Path
from types import SimpleNamespace

import pytest

from avo.adapters.motion import hyperframes_materialize
from avo.timeline.contracts import (
    document_hash_excluding,
    file_fingerprint,
    fingerprint_stage,
)


def load():
    return hyperframes_materialize


def png(index):
    def chunk(name, data):
        return (
            struct.pack(">I", len(data))
            + name
            + data
            + struct.pack(">I", zlib.crc32(name + data))
        )

    pixels = bytes([index % 256, 30, 80, 255]) * 16
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 16, 16, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress((b"\0" + pixels) * 16))
        + chunk(b"IEND", b"")
    )


class FakeAdapter:
    def __init__(self, fixture):
        self.fixture = fixture
        self.calls = []
        self.seek_mismatch = False
        self.render_mismatch = False
        self.mutate_source = False
        self.drop_sequence_frame = False
        self.snapshot_warning = ""
        self.snapshot_projects = []

    def execute(self, operation, project, *args, root=None):
        self.calls.append((operation, args))
        if operation == "check":
            assert "--strict" in args and "--no-browser-gpu" in args
            return SimpleNamespace(exit_code=0, stdout="", stderr="")
        self.snapshot_projects.append(project)
        assert operation == "snapshot"
        assert args[args.index("--describe") + 1] == "false"
        destination = Path(args[args.index("--output") + 1])
        destination.mkdir(parents=True)
        production = destination.name.startswith("chunk-")
        times = args[args.index("--at") + 1].split(",")
        rate = self.fixture.binding["renderContract"]["frameRate"]
        fps = Fraction(rate["num"], rate["den"])
        for time in times:
            index = round(float(time) * float(fps))
            if (
                self.seek_mismatch
                and not production
                and times[0] != "0"
                and index == 90
            ):
                index += 1
            if self.render_mismatch and production and index == 54:
                index += 1
            if (
                self.drop_sequence_frame
                and production
                and index == self.fixture.binding["renderContract"]["frameCount"] - 1
            ):
                continue
            (destination / f"main-at-{time}s.png").write_bytes(png(index))
        if self.mutate_source and production:
            (self.fixture.project / "untracked.txt").write_text("untracked source")
        return SimpleNamespace(exit_code=0, stdout=self.snapshot_warning, stderr="")

    def check_timeline_instance(self, **kwargs):
        from avo.adapters.motion.hyperframes import HyperframesAdapter

        return HyperframesAdapter.check_timeline_instance(self, **kwargs)


@pytest.fixture
def asset(tmp_path, monkeypatch):
    module = load()
    ffmpeg, ffprobe = shutil.which("ffmpeg"), shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        pytest.skip("Local FFmpeg and ffprobe required for exact-frame codec checks")
    raw = tmp_path / "raw"
    project = raw / "edit/derived/chapter/source"
    project.mkdir(parents=True)
    (project / "index.html").write_text(
        "<!doctype html><html><head></head><body>source-only test composition</body></html>"
    )
    closure = {str(p): file_fingerprint(p) for p in project.rglob("*") if p.is_file()}
    binding = {
        "instanceId": "chapter-one",
        "instanceHash": "a" * 64,
        "componentRef": "chapter-component",
        "bmapCueId": "chapter-card",
        "layerId": "chapter-overlay",
        "canonicalInputLock": {
            kind: str(i) * 64
            for i, kind in enumerate(
                ["cmap", "bmap", "tracks", "animation", "sync-map"], 1
            )
        },
        "range": {"startFrame": 90, "endFrameExclusive": 270},
        "placement": {"x": 0, "y": 0, "width": 16, "height": 16},
        "componentContract": {"lifecycle": {"hold": "readable"}},
        "inputs": [
            {
                "artifactId": "hyperframes-source:index.html",
                "fingerprint": file_fingerprint(project / "index.html"),
                "ancestryRole": "dependency",
            }
        ],
        "project": str(project),
        "renderContract": {
            "width": 16,
            "height": 16,
            "frameRate": {"num": 60, "den": 1},
            "frameCount": 180,
        },
    }

    def verify(workspace, value):
        actual = {
            str(p): file_fingerprint(p) for p in project.rglob("*") if p.is_file()
        }
        if value != binding or actual != closure:
            raise ValueError("binding or source closure changed")
        return deepcopy(binding)

    monkeypatch.setattr(module, "resolve_binding", lambda *_: deepcopy(binding))
    monkeypatch.setattr(module, "verify_binding", verify)
    tools = {
        "version": "0.7.109",
        "versions": {"ffmpeg": "fixture", "ffprobe": "fixture"},
        "executables": {"ffmpeg": ffmpeg, "ffprobe": ffprobe},
        "files": [file_fingerprint(Path(ffmpeg)), file_fingerprint(Path(ffprobe))],
    }
    tools["hash"] = document_hash_excluding(tools, "hash")
    monkeypatch.setattr(module, "_tool_environment", lambda *_: deepcopy(tools))
    records = []
    workspace = SimpleNamespace(raw_dir=raw, timeline_dir=raw / "edit/timeline")

    class Service:
        def __init__(self, ws):
            self.ws = ws

        def path(self, identity):
            return self.ws.timeline_dir / "generated-assets" / (identity + ".json")

        def register(self, record, *, hyperframes_environment):
            assert hyperframes_environment["encodedVerification"]["silent"]
            records.append(deepcopy(record))
            path = self.path(record["assetId"])
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(record))
            return record

        def admit(self, identity, *, hyperframes_environment):
            return next(r for r in records if r["assetId"] == identity)

    monkeypatch.setattr(module, "GeneratedAssetService", Service)
    fixture = SimpleNamespace(
        module=module,
        workspace=workspace,
        project=project,
        binding=binding,
        records=records,
        tools=tools,
    )
    fixture.adapter = FakeAdapter(fixture)
    fixture.output = raw / "edit/derived/chapter-one.mkv"
    return fixture


def test_materializes_lossless_source_only_and_freezes_receipt(asset):
    result = asset.module.materialize(
        asset.adapter, asset.workspace, "chapter-one", output=asset.output
    )
    assert result["status"] == "pass"
    record = asset.records[0]
    extension = record["parameters"]["hyperframes"]
    verification = extension["outputVerification"]
    assert verification["silent"] is True and verification["codec"] == "ffv1"
    assert verification["pixelFormat"] == "bgra" and verification["frameCount"] == 180
    assert len(verification["frameHashes"]) == 180
    assert (
        verification["frameHashes"][54]
        == hashlib.sha256(bytes([54, 30, 80, 255]) * 256).hexdigest()
    )
    assert (
        extension["seekEvidence"]["rgbaSha256"]["54"] == verification["frameHashes"][54]
    )
    assert {p.name for p in asset.project.iterdir()} == {"index.html"}
    lock = json.loads(Path(result["inputLockRef"]["path"]).read_text())
    assert set(lock) == {"instanceId", "binding", "environment", "inputLockHash"}
    assert lock["inputLockHash"] == document_hash_excluding(lock, "inputLockHash")
    assert record["approvalReference"] is None and record["sourceFree"] is False
    assert any(
        x["artifactId"] == "hyperframes-input-lock:chapter-one"
        for x in record["inputs"]
    )


@pytest.mark.parametrize("where", ["outside", "source", "existing", "lock", "receipt"])
def test_rejects_unsafe_or_existing_output_before_browser(asset, where):
    output = {
        "outside": asset.workspace.raw_dir / "preview.mkv",
        "source": asset.project / "bad.mkv",
        "existing": asset.output,
        "lock": asset.output,
        "receipt": asset.output,
    }[where]
    if where in {"existing", "lock", "receipt"}:
        collision = (
            output if where == "existing" else output.with_suffix(".input-lock.json")
        )
        if where == "receipt":
            identity = (
                "hyperframes-"
                + hashlib.sha256(str(output.resolve()).encode()).hexdigest()[:24]
            )
            collision = (
                asset.workspace.timeline_dir / "generated-assets" / (identity + ".json")
            )
        collision.parent.mkdir(parents=True, exist_ok=True)
        collision.write_bytes(b"existing")
    with pytest.raises(
        (ValueError, RuntimeError), match="output|Output|derived|source|existing"
    ):
        asset.module.materialize(
            asset.adapter, asset.workspace, "chapter-one", output=output
        )
    assert not asset.adapter.calls and not asset.records


def test_repeated_seek_mismatch_blocks_registration(asset):
    asset.adapter.seek_mismatch = True
    with pytest.raises((ValueError, RuntimeError), match="seek|Seek|capture"):
        asset.module.materialize(
            asset.adapter, asset.workspace, "chapter-one", output=asset.output
        )
    assert not asset.records


def test_source_mutation_after_render_blocks_registration(asset):
    asset.adapter.mutate_source = True
    with pytest.raises((ValueError, RuntimeError), match="closure|changed"):
        asset.module.materialize(
            asset.adapter, asset.workspace, "chapter-one", output=asset.output
        )
    assert not asset.records


def test_render_png_disagrees_with_seek_blocks_registration(asset):
    asset.adapter.render_mismatch = True
    with pytest.raises((ValueError, RuntimeError), match="seek|Seek|frame|Frame"):
        asset.module.materialize(
            asset.adapter, asset.workspace, "chapter-one", output=asset.output
        )
    assert not asset.records
    manifests = list(
        (asset.workspace.raw_dir / "edit/tmp").glob(
            "hyperframes-materialize-*/failure.json"
        )
    )
    assert len(manifests) == 1
    evidence = json.loads(manifests[0].read_text())
    assert evidence["details"]["renderedFrameHashes"]["mismatchFrameIndices"] == [54]
    assert len(evidence["details"]["renderedFrameHashes"]["actualRgba"]) == 180
    assert evidence["details"]["before"]["captureEvidence"]["frames"] == [
        0,
        54,
        90,
        163,
        179,
    ]
    job = manifests[0].parent
    assert len(list((job / "frames").glob("*.png"))) == 180
    assert len(list((job / "before/forward").glob("*.png"))) == 5
    assert len(list((job / "before/reverse").glob("*.png"))) == 5


def test_failed_observation_preserves_actual_seek_images(asset):
    asset.adapter.seek_mismatch = True
    with pytest.raises((ValueError, RuntimeError), match="seek|Seek|capture"):
        asset.module.observe(asset.adapter, asset.workspace, asset.binding)
    manifests = list(
        (asset.workspace.raw_dir / "edit/tmp").glob(
            "hyperframes-observe-*/failure.json"
        )
    )
    assert len(manifests) == 1
    assert len(list(manifests[0].parent.rglob("*.png"))) == 10
    evidence = json.loads(manifests[0].read_text())
    assert evidence["details"]["forwardRgba"] != evidence["details"]["reverseRgba"]


def test_observation_cleanup_preserves_callers_fresh_source_guard(asset):
    with fingerprint_stage(verify_on_exit=True):
        result = asset.module.observe(asset.adapter, asset.workspace, asset.binding)
    assert result["captureEvidence"]["frames"] == [0, 54, 90, 163, 179]
    assert not list(
        (asset.workspace.raw_dir / "edit/tmp").glob("hyperframes-observe-*")
    )


def test_observation_evidence_path_must_stay_in_raw_tmp(asset):
    with pytest.raises((ValueError, RuntimeError), match="evidence|temporary|tmp"):
        asset.module.observe(
            asset.adapter,
            asset.workspace,
            asset.binding,
            evidence_dir=asset.project / "forbidden-diagnostics",
        )
    assert not asset.adapter.calls


def test_environment_mutation_during_observation_blocks(asset, monkeypatch):
    count = 0

    def changing(*_):
        nonlocal count
        count += 1
        value = deepcopy(asset.tools)
        if count > 1:
            value["versions"]["ffmpeg"] = "changed"
            value["hash"] = document_hash_excluding(value, "hash")
        return value

    monkeypatch.setattr(asset.module, "_tool_environment", changing)
    with pytest.raises((ValueError, RuntimeError), match="environment|tool|changed"):
        asset.module.observe(asset.adapter, asset.workspace, asset.binding)


def test_encoded_frame_mismatch_cannot_be_registered(asset, monkeypatch):
    original = asset.module._encoded_verification

    def forged(*args, **kwargs):
        value = original(*args, **kwargs)
        value["frameHashes"][7] = "f" * 64
        return value

    monkeypatch.setattr(asset.module, "_encoded_verification", forged)
    with pytest.raises((ValueError, RuntimeError), match="encoded|frame|Frame"):
        asset.module.materialize(
            asset.adapter, asset.workspace, "chapter-one", output=asset.output
        )
    assert not asset.records


def test_existing_source_change_is_rejected_before_browser(asset):
    (asset.project / "index.html").write_text("changed source")
    with pytest.raises((ValueError, RuntimeError), match="closure|changed"):
        asset.module.materialize(
            asset.adapter, asset.workspace, "chapter-one", output=asset.output
        )
    assert not asset.adapter.calls and not asset.records


def test_materializer_uses_declared_fractional_rate_and_frame_count(asset):
    asset.binding["renderContract"].update(
        frameRate={"num": 30000, "den": 1001}, frameCount=9
    )
    asset.binding["range"]["endFrameExclusive"] = 99
    result = asset.module.materialize(
        asset.adapter, asset.workspace, "chapter-one", output=asset.output
    )
    verification = result["environment"]["encodedVerification"]
    assert verification["frameRate"] == {"num": 30000, "den": 1001}
    assert verification["frameCount"] == 9
    assert len(verification["frameHashes"]) == 9


def test_snapshot_production_chunks_preserve_every_frame_and_backend(asset):
    asset.binding["renderContract"]["frameCount"] = 257
    asset.binding["range"]["endFrameExclusive"] = 347
    result = asset.module.materialize(
        asset.adapter, asset.workspace, "chapter-one", output=asset.output
    )
    calls = [
        args
        for operation, args in asset.adapter.calls
        if operation == "snapshot"
        and Path(args[args.index("--output") + 1]).name.startswith("chunk-")
    ]
    assert [len(args[args.index("--at") + 1].split(",")) for args in calls] == [
        128,
        128,
        1,
    ]
    assert len(result["environment"]["encodedVerification"]["frameHashes"]) == 257
    assert result["environment"]["toolEnvironment"]["renderMode"]["rasterBackend"] == (
        "hyperframes-native-snapshot-png-sequence"
    )
    assert all(operation != "render" for operation, _ in asset.adapter.calls)


def test_snapshot_sequence_still_rejects_nondeterministic_source(asset, monkeypatch):
    source = asset.project / "index.html"
    source.write_text(source.read_text() + "<script>Math.random()</script>")
    asset.binding["inputs"][0]["fingerprint"] = file_fingerprint(source)
    # Model a newly registered source so this exercises the adapter's source gate,
    # independently of the binding service's frozen-source checks.
    monkeypatch.setattr(
        asset.module, "verify_binding", lambda _workspace, value: deepcopy(value)
    )
    with pytest.raises((ValueError, RuntimeError), match="nondeterministic"):
        asset.module.materialize(
            asset.adapter, asset.workspace, "chapter-one", output=asset.output
        )
    assert not asset.records


def test_missing_production_snapshot_cannot_reach_encoding_or_admission(asset):
    asset.adapter.drop_sequence_frame = True
    with pytest.raises((ValueError, RuntimeError), match="Missing exact seek"):
        asset.module.materialize(
            asset.adapter, asset.workspace, "chapter-one", output=asset.output
        )
    assert not asset.output.exists() and not asset.records


@pytest.mark.parametrize(
    "warning",
    [
        "Runtime did not become render-ready within 5000ms",
        "Fonts FAILED: missing-font",
        "1/1 active <video> frame(s) could not be extracted",
    ],
)
def test_successful_snapshot_exit_with_unready_media_cannot_be_admitted(asset, warning):
    asset.adapter.snapshot_warning = warning
    with pytest.raises((ValueError, RuntimeError), match="readiness verification"):
        asset.module.materialize(
            asset.adapter, asset.workspace, "chapter-one", output=asset.output
        )
    assert not asset.output.exists() and not asset.records


def test_capture_copy_preserves_original_and_declared_rational_clock(asset):
    node = shutil.which("node")
    if not node:
        pytest.skip(
            "Local Node required to execute the configuration compatibility setter"
        )
    asset.binding["renderContract"].update(
        frameRate={"num": 30000, "den": 1001}, frameCount=9
    )
    source = (asset.project / "index.html").read_bytes()
    evidence = asset.workspace.raw_dir / "edit/tmp/private-observation"
    result = asset.module.observe(
        asset.adapter, asset.workspace, asset.binding, evidence_dir=evidence
    )
    capture_project = evidence / "capture-project"
    assert asset.adapter.snapshot_projects == [capture_project, capture_project]
    assert (asset.project / "index.html").read_bytes() == source
    wrapped = (capture_project / "index.html").read_text()
    script = wrapped.split("<head>", 1)[1].split("</script>", 1)[0].split(">", 1)[1]
    # The installed CLI strips scripts containing its literal bootstrap marker.
    assert "__HF_EXPORT_RENDER_SEEK_CONFIG" not in script
    command = (
        "const vm=require('vm'); const context={window:{}};"
        "vm.runInNewContext(process.argv[1],context);"
        "const initial={...context.window.__HF_EXPORT_RENDER_SEEK_CONFIG};"
        "context.window.__HF_EXPORT_RENDER_SEEK_CONFIG="
        "{fps:30,fpsSource:'default',fallbackReason:'unset',fpsFallbackReason:'missing',keep:'unchanged'};"
        "process.stdout.write(JSON.stringify({initial,assigned:context.window.__HF_EXPORT_RENDER_SEEK_CONFIG}));"
    )
    actual = json.loads(
        subprocess.check_output([node, "-e", command, script], text=True)
    )
    assert actual["initial"] == {"fps": 30000 / 1001, "fpsSource": "render-options"}
    assert actual["assigned"] == {
        "fps": 30000 / 1001,
        "fpsSource": "render-options",
        "keep": "unchanged",
    }
    policy = result["toolEnvironment"]["renderMode"]["snapshotClockCompatibility"]
    assert policy["frameRate"] == {"num": 30000, "den": 1001}
    assert result["toolEnvironment"]["hash"] == document_hash_excluding(
        result["toolEnvironment"], "hash"
    )


@pytest.fixture
def capture_script(tmp_path):
    project = tmp_path / "source"
    project.mkdir()
    source = project / "index.html"
    original = b"<!doctype html><html><head></head><body>unchanged</body></html>"
    source.write_bytes(original)
    binding = {
        "project": str(project),
        "inputs": [{"fingerprint": file_fingerprint(source)}],
        "renderContract": {"frameRate": {"num": 60, "den": 1}},
    }
    work = tmp_path / "work"
    job = work / "job"
    job.mkdir(parents=True)
    clone = load()._capture_project(binding, job, work)
    assert source.read_bytes() == original
    cloned = (clone / "index.html").read_text()
    script = cloned.split("<script", 1)[1].split(">", 1)[1].split("</script>", 1)[0]
    assert "__hfWaitForSeekCompletion" not in script
    assert "__HF_EXPORT_RENDER_SEEK_CONFIG" not in script
    return script


def run_capture_script(script, body):
    node = shutil.which("node")
    if not node:
        pytest.skip(
            "Local Node required to execute the native capture compatibility shim"
        )
    return json.loads(
        subprocess.check_output([node, "-e", body, script], text=True, timeout=30)
    )


CAPTURE_DOM = r"""
const vm = require('vm');
const assert = require('assert/strict');
const events = [];
let failLayout = false;
function root(name, initial, parent = null) {
  let attribute = initial;
  return {
    parentElement: {closest(selector) {
      assert.equal(selector, '[data-composition-id]'); return parent;
    }},
    getAnimations(options) {
      assert.equal(options.subtree, true); return [];
    },
    querySelectorAll(selector) { assert.equal(selector, '*'); return []; },
    getAttribute(key) { assert.equal(key, 'style'); return attribute; },
    setAttribute(key, value) {
      assert.equal(key, 'style'); attribute = value; events.push('restore:' + name);
    },
    removeAttribute(key) {
      assert.equal(key, 'style'); attribute = null; events.push('remove:' + name);
    },
    style: {setProperty(key, value, priority) {
      assert.deepEqual([key, value, priority], ['display', 'none', 'important']);
      attribute = 'display: none !important;'; events.push('hide:' + name);
    }},
    get offsetHeight() {
      events.push('layout:' + name + ':' + attribute);
      if (failLayout) { failLayout = false; throw layoutError; }
      return 20;
    }
  };
}
const initialStyles = [null, '', 'display: inline !important; color: red; --x:  2;'];
const roots = initialStyles.map((style, i) => root('root' + i, style));
const nested = root('nested', 'opacity: .8', roots[0]);
const document = {querySelectorAll(selector) {
  assert.equal(selector, '[data-composition-id]'); return [...roots, nested];
}};
const window = {getComputedStyle() {
  return {animationName: 'none', transitionDuration: '0s'};
}};
const context = {window, document};
const layoutError = new Error('layout failed');
function restored() {
  assert.deepEqual(roots.map(item => item.getAttribute('style')), initialStyles);
  assert.equal(nested.getAttribute('style'), 'opacity: .8');
  assert(!events.some(item => item.includes('nested')));
}
"""


@pytest.mark.parametrize("assigned_before_shim", [False, True])
def test_capture_repaint_awaits_native_completion_and_preserves_call(
    capture_script, assigned_before_shim
):
    body = (
        CAPTURE_DOM
        + r"""
(async () => {
  let release;
  const ready = new Promise(resolve => { release = resolve; });
  const receiver = {identity: 'native receiver'};
  const argument = {identity: 'native argument'};
  const result = {identity: 'native result'};
  const native = async function(value, count) {
    assert.equal(this, receiver); assert.equal(value, argument); assert.equal(count, 7);
    events.push('native-start'); await ready; events.push('native-done'); return result;
  };
  if (ASSIGNED_BEFORE_SHIM) window.__hfWaitForSeekCompletion = native;
  vm.runInNewContext(process.argv[1], context);
  if (!ASSIGNED_BEFORE_SHIM) window.__hfWaitForSeekCompletion = native;
  const wrapped = window.__hfWaitForSeekCompletion;
  assert.notEqual(wrapped, native);
  window.__hfWaitForSeekCompletion = native;
  assert.equal(window.__hfWaitForSeekCompletion, wrapped);
  window.__hfWaitForSeekCompletion = wrapped;
  assert.equal(window.__hfWaitForSeekCompletion, wrapped);
  const pending = wrapped.call(receiver, argument, 7);
  assert.deepEqual(events, ['native-start']);
  release(); assert.equal(await pending, result);
  restored();
  assert.deepEqual(events.slice(0, 5), ['native-start', 'native-done', 'hide:root0', 'hide:root1', 'hide:root2']);
  assert.equal(events.filter(item => item.startsWith('layout:')).length, 6);
  assert.deepEqual(events.slice(-3), initialStyles.map((style, i) => 'layout:root' + i + ':' + style));
  events.length = 0;
  const replacement = function() { events.push('replacement'); return 42; };
  window.__hfWaitForSeekCompletion = replacement;
  assert.equal(await window.__hfWaitForSeekCompletion(), 42);
  assert.equal(events[0], 'replacement');
  assert.equal(events.filter(item => item.startsWith('hide:')).length, 3);
  restored();
  window.__hfWaitForSeekCompletion = null;
  assert.equal(window.__hfWaitForSeekCompletion, null);
  process.stdout.write(JSON.stringify({pass: true}));
})().catch(error => { console.error(error); process.exitCode = 1; });
"""
    )
    body = body.replace("ASSIGNED_BEFORE_SHIM", str(assigned_before_shim).lower())
    assert run_capture_script(capture_script, body) == {"pass": True}


@pytest.mark.parametrize("native_async", [False, True])
def test_capture_repaint_propagates_native_failure_without_flushing(
    capture_script, native_async
):
    body = (
        CAPTURE_DOM
        + r"""
(async () => {
  vm.runInNewContext(process.argv[1], context);
  const failure = new Error('native failure');
  const fail = function() { throw failure; };
  window.__hfWaitForSeekCompletion = NATIVE_ASYNC ? async function() { fail(); } : fail;
  await assert.rejects(window.__hfWaitForSeekCompletion(), error => error === failure);
  assert.deepEqual(events, []); restored();
  process.stdout.write(JSON.stringify({pass: true}));
})().catch(error => { console.error(error); process.exitCode = 1; });
"""
    )
    body = body.replace("NATIVE_ASYNC", str(native_async).lower())
    assert run_capture_script(capture_script, body) == {"pass": True}


def test_capture_repaint_restores_exact_styles_after_layout_failure(capture_script):
    body = (
        CAPTURE_DOM
        + r"""
(async () => {
  vm.runInNewContext(process.argv[1], context);
  window.__hfWaitForSeekCompletion = () => undefined;
  failLayout = true;
  await assert.rejects(window.__hfWaitForSeekCompletion(), error => error === layoutError);
  restored();
  assert.deepEqual(events.slice(-3), initialStyles.map((style, i) => 'layout:root' + i + ':' + style));
  process.stdout.write(JSON.stringify({pass: true}));
})().catch(error => { console.error(error); process.exitCode = 1; });
"""
    )
    assert run_capture_script(capture_script, body) == {"pass": True}


@pytest.mark.parametrize("state", ["running", "paused", "unavailable"])
def test_capture_repaint_preserves_roots_with_native_animation_or_unknown_api(
    capture_script, state
):
    body = (
        CAPTURE_DOM
        + r"""
(async () => {
  for (const item of roots) {
    if (STATE === 'unavailable') item.getAnimations = undefined;
    else item.getAnimations = options => {
      assert.equal(options.subtree, true); return [{playState: STATE}];
    };
  }
  vm.runInNewContext(process.argv[1], context);
  window.__hfWaitForSeekCompletion = () => 42;
  assert.equal(await window.__hfWaitForSeekCompletion(), 42);
  assert.deepEqual(events, []); restored();
  process.stdout.write(JSON.stringify({pass: true}));
})().catch(error => { console.error(error); process.exitCode = 1; });
"""
    )
    body = body.replace("STATE", json.dumps(state))
    assert run_capture_script(capture_script, body) == {"pass": True}


@pytest.mark.parametrize(
    "condition", ["finished-css-animation", "transition", "computed-style-unavailable"]
)
def test_capture_repaint_preserves_declared_css_motion(capture_script, condition):
    body = (
        CAPTURE_DOM
        + r"""
(async () => {
  if (CONDITION === 'computed-style-unavailable') window.getComputedStyle = undefined;
  else {
    const descendant = {};
    for (const item of roots) item.querySelectorAll = () => [descendant];
    window.getComputedStyle = element => ({
      animationName: CONDITION === 'finished-css-animation' && element === descendant ? 'finished-title' : 'none',
      transitionDuration: CONDITION === 'transition' && element === descendant ? '0s, 0.2s' : '0s'
    });
  }
  vm.runInNewContext(process.argv[1], context);
  window.__hfWaitForSeekCompletion = () => 42;
  assert.equal(await window.__hfWaitForSeekCompletion(), 42);
  assert.deepEqual(events, []); restored();
  process.stdout.write(JSON.stringify({pass: true}));
})().catch(error => { console.error(error); process.exitCode = 1; });
"""
    )
    body = body.replace("CONDITION", json.dumps(condition))
    assert run_capture_script(capture_script, body) == {"pass": True}


def test_capture_environment_binds_repaint_policy(asset):
    environment = asset.module._capture_environment(
        Path("."), asset.binding["renderContract"]
    )
    assert environment["renderMode"]["snapshotRepaintCompatibility"] == {
        "policy": "seek-completion-top-roots-display-reset-v1",
        "property": "__hfWaitForSeekCompletion",
        "qualifiedHyperframesVersion": "0.7.109",
        "scope": "capture-clone-only",
        "boundary": "after-successful-native-seek-completion",
        "roots": "top-level-[data-composition-id]",
        "eligibility": "no-native-animation-no-css-animation-or-transition",
        "styleRestoration": "exact-style-attribute-null-preserved",
        "runtimeHookIdentity": "wrapped-native-function-in-isolated-capture-page",
        "limitation": "after-seek-boundary-not-universal-post-lut-callback",
    }
    assert environment["hash"] == document_hash_excluding(environment, "hash")
