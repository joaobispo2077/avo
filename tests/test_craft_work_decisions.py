"""Explicit queue decisions preserve requests, canonical edits and actual completion."""

from copy import deepcopy

import pytest

from avo.timeline.contracts import content_hash
from avo.timeline.pipeline import TimelinePipeline
from avo.timeline.sound_planning import SoundPlanningService
from tests.integration.test_editing_craft_resume import fresh_map
from tests.test_sound_application import application
from tests.test_sound_proposals import prepared


def pending(tmp_path, *, two_events=False):
    workspace, catalogue, request = prepared(tmp_path)
    if two_events:
        second = deepcopy(request["intents"][0])
        second["eventId"] = "second-event"
        request["intents"].append(second)
    service = SoundPlanningService(workspace, catalogue=catalogue)
    service.propose(request)
    return workspace, service, request, fresh_map(workspace)["pendingRevisions"][0]


def decision(row, status, *, operation_id="work-first", replacement=None):
    value = {
        "contractVersion": "1.0.0",
        "operation": "work-decide",
        "operationId": operation_id,
        "actor": "creator",
        "reason": "Keep this production request explicit",
        "work": {
            key: deepcopy(row[key])
            for key in ("kind", "operationId", "requestId", "proposalRef", "scope")
        },
        "ids": row["scope"]["eventIds"]
        if row["kind"] == "sound"
        else row["scope"]["itemIds"],
        "status": status,
        "expectedDecisionHash": row.get("decisionHead"),
    }
    if replacement is not None:
        value["replacement"] = {
            key: deepcopy(replacement[key]) for key in value["work"]
        }
    return value


def decide(workspace, request):
    from avo.timeline.craft_work import decide_craft_work

    return decide_craft_work(workspace, request)


def test_defer_reopen_and_dismiss_survive_restart_without_granting_completion(tmp_path):
    workspace, _, _, row = pending(tmp_path)
    original = TimelinePipeline(workspace).motion_plan()["basisHeads"]
    deferred = decision(row, "deferred")
    decide(workspace, deferred)
    row = fresh_map(workspace)["pendingRevisions"][0]
    assert row["status"] == "deferred"
    assert row["pendingIds"] == deferred["ids"]
    assert row["completedIds"] == []
    assert row["decisionHead"] == content_hash(deferred)
    decide(workspace, decision(row, "pending", operation_id="work-reopen"))
    row = fresh_map(workspace)["pendingRevisions"][0]
    assert row["status"] == "awaiting-selection"
    decide(workspace, decision(row, "dismissed", operation_id="work-dismiss"))
    row = fresh_map(workspace)["pendingRevisions"][0]
    assert row["status"] == "dismissed"
    assert row["pendingIds"] == row["completedIds"] == []
    assert row["closedIds"] == deferred["ids"]
    assert TimelinePipeline(workspace).motion_plan()["basisHeads"] == original
    before = workspace.pipeline_run_path.read_bytes()
    replay = decide(workspace, deferred)
    assert replay["status"] == "replayed"
    assert workspace.pipeline_run_path.read_bytes() == before


@pytest.mark.parametrize(
    "problem",
    ["approved", "unknown-id", "scope", "stale-decision", "operation-conflict"],
)
def test_invalid_queue_decision_cannot_hide_work_or_replace_saved_history(
    tmp_path, problem
):
    workspace, _, _, row = pending(tmp_path)
    request = decision(row, "deferred")
    decide(workspace, request)
    row = fresh_map(workspace)["pendingRevisions"][0]
    changed = decision(row, "dismissed", operation_id="work-invalid")
    if problem == "approved":
        changed["status"] = "approved"
    elif problem == "unknown-id":
        changed["ids"] = ["another-event"]
    elif problem == "scope":
        changed["work"]["scope"]["itemIds"] = ["another-item"]
    elif problem == "stale-decision":
        changed["expectedDecisionHash"] = None
    else:
        changed["operationId"] = request["operationId"]
    before = workspace.pipeline_run_path.read_bytes()
    with pytest.raises(ValueError):
        decide(workspace, changed)
    assert workspace.pipeline_run_path.read_bytes() == before


def test_supersession_links_an_exact_requested_replacement_without_selecting_it(
    tmp_path,
):
    workspace, service, request, first = pending(tmp_path)
    replacement = deepcopy(request)
    replacement["operationId"] = "replacement-sound"
    replacement["intents"][0]["eventId"] = "replacement-event"
    service.propose(replacement)
    rows = {r["operationId"]: r for r in fresh_map(workspace)["pendingRevisions"]}
    target = rows[replacement["operationId"]]
    decide(workspace, decision(first, "superseded", replacement=target))
    rows = {r["operationId"]: r for r in fresh_map(workspace)["pendingRevisions"]}
    assert rows[first["operationId"]]["status"] == "superseded"
    assert rows[first["operationId"]]["completedIds"] == []
    assert rows[target["operationId"]]["status"] == "awaiting-selection"
    assert rows[target["operationId"]]["completedIds"] == []


