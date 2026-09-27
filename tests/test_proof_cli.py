from __future__ import annotations

import json

from avo.cli import build_parser, main


def _project(tmp_path):
    path = tmp_path / "avo.project.json"
    path.write_text(
        json.dumps({"provider": "bishop", "videoId": "video", "rawDir": str(tmp_path)}),
        encoding="utf-8",
    )
    return path


def test_proof_command_family_parses_all_contract_operations(tmp_path):
    project = _project(tmp_path)
    request = tmp_path / "request.json"
    request.write_text("{}", encoding="utf-8")
    parser = build_parser()
    requests = {
        "iteration-record": ["--request", str(request)],
        "component-scaffold": ["--request", str(request)],
        "component-register": ["--request", str(request)],
        "plan": [
            "--iteration-id",
            "iteration-0001",
            "--output",
            str(tmp_path / "proof.mp4"),
            "--profile",
            "draft",
        ],
        "microproof": ["--proof-plan", "proof-plan-123456789abc"],
        "build": ["--proof-plan", "proof-plan-123456789abc"],
        "validate": ["--proof-plan", "proof-plan-123456789abc"],
        "status": [],
    }
    for operation, extra in requests.items():
        args = parser.parse_args(
            ["proof", operation, "--project", str(project), *extra]
        )
        assert args.command == "proof"
        assert args.proof_command == operation


def test_missing_build_plan_returns_stable_structured_error(tmp_path, capsys):
    project = _project(tmp_path)
    exit_code = main(
        [
            "proof",
            "build",
            "--project",
            str(project),
            "--proof-plan",
            "proof-plan-123456789abc",
        ]
    )
    assert exit_code == 3
    error = json.loads(capsys.readouterr().err)
    assert error["code"] == "PROOF_PLAN_NOT_FOUND"
    assert error["blocking"] is True


def test_status_and_project_local_scaffold_are_operational(tmp_path, capsys):
    project = _project(tmp_path)
    assert main(["proof", "status", "--project", str(project)]) == 0
    status = json.loads(capsys.readouterr().out)
    assert status["status"] == "no-proof-plan-selected"

    request = tmp_path / "scaffold.json"
    request.write_text(
        json.dumps(
            {
                "componentId": "custom-title-card",
                "capabilityGap": {"status": "unsupported"},
            }
        ),
        encoding="utf-8",
    )
    assert (
        main(
            [
                "proof",
                "component-scaffold",
                "--project",
                str(project),
                "--request",
                str(request),
            ]
        )
        == 0
    )
    result = json.loads(capsys.readouterr().out)
    assert result["manifest"]["ownership"] == "project-local"
