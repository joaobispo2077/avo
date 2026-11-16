"""Selected concepts and recovery inputs survive cleanup without review caches."""

import json
from copy import deepcopy

import pytest

from avo.timeline.contracts import content_hash
from avo.timeline.motion_authoring import MotionAuthoringService
from avo.timeline.store import atomic_write_json
from avo.timeline.workspace import TimelineWorkspace
from tests.test_motion_authoring import propose, request, select


def selected_workspace(tmp_path):
    project = tmp_path / "avo.project.json"
    project.write_text(
        json.dumps(
            {"provider": "example", "videoId": "retention", "rawDir": str(tmp_path)}
        ),
        encoding="utf-8",
    )
    workspace = TimelineWorkspace.from_project(project)
    workspace.initialize()
    proposed, value = propose(workspace)
    selected = select(workspace, proposed)
    return workspace, proposed, selected, value


def test_selected_predecessors_and_operation_evidence_are_exact_but_reports_disposable(
    tmp_path,
):
    from avo.timeline.motion_retention import retained_motion_paths
    from avo.timeline.reconstruction import _required_files

    workspace, original, _, value = selected_workspace(tmp_path)
    revised = deepcopy(value)
    revised["operationId"] = "concept-second"
    revised["proposal"]["predecessor"] = original["proposalRef"]["sha256"]
    revised["proposal"]["items"][0]["concept"] = "Hold comparison"
    current = MotionAuthoringService(workspace).propose(revised)
    MotionAuthoringService(workspace).select(
        request(
            workspace,
            "plan-select",
            "select-second",
            selection={
                "proposalHash": current["proposalRef"]["sha256"],
                "dispositions": [
                    {"itemId": "mo04", "status": "selected", "reason": "Use revision"}
                ],
            },
        )
    )
    paths = set(retained_motion_paths(workspace))
    assert workspace.raw_dir / original["proposalRef"]["path"] in paths
    assert workspace.raw_dir / current["proposalRef"]["path"] in paths
    assert workspace.pipeline_run_path in paths
    assert any(path.parent.name == "operations" for path in paths)
    assert not any(
        path.is_relative_to(workspace.raw_dir / "edit/review/motion-plan")
        for path in paths
    )
    unrelated = deepcopy(value)
    unrelated["operationId"] = "unselected-other"
    unrelated["proposal"]["items"][0]["concept"] = "Other option"
    other = MotionAuthoringService(workspace).propose(unrelated)
    assert workspace.raw_dir / other["proposalRef"]["path"] not in set(
        retained_motion_paths(workspace)
    )
    required = _required_files(workspace.raw_dir, [], workspace=workspace)
    assert paths <= set(required)
    assert workspace.raw_dir / other["proposalRef"]["path"] not in required
    assert not any(
        path.is_relative_to(workspace.raw_dir / "edit/review/motion-plan")
        for path in required
    )


@pytest.mark.parametrize("kind", ["proposalRef", "decisionRef"])
def test_selected_missing_or_changed_evidence_fails_closed(tmp_path, kind):
    from avo.timeline.motion_retention import (
        MotionRetentionError,
        retained_motion_paths,
    )
    from avo.timeline.reconstruction import ReconstructionError, _required_files

    workspace, proposed, selected, _ = selected_workspace(tmp_path)
    reference = proposed[kind] if kind == "proposalRef" else selected[kind]
    (workspace.raw_dir / reference["path"]).write_text("{}", encoding="utf-8")
    with pytest.raises(MotionRetentionError):
        retained_motion_paths(workspace)
    with pytest.raises(ReconstructionError):
        _required_files(workspace.raw_dir, [], workspace=workspace)


def test_operation_evidence_cannot_change_the_frozen_request(tmp_path):
    from avo.timeline.motion_retention import (
        MotionRetentionError,
        retained_motion_paths,
    )

    workspace, _, _, value = selected_workspace(tmp_path)
    path = (
        workspace.raw_dir
        / "edit/motion/operations"
        / (content_hash(["plan-propose", value["operationId"]]) + ".json")
    )
    operation = json.loads(path.read_text(encoding="utf-8"))
    operation["request"]["reason"] = "Changed authority"
    atomic_write_json(path, operation)
    with pytest.raises(MotionRetentionError, match="request|identity|hash"):
        retained_motion_paths(workspace)


