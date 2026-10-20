"""Briefstart CLI preserves exact project scope and selection."""

import json

from avo import cli
from tests.test_briefstart import context, reference
from tests.test_briefstart_context import project_fixture, selected_project
from tests.test_direction_cli import emitted


def write_inputs(tmp_path):
    context_path = tmp_path / "context.json"
    reference_path = tmp_path / "reference.json"
    context_path.write_text(json.dumps(context()))
    reference_path.write_text(json.dumps(reference()))
    return context_path, reference_path


def test_cli_none_requires_no_provider_history_or_new_directory(tmp_path, capsys):
    project = project_fixture(tmp_path)
    assert (
        cli.main(
            [
                "briefstart",
                "prepare",
                "--project",
                str(project),
                "--direction",
                "none",
                "--json",
            ]
        )
        == 0
    )
    assert emitted(capsys)["status"] == "bypassed"
    assert not (project.parent / "edit/briefstart").exists()


def test_cli_reuses_typed_context_and_reference(tmp_path, capsys):
    project = project_fixture(tmp_path)
    context_path, reference_path = write_inputs(tmp_path)
    assert (
        cli.main(
            [
                "briefstart",
                "prepare",
                "--project",
                str(project),
                "--direction",
                "references",
                "--context",
                str(context_path),
                "--reference",
                str(reference_path),
                "--json",
            ]
        )
        == 0
    )
    value = emitted(capsys)
    assert value["status"] == "needs-authoring"
    assert value["refs"]["packet"]["documentHash"]
    assert value["expectedIndexHash"] == "absent"
    assert not (project.parent / "edit/briefstart/index.json").exists()


def test_cli_show_projects_exact_selected_brief_without_new_acceptance(
    tmp_path, capsys
):
    project, _service, brief_ref, _ = selected_project(tmp_path)
    before = (project.parent / "edit/briefstart/index.json").read_bytes()
    assert cli.main(["briefstart", "show", "--project", str(project), "--json"]) == 0
    value = emitted(capsys)
    assert value["status"] == "selected"
    assert value["refs"]["brief"] == brief_ref
    assert (project.parent / "edit/briefstart/index.json").read_bytes() == before


def test_cli_bad_project_decision_has_no_provider_authority(tmp_path, capsys):
    project, _, _, _ = selected_project(tmp_path)
    request_path = tmp_path / "wrong-scope.json"
    request_path.write_text(json.dumps({"scope": "provider", "action": "accept"}))
    before = (project.parent / "edit/briefstart/index.json").read_bytes()
    assert (
        cli.main(
            [
                "briefstart",
                "decide",
                "--project",
                str(project),
                "--request",
                str(request_path),
                "--json",
            ]
        )
        == 2
    )
    assert emitted(capsys)["status"] == "invalid-request"
    assert (project.parent / "edit/briefstart/index.json").read_bytes() == before
