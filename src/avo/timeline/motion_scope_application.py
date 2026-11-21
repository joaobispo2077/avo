"""Scoped motion publication reuses immutable requests, receipts and the existing run."""

from copy import deepcopy

from .craft_scope import CraftScopeError, build_scope_plan
from .motion_metadata import cue_item_claims, cue_item_identity


def _history_candidates(run):
    extensions = run.get("extensions") or {}
    history = extensions.get("motionApplicationHistory", [])
    selected = extensions.get("motionProposalSelection")
    older = (
        [selected]
        if selected and selected.get("receiptRef") and selected not in history
        else []
    )
    return history, older


def _capacity(run, request):
    history, older = _history_candidates(run)
    if ("productionScope" in request or history) and len(history) + len(
        older
    ) + 1 > 500:
        raise CraftScopeError(
            "Motion application history exceeds the 500-record budget"
        )


def _prior_bmap(service, request):
    if request["expectedBasis"]["bmap"] is None:
        return {"cues": []}
    if request["expectedBasis"]["bmap"].get("activeState") != "valid":
        raise CraftScopeError(
            "Scoped production requires a current valid BMap; rebase unresolved parents first"
        )
    from .motion_review import MAX_METADATA_BYTES, MotionReviewService

    snapshot = MotionReviewService(service.workspace)._retained_snapshot(
        "bmap", request["expectedBasis"]["bmap"], {"remaining": MAX_METADATA_BYTES}
    )
    basis, current = snapshot.get("basis") or {}, request["expectedBasis"]["cmap"]
    if any(basis.get(key) != current[key] for key in ("revisionId", "sha256")):
        raise CraftScopeError(
            "Scoped production requires a valid BMap on the exact current cut"
        )
    return snapshot


def _bmap(service, request):
    if "bmap" in request["authoring"]:
        return request["authoring"]["bmap"]
    return _prior_bmap(service, request)


def _require_prior_owners(service, request, shown, owned):
    previous = _prior_bmap(service, request).get("cues", [])
    if not previous:
        return
    scope = request["productionScope"]
    complete = {
        **scope,
        "selectedChunkIds": [chunk["chunkId"] for chunk in scope["chunks"]],
    }
    plan = build_scope_plan(
        _scope_items(shown["proposal"]["items"], previous),
        complete,
        basis_heads=request["expectedBasis"],
    )
    selected = set(scope["selectedChunkIds"])
    if any(
        row["itemId"] in owned and row["ownerChunkId"] not in selected
        for row in plan["production"]
    ):
        raise CraftScopeError(
            "Revising an item also requires its current canonical start chunk"
        )


def _scope_items(concepts, cues):
    from .motion_review import _canonical_part

    groups = {
        item["itemId"]: {"itemId": item["itemId"], "parts": [], "identityConflicts": []}
        for item in concepts
    }
    claims = cue_item_claims(concepts)
    for cue in cues:
        identity, conflicts = cue_item_identity(cue, claims)
        if conflicts:
            raise CraftScopeError("Canonical cue has conflicting motion item claims")
        groups.setdefault(
            identity, {"itemId": identity, "parts": [], "identityConflicts": []}
        )["parts"].append(_canonical_part(cue))
    return list(groups.values())


def _plan(service, request, shown):
    cues = _bmap(service, request).get("cues", [])
    plan = build_scope_plan(
        _scope_items(shown["proposal"]["items"], cues),
        request["productionScope"],
        basis_heads=request["expectedBasis"],
    )
    selected = {
        item["itemId"]
        for item in shown["decision"]["dispositions"]
        if item["status"] == "selected"
    }
    owned = {item["itemId"] for item in plan["production"]} & selected
    if not owned:
        raise CraftScopeError(
            "Selected chunks own no selected motion items; context is read-only"
        )
    _require_prior_owners(service, request, shown, owned)
    identities = [
        item["itemId"] for item in shown["proposal"]["items"] if item["itemId"] in owned
    ]
    return plan, identities, cues


