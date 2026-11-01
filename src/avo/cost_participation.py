"""Pure lifecycle and evidence decisions; immutable publication stays in CostStore."""

from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from uuid import NAMESPACE_URL, uuid5

from avo.timeline.contracts import content_hash


def _fail(message):
    from avo.cost_store import CostError

    raise CostError(message)


def _payload(record, field):
    return {
        key: value
        for key, value in record.items()
        if key not in {field, "recordedOrder"}
    }


def evidence_id(metadata):
    """A metadata revision has its own identity, independent of the usage row."""
    return content_hash(
        {
            "domain": "cost-evidence/v2",
            "metadata": {
                key: value
                for key, value in metadata.items()
                if key not in {"evidenceId", "_accountingVideoId"}
            },
        }
    )


def legacy_evidence_id(key):
    """Derive legacy identity without modifying a historical document."""
    return content_hash({"domain": "legacy-unknown/v1", "key": key})


def _validate_record(kind, record, field):
    from avo.cost_store import validate

    validate(kind, record)
    if content_hash(_payload(record, field)) != record[field]:
        _fail(f"cost {kind} integrity verification failed")
    return record


def build_participation_fact(payload):
    value = deepcopy(payload)
    value.setdefault("schemaVersion", "2.0.0")
    value.setdefault("predecessors", [])
    expected = content_hash(_payload(value, "factId"))
    if "factId" in value and value["factId"] != expected:
        _fail("cost participation integrity verification failed")
    value["factId"] = expected
    return _validate_record("participation", value, "factId")


def _acyclic(edges, message):
    """Iterative topological check also handles long imported histories."""
    nodes = set(edges)
    for targets in edges.values():
        nodes.update(targets)
    incoming = dict.fromkeys(nodes, 0)
    for targets in edges.values():
        for target in targets:
            incoming[target] += 1
    ready = [node for node, count in incoming.items() if count == 0]
    visited = 0
    while ready:
        node = ready.pop()
        visited += 1
        for target in edges.get(node, ()):
            incoming[target] -= 1
            if incoming[target] == 0:
                ready.append(target)
    if visited != len(nodes):
        _fail(message)


def _operations(records, id_field):
    operations = {}
    for record in records:
        key = (record["accountingVideoId"], record["operationId"])
        previous = operations.setdefault(key, record[id_field])
        if previous != record[id_field]:
            _fail("cost operation replay conflicts with previously accepted content")


def _predecessor_links(records):
    predecessors = {}
    for fact in records.values():
        for predecessor in fact["predecessors"]:
            if predecessor not in records:
                _fail("unknown cost participation predecessor")
            if records[predecessor]["accountingVideoId"] != fact["accountingVideoId"]:
                _fail("cost participation predecessor belongs to another production")
        predecessors[fact["factId"]] = fact["predecessors"]
    return predecessors


def _declared(identity, fact, declarations):
    target = declarations.get(identity)
    if target is None:
        _fail("cost participation fact lacks a known declaration")
    if target["accountingVideoId"] != fact["accountingVideoId"]:
        _fail("cost participation belongs to another production")
    return target


def _validate_transition(fact, declarations):
    if fact["kind"] != "transition":
        return
    for field in ("fromParticipationId", "toParticipationId"):
        _declared(fact[field], fact, declarations)
    if (
        fact["fromParticipationId"] == fact["toParticipationId"]
        and fact["transitionKind"] != "resume"
    ):
        _fail("cost transition cannot link a participation to itself")


def _parent_links(records, declarations):
    parents = defaultdict(set)
    for fact in records.values():
        _declared(fact["participationId"], fact, declarations)
        parent = fact.get("agent", {}).get("parentParticipationId")
        if parent:
            _declared(parent, fact, declarations)
            parents[fact["participationId"]].add(parent)
        _validate_transition(fact, declarations)
    return parents


def _validated_fact_records(facts):
    if not isinstance(facts, (list, tuple)) or len(facts) > 100000:
        _fail("invalid cost participation facts or record limit exceeded")
    records = {}
    for fact in facts:
        value = build_participation_fact(fact)
        records[value["factId"]] = value
    _operations(records.values(), "factId")
    declarations = {
        fact["participationId"]: fact
        for fact in records.values()
        if fact["kind"] in {"declare", "declare-no-external-agent"}
    }
    predecessors = _predecessor_links(records)
    _acyclic(predecessors, "cost participation predecessor cycle")
    _acyclic(_parent_links(records, declarations), "cost participation parent cycle")
    return records