def test_default_retention_does_not_initialize_or_discover_unselected_drafts(tmp_path):
    from avo.timeline.motion_retention import retained_motion_paths

    project = tmp_path / "avo.project.json"
    project.write_text(
        json.dumps(
            {"provider": "example", "videoId": "empty", "rawDir": str(tmp_path)}
        ),
        encoding="utf-8",
    )
    workspace = TimelineWorkspace.from_project(project)
    before = set(tmp_path.rglob("*"))
    assert retained_motion_paths(workspace) == []
    assert set(tmp_path.rglob("*")) == before


def test_legacy_unclaimed_metadata_stays_preserved_without_becoming_canonical(tmp_path):
    from avo.timeline.motion_retention import retained_motion_paths
    from avo.timeline.store import StoreError

    project = tmp_path / "avo.project.json"
    project.write_text(
        json.dumps(
            {"provider": "example", "videoId": "legacy", "rawDir": str(tmp_path)}
        ),
        encoding="utf-8",
    )
    workspace = TimelineWorkspace.from_project(project)
    path = workspace.timeline_dir / "cmap.json"
    path.parent.mkdir(parents=True)
    path.write_text("{}", encoding="utf-8")
    before = {item: item.read_bytes() for item in tmp_path.rglob("*") if item.is_file()}
    assert path in retained_motion_paths(workspace)
    assert {item: item.read_bytes() for item in before} == before
    with pytest.raises(StoreError):
        workspace.store("cmap").load_index()


def test_a_claimed_head_cannot_use_the_legacy_metadata_exception(tmp_path):
    from avo.timeline.motion_retention import (
        MotionRetentionError,
        retained_motion_paths,
    )

    workspace, _, _, _ = selected_workspace(tmp_path)
    path = workspace.timeline_dir / "cmap.json"
    atomic_write_json(path, {"headRevisionId": "cmap-r001"})
    with pytest.raises(MotionRetentionError):
        retained_motion_paths(workspace)


def test_canonical_motion_evidence_remains_required_without_a_run_record(tmp_path):
    from avo.timeline.motion_retention import (
        MotionRetentionError,
        retained_motion_paths,
    )

    workspace, proposed, _, _ = selected_workspace(tmp_path)
    reference = proposed["proposalRef"]
    workspace.store("bmap").append_revision(
        snapshot={"fixture": "retained canonical reference"},
        actor="fixture",
        reason="Recorded motion authority",
        evidence=[
            {
                "evidenceId": "motion-proposal:" + reference["sha256"],
                "kind": "motion-proposal",
                **reference,
            }
        ],
    )
    workspace.pipeline_run_path.unlink()
    (workspace.raw_dir / reference["path"]).unlink()
    with pytest.raises(MotionRetentionError):
        retained_motion_paths(workspace)


def test_cleanup_fallback_uses_verified_selected_closure(tmp_path):
    from avo.project_inventory import _fallback_reconstruction_metadata
    from avo.timeline.motion_retention import retained_motion_paths

    workspace, _, selected, _ = selected_workspace(tmp_path)
    expected = set(retained_motion_paths(workspace))
    assert expected <= set(
        _fallback_reconstruction_metadata(
            workspace.raw_dir, workspace.timeline_dir, workspace
        )
    )
    (workspace.raw_dir / selected["decisionRef"]["path"]).unlink()
    with pytest.raises((ValueError, RuntimeError)):
        _fallback_reconstruction_metadata(
            workspace.raw_dir, workspace.timeline_dir, workspace
        )


def test_metadata_retention_has_bounded_evidence_budget(tmp_path, monkeypatch):
    import avo.timeline.motion_retention as retention

    workspace, _, _, _ = selected_workspace(tmp_path)
    monkeypatch.setattr(retention, "MAX_TOTAL_BYTES", 10)
    with pytest.raises(retention.MotionRetentionError, match="budget"):
        retention.retained_motion_paths(workspace)


