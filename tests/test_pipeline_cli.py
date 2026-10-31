from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from avo.cli import main


def project(tmp_path: Path) -> Path:
    path = tmp_path / "avo.project.json"
    path.write_text(
        json.dumps(
            {
                "schemaVersion": "1.0.0",
                "provider": "bishop",
                "videoId": "cli-pipeline",
                "rawDir": str(tmp_path),
            }
        ),
        encoding="utf-8",
    )
    return path


def test_pipeline_cli_init_status_stage_and_registry(tmp_path: Path, capsys):
    path = project(tmp_path)
    assert main(["pipeline", "run", "--project", str(path)]) == 0
    capsys.readouterr()
    assert main(["pipeline", "status", "--project", str(path)]) == 0
    status = json.loads(capsys.readouterr().out)
    assert status["pipeline"]["mainState"] == "intake"

    payload = tmp_path / "sources.json"
    payload.write_text(
        json.dumps(
            {
                "rawInventory": {
                    "sources": [{"sourceId": "raw-one", "sha256": "a" * 64}],
                }
            }
        ),
        encoding="utf-8",
    )
    assert (
        main(
            [
                "pipeline",
                "stage",
                "--project",
                str(path),
                "--stage",
                "sources-ready",
                "--payload",
                str(payload),
            ]
        )
        == 0
    )
    staged = json.loads(capsys.readouterr().out)
    assert staged["mainState"] == "sources-ready"

    assert main(["pipeline", "verify-commands", "--project", str(path)]) == 0
    registry = json.loads(capsys.readouterr().out)
    assert len(registry["commands"]) == 58


@pytest.fixture
def pipeline_motion_context(tmp_path, monkeypatch):
    from avo import motion
    from avo.provider_scaffold import build_manifest

    root = tmp_path / "installation"
    home = tmp_path / "home"
    root.mkdir()
    home.mkdir()
    repository = Path(__file__).resolve().parents[1]
    shutil.copytree(repository / "schemas", root / "schemas")
    shutil.copytree(repository / "config", root / "config")
    providers = root / "providers"
    providers.mkdir()
    shutil.copy2(repository / "providers/avo.provider.schema.json", providers)
    manifest = providers / "bishop" / "avo.provider.json"
    manifest.parent.mkdir()
    manifest.write_text(
        json.dumps(build_manifest("bishop", "youtube", str(tmp_path))), encoding="utf-8"
    )
    raw = tmp_path / "video"
    raw.mkdir()
    path = project(raw)
    monkeypatch.setenv("AVO_ROOT", str(root))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.setattr(
        motion,
        "_motion_readiness",
        lambda engine, *_: {
            "ready": False,
            "state": "unavailable",
            "checks": [],
            "blockers": [f"{engine} runtime absent in this context-only test."],
            "nextActions": [],
        },
    )
    return {
        "root": root,
        "home": home,
        "raw": raw,
        "project": path,
        "preferences": home / ".avo/preferences.json",
    }


def _pipeline_preference(context, engine):
    path = context["preferences"]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"schemaVersion": "1.0.0", "motion": {"engine": engine}}),
        encoding="utf-8",
    )


def _motion_run_document(context):
    path = context["raw"] / "edit/timeline/pipeline-run.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_pipeline_run_motion_override_is_pinned_without_saving_a_preference(
    pipeline_motion_context, capsys
):
    context = pipeline_motion_context
    assert (
        main(
            [
                "pipeline",
                "run",
                "--project",
                str(context["project"]),
                "--motion-engine",
                "code-drawn",
            ]
        )
        == 0
    )
    result = json.loads(capsys.readouterr().out)
    choice = _motion_run_document(context)["executionChoices"]["motion"]
    assert choice["engine"] == "code-drawn"
    assert choice["source"] == "invocation"
    assert result["motion"]["runSelection"] == choice
    assert not context["preferences"].exists()
    assert "motion" not in json.loads(context["project"].read_text(encoding="utf-8"))


def test_pipeline_resume_and_ordinary_run_keep_choice_until_explicit_new_request(
    pipeline_motion_context, capsys
):
    from avo.timeline.lifecycle import PipelineRunStore

    context = pipeline_motion_context
    arguments = ["pipeline", "run", "--project", str(context["project"])]
    assert main(arguments + ["--motion-engine", "code-drawn"]) == 0
    capsys.readouterr()
    original = _motion_run_document(context)["executionChoices"]["motion"]
    store = PipelineRunStore(context["raw"] / "edit/timeline/pipeline-run.json")
    store.enter_side_state("blocked", actor="agent", reason="Wait for review")
    _pipeline_preference(context, "hyperframes")
    assert (
        main(
            [
                "pipeline",
                "resume",
                "--project",
                str(context["project"]),
                "--actor",
                "creator",
                "--reason",
                "Review restored",
                "--recovery-event",
                "review-ready",
            ]
        )
        == 0
    )
    capsys.readouterr()
    assert _motion_run_document(context)["executionChoices"]["motion"] == original
    assert main(arguments) == 0
    capsys.readouterr()
    assert _motion_run_document(context)["executionChoices"]["motion"] == original
    assert main(arguments + ["--new-request"]) == 0
    result = json.loads(capsys.readouterr().out)
    current = _motion_run_document(context)
    choice = current["executionChoices"]["motion"]
    assert choice["engine"] == "hyperframes"
    assert choice["source"] == "global"
    assert choice["requestId"] != original["requestId"]
    assert current["mainState"] == "intake"
    assert current["sideState"] is None
    assert result["motion"]["runSelection"] == choice