def validate_fact_graph(facts):
    records = _validated_fact_records(facts)
    projection = _project_fact_records(records)
    return {"facts": list(records.values()), "conflicts": projection["conflicts"]}


_STATE_FIELDS = ("agent", "scope", "mode", "sourceAttachment", "lifecycle")


def _fact_order(records):
    pending = {
        identity: len(fact["predecessors"]) for identity, fact in records.items()
    }
    successors = defaultdict(list)
    for identity, fact in records.items():
        for predecessor in fact["predecessors"]:
            successors[predecessor].append(identity)
    ready = [identity for identity, count in pending.items() if count == 0]
    while ready:
        identity = ready.pop()
        yield identity
        for successor in successors[identity]:
            pending[successor] -= 1
            if pending[successor] == 0:
                ready.append(successor)


def _inherit_fact_state(parents, fact):
    state = {}
    unresolved = set().union(*(parent.get("_unresolved", set()) for parent in parents))
    for field in _STATE_FIELDS:
        if field in fact:
            state[field] = deepcopy(fact[field])
            unresolved.discard(field)
            continue
        values = {
            content_hash(parent.get(field)): parent.get(field) for parent in parents
        }
        if len(values) > 1:
            unresolved.add(field)
        elif values:
            value = next(iter(values.values()))
            if value is not None:
                state[field] = deepcopy(value)
    state["_unresolved"] = unresolved
    state["diagnostics"] = _state_diagnostics(parents)
    return state


def _state_diagnostics(parents):
    diagnostics = {
        content_hash(item): item
        for parent in parents
        for item in parent.get("diagnostics", [])
    }
    return [diagnostics[key] for key in sorted(diagnostics)]


def _known_transition_boundary(state, boundary):
    scope = state.get("scope", {})
    session = state.get("agent", {}).get("sourceSessionId")
    return bool(
        boundary["kind"] in {"event", "turn"}
        and boundary.get("reference")
        and scope.get("sourceInstanceId")
        and session
        and scope.get("sourceSessionId") == session
    )


def _apply_fact_lifecycle(state, fact):
    state.setdefault(
        "lifecycle", "closed" if state.get("mode") == "human-ci" else "open"
    )
    if fact["kind"] not in {"transition", "boundary"}:
        return state
    state["diagnostics"].extend(
        {"code": code} for code in fact["provenance"]["reference"].split("|")[1:]
    )
    scope = state.get("scope", {})
    if state["lifecycle"] == "closed":
        if _known_transition_boundary(state, fact["boundary"]):
            scope["ending"] = deepcopy(fact["boundary"])
        else:
            state["lifecycle"] = "unknown"
    elif fact.get("transitionKind") == "resume" and state["lifecycle"] == "open":
        scope.pop("ending", None)
    return state


def _fact_states(records):
    states = {}
    for identity in _fact_order(records):
        fact = records[identity]
        parents = [
            states[key]
            for key in fact["predecessors"]
            if records[key]["participationId"] == fact["participationId"]
        ]
        states[identity] = _apply_fact_lifecycle(
            _inherit_fact_state(parents, fact), fact
        )
    return states


def _participation_frontiers(records):
    replaced = set()
    frontiers = defaultdict(list)
    for fact in records.values():
        replaced.update(
            key
            for key in fact["predecessors"]
            if records[key]["participationId"] == fact["participationId"]
        )
    for identity, fact in records.items():
        if identity not in replaced:
            frontiers[fact["participationId"]].append(identity)
    return {identity: sorted(keys) for identity, keys in frontiers.items()}


