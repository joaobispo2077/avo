"""The convenience import route stages through the shared service only."""

import json
from types import SimpleNamespace

import pytest

from avo import cli, timeline_import_cli
from avo.timeline.pipeline import TimelinePipeline
from tests.test_timeline_import_service import import_project as _project


@pytest.fixture(name="project_context")
def project_fixture(tmp_path):
    return _project.__wrapped__(tmp_path)


def test_pipeline_import_bypasses_new_edit_engine_briefing_and_cost_setup(
    project_context, tmp_path, monkeypatch, capsys
):
    project, _, _ = project_context
    maps, declarations = tmp_path / "maps.json", tmp_path / "declarations.json"
    maps.write_text('{"/reference": {"path": "original.mov"}}')
    declarations.write_text('{"sourceOnly": true}')
    export = tmp_path / "timeline.otio"
    export.write_text("{}")
    service = SimpleNamespace()
    calls = []
    monkeypatch.setattr(timeline_import_cli, "create_service", lambda args: service)
    monkeypatch.setattr(
        cli,
        "_initialize_pipeline_run",
        lambda *_: pytest.fail("ordinary initialization called"),
    )

    def prepare(self, received, path, **kwargs):
        calls.append((received, path, kwargs))
        return {
            "status": "awaiting-sync",
            "operation": "validate",
            "importId": "a" * 64,
            "readiness": {"activationAllowed": False},
            "findings": [],
            "nextAction": "Establish current Sync",
        }

    monkeypatch.setattr(
        TimelinePipeline, "prepare_timeline_import", prepare, raising=False
    )
    code = cli.main(
        [
            "pipeline",
            "run",
            "--project",
            str(project),
            "--timeline-import",
            str(export),
            "--import-mappings",
            str(maps),
            "--import-declarations",
            str(declarations),
            "--import-media-root",
            str(tmp_path),
            "--actor",
            "editor",
            "--reason",
            "Continue Resolve edit",
        ]
    )
    assert code == 3
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "awaiting-sync"
    assert calls[0][0] is service and calls[0][1] == export
    assert calls[0][2]["mappings"] == json.loads(maps.read_text())
    assert calls[0][2]["declarations"] == {"sourceOnly": True}
    assert calls[0][2]["media_roots"] == [tmp_path]
    assert not (project.parent / "edit/timeline/pipeline-run.json").exists()


@pytest.mark.parametrize(
    "flag,extra",
    [
        ("--motion-engine", "code-drawn"),
        ("--direction", "new edit"),
        ("--new-request", None),
    ],
)
def test_import_rejects_unrelated_new_authoring_options_before_setup(
    project_context, monkeypatch, capsys, flag, extra
):
    project, _, _ = project_context
    monkeypatch.setattr(
        cli, "_initialize_pipeline_run", lambda *_: pytest.fail("ordinary setup called")
    )
    monkeypatch.setattr(
        timeline_import_cli,
        "create_service",
        lambda *_: pytest.fail("import staged before options checked"),
    )
    args = [
        "pipeline",
        "run",
        "--project",
        str(project),
        "--timeline-import",
        "input.otio",
        flag,
    ]
    if extra is not None:
        args.append(extra)
    assert cli.main(args) == 3
    assert "OTIO_INPUT_INVALID" in capsys.readouterr().err


def test_import_options_without_export_do_not_fall_through_to_ordinary_run(
    project_context, monkeypatch, capsys
):
    project, _, _ = project_context
    monkeypatch.setattr(
        cli, "_initialize_pipeline_run", lambda *_: pytest.fail("ordinary setup called")
    )
    assert (
        cli.main(
            [
                "pipeline",
                "run",
                "--project",
                str(project),
                "--import-declarations",
                "settings.json",
            ]
        )
        == 3
    )
    assert "OTIO_INPUT_INVALID" in capsys.readouterr().err
