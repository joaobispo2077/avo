"""Requested craft work joins existing run references and bounded immutable evidence."""

from copy import deepcopy

from .craft_work_decisions import (
    WorkDecisionError,
    decorate_work_decisions,
    find_work_decision,
    require_decidable_work,
    require_registered_work,
)
from .lifecycle import PipelineRunStore
from .motion_metadata import _basis_matches


def _proposal_scope(kind, proposal):
    if kind == "motion":
        return {
            "itemIds": [item["itemId"] for item in proposal["items"]],
            "eventIds": [],
        }
    records = proposal["opportunities"]
    return {
        "itemIds": list(dict.fromkeys(record["itemId"] for record in records)),
        "eventIds": [record["eventId"] for record in records],
    }


def remember_craft_proposal(workspace, kind, shown):
    proposal = shown["proposal"]
    PipelineRunStore(workspace.pipeline_run_path).bind_editing_craft_work(
        {
            "kind": kind,
            "operationId": proposal["operationId"],
            "requestId": proposal["requestId"],
            "proposalRef": shown["proposalRef"],
            "scope": _proposal_scope(kind, proposal),
        }
    )
    return shown


def _basis_status(proposal, heads, direction_ref, committed=None):
    expected = {**proposal["basisHeads"], **(committed or {})}
    current = (
        _basis_matches(expected, heads)
        and proposal["directionRef"] == direction_ref
        and all(
            head is None
            or (
                head.get("activeState") == "valid"
                and head.get("availability") != "unavailable"
            )
            for head in heads.values()
        )
    )
    return "current" if current else "stale"


def _sound_receipts(retained, work):
    return sorted(
        (
            receipt
            for receipt in retained.sound_retention.applications.values()
            if receipt["proposalRef"] == work["proposalRef"]
        ),
        key=lambda receipt: receipt["operationId"],
    )


def _sound_completion(ids, receipts):
    completed = {
        choice["eventId"]
        for receipt in receipts
        if receipt["state"] == "committed"
        for choice in receipt["choices"]
    }
    state = "awaiting-selection" if ids else "completed"
    if completed:
        state = "partial" if set(ids) - completed else "completed"
    if any(receipt["state"] != "committed" for receipt in receipts):
        state = "recovery-needed"
    return state, completed


def _sound_progress(retained, work, proposal, heads):
    receipts = _sound_receipts(retained, work)
    ids = [record["eventId"] for record in proposal["opportunities"]]
    state, completed = _sound_completion(ids, receipts)
    committed = next(
        (
            receipt["committedHeads"]
            for receipt in receipts
            if _basis_matches(receipt["committedHeads"], heads)
        ),
        {},
    )
    return {
        "status": state,
        "itemIds": list(dict.fromkeys(r["itemId"] for r in proposal["opportunities"])),
        "pendingIds": [identity for identity in ids if identity not in completed],
        "completedIds": [identity for identity in ids if identity in completed],
        "applications": [
            {
                "requestRef": receipt["requestRef"],
                "publicationState": receipt["state"],
                "committedHeads": receipt["committedHeads"],
            }
            for receipt in receipts
        ],
    }, committed


def _motion_decision(retained, work, run):
    extensions = run.get("extensions") or {}
    selected = [
        value
        for value in [
            *extensions.get("motionProposalSelectionHistory", []),
            extensions.get("motionProposalSelection"),
        ]
        if value and value["proposalRef"] == work["proposalRef"]
    ]
    states, committed, applied = {}, {}, set()
    if selected:
        choice = selected[-1]
        retained.selection(choice)
        decision = retained.decision(choice["decisionRef"])
        states = {item["itemId"]: item["status"] for item in decision["dispositions"]}
        if choice.get("receiptRef"):
            receipt = retained.receipt(choice["receiptRef"])
            committed = receipt["committedHeads"]
            if receipt["state"] == "committed":
                from .motion_scope_application import completed_item_ids

                applied = completed_item_ids(retained, run, choice, decision)
    return states, committed, applied


def _motion_work_status(states, completed, pending):
    if not pending:
        return "completed"
    if completed:
        return "partial"
    return (
        "selected-unapplied" if "selected" in states.values() else "awaiting-selection"
    )


def _motion_progress(retained, work, proposal, run):
    states, committed, applied = _motion_decision(retained, work, run)
    ids = [item["itemId"] for item in proposal["items"]]
    completed = [
        identity
        for identity in ids
        if states.get(identity) == "rejected"
        or (identity in applied and states.get(identity) == "selected")
    ]
    pending = [identity for identity in ids if identity not in completed]
    return {
        "status": _motion_work_status(states, completed, pending),
        "itemIds": ids,
        "pendingIds": pending,
        "completedIds": completed,
    }, committed