def _project_frontier(identity, frontier, states, records):
    state = _inherit_fact_state([states[key] for key in frontier], {})
    unresolved = state.pop("_unresolved")
    state.update(
        participationId=identity,
        frontier=frontier,
        conflicted=bool(unresolved),
        kind=records[frontier[0]]["kind"] if len(frontier) == 1 else "revise",
    )
    if len(frontier) == 1:
        state["factId"] = frontier[0]
    if unresolved:
        state["mode"] = "identity-unknown"
        state["lifecycle"] = "unknown"
    if "agent" not in state:
        state["agent"] = {
            "family": "unknown",
            "surface": "unknown",
            "version": None,
            "role": "driver",
        }
    if "scope" not in state:
        aliases = {
            alias
            for key in frontier
            for alias in states[key].get("scope", {}).get("runAliases", [])
        }
        state["scope"] = {
            "runAliases": sorted(aliases),
            "beginning": {"kind": "unknown"},
        }
    return state


def _project_fact_records(records):
    states = _fact_states(records)
    frontiers = _participation_frontiers(records)
    participants = [
        _project_frontier(identity, keys, states, records)
        for identity, keys in sorted(frontiers.items())
    ]
    conflicts = [
        {
            "code": "participation-frontier-conflict",
            "participationId": item["participationId"],
            "factIds": item["frontier"],
        }
        for item in participants
        if item["conflicted"]
    ]
    return {
        "participations": participants,
        "frontiers": frontiers,
        "conflicts": conflicts,
    }


def project_participation_facts(facts):
    """Project only explicit causal frontiers; timestamps never choose a host."""
    return _project_fact_records(_validated_fact_records(facts))


def _key(record):
    return record.get("key", record.get("observationKey"))


def _scope(record):
    return record.get("scope", record.get("attribution", {}).get("scope"))


def _known(reference, known_refs):
    record = known_refs.get(reference["id"])
    if record is None:
        _fail("unknown cost reconciliation reference")
    _validate_reference_identity(reference, record)
    return record


def _validate_reference_identity(reference, record):
    if _reference_family(record) != reference["kind"]:
        _fail("cost reconciliation reference kind does not match its record family")
    if (
        reference["kind"] == "observation"
        and reference["id"] != record["key"]["sourceDigest"]
    ):
        _fail("cost observation reference must identify its exact source digest")
    if reference.get("key") is not None and _key(record) != reference["key"]:
        _fail("cost reconciliation observation key does not match its reference")
    if reference.get("scope") is not None and _scope(record) != reference["scope"]:
        _fail("cost reconciliation reference scope does not match its producer")


def _reference_family(record):
    fields = {
        "evidenceId": "evidence",
        "estimateId": "estimate",
        "reconciliationId": "decision",
        "aggregateId": "aggregate",
    }
    found = [family for field, family in fields.items() if field in record]
    if len(found) == 1:
        return found[0]
    return "observation" if not found and "key" in record else None


def _decision_records(known_refs):
    return {
        key: value for key, value in known_refs.items() if "reconciliationId" in value
    }


def _validate_reconciliation_base(record):
    _validate_reconciliation_audit(record)
    if not record["proofRefs"]:
        _fail("cost reconciliation requires explicit proof references")
    refs = record["references"]
    if len({content_hash(ref) for ref in refs}) != len(refs):
        _fail("duplicate cost reconciliation reference")
    if record["reconciliationId"] in {ref["id"] for ref in refs} | set(
        record["supersedes"]
    ):
        _fail("cost reconciliation cannot reference itself")
    selected = record["selectedRepresentation"]
    if selected is not None and selected not in refs:
        _fail("cost reconciliation selection must be an exact affected reference")


def _validate_reconciliation_audit(record):
    if (
        not record["actor"].strip()
        or not record["reason"].strip()
        or any(not proof.strip() for proof in record["proofRefs"])
    ):
        _fail(
            "cost reconciliation requires meaningful actor, reason and proof references"
        )


def _validate_reference_scope(record, target):
    if record["relation"] in {"same-activity", "covers-rollup", "allocation"}:
        return
    target_scope = _scope(target)
    if target_scope:
        for field in ("sourceInstanceId", "sourceSessionId", "counterEpoch"):
            if (
                field in record["scope"]
                and field in target_scope
                and record["scope"][field] != target_scope[field]
            ):
                _fail("cost reconciliation reference is outside its declared scope")