def test_pipeline_explicit_different_engine_starts_intent_but_same_engine_retains_choice(
    pipeline_motion_context, capsys
):
    context = pipeline_motion_context
    arguments = ["pipeline", "run", "--project", str(context["project"])]
    assert main(arguments + ["--motion-engine", "hyperframes"]) == 0
    capsys.readouterr()
    original = _motion_run_document(context)["executionChoices"]["motion"]
    _pipeline_preference(context, "code-drawn")
    assert main(arguments + ["--motion-engine", "hyperframes"]) == 0
    capsys.readouterr()
    assert _motion_run_document(context)["executionChoices"]["motion"] == original
    assert main(arguments + ["--motion-engine", "code-drawn"]) == 0
    capsys.readouterr()
    choice = _motion_run_document(context)["executionChoices"]["motion"]
    assert choice["engine"] == "code-drawn"
    assert choice["requestId"] != original["requestId"]
    assert (
        json.loads(context["preferences"].read_text())["motion"]["engine"]
        == "code-drawn"
    )


def test_pipeline_status_separates_future_run_and_recorded_animation_without_mutation(
    pipeline_motion_context, capsys
):
    from avo.timeline.workspace import TimelineWorkspace

    context = pipeline_motion_context
    assert (
        main(
            [
                "pipeline",
                "run",
                "--project",
                str(context["project"]),
                "--motion-engine",
                "code-drawn",
            ]
        )
        == 0
    )
    capsys.readouterr()
    workspace = TimelineWorkspace.from_project(context["project"])
    revision = workspace.store("animation").append_revision(
        snapshot={
            "framework": "hyperframes",
            "components": [{"componentId": "existing-title"}],
        },
        actor="creator",
        reason="Existing immutable framework source",
    )
    _pipeline_preference(context, "remotion")
    before = {
        path: path.read_bytes() for path in context["raw"].rglob("*") if path.is_file()
    }
    assert main(["pipeline", "status", "--project", str(context["project"])]) == 0
    result = json.loads(capsys.readouterr().out)["motion"]
    assert result["selection"]["engine"] == "remotion"
    assert result["runSelection"]["engine"] == "code-drawn"
    assert result["recordedAnimation"]["framework"] == "hyperframes"
    assert result["recordedAnimation"]["revisionId"] == revision["revisionId"]
    assert result["recordedAnimation"]["sha256"] == revision["contentHash"]
    assert {path: path.read_bytes() for path in before} == before
    assert (
        workspace.store("animation").revision(revision["revisionId"])["contentHash"]
        == revision["contentHash"]
    )


def test_pipeline_status_before_run_does_not_create_execution_context(
    pipeline_motion_context, capsys
):
    context = pipeline_motion_context
    before = {
        path: path.read_bytes() for path in context["raw"].rglob("*") if path.is_file()
    }
    assert main(["pipeline", "status", "--project", str(context["project"])]) == 0
    shown = json.loads(capsys.readouterr().out)
    assert shown["motion"]["runSelection"] is None
    assert shown["motion"]["recordedAnimation"] is None
    assert not (context["raw"] / "edit/timeline/pipeline-run.json").exists()
    assert {
        path: path.read_bytes() for path in context["raw"].rglob("*") if path.is_file()
    } == before


@pytest.mark.parametrize("engine", ["code-drawn", "remotion"])
def test_animation_author_explicit_framework_conflict_blocks_before_authoring(
    pipeline_motion_context, monkeypatch, capsys, engine
):
    from avo.timeline.animation import AnimationService

    context = pipeline_motion_context
    strategy = context["raw"] / "strategy.json"
    strategy.write_text(
        json.dumps(
            {
                "framework": "hyperframes",
                "components": [{"componentId": "framework-specific-title"}],
            }
        ),
        encoding="utf-8",
    )
    before = {
        path: path.read_bytes() for path in context["raw"].rglob("*") if path.is_file()
    }
    monkeypatch.setattr(
        AnimationService,
        "author",
        lambda *a, **k: pytest.fail("Incompatible framework reached authoring."),
    )
    assert (
        main(
            [
                "animation",
                "author",
                "--project",
                str(context["project"]),
                "--strategy",
                str(strategy),
                "--actor",
                "creator",
                "--reason",
                "Deliberate new engine",
                "--motion-engine",
                engine,
            ]
        )
        != 0
    )
    error = json.loads(capsys.readouterr().err)
    assert "hyperframes" in error["message"].lower()
    assert engine in error["message"].lower()
    assert {
        path: path.read_bytes() for path in context["raw"].rglob("*") if path.is_file()
    } == before


