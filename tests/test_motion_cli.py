"""Native motion preference commands use isolated home/provider/project files."""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import pytest

from avo.mcp.bridge import run_cli
from avo.provider_scaffold import build_manifest

ROOT = Path(__file__).resolve().parents[1]
INSPECTION_KEYS = {
    "operation",
    "status",
    "selection",
    "savedPreferences",
    "runSelection",
    "recordedAnimation",
    "readiness",
    "artifacts",
    "checks",
    "errors",
}


@pytest.fixture
def motion_cli_sandbox(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    root = tmp_path / "installation"
    root.mkdir()
    shutil.copytree(ROOT / "schemas", root / "schemas")
    (root / "config").mkdir()
    shutil.copy2(ROOT / "config/avo.config.json", root / "config/avo.config.json")
    providers = root / "providers"
    providers.mkdir()
    shutil.copy2(ROOT / "providers/avo.provider.schema.json", providers)
    raw = tmp_path / "external-video"
    raw.mkdir()
    manifests = {}
    for slug in ("channel-a", "channel-b"):
        destination = providers / slug
        destination.mkdir()
        manifest = destination / "avo.provider.json"
        manifest.write_text(
            json.dumps(build_manifest(slug, "youtube", str(raw))), encoding="utf-8"
        )
        manifests[slug] = manifest
    project = raw / "avo.project.json"
    project.write_text(
        json.dumps(
            {
                "schemaVersion": "1.0.0",
                "provider": "channel-a",
                "videoId": "motion-cli",
                "rawDir": str(raw),
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("AVO_ROOT", str(root))
    return {
        "home": home,
        "root": root,
        "global": home / ".avo/preferences.json",
        "provider": manifests["channel-a"],
        "other_provider": manifests["channel-b"],
        "project": project,
        "raw": raw,
    }


def inspect_result(result, *, operation="engine-show"):
    assert result.exit_code == 0, result.stderr
    assert result.stderr == ""
    body = result.parsed_json
    assert isinstance(body, dict)
    assert set(body) == INSPECTION_KEYS
    assert body["operation"] == operation
    assert body["status"] == "ok"
    assert set(body["selection"]) == {
        "engine",
        "source",
        "advanced",
        "resolutionHash",
        "maskedChoices",
    }
    assert re.fullmatch(r"[a-f0-9]{64}", body["selection"]["resolutionHash"])
    assert set(body["savedPreferences"]) == {"global", "provider", "project"}
    for preference in body["savedPreferences"].values():
        assert set(preference) == {"engine", "target"}
    assert set(body["readiness"]) == {
        "ready",
        "state",
        "checks",
        "blockers",
        "nextActions",
    }
    assert body["artifacts"] == []
    assert body["errors"] == []
    return body


def test_global_show_needs_no_project_and_does_not_write(motion_cli_sandbox):
    box = motion_cli_sandbox
    provider_before = box["provider"].read_bytes()
    body = inspect_result(run_cli(["animation", "engine-show", "--json"]))
    assert body["selection"]["engine"] == "hyperframes"
    assert body["selection"]["source"] == "default"
    assert body["selection"]["advanced"] is False
    assert body["savedPreferences"]["global"]["engine"] is None
    assert Path(body["savedPreferences"]["global"]["target"]) == box["global"]
    assert body["runSelection"] is None
    assert body["recordedAnimation"] is None
    assert not box["global"].exists()
    assert not (box["raw"] / "edit").exists()
    assert box["provider"].read_bytes() == provider_before


def test_show_override_is_advanced_without_saving(motion_cli_sandbox):
    body = inspect_result(
        run_cli(["animation", "engine-show", "--motion-engine", "code-drawn", "--json"])
    )
    assert body["selection"]["engine"] == "code-drawn"
    assert body["selection"]["source"] == "invocation"
    assert body["selection"]["advanced"] is True
    assert body["savedPreferences"]["global"]["engine"] is None
    assert not motion_cli_sandbox["global"].exists()


def test_global_set_can_save_unavailable_remotion(motion_cli_sandbox):
    body = inspect_result(
        run_cli(
            [
                "animation",
                "engine-set",
                "--scope",
                "global",
                "--engine",
                "remotion",
                "--json",
            ]
        ),
        operation="engine-set",
    )
    assert body["selection"]["engine"] == "remotion"
    assert body["selection"]["source"] == "global"
    assert body["readiness"]["ready"] is False
    assert body["readiness"]["state"] in {"unavailable", "unsupported"}
    assert body["readiness"]["nextActions"]
    stored = json.loads(motion_cli_sandbox["global"].read_text(encoding="utf-8"))
    assert stored["motion"]["engine"] == "remotion"
    again = inspect_result(run_cli(["animation", "engine-show", "--json"]))
    assert again["selection"]["engine"] == "remotion"


def test_global_reset_is_idempotent_and_preserves_other_settings(motion_cli_sandbox):
    path = motion_cli_sandbox["global"]
    path.parent.mkdir()
    path.write_text(
        json.dumps(
            {
                "schemaVersion": "1.0.0",
                "motion": {"engine": "code-drawn"},
                "anotherFeature": {"value": 4},
            }
        ),
        encoding="utf-8",
    )
    args = ["animation", "engine-reset", "--scope", "global", "--json"]
    for _ in range(2):
        body = inspect_result(run_cli(args), operation="engine-reset")
        assert body["selection"]["engine"] == "hyperframes"
        assert body["selection"]["source"] == "default"
        assert body["savedPreferences"]["global"]["engine"] is None
    stored = json.loads(path.read_text(encoding="utf-8"))
    assert "engine" not in stored.get("motion", {})
    assert stored["anotherFeature"] == {"value": 4}


@pytest.mark.parametrize("scope", ["provider", "project"])
def test_targeted_scopes_require_their_target(motion_cli_sandbox, scope):
    before = motion_cli_sandbox["provider"].read_bytes()
    result = run_cli(
        [
            "animation",
            "engine-set",
            "--scope",
            scope,
            "--engine",
            "code-drawn",
            "--json",
        ]
    )
    assert result.exit_code == 2
    error = json.loads(result.stderr)
    assert error["code"] in {"MOTION_SCOPE_REQUIRED", "MOTION_TARGET_INVALID"}
    assert result.stdout == ""
    assert motion_cli_sandbox["provider"].read_bytes() == before
    assert not motion_cli_sandbox["global"].exists()


def test_provider_write_and_reset_do_not_change_other_scopes(motion_cli_sandbox):
    box = motion_cli_sandbox
    before = box["other_provider"].read_bytes()
    args = ["--scope", "provider", "--provider", "channel-a", "--json"]
    body = inspect_result(
        run_cli(["animation", "engine-set", *args, "--engine", "code-drawn"]),
        operation="engine-set",
    )
    assert body["selection"]["source"] == "provider"
    assert body["savedPreferences"]["provider"] == {
        "engine": "code-drawn",
        "target": str(box["provider"]),
    }
    stored = json.loads(box["provider"].read_text(encoding="utf-8"))
    assert stored["routingOverrides"]["motion"]["engine"] == "code-drawn"
    reset = inspect_result(
        run_cli(["animation", "engine-reset", *args]), operation="engine-reset"
    )
    assert reset["selection"]["source"] == "default"
    assert box["other_provider"].read_bytes() == before
    assert not box["global"].exists()


def test_project_preference_and_one_run_override_stay_distinct(motion_cli_sandbox):
    box = motion_cli_sandbox
    body = inspect_result(
        run_cli(
            [
                "animation",
                "engine-set",
                "--scope",
                "project",
                "--project",
                str(box["project"]),
                "--engine",
                "code-drawn",
                "--json",
            ]
        ),
        operation="engine-set",
    )
    assert body["selection"]["source"] == "project"
    assert body["savedPreferences"]["project"]["engine"] == "code-drawn"
    before = box["project"].read_bytes()
    override = inspect_result(
        run_cli(
            [
                "animation",
                "engine-show",
                "--project",
                str(box["project"]),
                "--motion-engine",
                "remotion",
                "--json",
            ]
        )
    )
    assert override["selection"]["engine"] == "remotion"
    assert override["selection"]["source"] == "invocation"
    assert override["savedPreferences"]["project"]["engine"] == "code-drawn"
    assert override["runSelection"] is None
    assert box["project"].read_bytes() == before
    assert not (box["raw"] / "edit").exists()


def test_mismatched_provider_and_project_fail_without_writes(motion_cli_sandbox):
    box = motion_cli_sandbox
    before = box["project"].read_bytes()
    result = run_cli(
        [
            "animation",
            "engine-set",
            "--scope",
            "project",
            "--project",
            str(box["project"]),
            "--provider",
            "channel-b",
            "--engine",
            "code-drawn",
            "--json",
        ]
    )
    assert result.exit_code == 2
    assert json.loads(result.stderr)["code"] == "MOTION_TARGET_INVALID"
    assert box["project"].read_bytes() == before
    assert not box["global"].exists()


@pytest.mark.parametrize(
    "engine", ["canvas", "none", "HyperFrames", "no frameworks", ""]
)
def test_native_commands_reject_noncanonical_engine_ids(motion_cli_sandbox, engine):
    result = run_cli(
        ["animation", "engine-set", "--scope", "global", "--engine", engine, "--json"]
    )
    assert result.exit_code == 2
    assert result.stderr
    assert result.stdout == ""
    assert not motion_cli_sandbox["global"].exists()


def test_malformed_global_json_is_an_error_not_default_fallback(motion_cli_sandbox):
    path = motion_cli_sandbox["global"]
    path.parent.mkdir()
    invalid = b'{"motion":'
    path.write_bytes(invalid)
    result = run_cli(["animation", "engine-show", "--json"])
    assert result.exit_code == 2
    assert json.loads(result.stderr)["code"] == "MOTION_CONFIG_INVALID"
    assert result.stdout == ""
    assert path.read_bytes() == invalid


def test_invalid_saved_engine_does_not_fall_through(motion_cli_sandbox):
    path = motion_cli_sandbox["global"]
    path.parent.mkdir()
    path.write_text(
        json.dumps({"schemaVersion": "1.0.0", "motion": {"engine": "canvas"}}),
        encoding="utf-8",
    )
    before = path.read_bytes()
    result = run_cli(["animation", "engine-show", "--json"])
    assert result.exit_code == 2
    assert json.loads(result.stderr)["code"] in {
        "MOTION_ENGINE_INVALID",
        "MOTION_CONFIG_INVALID",
    }
    assert result.stdout == ""
    assert path.read_bytes() == before


@pytest.fixture
def capture_cli_backend(monkeypatch):
    from avo.adapters.motion import code_drawn

    calls = []
    state = {"error": None}

    def execute(operation, *args, **kwargs):
        calls.append((operation, args, kwargs))
        if state["error"] is not None:
            raise state["error"]
        return code_drawn.motion_result(operation)

    class RecordingAdapter:
        def check(self, composition, **kwargs):
            return execute("code-drawn-check", composition, **kwargs)

        def snapshot(self, composition, **kwargs):
            return execute("code-drawn-snapshot", composition, **kwargs)

        def render(self, composition, **kwargs):
            return execute("code-drawn-render", composition, **kwargs)

    monkeypatch.setattr(code_drawn, "CodeDrawnAdapter", RecordingAdapter)
    monkeypatch.setattr(
        code_drawn,
        "install_runtime",
        lambda **kwargs: execute("runtime-install", **kwargs),
    )
    return calls, state


def test_code_drawn_scaffold_is_standalone_and_keeps_exact_targets(
    motion_cli_sandbox, tmp_path
):
    destination = tmp_path / "new animation with spaces"
    result = run_cli(
        [
            "animation",
            "code-drawn-scaffold",
            "--destination",
            str(destination),
            "--route",
            "svg",
            "--width",
            "128",
            "--height",
            "96",
            "--fps",
            "30000/1001",
            "--frames",
            "12",
            "--background",
            "opaque",
            "--background-color",
            "#14202a",
            "--json",
        ]
    )
    assert result.exit_code == 0, result.stderr
    assert result.stderr == ""
    body = result.parsed_json
    assert set(body) == INSPECTION_KEYS
    assert body["status"] == "ok"
    manifest = json.loads(
        (destination / "composition.json").read_text(encoding="utf-8")
    )
    assert manifest["drawingRoute"] == "svg"
    assert manifest["renderContract"]["frameRate"] == {"num": 30000, "den": 1001}
    assert manifest["renderContract"]["frameCount"] == 12
    assert manifest["renderContract"]["background"] == {
        "mode": "opaque",
        "color": "#14202a",
    }
    assert not (motion_cli_sandbox["raw"] / "edit").exists()


@pytest.mark.parametrize("brush", [False, True])
def test_native_runtime_install_dispatches_only_explicit_selected_runtime(
    motion_cli_sandbox, capture_cli_backend, brush
):
    calls, _state = capture_cli_backend
    args = ["animation", "runtime-install", "--engine", "code-drawn", "--json"]
    if brush:
        args.append("--brush")
    result = run_cli(args)
    assert result.exit_code == 0, result.stderr
    assert result.parsed_json["operation"] == "runtime-install"
    assert calls == [("runtime-install", (), {"brush": brush})]


@pytest.mark.parametrize("engine", ["hyperframes", "remotion"])
def test_runtime_install_rejects_other_engines_before_provisioning(
    motion_cli_sandbox, capture_cli_backend, engine
):
    calls, _state = capture_cli_backend
    result = run_cli(["animation", "runtime-install", "--engine", engine, "--json"])
    assert result.exit_code == 2
    assert calls == []
    assert not motion_cli_sandbox["global"].exists()


@pytest.mark.parametrize("operation", ["check", "snapshot", "render"])
def test_native_capture_dispatch_preserves_paths_and_integer_frames(
    motion_cli_sandbox, capture_cli_backend, tmp_path, operation
):
    calls, _state = capture_cli_backend
    composition = tmp_path / "source with spaces" / "composition.json"
    input_lock = tmp_path / "original input-lock.json"
    output = tmp_path / ("frame.png" if operation == "snapshot" else "asset.mkv")
    output_lock = tmp_path / "new input-lock.json"
    args = [
        "animation",
        f"code-drawn-{operation}",
        "--composition",
        str(composition),
        "--input-lock",
        str(input_lock),
        "--json",
    ]
    if operation == "check":
        args += ["--output-lock", str(output_lock)]
        expected = {"input_lock": input_lock, "output_lock": output_lock}
    else:
        args += ["--output", str(output)]
        expected = {"input_lock": input_lock, "output": output}
        if operation == "snapshot":
            args += ["--frame", "11"]
            expected["frame"] = 11
    result = run_cli(args)
    assert result.exit_code == 0, result.stderr
    assert result.stderr == ""
    assert set(result.parsed_json) == INSPECTION_KEYS
    assert result.parsed_json["operation"] == f"code-drawn-{operation}"
    assert calls == [(f"code-drawn-{operation}", (composition,), expected)]
    assert not (motion_cli_sandbox["raw"] / "edit").exists()


@pytest.mark.parametrize(
    ("arguments", "field"),
    [
        (["--composition", "relative.json"], "composition"),
        (
            ["--composition", "{absolute}", "--input-lock", "relative.json"],
            "input_lock",
        ),
        (
            ["--composition", "{absolute}", "--output-lock", "relative.json"],
            "output_lock",
        ),
    ],
)
def test_native_capture_rejects_relative_paths_before_backend(
    motion_cli_sandbox, capture_cli_backend, tmp_path, arguments, field
):
    calls, _state = capture_cli_backend
    absolute = str(tmp_path / "composition.json")
    arguments = [part.replace("{absolute}", absolute) for part in arguments]
    result = run_cli(["animation", "code-drawn-check", *arguments, "--json"])
    assert result.exit_code == 2
    assert result.stdout == ""
    error = json.loads(result.stderr)
    assert error["code"] == "CODE_DRAWN_INPUT_INVALID"
    assert error["field"] == field
    assert calls == []


@pytest.mark.parametrize(
    ("code", "exit_code"),
    [
        ("CODE_DRAWN_RUNTIME_MISSING", 2),
        ("CODE_DRAWN_INPUT_INVALID", 2),
        ("CODE_DRAWN_ASSET_NOT_READY", 2),
        ("CODE_DRAWN_LOCK_STALE", 2),
        ("CODE_DRAWN_RENDER_FAILED", 1),
        ("CODE_DRAWN_OUTPUT_INVALID", 1),
        ("CODE_DRAWN_CANCELLED", 130),
    ],
)
def test_native_capture_preserves_flat_errors_and_exit_semantics(
    motion_cli_sandbox, capture_cli_backend, tmp_path, code, exit_code
):
    from avo.motion import MotionError

    _calls, state = capture_cli_backend
    error = MotionError(
        code,
        "Synthetic transport failure.",
        field="composition",
        remediation="Fix the selected input and retry.",
    )
    state["error"] = error
    result = run_cli(
        [
            "animation",
            "code-drawn-check",
            "--composition",
            str(tmp_path / "composition.json"),
            "--json",
        ]
    )
    assert result.exit_code == exit_code
    assert result.stdout == ""
    assert json.loads(result.stderr) == error.to_dict()


def test_native_capture_interrupt_reports_cancellation(
    motion_cli_sandbox, capture_cli_backend, tmp_path
):
    _calls, state = capture_cli_backend
    state["error"] = KeyboardInterrupt()
    try:
        result = run_cli(
            [
                "animation",
                "code-drawn-check",
                "--composition",
                str(tmp_path / "composition.json"),
                "--json",
            ]
        )
    except KeyboardInterrupt:
        pytest.fail("The native capture boundary leaked its cancellation signal.")
    assert result.exit_code == 130
    assert result.stdout == ""
    assert json.loads(result.stderr)["code"] == "CODE_DRAWN_CANCELLED"


@pytest.mark.parametrize(
    "arguments",
    [
        ["runtime-install"],
        ["code-drawn-scaffold", "--destination", "{destination}"],
        [
            "code-drawn-snapshot",
            "--composition",
            "{composition}",
            "--output",
            "{output}",
        ],
        ["code-drawn-render", "--composition", "{composition}", "--output", "{output}"],
    ],
)
def test_native_capture_requires_each_operation_contract(
    motion_cli_sandbox, capture_cli_backend, tmp_path, arguments
):
    calls, _state = capture_cli_backend
    paths = {
        "{destination}": str(tmp_path / "destination"),
        "{composition}": str(tmp_path / "composition.json"),
        "{output}": str(tmp_path / "output.mkv"),
    }
    arguments = [paths.get(part, part) for part in arguments]
    result = run_cli(["animation", *arguments, "--json"])
    assert result.exit_code == 2
    assert calls == []


def test_installed_cli_prefix_reaches_native_capture_without_new_alias(
    motion_cli_sandbox, capture_cli_backend, tmp_path, capsys
):
    from avo import engine_cli

    calls, _state = capture_cli_backend
    composition = tmp_path / "composition.json"
    exit_code = engine_cli.main(
        [
            "cli",
            "animation",
            "code-drawn-check",
            "--composition",
            str(composition),
            "--json",
        ]
    )
    captured = capsys.readouterr()
    assert exit_code == 0, captured.err
    assert json.loads(captured.out)["operation"] == "code-drawn-check"
    assert calls == [
        ("code-drawn-check", (composition,), {"input_lock": None, "output_lock": None})
    ]


def test_canonical_materialize_command_uses_injected_existing_pipeline_port(
    tmp_path, monkeypatch
):
    from avo.timeline.workspace import TimelineWorkspace

    project = tmp_path / "avo.project.json"
    project.write_text(
        json.dumps({"provider": "test", "rawDir": str(tmp_path)}), encoding="utf-8"
    )
    seen = []

    def materialize(workspace, instance_id, *, output):
        assert isinstance(workspace, TimelineWorkspace)
        seen.append((instance_id, output))
        return {"status": "ok", "operation": "code-drawn-render"}

    monkeypatch.setattr("avo.cli.create_motion_materializer", lambda: materialize)
    output = tmp_path / "edit/derived/new-asset.mkv"
    result = run_cli(
        [
            "animation",
            "materialize",
            "--project",
            str(project),
            "--instance-id",
            "logical-overlay",
            "--output",
            str(output),
            "--json",
        ]
    )
    assert result.exit_code == 0, result.stderr
    assert seen == [("logical-overlay", output)]
    assert not (tmp_path / "edit").exists()


@pytest.mark.parametrize("relative", ["candidate", "receipt", "output"])
def test_native_drawing_review_rejects_relative_paths_before_runtime(
    tmp_path, capture_cli_backend, relative
):
    paths = {name: str(tmp_path / name) for name in ("candidate", "receipt", "output")}
    paths[relative] = "relative-path"
    result = run_cli(
        [
            "animation",
            "code-drawn-review",
            "--candidate",
            paths["candidate"],
            "--source-receipt",
            paths["receipt"],
            "--output",
            paths["output"],
            "--json",
        ]
    )
    assert result.exit_code == 2
    assert json.loads(result.stderr)["code"] == "CODE_DRAWN_INPUT_INVALID"
    assert capture_cli_backend[0] == []


def test_native_drawing_review_missing_source_blocks_before_runtime(
    tmp_path, capture_cli_backend
):
    result = run_cli(
        [
            "animation",
            "code-drawn-review",
            "--candidate",
            str(tmp_path / "candidate.mkv"),
            "--source-receipt",
            str(tmp_path / "absent.generated-asset.json"),
            "--output",
            str(tmp_path / "review"),
            "--json",
        ]
    )
    assert result.exit_code == 2
    assert json.loads(result.stderr)["code"] == "CODE_DRAWN_INPUT_INVALID"
    assert capture_cli_backend[0] == []
    assert not (tmp_path / "review").exists()


def test_canonical_review_rejects_same_id_substituted_receipt(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from avo.cli import _review_drawing_sources
    from avo.motion import MotionError
    from avo.timeline.generated_assets import GeneratedAssetService
    from tests.code_drawn_asset_fixture import canonical_asset, reseal_record

    asset = canonical_asset(tmp_path)
    GeneratedAssetService(asset.workspace).register(
        asset.record, code_drawn_environment=asset.environment
    )
    supplied = dict(asset.record)
    supplied["role"] = "authored-graphic"
    supplied = reseal_record(supplied)
    receipt = asset.workspace.raw_dir / "substitute.generated-asset.json"
    receipt.write_text(json.dumps(supplied), encoding="utf-8")
    monkeypatch.setattr(
        "avo.adapters.motion.code_drawn.CodeDrawnAdapter.check",
        lambda *args, **kwargs: {
            "checks": [{"evidence": {"environment": asset.environment}}]
        },
    )
    with pytest.raises(MotionError, match="receipt|registered|admitted"):
        _review_drawing_sources(
            SimpleNamespace(source_receipt=[receipt]), asset.workspace
        )
