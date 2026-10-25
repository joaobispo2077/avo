import json

import pytest

from avo.timeline.store import StoreError
from avo.timeline.workspace import TimelineWorkspace, WorkspaceError
from tests.test_briefstart_context import project_fixture


def broken_history():
    raise WorkspaceError("optional provider history is unavailable")


def test_initialization_reports_history_metadata_without_dumping_old_source_bodies(
    tmp_path, monkeypatch
):
    workspace = TimelineWorkspace.from_project(project_fixture(tmp_path))
    monkeypatch.setattr(
        workspace,
        "finalized_provider_learning",
        lambda: [
            {
                "snapshotId": "old",
                "snapshotHash": "a" * 64,
                "privateBody": "Unicode minus: \u2212",
            }
        ],
    )
    result = workspace.initialize()["providerLearning"]
    assert result["loadedFinalSnapshots"] == 1
    assert "snapshots" not in result
    assert "privateBody" not in str(result)


@pytest.mark.parametrize("index", [[], {"snapshots": ["bad"], "activeSnapshotId": "x"}])
def test_optional_history_with_valid_json_bad_shape_still_reports_unknown(
    tmp_path, index
):
    project = project_fixture(tmp_path)
    history = tmp_path / "history/old/timeline-learning"
    history.mkdir(parents=True)
    (history / "index.json").write_text(json.dumps(index), encoding="utf8")
    workspace = TimelineWorkspace.from_project(project)
    workspace.project["providerLearningDirectory"] = str(tmp_path / "history")
    assert workspace.initialize()["providerLearning"]["status"] == "unavailable"
    with pytest.raises(WorkspaceError):
        workspace.finalized_provider_learning()


def test_optional_learning_status_keeps_unknown_count_and_strict_reader(
    tmp_path, monkeypatch
):
    workspace = TimelineWorkspace.from_project(project_fixture(tmp_path))
    monkeypatch.setattr(workspace, "finalized_provider_learning", broken_history)
    result = workspace.initialize()
    assert result["providerLearning"]["status"] == "unavailable"
    assert result["providerLearning"]["loadedFinalSnapshots"] is None
    assert result["providerLearning"]["warnings"]
    with pytest.raises(WorkspaceError):
        workspace.finalized_provider_learning()


def test_required_current_timeline_corruption_stays_blocking(tmp_path):
    workspace = TimelineWorkspace.from_project(project_fixture(tmp_path))
    workspace.initialize()
    workspace.artifact_path("cmap").write_text("{}", encoding="utf8")
    with pytest.raises(StoreError):
        workspace.validate()


def test_proof_preflight_warns_for_history_but_keeps_current_media_blocker(tmp_path):
    from avo.timeline.proof_plan import ProofPlanCompiler
    from tests.test_proof_plan import (
        proof_request,
        registry,
        regression_contract,
        workspace_with_heads,
    )

    workspace = workspace_with_heads(tmp_path)
    workspace.finalized_provider_learning = broken_history
    compiler = ProofPlanCompiler(workspace, registry())
    plan = compiler.compile(
        proof_request(tmp_path), regression_contract=regression_contract()
    )
    report = compiler.preflight(
        plan,
        media_inputs={},
        tool_readiness={"proof-plan-executor": True, "ffmpeg": True},
    )
    assert report["providerLearning"]["status"] == "unavailable"
    assert report["providerLearning"]["loadedFinalSnapshots"] is None
    assert "PROOF_MEDIA_MISSING" in {item["code"] for item in report["blockers"]}
