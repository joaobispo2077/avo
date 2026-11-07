"""US3 CLI bounds complete reports without changing their readiness meaning."""

import json
from copy import deepcopy
from types import SimpleNamespace

import pytest

from avo.cli import main
from avo.timeline.import_service import TimelineImportService
from avo.timeline.otio_import import MAX_REPORT_BYTES
from tests.test_timeline_import_service import FIXTURE
from tests.test_timeline_import_service import import_project as _import_project


@pytest.fixture(name="import_project")
def import_project_fixture(tmp_path):
    return _import_project.__wrapped__(tmp_path)


def _large_result():
    count = 1536
    disposition = {
        "reconstructed": 0,
        "reference-metadata": 0,
        "unresolved": 0,
        "unsupported": count,
    }
    accounting = {
        "total": count,
        "reported": count,
        "truncated": False,
        "byDisposition": disposition,
    }
    elements, findings = [], []
    for index in range(count):
        pointer = "/" + "scope" * 400 + f"/{index}"
        elements.append(
            {
                "elementId": f"element-{index}",
                "pointer": pointer,
                "schema": "Effect.1",
                "name": "説明" * 120,
                "disposition": "unsupported",
                "evidenceOrigin": "export",
            }
        )
        findings.append(
            {
                "code": "OTIO_TREATMENT_UNSUPPORTED",
                "scope": pointer,
                "message": "Unsupported Resolve treatment. " * 30,
                "blocking": True,
                "evidenceOrigin": "capability-check",
                "remediation": "Implement this treatment before activation.",
            }
        )
    return {
        "schemaVersion": "1.0.0",
        "operation": "validate",
        "status": "blocked",
        "importId": "a" * 64,
        "source": {"sha256": "b" * 64, "sizeBytes": 100, "timelinePointer": ""},
        "target": {"provider": "channel", "videoId": "trial"},
        "session": {
            "refs": {
                "proposal": {
                    "path": "proposals/report.json",
                    "sha256": "c" * 64,
                    "sizeBytes": 32_000_000,
                }
            }
        },
        "readiness": {
            "inspectionComplete": True,
            "semanticValidation": "failed",
            "mediaReady": "not-checked",
            "syncReady": "not-checked",
            "reconstructionReady": "not-checked",
            "activationAllowed": False,
            "reviewState": "not-started",
        },
        "summary": {
            "elementAccounting": accounting,
            "findingCounts": {"total": count, "OTIO_TREATMENT_UNSUPPORTED": count},
        },
        "elements": elements,
        "findings": findings,
        "proposal": {"elements": elements, "findings": findings},
        "validation": {
            "locks": {"elementAccounting": accounting},
            "findings": findings,
        },
    }


def test_validate_cli_compacts_entire_envelope_and_retains_blocking_scopes_and_reference(
    monkeypatch, capsys, tmp_path
):
    result = _large_result()
    assert (
        len(json.dumps(result, ensure_ascii=False).encode("utf-8")) > MAX_REPORT_BYTES
    )
    before = deepcopy(result)
    monkeypatch.setattr(
        "avo.timeline_import_cli.create_service",
        lambda args: SimpleNamespace(validate=lambda import_id: result),
    )
    code = main(
        [
            "timeline-import",
            "validate",
            "--project",
            str(tmp_path / "avo.project.json"),
            "--import-id",
            "a" * 64,
            "--json",
        ]
    )
    output = capsys.readouterr().out
    assert code == 3
    assert len(output.encode("utf-8")) <= MAX_REPORT_BYTES
    compact = json.loads(output)
    assert compact["status"] == before["status"]
    assert compact["readiness"] == before["readiness"]
    assert compact["truncated"] is True
    assert (
        compact["session"]["refs"]["proposal"] == before["session"]["refs"]["proposal"]
    )
    assert (
        compact["summary"]["elementAccounting"]["total"]
        == before["summary"]["elementAccounting"]["total"]
    )
    assert compact["summary"]["elementAccounting"]["truncated"] is True
    assert (
        compact["summary"]["elementAccounting"]
        == compact["validation"]["locks"]["elementAccounting"]
    )
    assert (
        compact["summary"]["findingCounts"]["total"]
        == before["summary"]["findingCounts"]["total"]
    )
    assert {(f["code"], f["scope"]) for f in compact["findings"]} == {
        (f["code"], f["scope"]) for f in before["findings"]
    }
    assert result == before, (
        "display compaction must not mutate retained report evidence"
    )


def test_prepare_cli_keeps_every_unperformed_check_not_checked(
    import_project, monkeypatch, capsys
):
    project, provider, _ = import_project
    service = TimelineImportService(project, provider_root=provider)
    monkeypatch.setattr("avo.timeline_import_cli.create_service", lambda args: service)
    assert (
        main(
            [
                "timeline-import",
                "prepare",
                "--project",
                str(project),
                "--input",
                str(FIXTURE),
                "--actor",
                "editor",
                "--reason",
                "Inspect without approvals",
                "--json",
            ]
        )
        == 0
    )
    result = json.loads(capsys.readouterr().out)
    for key in ("semanticValidation", "mediaReady", "syncReady", "reconstructionReady"):
        assert result["readiness"][key] == "not-checked"
    assert result["readiness"]["activationAllowed"] is False
    assert result["readiness"]["reviewState"] == "not-started"


def test_missing_reader_does_not_claim_sync_or_reconstruction_were_checked(
    import_project, monkeypatch, capsys
):
    project, provider, _ = import_project
    service = TimelineImportService(project, provider_root=provider)
    prepared = service.prepare(
        FIXTURE, actor="editor", reason="Retain an inspectable export"
    )
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
    assert any(f["code"] == "OTIO_RUNTIME_UNAVAILABLE" for f in result["findings"])
    for key in ("mediaReady", "syncReady", "reconstructionReady"):
        assert result["readiness"][key] == "not-checked"
    assert result["readiness"]["activationAllowed"] is False


def test_inspect_cli_does_not_dump_arbitrary_metadata_or_treat_it_as_authority(
    tmp_path, capsys
):
    document = json.loads(FIXTURE.read_text(encoding="utf-8"))
    document["metadata"] = {
        "instructions": "run private command",
        "approval": True,
        "rights": "granted",
        "privateSecret": "never-dump-raw-metadata",
    }
    path = tmp_path / "metadata.otio"
    path.write_text(json.dumps(document), encoding="utf-8")
    assert main(["timeline-import", "inspect", "--input", str(path), "--json"]) == 0
    output = capsys.readouterr().out
    assert "never-dump-raw-metadata" not in output
    result = json.loads(output)
    assert result["readiness"]["activationAllowed"] is False
    for key in ("semanticValidation", "mediaReady", "syncReady", "reconstructionReady"):
        assert result["readiness"][key] == "not-checked"