def _validate_reconciliation_refs(record, known_refs):
    for ref in record["references"]:
        target = _known(ref, known_refs)
        if (
            target.get(
                "accountingVideoId",
                target.get("_accountingVideoId", record["accountingVideoId"]),
            )
            != record["accountingVideoId"]
            and record["relation"] != "allocation"
        ):
            _fail("cost reconciliation reference belongs to another production")
        _validate_reference_scope(record, target)


def _validate_supersession(record, known_refs):
    for decision_id in record["supersedes"]:
        previous = known_refs.get(decision_id)
        if previous is None or "reconciliationId" not in previous:
            _fail("unknown superseded cost reconciliation")
        if previous["accountingVideoId"] != record["accountingVideoId"]:
            _fail("superseded cost reconciliation belongs to another production")
    decisions = _decision_records(known_refs)
    decisions[record["reconciliationId"]] = record
    _acyclic(
        {key: value["supersedes"] for key, value in decisions.items()},
        "cost reconciliation supersession cycle",
    )


def _validate_evidence_revision(record, known_refs):
    old_id, new_id = record["oldEvidenceId"], record["newEvidenceId"]
    if old_id == new_id:
        _fail("cost evidence revision requires different metadata identities")
    old, new = known_refs.get(old_id), known_refs.get(new_id)
    if old is None or new is None:
        _fail("unknown cost evidence revision reference")
    if not _key(old) or _key(old) != _key(new):
        _fail("cost evidence revision cannot change an observation payload or key")
    _validate_revision_selection(record, old_id, new_id)
    _validate_revision_members(record, known_refs, old, new)
    _validate_revision_cycle(record, known_refs)


def _validate_revision_selection(record, old_id, new_id):
    identities = {
        ref["id"] for ref in record["references"] if ref["kind"] == "evidence"
    }
    selected = record["selectedRepresentation"] or {}
    if (
        not {old_id, new_id}.issubset(identities)
        or selected.get("kind") != "evidence"
        or selected.get("id") != new_id
    ):
        _fail("cost evidence revision must select its exact new evidence identity")


def _active_reconciliation_records(record, known_refs):
    decisions = _decision_records(known_refs)
    decisions[record["reconciliationId"]] = record
    superseded = {
        identity for item in decisions.values() for identity in item["supersedes"]
    }
    return [item for identity, item in decisions.items() if identity not in superseded]


def _validate_revision_cycle(record, known_refs):
    revisions = [
        item
        for item in _active_reconciliation_records(record, known_refs)
        if item["relation"] == "revises-evidence"
    ]
    _selected_revision_edges(revisions)


def _validate_revision_members(record, known_refs, old, new):
    for ref in record["references"]:
        if ref["kind"] != "evidence" or _key(_known(ref, known_refs)) != _key(new):
            _fail(
                "metadata revision references must share one unchanged observation key"
            )
    if old.get("participationId") and old["participationId"] != new.get(
        "participationId"
    ):
        _fail(
            "metadata revision cannot reassign a participation; use explicit allocation"
        )
    _validate_served_model_revision(old, new, known_refs)


def _validate_served_model_revision(old, new, known_refs):
    if new.get("modelBasis") != "served" or old.get("modelBasis") == "served":
        return
    row = known_refs.get(new["key"]["sourceDigest"], {}).get("observation", {})
    profile = known_refs.get(new.get("profileId"), {})
    qualified = profile.get("capability") == "qualified"
    supported = (
        "model" in profile.get("allowedFields", [])
        or profile.get("qualification", {}).get("kind") == "synthetic"
    )
    if not row.get("model") or not qualified or not supported:
        _fail(
            "selected model hint cannot become served model evidence without qualified source proof"
        )


def _validate_representations(record, known_refs):
    if len(record["references"]) < 2 or record["selectedRepresentation"] is None:
        _fail(
            "cost reconciliation requires multiple representations and an explicit selection"
        )
    if any(ref["kind"] != "evidence" for ref in record["references"]):
        _fail("same-activity requires exact admitted evidence references")
    observations = [
        _known(ref, known_refs)["key"]["observationId"] for ref in record["references"]
    ]
    if len(set(observations)) != len(observations):
        _fail(
            "one observation requires metadata revision or row correction, not an activity alias"
        )
    if _scope(_known(record["selectedRepresentation"], known_refs)) != record["scope"]:
        _fail("activity covered scope must match the selected producer scope")
    _validate_same_activity_composition(record, known_refs)