def load_craft_proposal(retained, work):
    if work["kind"] == "sound":
        retained.sound_retention.proposal(work["proposalRef"])
        proposal = retained.sound_retention.reference(work["proposalRef"], "proposal")
    else:
        proposal = retained.proposal(work["proposalRef"])
    if (proposal["operationId"], proposal["requestId"]) != (
        work["operationId"],
        work["requestId"],
    ):
        raise ValueError("Requested craft work changes its operation or frozen request")
    if work["scope"] != _proposal_scope(work["kind"], proposal):
        raise ValueError("Requested craft work changes its original scope")
    return proposal


def _project_work(retained, work, heads, direction_ref, run, current_generation):
    proposal = load_craft_proposal(retained, work)
    if work["kind"] == "sound":
        progress, committed = _sound_progress(retained, work, proposal, heads)
    else:
        progress, committed = _motion_progress(retained, work, proposal, run)
    basis = _basis_status(proposal, heads, direction_ref, committed)
    active = (run.get("executionChoices") or {}).get("editingCraft") or {}
    request_status = (
        "active" if active.get("requestId") == work["requestId"] else "historical"
    )
    if request_status == "historical":
        basis = "stale"
    if work["kind"] == "sound" and proposal["generationId"] != current_generation:
        basis = "stale"
    return {
        **deepcopy(work),
        **progress,
        "basisStatus": basis,
        "requestStatus": request_status,
    }


def _unavailable_work(item):
    scope = item["scope"]
    return {
        **deepcopy(item),
        "status": "unavailable",
        "basisStatus": "unavailable",
        "itemIds": deepcopy(scope["itemIds"]),
        "pendingIds": deepcopy(
            scope["eventIds"] if item["kind"] == "sound" else scope["itemIds"]
        ),
        "completedIds": [],
    }


def _project_row(
    retained, item, heads, direction_ref, run, current_generation, rows, gaps
):
    try:
        rows.append(
            _project_work(retained, item, heads, direction_ref, run, current_generation)
        )
    except (OSError, ValueError, RuntimeError, KeyError, TypeError) as error:
        rows.append(_unavailable_work(item))
        gaps.append(
            {
                "kind": "craft-work-unavailable",
                "operationId": item["operationId"],
                "detail": str(error)[:500],
            }
        )


def project_craft_work(workspace, heads):
    """Inspect requested work; never scan sources, select media or advance a stage."""
    from .motion_retention import _Retention

    path = workspace.pipeline_run_path
    if not path.exists() and not path.is_symlink():
        return [], []
    rows, gaps, work, decisions = [], [], [], []
    try:
        retained = _Retention(workspace)
        run, _ = retained.read(path)
        PipelineRunStore(path)._validate(run)
        extensions = run.get("extensions") or {}
        decisions = extensions.get("editingCraftWorkDecisions", [])
        work = extensions.get("editingCraftWork", [])
        if not work:
            return [], []
        direction_ref = retained.service._direction_ref()
        current_generation = None
        if any(item["kind"] == "sound" for item in work):
            current_generation = retained.sound_retention.current_generation()
            retained.sound_retention.load_applications()
        for item in work:
            _project_row(
                retained,
                item,
                heads,
                direction_ref,
                run,
                current_generation,
                rows,
                gaps,
            )
    except (OSError, ValueError, RuntimeError, KeyError, TypeError) as error:
        rows = [_unavailable_work(item) for item in work]
        gaps.append({"kind": "craft-work-unavailable", "detail": str(error)[:500]})
    return decorate_work_decisions(rows, decisions), gaps


def decide_craft_work(workspace, request):
    from .command_registry import authorize
    from .contracts import validate_document
    from .motion_review import MotionReviewService
    from .store import timeline_writer

    try:
        validate_document(
            request, "avo.editing-craft-run.schema.json#/$defs/workDecisionRequest"
        )
        authorize("pipeline")
        with timeline_writer(workspace.timeline_dir):
            store = PipelineRunStore(workspace.pipeline_run_path)
            run = store.load()
            record = find_work_decision(run, request)
            replayed = record is not None
            if record is None:
                require_registered_work(run, request["work"])
                heads = MotionReviewService(workspace)._metadata(snapshots=False)[0]
                rows, _ = project_craft_work(workspace, heads)
                require_decidable_work(rows, request)
                run = store.record_editing_craft_work_decision(request)
                record = find_work_decision(run, request)
        return {
            "contractVersion": "1.0.0",
            "operation": "work-decide",
            "operationId": request["operationId"],
            "status": "replayed" if replayed else "recorded",
            "effect": "request-decision-write",
            "decision": record,
        }
    except (ValueError, RuntimeError, OSError, KeyError, TypeError) as error:
        if isinstance(error, WorkDecisionError):
            raise
        raise WorkDecisionError(str(error)) from error
