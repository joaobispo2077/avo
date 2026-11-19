"""Untimed motion concepts retain exact creator choices and stable identity."""

import json
from copy import deepcopy

import pytest

from avo.editing_craft import resolve_editing_craft_selection
from avo.timeline.contracts import content_hash
from avo.timeline.motion_authoring import MotionAuthoringError, MotionAuthoringService
from avo.timeline.motion_review import MotionReviewService
from avo.timeline.store import atomic_write_json
from avo.timeline.workspace import TimelineWorkspace


@pytest.fixture
def workspace(tmp_path):
    project = tmp_path / "avo.project.json"
    project.write_text(
        json.dumps(
            {"provider": "example", "videoId": "motion-plan", "rawDir": str(tmp_path)}
        )
    )
    return TimelineWorkspace.from_project(project)


def heads(workspace):
    return MotionReviewService(workspace).project()["basisHeads"]


def item(identity="mo04", concept="Hold presenter"):
    return {
        "itemId": identity,
        "label": identity,
        "sectionId": "opening",
        "concept": concept,
        "purpose": "Explain the spoken comparison",
        "treatment": "static",
        "density": 0,
        "dominantFocus": "Presenter",
        "cueId": "cue-one",
        "layerIds": ["base-video", "dialogue"],
        "componentIds": ["chapter-pair"],
    }


def request(workspace, operation, operation_id, **fields):
    return {
        "contractVersion": "1.0.0",
        "operation": operation,
        "operationId": operation_id,
        "actor": "creator",
        "reason": "Review this explanation",
        "expectedBasis": heads(workspace),
        **fields,
    }


def propose(workspace, **proposal):
    value = request(
        workspace,
        "plan-propose",
        "concept-first",
        selection=resolve_editing_craft_selection(),
        proposal={"items": [item()], **proposal},
    )
    return MotionAuthoringService(workspace).propose(value), value


def select(workspace, proposed):
    return MotionAuthoringService(workspace).select(
        request(
            workspace,
            "plan-select",
            "select-first",
            selection={
                "proposalHash": proposed["proposalRef"]["sha256"],
                "dispositions": [
                    {
                        "itemId": "mo04",
                        "status": "selected",
                        "reason": "Use this concept",
                    }
                ],
            },
        )
    )


def test_constructor_and_unselected_show_are_read_only(workspace):
    before = sorted(workspace.raw_dir.rglob("*"))
    shown = MotionAuthoringService(workspace).show()
    assert shown["status"] == "unselected"
    assert shown["proposal"] is None
    assert sorted(workspace.raw_dir.rglob("*")) == before


def test_propose_before_cut_is_untimed_and_idempotent(workspace):
    result, value = propose(workspace)
    again = MotionAuthoringService(workspace).propose(value)
    assert result["proposalRef"] == again["proposalRef"]
    assert result["proposal"]["items"][0]["treatment"] == "static"
    assert result["proposal"]["basisHeads"] == dict.fromkeys(
        ("cmap", "bmap", "tracks", "animation", "sync-map")
    )
    assert not workspace.artifact_path("cmap").exists()
    assert not workspace.artifact_path("bmap").exists()


@pytest.mark.parametrize(
    "mutation", ["timing", "unknown", "duplicates", "operation-conflict"]
)
def test_invalid_proposals_never_become_authorial_history(workspace, mutation):
    _, value = propose(workspace)
    changed = deepcopy(value)
    if mutation == "timing":
        changed["proposal"]["items"][0]["startTicks"] = 100
    elif mutation == "unknown":
        changed["proposal"]["items"][0]["shell"] = "execute"
    elif mutation == "duplicates":
        changed["proposal"]["items"].append(item())
    else:
        changed["proposal"]["items"][0]["concept"] = (
            "Different intent for the same operation"
        )
    before = {
        str(path): path.read_bytes()
        for path in workspace.raw_dir.rglob("*")
        if path.is_file()
    }
    with pytest.raises(MotionAuthoringError):
        MotionAuthoringService(workspace).propose(changed)
    assert {
        str(path): path.read_bytes()
        for path in workspace.raw_dir.rglob("*")
        if path.is_file()
    } == before