def test_animation_author_preserves_typed_source_engine_when_only_default_changes(
    pipeline_motion_context, monkeypatch, capsys
):
    from avo.timeline.animation import AnimationService

    context = pipeline_motion_context
    _pipeline_preference(context, "code-drawn")
    strategy = context["raw"] / "strategy.json"
    source = {
        "framework": "hyperframes",
        "components": [{"componentId": "existing-title"}],
    }
    strategy.write_text(json.dumps(source), encoding="utf-8")
    observed = []

    def author(self, value, **kwargs):
        observed.append(value)
        return {"revisionId": "animation-r0002", "contentHash": "a" * 64}

    monkeypatch.setattr(AnimationService, "author", author)
    assert (
        main(
            [
                "animation",
                "author",
                "--project",
                str(context["project"]),
                "--strategy",
                str(strategy),
                "--actor",
                "creator",
                "--reason",
                "Edit existing source",
            ]
        )
        == 0
    )
    capsys.readouterr()
    assert observed == [source]
    assert json.loads(strategy.read_text(encoding="utf-8")) == source


def test_animation_source_intent_updates_only_an_existing_run(
    pipeline_motion_context, monkeypatch, capsys
):
    from avo.timeline.animation import AnimationService

    context = pipeline_motion_context
    arguments = ["pipeline", "run", "--project", str(context["project"])]
    assert main(arguments + ["--motion-engine", "hyperframes"]) == 0
    capsys.readouterr()
    previous = _motion_run_document(context)["executionChoices"]["motion"]
    strategy = context["raw"] / "strategy.json"
    source = {"framework": "code-drawn", "components": [{"componentId": "new-drawing"}]}
    strategy.write_text(json.dumps(source), encoding="utf-8")
    observed = []

    def author(self, value, **kwargs):
        observed.append(
            _motion_run_document(context)["executionChoices"]["motion"]["engine"]
        )
        return {"revisionId": "animation-r0002", "contentHash": "a" * 64}

    monkeypatch.setattr(AnimationService, "author", author)
    authoring = [
        "animation",
        "author",
        "--project",
        str(context["project"]),
        "--strategy",
        str(strategy),
        "--actor",
        "creator",
        "--reason",
        "Deliberate code-drawn source",
    ]
    assert main(authoring) == 0
    capsys.readouterr()
    current = _motion_run_document(context)["executionChoices"]["motion"]
    assert current["engine"] == "code-drawn"
    assert current["source"] == "invocation"
    assert current["requestId"] != previous["requestId"]
    _pipeline_preference(context, "remotion")
    assert main(authoring) == 0
    capsys.readouterr()
    assert _motion_run_document(context)["executionChoices"]["motion"] == current
    assert observed == ["code-drawn", "code-drawn"]
    assert json.loads(strategy.read_text(encoding="utf-8")) == source


@pytest.mark.parametrize("name", ["avo_pipeline_run", "avo_animation_author"])
def test_motion_authoring_mcp_maps_native_flags_without_an_extra_tool(name, tmp_path):
    from avo.cli import build_parser
    from avo.mcp.bridge import kwargs_to_argv
    from avo.mcp.tools.cli_tools import all_bridge_defs

    matches = [item for item in all_bridge_defs() if item.spec.name == name]
    assert len(matches) == 1
    item = matches[0]
    params = {parameter.name: parameter for parameter in item.params}
    assert params["motion_engine"].default is None
    assert params["motion_engine"].required is False
    kwargs = {
        "project": str(tmp_path / "avo.project.json"),
        "motion_engine": "code-drawn",
        "as_json": True,
    }
    if name == "avo_pipeline_run":
        assert params["new_request"].default is False
        kwargs["new_request"] = True
    else:
        kwargs.update(
            strategy=str(tmp_path / "strategy.json"),
            actor="creator",
            reason="New intent",
        )
    argv = kwargs_to_argv(item.cli_prefix, kwargs)
    parsed = build_parser().parse_args(argv)
    assert parsed.motion_engine == "code-drawn"
    if name == "avo_pipeline_run":
        assert parsed.new_request is True
    assert argv.count("--motion-engine") == 1