def _validate_same_activity_composition(record, known_refs):
    footprints = []
    for ref in record["references"]:
        item = _known(ref, known_refs)
        members = item.get("aggregateScope", {}).get("members") or [item["key"]]
        footprints.append({content_hash(key) for key in members})
    composite = any(
        _known(ref, known_refs).get("aggregateScope", {}).get("members")
        for ref in record["references"]
    )
    if composite and any(members != footprints[0] for members in footprints[1:]):
        _fail("partial tree activity requires complete covers-rollup selection")


def _validate_estimate_replacement(record, known_refs):
    selected = record["selectedRepresentation"]
    estimates = [ref for ref in record["references"] if ref["kind"] == "estimate"]
    if len(estimates) != 1 or selected is None or selected["kind"] == "estimate":
        _fail(
            "cost estimate replacement requires one estimate and stronger selected evidence"
        )
    if any(
        _scope(_known(ref, known_refs)) != record["scope"]
        for ref in record["references"]
    ):
        _fail("partial estimate scope requires explicit bounded decomposition")
    _validate_stronger_estimate_evidence(
        _known(estimates[0], known_refs), _known(selected, known_refs), selected
    )


def _validate_stronger_estimate_evidence(estimate, evidence, selected):
    if selected["kind"] != "evidence" or evidence.get("nature") not in {
        "measured",
        "manual",
    }:
        _fail("estimate replacement requires explicit measured or manual evidence")
    if evidence.get("attribution", {}).get("status") != "assigned":
        _fail("estimate replacement requires assigned evidence")
    if evidence.get("participationId") != estimate["participationId"]:
        _fail("estimate replacement evidence belongs to another participation")


def _validate_allocation(record, known_refs):
    allocations = record.get("allocations", [])
    if not allocations:
        _fail("cost allocation requires explicit bounded partitions")
    allocated = set()
    for allocation in allocations:
        target = _known(allocation["reference"], known_refs)
        if (
            allocation["reference"] not in record["references"]
            or _scope(target) != allocation["scope"]
        ):
            _fail(
                "cost allocation requires exact affected references and producer scopes"
            )
        key = content_hash(allocation["reference"])
        if key in allocated:
            _fail("duplicate cost allocation requires explicit disjoint decomposition")
        allocated.add(key)
    _validate_prior_allocations(record, known_refs, allocated)


def _validate_prior_allocations(record, known_refs, allocated):
    decisions = _decision_records(known_refs)
    superseded = set(record["supersedes"]) | {
        identity for item in decisions.values() for identity in item["supersedes"]
    }
    for identity, previous in decisions.items():
        if (
            identity == record["reconciliationId"]
            or identity in superseded
            or previous["relation"] != "allocation"
        ):
            continue
        previous_refs = {
            content_hash(item["reference"]) for item in previous.get("allocations", [])
        }
        if previous_refs & allocated:
            _fail(
                "cost activity already has an active allocation; explicitly supersede it"
            )


def _validate_withdrawal(record, known_refs):
    if not record["supersedes"]:
        _fail("cost withdrawal requires explicit superseded decisions")
    refs = {ref["id"] for ref in record["references"] if ref["kind"] == "decision"}
    if refs != set(record["supersedes"]) or len(refs) != len(record["references"]):
        _fail("withdrawal must reference exactly its superseded decisions")


def validate_reconciliation(record, *, known_refs):
    _validate_record("reconciliation", record, "reconciliationId")
    _operations(
        list(_decision_records(known_refs).values()) + [record], "reconciliationId"
    )
    _validate_reconciliation_base(record)
    _validate_reconciliation_refs(record, known_refs)
    _validate_supersession(record, known_refs)
    handlers = {
        "revises-evidence": _validate_evidence_revision,
        "same-activity": _validate_representations,
        "covers-rollup": _validate_rollup_selection,
        "replaces-estimate": _validate_estimate_replacement,
        "allocation": _validate_allocation,
        "withdraw": _validate_withdrawal,
    }
    handlers[record["relation"]](record, known_refs)
    return record


