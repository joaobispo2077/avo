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








































































































def _source_lineage(state):
    scope = state["scope"]
    return tuple(
        scope.get(key)
        for key in ("sourceInstanceId", "sourceSessionId", "counterEpoch")
    )






























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
