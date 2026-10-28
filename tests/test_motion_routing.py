"""Motion dispatch contracts independent of motion-framework installation."""

from __future__ import annotations

import importlib
import json
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

from avo import motion
from avo.adapters import base, run_job
from avo.adapters.base import AdapterError, JobRequest, JobResult, resolve_adapter
from avo.adapters.motion import code_drawn
from avo.motion import MotionError, inspect_motion

REPO = Path(__file__).resolve().parents[1]


def _write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value) + "\n", encoding="utf-8")


def _update(path: Path, **changes) -> None:
    value = json.loads(path.read_text(encoding="utf-8"))
    value.update(changes)
    _write(path, value)


@pytest.fixture
def context(tmp_path):
    root, home, raw = (tmp_path / name for name in ("repository", "home", "footage"))
    home.mkdir()
    raw.mkdir()
    config = root / "config" / "avo.config.json"
    _write(
        config,
        {
            "jobs": {
                "motion": {"local": ["remotion", "code-drawn", "hyperframes"]},
                "transcribe": {"local": "local+faster-whisper"},
                "understand": {"local": "local+watch-skill"},
                "memory": {"local": "local+ai-memory"},
                "plan": {"local": "local+speckit"},
            }
        },
    )
    schema = root / "providers" / "avo.provider.schema.json"
    schema.parent.mkdir(parents=True)
    shutil.copyfile(REPO / "providers" / "avo.provider.schema.json", schema)
    provider = root / "providers" / "sample" / "avo.provider.json"
    _write(
        provider,
        {
            "name": "sample",
            "displayName": "Example channel",
            "kind": "youtube",
            "media": {"rawRoot": str(raw.parent)},
        },
    )
    project = raw / "avo.project.json"
    _write(project, {"provider": "sample", "videoId": "routing", "rawDir": str(raw)})
    return SimpleNamespace(
        root=root,
        home=home,
        raw=raw,
        config=config,
        provider=provider,
        project=project,
        preferences=home / ".avo" / "preferences.json",
    )


def _resolve(context, **kwargs):
    return resolve_adapter(
        "motion",
        "local",
        context.root,
        project=context.project,
        provider="sample",
        home=context.home,
        **kwargs,
    )


def test_builtin_default_does_not_follow_routing_list_order(context):
    adapter = _resolve(context)
    assert adapter.routing_id == "hyperframes"
    assert not context.preferences.exists()


@pytest.mark.parametrize("engine", ["hyperframes", "code-drawn", "remotion"])
def test_explicit_engine_selects_its_actual_adapter_without_saving(context, engine):
    before = {
        path: path.read_bytes()
        for path in (context.config, context.provider, context.project)
    }
    adapter = _resolve(context, motion_engine=engine)
    assert adapter.routing_id == engine
    assert all(path.read_bytes() == data for path, data in before.items())
    assert not context.preferences.exists()


def test_scope_precedence_is_used_for_dispatch_and_override_does_not_persist(context):
    _write(
        context.preferences,
        {"schemaVersion": "1.0.0", "motion": {"engine": "code-drawn"}},
    )
    assert _resolve(context).routing_id == "code-drawn"
    _update(context.provider, routingOverrides={"motion": {"engine": "remotion"}})
    assert _resolve(context).routing_id == "remotion"
    _update(context.project, motion={"engine": "hyperframes"})
    assert _resolve(context).routing_id == "hyperframes"
    assert _resolve(context, motion_engine="code-drawn").routing_id == "code-drawn"
    assert _resolve(context).routing_id == "hyperframes"
    assert (
        json.loads(context.preferences.read_text())["motion"]["engine"] == "code-drawn"
    )


@pytest.mark.parametrize(
    ("scope", "payload"),
    [
        ("global", {"schemaVersion": "1.0.0", "motion": {"engine": "invalid"}}),
        ("provider", {"routingOverrides": {"motion": {"engine": "invalid"}}}),
        ("project", {"motion": {"engine": "invalid"}}),
    ],
)
def test_invalid_masked_scope_fails_closed_before_adapter_loading(
    context, monkeypatch, scope, payload
):
    path = getattr(context, "preferences" if scope == "global" else scope)
    if scope == "global":
        _write(path, payload)
    else:
        _update(path, **payload)
    monkeypatch.setattr(
        base,
        "load_adapter_class",
        lambda _: pytest.fail("Invalid scope loaded an adapter."),
    )
    with pytest.raises((MotionError, AdapterError)):
        _resolve(context, motion_engine="hyperframes")


def test_malformed_global_preference_fails_without_fallback_or_repair(
    context, monkeypatch
):
    context.preferences.parent.mkdir()
    context.preferences.write_text("{broken", encoding="utf-8")
    monkeypatch.setattr(
        base, "load_adapter_class", lambda _: pytest.fail("Malformed data fell back.")
    )
    with pytest.raises((MotionError, AdapterError)):
        _resolve(context)
    assert context.preferences.read_text(encoding="utf-8") == "{broken"