def _evidence_groups(evidence):
    variants = {}
    groups = defaultdict(dict)
    for item in evidence:
        identity = item["evidenceId"]
        expected = (
            legacy_evidence_id(item["key"])
            if item.get("nature") == "legacy-unknown"
            else evidence_id(item)
        )
        if identity != expected:
            _fail("cost evidence integrity verification failed")
        if identity in variants and variants[identity] != item:
            _fail("conflicting cost evidence identity")
        variants[identity] = item
        groups[content_hash(item["key"])][identity] = item
    return variants, groups


def _revision_edges(variants, reconciliations, known_refs=None):
    decisions = {item["reconciliationId"]: item for item in reconciliations}
    known_refs = {**variants, **decisions, **(known_refs or {})}
    revisions = [
        item for item in decisions.values() if item["relation"] == "revises-evidence"
    ]
    for decision in revisions:
        validate_reconciliation(decision, known_refs=known_refs)
    superseded = {
        identity for item in decisions.values() for identity in item["supersedes"]
    }
    active = [item for item in revisions if item["reconciliationId"] not in superseded]
    return _selected_revision_edges(active)


def _selected_revision_edges(active):
    edges = defaultdict(set)
    for item in active:
        for ref in item["references"]:
            if ref["id"] != item["newEvidenceId"]:
                edges[ref["id"]].add(item["newEvidenceId"])
    _acyclic(edges, "cost evidence revision cycle")
    return edges


def _evidence_terminals(group, edges):
    terminals = set()
    for identity in group:
        while edges.get(identity):
            if len(edges[identity]) != 1:
                return set()
            identity = next(iter(edges[identity]))
        terminals.add(identity)
    return terminals


def resolve_evidence(evidence, reconciliations, *, known_refs=None):
    """Select exact revisions only; never choose metadata by strength or timestamp."""
    variants, groups = _evidence_groups(evidence)
    edges = _revision_edges(variants, reconciliations, known_refs)
    selected, conflicts = [], []
    for group in groups.values():
        terminals = _evidence_terminals(group, edges)
        if len(terminals) == 1:
            selected.append(group[next(iter(terminals))])
        else:
            conflicts.append(
                {
                    "code": "cost-evidence-conflict",
                    "observationId": next(iter(group.values()))["key"]["observationId"],
                    "evidenceIds": sorted(group),
                }
            )
    return {"selected": selected, "conflicts": conflicts}












































def _source_lineage(state):
    scope = state["scope"]
    return tuple(
        scope.get(key)
        for key in ("sourceInstanceId", "sourceSessionId", "counterEpoch")
    )
















def _rollup_representations(record, known_refs):
    if any(ref["kind"] != "evidence" for ref in record["references"]):
        _fail("rollup selection requires exact admitted evidence references")
    items = [_known(ref, known_refs) for ref in record["references"]]
    aggregates = [
        item for item in items if item.get("aggregateScope", {}).get("members")
    ]
    if len(aggregates) != 1:
        _fail("rollup selection requires one exact known composition")
    aggregate = aggregates[0]
    leaves = [item for item in items if item["evidenceId"] != aggregate["evidenceId"]]
    return aggregate, leaves


def _validate_rollup_proof(record, aggregate, leaves, known_refs):
    composition = aggregate["aggregateScope"]
    profile = known_refs.get(aggregate.get("profileId"), {})
    if not composition["proofRefs"] or profile.get("capability") != "qualified":
        _fail("rollup composition requires qualified source proof")
    if profile.get("semantics", {}).get("aggregateScope") != composition["kind"]:
        _fail("rollup composition disagrees with its frozen source profile")
    members = {content_hash(key) for key in composition["members"]}
    if (
        members != {content_hash(item["key"]) for item in leaves}
        or content_hash(aggregate["key"]) in members
    ):
        _fail("rollup selection requires complete exact leaf membership")
    if _scope(aggregate) != record["scope"]:
        _fail("rollup covered scope must match its producer scope")


def _validate_rollup_selection(record, known_refs):
    aggregate, leaves = _rollup_representations(record, known_refs)
    _validate_rollup_proof(record, aggregate, leaves, known_refs)
    plural = record.get("selectedRepresentations")
    if plural is not None:
        selected = {ref["id"] for ref in plural}
        if record["selectedRepresentation"] is not None or selected != {
            item["evidenceId"] for item in leaves
        }:
            _fail("rollup leaf selection requires the complete reviewed leaf set")
        if any(ref not in record["references"] for ref in plural):
            _fail("rollup leaf selection must use exact affected references")
        return
    selected = record["selectedRepresentation"] or {}
    if selected.get("id") != aggregate["evidenceId"]:
        _fail("rollup requires its aggregate or the complete explicit leaf set")


