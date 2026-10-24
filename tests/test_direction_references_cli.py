import json

from avo.cli import main
from tests.test_briefstart import context, reference
from tests.test_briefstart_context import project_fixture


def test_native_reference_boundary_freezes_descriptions_without_opening_locator(
    tmp_path, capsys
):
    project = project_fixture(tmp_path)
    info = tmp_path / "context.json"
    descriptor = tmp_path / "reference.json"
    info.write_text(json.dumps(context()), encoding="utf8")
    descriptor.write_text(
        json.dumps(
            {**reference(), "locator": "https://invalid.example/never-fetch.mp4"}
        ),
        encoding="utf8",
    )
    assert (
        main(
            [
                "briefstart",
                "prepare",
                "--project",
                str(project),
                "--direction",
                "references",
                "--context",
                str(info),
                "--reference",
                str(descriptor),
                "--json",
            ]
        )
        == 0
    )
    result = json.loads(capsys.readouterr().out)
    packet = json.loads(
        (
            project.parent / "edit/briefstart" / result["refs"]["packet"]["path"]
        ).read_text()
    )
    assert packet["sources"][0]["kind"] == "reference"
    assert packet["sources"][0]["document"]["observationKind"] == "user-described"
    assert packet["sources"][0]["document"]["description"] == reference()["description"]
    assert result["status"] == "needs-authoring"


def test_actual_cli_exposes_subset_and_refresh_inputs():
    from avo.cli import build_parser

    parsed = build_parser().parse_args(
        [
            "direction",
            "prepare",
            "--provider",
            "neutral",
            "--profile-id",
            "analysis",
            "--entry",
            "project-a",
            "--entry",
            "project-b",
            "--refresh-from",
            "analysis@r0001",
        ]
    )
    assert parsed.entry == ["project-a", "project-b"]
    assert parsed.refresh_from == "analysis@r0001"
