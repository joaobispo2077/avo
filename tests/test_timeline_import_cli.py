from __future__ import annotations

import json
from pathlib import Path

import pytest

from avo.cli import main
from avo.timeline.import_service import TimelineImportService
from tests.test_timeline_import_service import import_project as _project_fixture

FIXTURE = Path(__file__).parent / "fixtures/otio/clip-v1.otio"


@pytest.fixture
def import_project(tmp_path):
    return _project_fixture.__wrapped__(tmp_path)


def test_inspect_cli_without_project_or_native_dependency(capsys):
    assert main(["timeline-import", "inspect", "--input", str(FIXTURE), "--json"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["operation"] == "inspect"
    assert result["status"] == "inspected"
    assert result["readiness"]["activationAllowed"] is False


@pytest.mark.parametrize("flag", ["--mappings", "--declarations"])
def test_missing_repair_document_is_scoped_json_error(
    import_project, tmp_path, monkeypatch, capsys, flag
):
    project, provider, _ = import_project
    service = TimelineImportService(project, provider_root=provider)
    monkeypatch.setattr("avo.timeline_import_cli.create_service", lambda args: service)
    path = tmp_path / "missing.json"
    assert (
        main(
            [
                "timeline-import",
                "prepare",
                "--project",
                str(project),
                "--input",
                str(FIXTURE),
                flag,
                str(path),
                "--actor",
                "editor",
                "--reason",
                "Relink originals",
                "--json",
            ]
        )
        == 3
    )
    error = json.loads(capsys.readouterr().err)
    assert error["code"] == "OTIO_INPUT_INVALID"
    assert error["scope"] == str(path)
    assert not service.root.exists()


def test_inspect_cli_invalid_input_is_json_error(tmp_path, capsys):
    path = tmp_path / "invalid.otio"
    path.write_text("{")
    assert main(["timeline-import", "inspect", "--input", str(path)]) == 3
    error = json.loads(capsys.readouterr().err)
    assert error["code"] == "OTIO_INPUT_INVALID"
    assert error["remediation"]


def test_optional_project_context_does_not_initialize(tmp_path, capsys):
    project = tmp_path / "avo.project.json"
    project.write_text(json.dumps({"provider": "neutral", "rawDir": str(tmp_path)}))
    assert (
        main(
            [
                "timeline-import",
                "inspect",
                "--input",
                str(FIXTURE),
                "--project",
                str(project),
            ]
        )
        == 0
    )
    result = json.loads(capsys.readouterr().out)
    assert result["target"]["provider"] == "neutral"
    assert not (tmp_path / "edit").exists()


def test_prepare_cli_stages_without_native_read_or_activation(
    import_project, monkeypatch, capsys
):
    project, provider, original = import_project
    monkeypatch.setattr(
        "avo.timeline_import_cli.create_service",
        lambda args: TimelineImportService(args.project, provider_root=provider),
    )
    assert (
        main(
            [
                "timeline-import",
                "prepare",
                "--input",
                str(FIXTURE),
                "--project",
                str(project),
                "--media-root",
                str(original.parent),
                "--actor",
                "editor",
                "--reason",
                "Try export",
                "--json",
            ]
        )
        == 0
    )
    result = json.loads(capsys.readouterr().out)
    assert result["operation"] == "prepare"
    assert result["status"] == "prepared"
    assert result["readiness"]["semanticValidation"] == "not-checked"
    assert not (project.parent / "edit/timeline/cmap.json").exists()
    assert (
        main(
            [
                "timeline-import",
                "status",
                "--project",
                str(project),
                "--import-id",
                result["importId"],
                "--json",
            ]
        )
        == 0
    )
    status = json.loads(capsys.readouterr().out)
    assert status["status"] == "prepared"


def test_cli_validation_reports_missing_native_port_as_unperformed(
    import_project, monkeypatch, capsys
):
    project, provider, _ = import_project
    service = TimelineImportService(project, provider_root=provider)
    prepared = service.prepare(FIXTURE, actor="editor", reason="Try export")
    monkeypatch.setattr("avo.timeline_import_cli.create_service", lambda args: service)
    assert (
        main(
            [
                "timeline-import",
                "validate",
                "--project",
                str(project),
                "--import-id",
                prepared["importId"],
                "--json",
            ]
        )
        == 3
    )
    result = json.loads(capsys.readouterr().out)
    assert result["findings"][0]["code"] == "OTIO_RUNTIME_UNAVAILABLE"
    assert result["readiness"]["mediaReady"] == "not-checked"