def _normalized_reconcile_request(request):
    value = deepcopy(request)
    for field in ("references", "selectedRepresentations", "allocations"):
        if field in value:
            value[field] = sorted(value[field], key=content_hash)
    for field in ("supersedes", "proofRefs"):
        value[field] = sorted(value[field])
    return value


def _reconcile_result(record, replayed):
    return {
        "schemaVersion": "2.0.0",
        "status": "ok",
        "accountingVideoId": record["accountingVideoId"],
        "reconciliationId": record["reconciliationId"],
        "recordIds": [record["reconciliationId"]],
        "replayed": replayed,
        "diagnostics": [],
    }


def _reconcile_replay(records, request):
    previous = next(
        (item for item in records if item["operationId"] == request["operationId"]),
        None,
    )
    if previous is None:
        return None
    payload = {
        key: value
        for key, value in previous.items()
        if key not in {"reconciliationId", "createdAt", "recordedOrder"}
    }
    if _normalized_reconcile_request(payload) != request:
        _fail("cost reconciliation operation replay conflicts with accepted content")
    return _reconcile_result(previous, True)


def reconcile_costs(store, request):
    """Append a reviewed relation; retain all source evidence and prior decisions."""
    from avo.avo_state import now_iso
    from avo.cost_store import CostError, validate

    validate("reconcile-request", request)
    if (
        not store.identity()
        or request["accountingVideoId"] != store.identity()["accountingVideoId"]
    ):
        _fail("cost reconciliation belongs to an unknown or different production")
    request = _normalized_reconcile_request(request)
    view = store.capture()
    replay = _reconcile_replay(view["reconciliations"], request)
    if replay:
        store.amend_if_closed()
        return replay
    record = {**request, "createdAt": now_iso()}
    record["reconciliationId"] = content_hash(record)
    validate_reconciliation(record, known_refs=store.references(view))
    try:
        saved = store.append_record("reconciliations", record)
    except CostError:
        replay = _reconcile_replay(store.capture()["reconciliations"], request)
        if replay:
            store.amend_if_closed()
            return replay
        raise
    return _reconcile_result(saved, False)


def _interval_parent_state(fact, records, states):
    parents = [
        states[key]
        for key in fact["predecessors"]
        if records[key]["participationId"] == fact["participationId"]
    ]
    active = set().union(*(parent["active"] for parent in parents))
    grants = {content_hash(parent["grant"]): parent["grant"] for parent in parents}
    grant = fact.get("scope")
    if grant is None and len(grants) == 1:
        grant = next(iter(grants.values()))
    return {"active": active, "grant": grant}


def _interval_start(fact, state, spans, effective, rank, boundary=None):
    scope = deepcopy(state["grant"] or effective.get("scope", {}))
    scope.setdefault("runAliases", [])
    if boundary is not None:
        scope["beginning"] = deepcopy(boundary)
    scope.setdefault("beginning", {"kind": "unknown"})
    identity = fact["factId"]
    lifecycle = "closed" if effective.get("mode") == "human-ci" else "open"
    spans[identity] = {
        "participationId": fact["participationId"],
        "scope": scope,
        "lifecycle": lifecycle,
        "startFactId": identity,
        "facts": {identity},
        "ends": {},
        "rank": rank,
    }
    state["active"] = {identity}


def _interval_stop(fact, state, spans, effective, boundary, *, uncertain=False):
    known = not uncertain and _known_transition_boundary(effective, boundary)
    lifecycle = "closed" if known else "unknown"
    for identity in state["active"]:
        span = spans[identity]
        span["facts"].add(fact["factId"])
        key = content_hash({"boundary": boundary, "lifecycle": lifecycle})
        end = span["ends"].setdefault(
            key,
            {"boundary": deepcopy(boundary), "lifecycle": lifecycle, "facts": set()},
        )
        end["facts"].add(fact["factId"])
    state["active"] = set()


