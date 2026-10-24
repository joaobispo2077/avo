import json

import pytest
from tests.test_briefstart import context
from tests.test_briefstart_context import project_fixture, selected_project

from avo.cli import main
from avo.direction.brief import BriefService
from avo.timeline.pipeline import TimelinePipeline
from avo.timeline.workspace import TimelineWorkspace


@pytest.mark.parametrize(
    "selector",
    [
        "none",
        "builtin:analysis-review@1.0.0",
        "builtin:step-by-step@1.0.0",
        "builtin:narrative-conversation@1.0.0",
        "builtin:focused-short@1.0.0",
    ],
)
def test_native_entry_keeps_creative_preparation_optional(tmp_path, capsys, selector):
    project = project_fixture(tmp_path)
    source = tmp_path / "context.json"
    source.write_text(json.dumps(context()), encoding="utf8")
    assert (
        main(
            [
                "pipeline",
                "run",
                "--project",
                str(project),
                "--direction",
                selector,
                "--brief-context",
                str(source),
            ]
        )
        == 0
    )
    result = json.loads(capsys.readouterr().out)
    expected = "bypassed" if selector == "none" else "needs-authoring"
    assert result["briefingPreparation"]["status"] == expected
    assert result["pipeline"]["mainState"] == "intake"
    assert result["briefing"]["status"] == "bypassed"
    assert not (project.parent / "edit/briefstart/index.json").exists()


def test_bound_provider_brief_reopens_offline_with_exact_canonical_head_identity(
    tmp_path,
):
    project, _, brief_ref, _ = selected_project(tmp_path, provider_mode=True)
    workspace = TimelineWorkspace.from_project(project)
    workspace.initialize()
    revision = workspace.store("cmap").append_revision(
        snapshot={"neutral": True}, actor="test", reason="synthetic source"
    )
    pipeline = TimelinePipeline(workspace)
    context = pipeline.authoring_context("cmap")["context"]
    assert context["canonicalHeads"]["cmap"] == revision["contentHash"]
    assert context["briefRef"] == brief_ref
    assert BriefService(project).prepare()["refs"]["brief"] == brief_ref