def test_queue_dismissal_cannot_remove_an_already_published_effect(tmp_path):
    workspace, _, service, _, request, _ = application(tmp_path)
    service.apply(request)
    row = fresh_map(workspace)["pendingRevisions"][0]
    before = {p: p.read_bytes() for p in workspace.raw_dir.rglob("*") if p.is_file()}
    with pytest.raises(ValueError):
        decide(workspace, decision(row, "dismissed"))
    assert {
        p: p.read_bytes() for p in workspace.raw_dir.rglob("*") if p.is_file()
    } == before


def test_partial_dismissal_keeps_the_other_event_pending(tmp_path):
    workspace, _, _, row = pending(tmp_path, two_events=True)
    request = decision(row, "dismissed")
    request["ids"] = request["ids"][:1]
    decide(workspace, request)
    changed = fresh_map(workspace)["pendingRevisions"][0]
    assert changed["status"] == "partial"
    assert changed["pendingIds"] == ["second-event"]
    assert changed["closedIds"] == request["ids"]
    assert changed["completedIds"] == []
    assert changed["scope"] == row["scope"]


def test_motion_deferral_preserves_the_actual_selected_concept(tmp_path):
    import json

    from avo.timeline.motion_authoring import MotionAuthoringService
    from avo.timeline.workspace import TimelineWorkspace
    from tests.test_motion_authoring import item, propose, select

    path = tmp_path / "avo.project.json"
    path.write_text(
        json.dumps(
            {"provider": "example", "videoId": "motion", "rawDir": str(tmp_path)}
        )
    )
    workspace = TimelineWorkspace.from_project(path)
    proposed, _ = propose(workspace, items=[item(), item("mo05")])
    select(workspace, proposed)
    before = MotionAuthoringService(workspace).show()["decision"]
    row = fresh_map(workspace)["pendingRevisions"][0]
    request = decision(row, "deferred")
    request["ids"] = ["mo05"]
    decide(workspace, request)
    changed = fresh_map(workspace)["pendingRevisions"][0]
    assert changed["pendingIds"] == ["mo04", "mo05"]
    assert changed["deferredIds"] == ["mo05"]
    assert MotionAuthoringService(workspace).show()["decision"] == before


def test_decision_history_cannot_drop_a_predecessor_or_rewrite_its_request(tmp_path):
    from avo.timeline.lifecycle import LifecycleError, PipelineRunStore

    workspace, _, _, row = pending(tmp_path)
    decide(workspace, decision(row, "deferred"))
    row = fresh_map(workspace)["pendingRevisions"][0]
    decide(workspace, decision(row, "pending", operation_id="work-resume"))
    store = PipelineRunStore(workspace.pipeline_run_path)
    original = store.path.read_bytes()
    value = store.load()
    value["extensions"]["editingCraftWorkDecisions"].pop(0)
    with pytest.raises(LifecycleError, match="predecessor"):
        store._write(value)
    assert store.path.read_bytes() == original
    value = store.load()
    value["extensions"]["editingCraftWorkDecisions"][0]["request"]["reason"] = (
        "Rewritten"
    )
    with pytest.raises(LifecycleError, match="operation"):
        store._write(value)
    assert store.path.read_bytes() == original


def test_queue_decision_preserves_the_current_canonical_proof_plan(tmp_path):
    from avo.editing_craft import resolve_editing_craft_selection
    from avo.sfx_catalog import SfxCatalogService
    from avo.timeline.motion_review import MotionReviewService
    from tests.test_proof_plan import regression_contract
    from tests.test_sound_opportunities import intent
    from tests.test_sound_proof_plan import published_program

    workspace, compiler, proof_request, _ = published_program(tmp_path)
    catalogue = SfxCatalogService(workspace, roots={})
    generation = catalogue.show()
    catalogue = SfxCatalogService(workspace, roots=generation["roots"])
    SoundPlanningService(workspace, catalogue=catalogue).propose(
        {
            "contractVersion": "1.0.0",
            "operation": "propose",
            "operationId": "extra-pending-sound",
            "actor": "creator",
            "reason": "Keep one extra request visible",
            "expectedBasis": MotionReviewService(workspace).project()["basisHeads"],
            "selection": resolve_editing_craft_selection(
                invocation={"soundMatching": {"enabled": True}}
            ),
            "expectedGeneration": generation["generationId"],
            "clock": {
                "frameRate": {"num": 24, "den": 1},
                "sampleRate": 48000,
                "programEndFrame": 24,
            },
            "intents": [intent(eventId="queue-only-event")],
        }
    )
    before = compiler.compile(proof_request, regression_contract=regression_contract())
    row = next(
        row
        for row in fresh_map(workspace)["pendingRevisions"]
        if row["operationId"] == "extra-pending-sound"
    )
    decide(workspace, decision(row, "dismissed"))
    assert (
        compiler.compile(proof_request, regression_contract=regression_contract())
        == before
    )