def _interval_transition(fact, state, spans, effective, rank):
    kind = fact["transitionKind"]
    if kind == "delegation":
        return
    uncertain = kind == "boundary-unknown" or fact.get("lifecycle") == "unknown"
    _interval_stop(fact, state, spans, effective, fact["boundary"], uncertain=uncertain)
    if kind == "resume" and fact["fromParticipationId"] == fact["toParticipationId"]:
        _interval_start(fact, state, spans, effective, rank, fact["boundary"])


def _interval_changed_source(state, spans):
    grant = state["grant"]
    if not grant:
        return False
    requested = tuple(
        grant.get(field)
        for field in ("sourceInstanceId", "sourceSessionId", "counterEpoch")
    )
    return any(
        tuple(
            spans[key]["scope"].get(field)
            for field in ("sourceInstanceId", "sourceSessionId", "counterEpoch")
        )
        != requested
        for key in state["active"]
    )


def _interval_review(fact, state, spans, effective):
    scope = fact.get("scope", {})
    ending = scope.get("ending")
    if (
        not fact.get("contextRequestDigest")
        or not ending
        or not _known_transition_boundary(effective, ending)
    ):
        return
    for identity, span in spans.items():
        same_start = span["scope"].get("beginning") == scope.get("beginning")
        same_source = _source_lineage({"scope": span["scope"]}) == _source_lineage(
            {"scope": scope}
        )
        if (
            span["participationId"] == fact["participationId"]
            and span["ends"]
            and same_start
            and same_source
        ):
            span["facts"].add(fact["factId"])
            span["ends"] = {
                content_hash(ending): {
                    "boundary": deepcopy(ending),
                    "lifecycle": "closed",
                    "facts": {fact["factId"]},
                }
            }
            state["active"].discard(identity)


def _interval_revise(fact, state, spans, effective, rank):
    if _interval_changed_source(state, spans):
        _interval_stop(fact, state, spans, effective, {"kind": "unknown"})
        _interval_start(fact, state, spans, effective, rank)
    _interval_review(fact, state, spans, effective)


def _interval_step(fact, state, spans, effective, rank):
    for identity in state["active"]:
        spans[identity]["facts"].add(fact["factId"])
    if fact["kind"] in {"declare", "declare-no-external-agent"}:
        _interval_start(fact, state, spans, effective, rank)
    elif fact["kind"] == "transition":
        _interval_transition(fact, state, spans, effective, rank)
    elif fact["kind"] == "boundary" and fact.get("lifecycle") in {"closed", "unknown"}:
        _interval_stop(fact, state, spans, effective, fact["boundary"])
    else:
        _interval_revise(fact, state, spans, effective, rank)


def _interval_result(span, active):
    scope = deepcopy(span["scope"])
    ends = list(span["ends"].values())
    conflicted = len(ends) > 1 or bool(ends and span["startFactId"] in active)
    lifecycle, end_fact = span["lifecycle"], None
    if conflicted:
        scope["ending"], lifecycle = {"kind": "unknown"}, "unknown"
    elif ends:
        scope["ending"], lifecycle = ends[0]["boundary"], ends[0]["lifecycle"]
        end_fact = min(ends[0]["facts"])
    return {
        "scope": scope,
        "lifecycle": lifecycle,
        "startFactId": span["startFactId"],
        "endFactId": end_fact,
        "factIds": sorted(span["facts"]),
        "conflicted": conflicted,
    }


def expected_participation_intervals(facts):
    """Separate responsibility intervals from reusable source/grant extents."""
    records = _validated_fact_records(facts)
    effective = _fact_states(records)
    states, spans = {}, {}
    for rank, identity in enumerate(_fact_order(records)):
        fact = records[identity]
        state = _interval_parent_state(fact, records, states)
        _interval_step(fact, state, spans, effective[identity], rank)
        states[identity] = state
    frontiers = _participation_frontiers(records)
    active = set().union(
        *(states[key]["active"] for keys in frontiers.values() for key in keys)
    )
    result = defaultdict(list)
    for span in sorted(spans.values(), key=lambda item: item["rank"]):
        result[span["participationId"]].append(_interval_result(span, active))
    return dict(result)