def test_select_retains_exact_proposal_and_actual_disposition_across_restart(workspace):
    proposed, _ = propose(workspace)
    selected = select(workspace, proposed)
    shown = MotionAuthoringService(workspace).show()
    assert shown["proposalRef"] == proposed["proposalRef"]
    assert shown["decisionRef"] == selected["decisionRef"]
    assert shown["decision"]["dispositions"][0]["status"] == "selected"
    assert not workspace.artifact_path("bmap").exists()


def test_concept_revisions_keep_aliases_and_show_differences(workspace):
    previous, value = propose(workspace)
    revised = deepcopy(value)
    revised["operationId"] = "concept-revision"
    revised["proposal"]["predecessor"] = previous["proposalRef"]["sha256"]
    revised["proposal"]["items"][0]["concept"] = "Use the existing screen demonstration"
    result = MotionAuthoringService(workspace).propose(revised)
    assert result["proposal"]["items"][0]["label"] == "mo04"
    assert result["changes"][0]["itemId"] == "mo04"
    assert result["changes"][0]["before"]["concept"] == "Hold presenter"


def test_frozen_request_cannot_be_retargeted_by_future_preferences(workspace):
    _, value = propose(workspace)
    changed = deepcopy(value)
    changed["operationId"] = "future-preferences"
    changed["selection"] = resolve_editing_craft_selection(
        invocation={"camera": {"enabled": True}}
    )
    result = MotionAuthoringService(workspace).propose(changed)
    assert result["proposal"]["options"]["effective"]["camera"]["enabled"] is False


def test_selected_show_rejects_tampered_contained_metadata(workspace):
    proposed, _ = propose(workspace)
    select(workspace, proposed)
    path = workspace.raw_dir / proposed["proposalRef"]["path"]
    path.write_text("{}")
    with pytest.raises(MotionAuthoringError):
        MotionAuthoringService(workspace).show()


def test_presentation_failure_keeps_successful_proposal(workspace, monkeypatch):
    def unavailable(*args, **kwargs):
        raise OSError("Review location temporarily unavailable")

    monkeypatch.setattr(MotionReviewService, "publish", unavailable)
    result, _ = propose(workspace)
    assert result["status"] == "proposed"
    assert result["reviewReady"] is False
    assert (workspace.raw_dir / result["proposalRef"]["path"]).exists()
    assert "temporarily unavailable" in result["warnings"][0]


def test_selected_direction_context_is_frozen_and_hybrid_static_choices_remain(
    tmp_path,
):
    from tests.test_briefstart_context import selected_project

    project, brief, _, _ = selected_project(tmp_path)
    current = TimelineWorkspace.from_project(project)
    proposed, value = propose(current)
    select(current, proposed)
    context = MotionAuthoringService.review_context(proposed)
    assert context["direction"]["optionId"] == "quiet"
    assert "No decorative SFX" in context["direction"]["exclusions"]
    revised = deepcopy(value)
    revised["operationId"] = "hybrid-revision"
    revised["proposal"]["predecessor"] = proposed["proposalRef"]["sha256"]
    revised["proposal"]["items"].append(
        {**item("mo07"), "sectionId": "evidence", "soundIntent": "none"}
    )
    result = MotionAuthoringService(current).propose(revised)
    assert result["proposal"]["direction"] == proposed["proposal"]["direction"]
    assert result["proposal"]["items"][1]["soundIntent"] == "none"
    assert result["proposal"]["items"][0]["treatment"] == "static"
    assert brief.stage_context("motion")["context"]["optionId"] == "quiet"


def test_scoped_concept_revision_inherits_only_unchanged_choices(workspace):
    proposed, value = propose(workspace, items=[item(), item("mo07")])
    service = MotionAuthoringService(workspace)
    service.select(
        request(
            workspace,
            "plan-select",
            "both-selected",
            selection={
                "proposalHash": proposed["proposalRef"]["sha256"],
                "dispositions": [
                    {"itemId": identity, "status": "selected", "reason": "Use this"}
                    for identity in ("mo04", "mo07")
                ],
            },
        )
    )
    revised = deepcopy(value)
    revised["operationId"] = "scoped-revision"
    revised["proposal"]["predecessor"] = proposed["proposalRef"]["sha256"]
    revised["proposal"]["items"][0]["concept"] = "Read the evidence"
    changed = service.propose(revised)
    selection = service.select(
        request(
            workspace,
            "plan-select",
            "scoped-selection",
            selection={
                "proposalHash": changed["proposalRef"]["sha256"],
                "dispositions": [
                    {
                        "itemId": "mo04",
                        "status": "rejected",
                        "reason": "Keep original delivery",
                    }
                ],
            },
        )
    )
    assert {
        entry["itemId"]: entry["status"]
        for entry in selection["decision"]["dispositions"]
    } == {"mo04": "rejected", "mo07": "selected"}


