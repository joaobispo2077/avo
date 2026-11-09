"""Explicit prior-content return uses the same native service and exact selection."""

import json
from unittest.mock import Mock

import pytest

from avo.cli import build_parser, main


def test_return_cli_delegates_exact_activation_head_actor_and_reason(
    tmp_path, monkeypatch, capsys
):
    service = Mock()
    service.rollback.return_value = {
        "schemaVersion": "1.0.0",
        "operation": "rollback",
        "status": "active-draft",
        "revision": {"revisionId": "new-return-draft"},
    }
    monkeypatch.setattr("avo.timeline_import_cli.create_service", lambda args: service)
    project = tmp_path / "avo.project.json"
    assert (
        main(
            [
                "timeline-import",
                "rollback",
                "--project",
                str(project),
                "--activation-id",
                "a" * 64,
                "--expected-head",
                "b" * 64,
                "--actor",
                "editor",
                "--reason",
                "Return prior content",
                "--json",
            ]
        )
        == 0
    )
    service.rollback.assert_called_once_with(
        "a" * 64, expected_head="b" * 64, actor="editor", reason="Return prior content"
    )
    assert (
        json.loads(capsys.readouterr().out)["revision"]["revisionId"]
        == "new-return-draft"
    )


@pytest.mark.parametrize(
    "missing", ["--activation-id", "--expected-head", "--actor", "--reason"]
)
def test_return_parser_requires_explicit_selection_and_attribution(missing):
    options = {
        "--project": "project.json",
        "--activation-id": "a" * 64,
        "--expected-head": "b" * 64,
        "--actor": "editor",
        "--reason": "Return",
    }
    args = ["timeline-import", "rollback"]
    for flag, value in options.items():
        if flag != missing:
            args.extend((flag, value))
    with pytest.raises(SystemExit) as error:
        build_parser().parse_args(args)
    assert error.value.code == 2