@pytest.mark.parametrize("engine", ["none", "canvas", "HyperFrames", "no-framework"])
def test_noncanonical_explicit_id_never_falls_back(context, monkeypatch, engine):
    monkeypatch.setattr(
        base,
        "load_adapter_class",
        lambda _: pytest.fail("Invalid engine loaded an adapter."),
    )
    with pytest.raises((MotionError, AdapterError)):
        _resolve(context, motion_engine=engine)


@pytest.mark.parametrize(
    ("job", "module"),
    [
        ("transcribe", "avo.adapters.transcribe.faster_whisper:FasterWhisperAdapter"),
        ("understand", "avo.adapters.understand.watch_skill:WatchSkillAdapter"),
        ("memory", "avo.adapters.stubs.memory_ai_memory:AiMemoryStubAdapter"),
        ("plan", "avo.adapters.stubs.plan_speckit:SpeckitStubAdapter"),
    ],
)
def test_motion_preferences_do_not_change_other_job_routes(
    context, monkeypatch, job, module
):
    context.preferences.parent.mkdir()
    context.preferences.write_text("{irrelevant-to-this-job", encoding="utf-8")
    loaded = []

    class ExistingAdapter:
        pass

    def load(path):
        loaded.append(path)
        return ExistingAdapter

    monkeypatch.setattr(base, "load_adapter_class", load)
    adapter = resolve_adapter(
        job,
        "local",
        context.root,
        motion_engine="code-drawn",
        project=context.project,
        provider="sample",
        home=context.home,
    )
    assert isinstance(adapter, ExistingAdapter)
    assert loaded == [module]


def test_code_drawn_resolution_never_loads_a_motion_framework(context, monkeypatch):
    loaded = []
    original = importlib.import_module

    def guarded(name, *args, **kwargs):
        assert name not in {
            "avo.adapters.motion.hyperframes",
            "avo.adapters.stubs.motion_remotion",
        }, f"Unused motion-framework adapter loaded: {name}"
        loaded.append(name)
        return original(name, *args, **kwargs)

    monkeypatch.setattr(importlib, "import_module", guarded)
    adapter = _resolve(context, motion_engine="code-drawn")
    assert isinstance(adapter, code_drawn.CodeDrawnAdapter)
    assert "avo.adapters.motion.code_drawn" in loaded


def test_code_drawn_inspection_checks_only_its_selected_runtime(context, monkeypatch):
    observed = []
    readiness = {
        "ready": False,
        "state": "unavailable",
        "checks": [],
        "blockers": ["Managed Chromium is absent."],
        "nextActions": ["Install the runtime."],
    }

    def selected_runtime(**kwargs):
        observed.append(kwargs)
        return readiness

    runtime = importlib.import_module("avo.motion_runtime")
    monkeypatch.setattr(runtime, "runtime_readiness", selected_runtime)
    monkeypatch.setattr(
        motion,
        "_hyperframes_readiness",
        lambda *_: pytest.fail("Code-drawn inspection checked HyperFrames."),
    )
    shown = inspect_motion(
        project=context.project,
        provider="sample",
        root=context.root,
        home=context.home,
        invocation="code-drawn",
    )
    assert observed
    assert shown["selection"]["engine"] == "code-drawn"
    assert shown["readiness"] == readiness


def test_explicit_remotion_is_an_honest_stub_and_never_falls_back(context):
    guide = context.root / "docs" / "remotion-decision-guide.md"
    guide.parent.mkdir()
    guide.write_text("Per-project Remotion setup.", encoding="utf-8")
    adapter = _resolve(context, motion_engine="remotion")
    result = adapter.run(JobRequest("motion", "local", [], root=context.root))
    assert adapter.routing_id == "remotion"
    assert result.exit_code == 2
    assert "remotion" in result.stderr.lower()
    assert "stub" in result.stderr.lower()
    assert result.artifact_paths == []