def test_repeated_motion_is_an_advisory_and_never_changes_choices(workspace):
    result, _ = propose(
        workspace,
        items=[
            {**item(identity), "treatment": "progressive-reveal"}
            for identity in ("mo04", "mo07", "mo09")
        ],
    )
    assert result["advisories"][0]["code"] == "motion-repetition"
    assert len(result["proposal"]["items"]) == 3
    assert all(
        entry["treatment"] == "progressive-reveal"
        for entry in result["proposal"]["items"]
    )


def test_section_direction_supports_evidence_overlays_and_readable_holds(workspace):
    layouts = (
        "full-frame",
        "transparent-overlay",
        "lateral-overlay",
        "footage-emphasis",
    )
    items = [
        {
            **item(f"mo{index:02}"),
            "sectionId": section,
            "layout": {
                "mode": layout,
                "placement": "Preserve presenter and captions",
                "grouping": "One comparison per reading group",
            },
            "readingIntent": "Hold until the comparison is readable",
            "depthIntent": "Separate evidence and explanation without inventing importance",
            "continuityIntent": "Carry the same evidence identifier between sections",
            "anchors": {
                "sourceId": "original-comparison",
                "description": "Original evidence, not decorative stock",
            },
            "soundIntent": "none",
        }
        for index, (section, layout) in enumerate(
            zip(
                ("opening", "demonstration", "comparison", "conclusion"),
                layouts,
                strict=True,
            ),
            start=1,
        )
    ]
    result, _ = propose(workspace, items=items)
    assert [entry["layout"]["mode"] for entry in result["proposal"]["items"]] == list(
        layouts
    )
    assert all(
        entry["treatment"] == "static" and entry["soundIntent"] == "none"
        for entry in result["proposal"]["items"]
    )
    assert not workspace.artifact_path("animation").exists()


def test_switching_option_in_same_brief_stales_plan_without_retargeting_it(tmp_path):
    from tests.test_briefstart_context import selected_project

    project, brief, brief_ref, selection = selected_project(tmp_path)
    current = TimelineWorkspace.from_project(project)
    proposed, _ = propose(current)
    select(current, proposed)
    brief.decide(
        {
            "requestId": "another-option",
            "targetRef": brief_ref,
            "expectedIndexHash": selection["expectedIndexHash"],
            "action": "select",
            "scope": "project",
            "actor": {"type": "human", "id": "neutral-creator"},
            "reason": "Change visual comparison",
            "humanInstruction": {"source": "session:new-choice", "text": "Use compare"},
            "optionId": "compare",
        }
    )
    shown = MotionAuthoringService(current).show()
    assert shown["status"] == "stale"
    assert (
        MotionAuthoringService.review_context(shown)["direction"]["optionId"] == "quiet"
    )


@pytest.mark.parametrize(
    "tamper", ["saved-request", "operation-id", "swapped-result", "rehashed-request"]
)
def test_operation_records_bind_actual_request_and_immutable_result(workspace, tamper):
    service = MotionAuthoringService(workspace)
    proposed, value = propose(workspace)
    select(workspace, proposed)
    path = service._operation_path(value)
    record = json.loads(path.read_text())
    if tamper == "swapped-result":
        other = deepcopy(value)
        other["operationId"] = "another-immutable-result"
        other["proposal"]["items"][0]["concept"] = "Different concept"
        record["resultRef"] = service.propose(other)["proposalRef"]
    elif tamper == "operation-id":
        record["operationId"] = "different-operation"
    else:
        record["request"]["reason"] = "Changed authorial request"
        if tamper == "rehashed-request":
            record["requestHash"] = content_hash(record["request"])
    atomic_write_json(path, record)
    with pytest.raises(MotionAuthoringError):
        service.show() if tamper == "rehashed-request" else service.propose(value)