def test_selected_reference_spelling_cannot_alias_a_different_locator(tmp_path):
    from avo.timeline.motion_retention import (
        MotionRetentionError,
        retained_motion_paths,
    )

    workspace, _, _, _ = selected_workspace(tmp_path)
    run = json.loads(workspace.pipeline_run_path.read_text(encoding="utf-8"))
    reference = run["extensions"]["motionProposalSelection"]["proposalRef"]
    reference["path"] = reference["path"].replace("proposals/", "proposals/./")
    atomic_write_json(workspace.pipeline_run_path, run)
    with pytest.raises(MotionRetentionError, match="exact typed"):
        retained_motion_paths(workspace)


def test_valid_revision_body_cannot_be_substituted_under_another_reference(tmp_path):
    from avo.timeline.motion_retention import (
        MotionRetentionError,
        retained_motion_paths,
    )

    workspace, _, _, _ = selected_workspace(tmp_path)
    store = workspace.store("bmap")
    for value in ("first", "second"):
        store.append_revision(
            snapshot={"fixture": value}, actor="fixture", reason="Metadata identity"
        )
    index = store.load_index()
    index["revisionRefs"][0]["path"] = index["revisionRefs"][1]["path"]
    atomic_write_json(store.path, index)
    with pytest.raises(MotionRetentionError, match="reference identity"):
        retained_motion_paths(workspace)


def test_bundle_fingerprinting_binds_previously_verified_evidence_bytes(
    tmp_path, monkeypatch
):
    from avo.timeline import reconstruction
    from avo.timeline.motion_retention import retained_motion_files

    workspace, _, selected, _ = selected_workspace(tmp_path)
    verified = retained_motion_files(workspace)
    monkeypatch.setattr(
        reconstruction, "_motion_evidence_files", lambda workspace: verified
    )
    (workspace.raw_dir / selected["decisionRef"]["path"]).write_text(
        "{}", encoding="utf-8"
    )
    with pytest.raises(reconstruction.ReconstructionError, match="fingerprint changed"):
        reconstruction._required_entries(workspace.raw_dir, [], workspace=workspace)


def test_selected_direction_retains_exact_choice_brief_and_frozen_sources(tmp_path):
    from avo.timeline.motion_retention import (
        MotionRetentionError,
        retained_motion_paths,
    )
    from tests.test_briefstart_context import selected_project

    project, _, _, _ = selected_project(tmp_path)
    workspace = TimelineWorkspace.from_project(project)
    proposed, _ = propose(workspace)
    select(workspace, proposed)
    direction = workspace.raw_dir / proposed["proposal"]["directionRef"]["path"]
    selection = json.loads(direction.read_text(encoding="utf-8"))
    root = workspace.raw_dir / "edit/briefstart"
    refs = [selection["briefRef"], selection["decisionRef"], *selection["sourceRefs"]]
    assert {root / ref["path"] for ref in refs} <= set(retained_motion_paths(workspace))
    (root / selection["sourceRefs"][0]["path"]).unlink()
    with pytest.raises(MotionRetentionError):
        retained_motion_paths(workspace)


def test_pending_receipt_retains_exact_prepared_recovery_without_approving(tmp_path):
    from avo.timeline.motion_retention import retained_motion_paths
    from avo.timeline.store import timeline_writer
    from tests.integration.test_motion_authoring_flow import prepared_request
    from tests.test_timeline_bmap_service import approved_workspace

    workspace, _, _ = approved_workspace(tmp_path)
    value = prepared_request(workspace)
    service = MotionAuthoringService(workspace)
    with timeline_writer(workspace.timeline_dir):
        receipt = service._prepare(value, service.show())
        reference = service._save_receipt(value, receipt)
        marker = {
            "operationId": value["operationId"],
            "requestHash": content_hash(value),
        }
        atomic_write_json(
            workspace.timeline_dir / "motion-application.pending.json", marker
        )
    before = {
        path: path.read_bytes()
        for path in workspace.raw_dir.rglob("*")
        if path.is_file()
    }
    paths = set(retained_motion_paths(workspace))
    assert workspace.raw_dir / reference["path"] in paths
    assert workspace.raw_dir / receipt["requestRef"]["path"] in paths
    assert workspace.timeline_dir / "motion-application.pending.json" in paths
    assert {path: path.read_bytes() for path in before} == before