def _protected_ids(shown, owned, cues):
    from .motion_authoring import _scope_ids

    outside = [
        item for item in shown["proposal"]["items"] if item["itemId"] not in owned
    ]
    protected = _scope_ids(outside)
    claims = cue_item_claims(shown["proposal"]["items"])
    for cue in cues:
        identity, _ = cue_item_identity(cue, claims)
        if identity in owned:
            continue
        protected["tracks"].add(cue["targetLayerId"])
        component = cue.get("componentRef") or (cue.get("contentRef") or {}).get(
            "componentId"
        )
        if component:
            protected["animation"].add(component)
    return protected


def prepare_scope(service, request, shown):
    _capacity(service._run(), request)
    if "productionScope" not in request:
        return shown, {}
    from .program_clock import require_program_clock

    require_program_clock(
        service.workspace, request["productionScope"]["clock"], subject="Production"
    )
    plan, identities, cues = _plan(service, request, shown)
    narrowed = deepcopy(shown)
    narrowed["proposal"]["items"] = [
        item for item in narrowed["proposal"]["items"] if item["itemId"] in identities
    ]
    narrowed["_scopeOwnedCueIds"] = {
        part["cueId"]
        for row in plan["production"]
        if row["itemId"] in identities
        for part in row["parts"]
    }
    narrowed["_scopeProtectedIds"] = _protected_ids(shown, set(identities), cues)
    return narrowed, {"productionScope": plan, "appliedItemIds": identities}


def verify_receipt_scope(service, request, receipt):
    if "productionScope" not in request:
        if "productionScope" in receipt or "appliedItemIds" in receipt:
            raise CraftScopeError(
                "Unscoped motion receipt cannot invent scoped completion"
            )
        return
    proposed = service._proposal_result(receipt["proposalRef"]["sha256"])
    decision, reference = service._load(
        "decisions", receipt["decisionRef"]["sha256"], "decision"
    )
    service._verify_result_operation(decision, reference, "decision")
    plan, identities, _ = _plan(service, request, {**proposed, "decision": decision})
    if (
        receipt.get("productionScope") != plan
        or receipt.get("appliedItemIds") != identities
    ):
        raise CraftScopeError(
            "Motion receipt changes its exact requested production ownership"
        )


def remember_application(run, reference, request):
    extensions = run["extensions"]
    selector = extensions["motionProposalSelection"]
    history, older = _history_candidates(run)
    if "productionScope" in request or history:
        history = deepcopy(history)
        current = {**deepcopy(selector), "receiptRef": deepcopy(reference)}
        for entry in [*older, current]:
            if entry not in history:
                history.append(deepcopy(entry))
        if len(history) > 500:
            raise CraftScopeError(
                "Motion application history exceeds the 500-record budget"
            )
        extensions["motionApplicationHistory"] = history
    selector["receiptRef"] = reference


def _matching_applications(history, selector):
    return [
        entry
        for entry in [*history, selector]
        if all(
            entry.get(key) == selector[key] for key in ("proposalRef", "decisionRef")
        )
    ]


def completed_item_ids(retained, run, selector, decision):
    history = (run.get("extensions") or {}).get("motionApplicationHistory", [])
    selected = {
        item["itemId"]
        for item in decision["dispositions"]
        if item["status"] == "selected"
    }
    if not history:
        return selected
    completed, visited = set(), set()
    for entry in _matching_applications(history, selector):
        reference = entry.get("receiptRef")
        if not reference or reference["sha256"] in visited:
            continue
        visited.add(reference["sha256"])
        retained.selection(entry)
        receipt = retained.receipt(reference)
        if receipt["state"] != "committed":
            raise CraftScopeError(
                "Motion application history contains unfinished publication"
            )
        completed.update(receipt.get("appliedItemIds", selected))
    return completed & selected


def shown_applied_ids(service, run, selector, decision, applied):
    if not applied:
        return []
    history = (run.get("extensions") or {}).get("motionApplicationHistory", [])
    selected = [
        item["itemId"]
        for item in decision["dispositions"]
        if item["status"] == "selected"
    ]
    if not history:
        return selected
    from .motion_retention import _Retention

    completed = completed_item_ids(
        _Retention(service.workspace), run, selector, decision
    )
    return [identity for identity in selected if identity in completed]


def item_was_applied(shown, identity):
    applied_ids = shown.get("appliedItemIds")
    if applied_ids is not None:
        return identity in applied_ids
    return shown["status"] == "committed" or shown.get("applied", False)