@pytest.mark.parametrize("operation", ["check", "snapshot", "render"])
def test_code_drawn_job_dispatch_forwards_typed_inputs_and_actual_result(
    tmp_path, monkeypatch, operation
):
    adapter = code_drawn.CodeDrawnAdapter()
    composition, input_lock = (
        tmp_path / "composition.json",
        tmp_path / "input-lock.json",
    )
    output_lock = tmp_path / "frozen-lock.json"
    output = tmp_path / ("frame.png" if operation == "snapshot" else "asset.mkv")
    artifact = output_lock if operation == "check" else output
    artifacts = [{"path": str(artifact), "sha256": "a" * 64}]
    if operation == "render":
        artifacts.append(
            {"path": str(tmp_path / "asset.generated-asset.json"), "sha256": "b" * 64}
        )
    envelope = code_drawn.motion_result("code-drawn-" + operation, artifacts=artifacts)
    observed = []

    def check(composition, input_lock=None, output_lock=None):
        observed.append((composition, input_lock, output_lock))
        return envelope

    def snapshot(composition, frame, output, input_lock=None):
        observed.append((composition, frame, output, input_lock))
        return envelope

    def render(composition, input_lock, output):
        observed.append((composition, input_lock, output))
        return envelope

    for name, method in (("check", check), ("snapshot", snapshot), ("render", render)):
        monkeypatch.setattr(adapter, name, method)
    argv = [
        operation,
        "--composition",
        str(composition),
        "--input-lock",
        str(input_lock),
    ]
    if operation == "check":
        argv += ["--output-lock", str(output_lock)]
        expected = (composition, input_lock, output_lock)
    elif operation == "snapshot":
        argv += ["--frame", "7", "--output", str(output)]
        expected = (composition, 7, output, input_lock)
    else:
        argv += ["--output", str(output)]
        expected = (composition, input_lock, output)
    result = adapter.run(JobRequest("motion", "local", argv, root=tmp_path))
    assert observed == [expected]
    assert result.exit_code == 0
    assert json.loads(result.stdout) == envelope
    assert result.artifact_paths == [Path(item["path"]) for item in artifacts]
    assert result.stderr == ""


@pytest.mark.parametrize(
    ("code", "exit_code"),
    [
        ("CODE_DRAWN_INPUT_INVALID", 2),
        ("CODE_DRAWN_RUNTIME_UNAVAILABLE", 2),
        ("CODE_DRAWN_RENDER_FAILED", 1),
        ("CODE_DRAWN_CANCELLED", 130),
    ],
)
def test_code_drawn_job_preserves_actionable_error_and_exit_code(
    tmp_path, monkeypatch, code, exit_code
):
    adapter = code_drawn.CodeDrawnAdapter()
    error = MotionError(
        code, "Specific motion failure.", field="composition", remediation="Repair it."
    )

    def fail(*args, **kwargs):
        raise error

    monkeypatch.setattr(adapter, "check", fail)
    result = adapter.run(
        JobRequest(
            "motion",
            "local",
            ["check", "--composition", str(tmp_path / "composition.json")],
            root=tmp_path,
        )
    )
    assert result.exit_code == exit_code
    assert json.loads(result.stderr) == error.to_dict()
    assert result.artifact_paths == []
    assert not result.stdout


@pytest.mark.parametrize(
    "argv",
    [
        ["preview", "--composition", "composition.json"],
        ["check", "--composition"],
        [
            "check",
            "--composition",
            "composition.json",
            "--treatment",
            "hyperframes-only",
        ],
        ["render", "--composition", "composition.json", "--output", "asset.mkv"],
    ],
)
def test_unsupported_or_incomplete_job_request_fails_before_public_operation(
    tmp_path, monkeypatch, argv
):
    adapter = code_drawn.CodeDrawnAdapter()
    for name in ("check", "snapshot", "render"):
        monkeypatch.setattr(
            adapter,
            name,
            lambda *a, **k: pytest.fail("Invalid request reached backend."),
        )
    result = adapter.run(JobRequest("motion", "local", argv, root=tmp_path))
    assert result.exit_code == 2
    assert result.stderr
    assert result.artifact_paths == []


@pytest.mark.parametrize("metadata_first", [False, True])
def test_job_runner_consumes_metadata_before_boundary_and_preserves_suffix(
    context,
    monkeypatch,
    capsys,
    metadata_first,
):
    resolved, requests = [], []
    artifact = context.raw / "result.mkv"

    class RecordingAdapter:
        routing_id = "code-drawn"

        def run(self, request):
            requests.append(request)
            return JobResult(0, artifact_paths=[artifact])

    def resolve(job, label, root=None, **kwargs):
        resolved.append((job, label, root, kwargs))
        return RecordingAdapter()

    monkeypatch.setattr(run_job, "resolve_adapter", resolve)
    metadata = [
        "--label",
        "paid",
        "--root",
        str(context.root),
        "--motion-engine",
        "code-drawn",
        "--project",
        str(context.project),
        "--provider",
        "sample",
    ]
    suffix = [
        "check",
        "--motion-engine",
        "remotion",
        "--project",
        "literal-project",
        "--",
        "--label",
        "local",
    ]
    prefix = metadata + ["motion"] if metadata_first else ["motion"] + metadata
    assert run_job.main(prefix + ["--"] + suffix) == 0
    assert len(resolved) == len(requests) == 1
    job, label, root, kwargs = resolved[0]
    assert (job, label, root) == ("motion", "paid", context.root)
    assert kwargs["motion_engine"] == "code-drawn"
    assert Path(kwargs["project"]) == context.project
    assert kwargs["provider"] == "sample"
    assert requests[0].argv == suffix
    assert requests[0].root == context.root
    assert requests[0].label == "paid"
    result = json.loads(capsys.readouterr().out)
    assert result["adapter"] == "code-drawn"
    assert result["artifacts"] == [str(artifact)]
