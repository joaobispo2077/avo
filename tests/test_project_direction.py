import json

import pytest

from avo.cli import build_parser
from avo.init_project import build_project
from avo.timeline.contracts import ContractError, validate_document


def test_optional_project_direction_is_typed_and_does_not_grant_approval():
    base = {"provider": "neutral", "rawDir": "/raw"}
    validate_document(base, "avo.project.schema.json")
    direction = {
        "selector": "builtin:analysis-review@1.0.0",
        "contextFile": "edit/briefstart/inputs/context.json",
        "referenceFiles": [],
    }
    validate_document({**base, "direction": direction}, "avo.project.schema.json")
    with pytest.raises(ContractError):
        validate_document(
            {**base, "direction": {**direction, "approved": True}},
            "avo.project.schema.json",
        )
    project = build_project("neutral", "/raw", direction_settings=direction)
    assert project["direction"] == direction


@pytest.mark.parametrize(
    "selector",
    [
        "latest",
        "provider:editorial",
        "builtin:analysis-review",
        "builtin:analysis-review@latest",
    ],
)
def test_initial_direction_must_have_exact_version_or_explicit_bypass(selector):
    with pytest.raises(ContractError):
        validate_document(
            {
                "provider": "neutral",
                "rawDir": "/raw",
                "direction": {"selector": selector},
            },
            "avo.project.schema.json",
        )


def test_pipeline_flags_are_optional_and_descriptors_remain_paths():
    parser = build_parser()
    old = parser.parse_args(["pipeline", "run", "--project", "project.json"])
    assert old.direction is None
    new = parser.parse_args(
        [
            "pipeline",
            "run",
            "--project",
            "project.json",
            "--direction",
            "references",
            "--brief-context",
            "context.json",
            "--direction-reference",
            "ref.json",
        ]
    )
    assert new.direction == "references"
    assert str(new.direction_reference[0]) == "ref.json"


def test_pipeline_direction_errors_use_the_same_structured_status(tmp_path, capsys):
    from avo.cli import main
    from tests.test_briefstart_context import project_fixture

    project = project_fixture(tmp_path)
    assert (
        main(["pipeline", "run", "--project", str(project), "--direction", "latest"])
        == 2
    )
    result = json.loads(capsys.readouterr().err)
    assert result["status"] == "invalid-request"
    assert not (project.parent / "edit").exists()
