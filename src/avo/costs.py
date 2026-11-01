"""Deterministic token accounting and frozen decimal valuations."""

from __future__ import annotations

from collections import defaultdict, deque
from datetime import datetime
from decimal import Decimal, localcontext

from avo.cost_participation import (
    legacy_evidence_id,
    project_participation_facts,
    resolve_evidence,
    validate_reconciliation,
)
from avo.cost_store import CostError


def _leaves(rows, diagnostics):
    groups = defaultdict(list)
    result = []
    for row in rows:
        if row.get("measurementKind") == "cumulative":
            groups[
                (
                    row["sourceInstanceId"],
                    row["sourceSessionId"],
                    row.get("counterEpoch"),
                )
            ].append(row)
        else:
            result.append(row)
    for series in groups.values():
        if _has_request_overlap(series, result):
            diagnostics.append({"code": "counter-request-overlap"})
            continue
        _series_deltas(series, result, diagnostics)
    rollups = {_rollup_key(r) for r in result if r.get("inclusion") == "rollup"}
    return [r for r in result if _rollup_key(r, parent=True) not in rollups]


def _legacy_rollup(row):
    return (
        row.get("inclusion") == "rollup"
        and row.get("_nature", "legacy-unknown") == "legacy-unknown"
    )


def _rollup_key(row, *, parent=False):
    if not parent:
        return (
            row["sourceInstanceId"],
            row["sourceSessionId"],
            row.get("counterEpoch"),
            row["requestId"],
        )
    return (
        row.get("parentSourceInstanceId", row["sourceInstanceId"]),
        row.get("parentSessionId", row["sourceSessionId"]),
        row.get("parentCounterEpoch", row.get("counterEpoch")),
        row.get("parentRequestId"),
    )


def _series_deltas(series, result, diagnostics):
    previous = None
    for row in sorted(series, key=lambda r: r.get("sequence", -1)):
        if previous is not None:
            _delta(previous, row, result, diagnostics)
        previous = row


def _delta(previous, row, result, diagnostics):
    same = row["semantics"] == previous["semantics"]
    keys = set(row["tokens"]) | set(previous["tokens"])
    values = {k: row["tokens"].get(k) for k in keys}
    known = all(
        v is not None and previous["tokens"].get(k) is not None
        for k, v in values.items()
    )
    if (
        not same
        or not known
        or any(v < previous["tokens"][k] for k, v in values.items())
    ):
        diagnostics.append({"code": "ambiguous-counter-interval"})
        return
    delta = {k: v - previous["tokens"][k] for k, v in values.items()}
    result.append(
        _counter_identity(
            previous, {**row, "tokens": delta, "amounts": []}, diagnostics
        )
    )


def _counter_values(previous, row):
    if row["semantics"] != previous["semantics"]:
        return None
    if row.get("sequence", -1) <= previous.get("sequence", -1):
        return None
    delta = {}
    for key in set(previous["tokens"]) | set(row["tokens"]):
        before, after = previous["tokens"].get(key), row["tokens"].get(key)
        delta[key] = (
            after - before if before is not None and after is not None else None
        )
        if delta[key] is not None and delta[key] < 0:
            return None
    return delta


def _counter_attribution(previous, row):
    state = row.get("_attributionState", "assigned")
    if state != "assigned":
        return state
    before, after = previous.get("_evidence") or {}, row.get("_evidence") or {}
    same = before.get("participationId") == after.get("participationId")
    same = same and _scope_boundaries(before) == _scope_boundaries(after)
    if previous.get("_attributionState", "assigned") == "assigned" and same:
        return state
    return state if _counter_boundary_proven(previous, row) else "unallocated"


def _scope_boundaries(metadata):
    scope = metadata.get("attribution", {}).get("scope", {})
    return {key: value for key, value in scope.items() if key != "runAliases"}


def _counter_boundary_proven(previous, row):
    metadata = row.get("_evidence") or {}
    reference = metadata.get("interval", {}).get("start", {}).get("reference")
    return reference == previous["requestId"] and reference in row.get(
        "_baselineRefs", ()
    )


def _has_request_overlap(series, rows):
    key = (series[0]["sourceInstanceId"], series[0]["sourceSessionId"])
    return any(
        (r["sourceInstanceId"], r["sourceSessionId"]) == key
        and r.get("measurementKind") != "cumulative"
        for r in rows
    )


def _counter_identity(previous, row, diagnostics):
    if any(row.get(k) != previous.get(k) for k in ("model", "serviceProvider")):
        diagnostics.append({"code": "mixed-model-counter-interval"})
        return {**row, "model": None, "serviceProvider": None, "_prices": []}
    return row


def _counter_dimensions(previous, row, diagnostics):
    for key, unknown in (
        ("phase", None),
        ("agent", "unknown"),
        ("billingMode", "unknown"),
    ):
        if previous.get(key) != row.get(key):
            row = {**row, key: unknown}
    if previous.get("pricingDimensions", {}) != row.get("pricingDimensions", {}):
        diagnostics.append({"code": "mixed-pricing-counter-interval"})
        row = {**row, "_prices": []}
    return row


def _token_total(row):
    tokens = row["tokens"]
    if tokens.get("total") is not None:
        return tokens["total"]
    if tokens.get("input") is None or tokens.get("output") is None:
        return None
    extra = _extra_tokens(row)
    return tokens["input"] + tokens["output"] + extra if extra is not None else None


def _extra_tokens(row):
    total = 0
    for key in ("cacheRead", "cacheWrite", "reasoning", "tool"):
        if key not in row["tokens"]:
            continue
        value = row["tokens"][key]
        relation = row["semantics"].get(key, "unknown")
        if relation == "unknown":
            return None
        if relation == "disjoint":
            if value is None:
                return None
            total += value
    return total


def _estimate(row, prices):
    price = _matching_price(row, prices)
    if price is None:
        return []
    buckets = _priced_buckets(row, price)
    if buckets is None:
        return []
    value = (
        sum(Decimal(rate) * buckets[k] for k, rate in price["rates"].items())
        / price["denominator"]
    )
    return [
        {
            "basis": price["basis"],
            "unit": price["unit"],
            "amount": format(value, "f"),
            "provenance": price["provenance"],
        }
    ]


def _tariff_value(rates, counts, denominator):
    """Keep finite products exact; recurring ratios use at least 28 significant digits."""
    terms = [(Decimal(rate), counts[key]) for key, rate in rates.items()]
    high = max(rate.adjusted() + len(str(count)) for rate, count in terms)
    low = min(rate.as_tuple().exponent for rate, _ in terms)
    precision = high - low + len(str(len(terms))) + 4 * len(str(denominator)) + 4
    with localcontext(prec=max(28, precision)):
        return sum((rate * count for rate, count in terms), Decimal(0)) / denominator


def _matching_price(row, prices):
    matches = [
        p
        for p in prices
        if p["model"] == row["model"]
        and p["serviceProvider"] == row["serviceProvider"]
        and _dimensions_match(row, p)
        and row["occurredAt"]
        and _time(p["effectiveAt"]) <= _time(row["occurredAt"])
    ]
    if not matches:
        return None
    return max(
        matches, key=lambda p: (_time(p["effectiveAt"]), len(p.get("dimensions", {})))
    )


def _dimensions_match(row, price):
    actual = row.get("pricingDimensions", {})
    return all(actual.get(k) == v for k, v in price.get("dimensions", {}).items())


def _priced_buckets(row, price):
    buckets = dict(row["tokens"])
    if buckets.get("input") is None or buckets.get("output") is None:
        return None
    if not _covered_categories(row, price):
        return None
    if not _subtract_subsets(buckets, row["semantics"], price["rates"]):
        return None
    if not _priceable(buckets, price["rates"]):
        return None
    return buckets


def _priceable(buckets, rates):
    return not any(buckets.get(k) is None or buckets[k] < 0 for k in rates) and not any(
        buckets[k] > 0 and k not in rates for k in ("input", "output")
    )


def _subtract_subsets(buckets, semantics, rates):
    for key, parent in semantics.items():
        if parent in {"input", "output"} and key in rates:
            if buckets.get(parent) is None or buckets.get(key) is None:
                return False
            buckets[parent] -= buckets[key]
    return True


def _covered_categories(row, price):
    for key in ("cacheRead", "cacheWrite", "reasoning", "tool"):
        value = row["tokens"].get(key)
        relation = row["semantics"].get(key, "unknown")
        if value == 0:
            continue
        if relation == "unknown" and key in row["tokens"]:
            return False
        if value is None:
            if key in price["rates"] or relation == "disjoint":
                return False
            continue
        if relation == "disjoint" and key not in price["rates"]:
            return False
    return True


def _amount_values(valuations):
    seen = set()
    result = []
    for value in valuations:
        key = (value["basis"], value["unit"])
        if key in seen:
            raise CostError("duplicate alternate valuation for one observation")
        result.append((key, Decimal(value["amount"])))
        seen.add(key)
    return result


def _measurement(row, prices):
    measured = row.get("_measured")
    if measured is not None:
        return measured
    valuations = row["amounts"] or _estimate(row, row.get("_prices", prices))
    amounts = _amount_values(valuations)
    items = [(k, v) for k, v in row["tokens"].items() if k != "total" and v is not None]
    measured = (_token_total(row), items, amounts, not bool(valuations))
    row["_measured"] = measured
    return measured


def _aggregate(rows, prices):
    amounts = defaultdict(Decimal)
    tokens = {}
    totals = []
    unpriced = 0
    for row in rows:
        total, items, values, missing = _measurement(row, prices)
        totals.append(total)
        for key, value in items:
            tokens[key] = tokens.get(key, 0) + value
        for key, value in values:
            amounts[key] += value
        unpriced += missing
    tokens["total"] = sum(totals) if totals and None not in totals else None
    return (
        tokens,
        [
            {"basis": b, "unit": u, "amount": format(v, "f")}
            for (b, u), v in sorted(amounts.items())
        ],
        unpriced,
    )


def _decimal_sum(values):
    values = list(values)
    if not values:
        return Decimal(0)
    precision = max(value.adjusted() for value in values) - min(
        value.as_tuple().exponent for value in values
    )
    with localcontext(prec=max(28, precision + len(str(len(values))) + 2)):
        return sum(values, Decimal(0))


def _breakdowns(rows, prices, total):
    breakdowns = {}
    for dimension in ("model", "serviceProvider", "agent", "phase", "serviceClass"):
        groups = defaultdict(list)
        for row in rows:
            groups[row.get(dimension) or "unknown"].append(row)
        breakdowns[dimension] = {
            key: total if len(group) == len(rows) else _group_report(group, prices)
            for key, group in sorted(groups.items())
        }
    return breakdowns


def _group_report(rows, prices):
    tokens, amounts, _ = _aggregate(rows, prices)
    return {"tokens": tokens, "amounts": amounts}


def summarize(store, *, phase=None):
    identity = store.identity() or {}
    view = store.capture()
    observations, diagnostics = store.observations(view)
    rows = _leaves(observations, diagnostics)
    if phase:
        rows = [r for r in rows if r.get("phase") == phase]
    prices = view["prices"]
    tokens, amounts, unpriced = _aggregate(rows, prices)
    if unpriced:
        diagnostics.append({"code": "unpriced-usage", "count": unpriced})
    # Imported events alone cannot prove all external usage has been collected.
    coverage = "partial" if rows or diagnostics else "not-recorded"
    return {
        "schemaVersion": "1.0.0",
        "status": "ok",
        "accountingVideoId": identity.get("accountingVideoId"),
        "provider": identity.get("provider"),
        "videoId": identity.get("videoId"),
        "lifecycle": "working",
        "coverage": coverage,
        "cutoff": _cutoff(rows),
        "lastCollectedAt": _last_collected(view["batches"]),
        "sourceWatermarks": _watermarks(observations),
        "tokens": tokens,
        "amounts": amounts,
        "observationCount": len(rows),
        "breakdowns": _breakdowns(rows, prices, {"tokens": tokens, "amounts": amounts}),
        "diagnostics": diagnostics,
        "pendingTurn": True,
        "excludedCosts": [
            "labor",
            "hardware",
            "electricity",
            "unallocated subscriptions",
            "unreported service usage",
        ],
        "membership": _membership(view, store),
    }


def _continuity_fields(store, view, projection, rows, diagnostics, tokens):
    sources = _source_coverage(store, view, projection)
    participants = _participation_summaries(view, projection, sources, diagnostics)
    pending = _pending(
        [item["pendingState"] for item in participants + sources]
        + ([] if participants else ["unknown"])
    )
    unallocated = _group_report(projection["unallocated"], view["prices"])
    conflicts = _conflict_summary(projection["conflict"], view["prices"])
    closure = store.closure_status(view)
    if closure["stale"]:
        diagnostics.append({"code": "closure-stale"})
    return {
        "coverage": _overall_coverage(view, projection, participants, sources),
        "pendingTurn": None if pending == "unknown" else pending != "none",
        "pendingState": pending,
        "usageByNature": _usage_by_nature(
            rows, projection["estimates"], view["prices"], tokens
        ),
        "participations": participants,
        "coverageBySource": sources,
        "selectedEvidenceIds": sorted(
            item["evidenceId"] for item in projection["selected"]
        ),
        "activeEstimateIds": sorted(
            item["estimateId"]
            for item in projection["estimateViews"]
            if item["status"] != "replaced"
        ),
        "estimateViews": projection["estimateViews"],
        "activityEvidenceIds": _activity_ids(rows),
        "unallocatedEvidenceIds": _activity_ids(projection["unallocated"]),
        "conflictEvidenceIds": _activity_ids(projection["conflict"]),
        "excludedEvidenceIds": _activity_ids(projection["excluded"]),
        "representationConflicts": _representation_conflicts(
            projection["conflict"], view["prices"]
        ),
        "unallocated": unallocated,
        "conflicts": conflicts,
        "previousClosureId": closure["previousClosureId"],
        "diagnostics": [_safe_diagnostic(item) for item in diagnostics],
    }


def _evidence_projection(store, view, observations, diagnostics):
    metadata = _observation_metadata(store, view["batches"])
    if _only_legacy_evidence(view):
        return _legacy_projection(metadata, observations, diagnostics)
    known = store.references(view)
    resolved = resolve_evidence(metadata, view["reconciliations"], known_refs=known)
    diagnostics.extend(resolved["conflicts"])
    selected = {
        (item["key"]["observationId"], item["key"]["sourceDigest"]): item
        for item in resolved["selected"]
    }
    result = {"assigned": [], "unallocated": [], "conflict": [], "excluded": []}
    result["raw"] = observations
    baselines = _accepted_baselines(view["batches"])
    projected = []
    for row in observations:
        item = selected.get((row["observationId"], row["_sourceDigest"]))
        current = _projected_observation(row, item)
        current["_baselineRefs"] = baselines.get(_baseline_scope(current), set())
        projected.append(current)
    activities = _activity_projection(
        store, view, _leaves(projected, diagnostics), diagnostics, known
    )
    result["roleRows"] = activities.pop("roleRows")
    result["excluded"] = activities.pop("excluded")
    for row in activities["rows"]:
        result[row["_attributionState"]].append(row)
    result.update(metadata=metadata, selected=resolved["selected"])
    result["estimateViews"] = _estimate_views(
        store, view, result["assigned"], diagnostics, known
    )
    active = {
        item["estimateId"]
        for item in result["estimateViews"]
        if item["status"] == "active"
    }
    result["estimates"] = [
        item for item in view["estimates"] if item["estimateId"] in active
    ]
    return result


def _only_legacy_evidence(view):
    return (
        not view["reconciliations"]
        and not view["estimates"]
        and all(batch["schemaVersion"] == "1.0.0" for batch in view["batches"])
    )


def _legacy_projection(metadata, observations, diagnostics):
    # Generated v1 identities have no native composition or metadata revisions.
    selected = {_key_tuple(item["key"]): item for item in metadata}
    # observations() owns these top-level copies; canonical nested fields stay intact.
    for row in observations:
        item = selected.get((row["observationId"], row["_sourceDigest"]))
        row.update(
            _nature="legacy-unknown",
            _evidence=item,
            _attributionState="assigned" if item else "conflict",
        )
    rows = _leaves(observations, diagnostics)
    result = {
        state: [row for row in rows if row["_attributionState"] == state]
        for state in ("assigned", "unallocated", "conflict", "excluded")
    }
    result.update(
        raw=observations,
        roleRows=result["assigned"],
        metadata=metadata,
        selected=metadata,
        estimateViews=[],
        estimates=[],
    )
    return result


def _activity_ids(rows):
    return sorted(
        {row["_evidence"]["evidenceId"] for row in rows if row.get("_evidence")}
    )


def _activity_projection(store, view, rows, diagnostics, known):
    indexed = {
        row["_evidence"]["evidenceId"]: row for row in rows if row.get("_evidence")
    }
    choices, reviewed = _activity_choices(store, view, known)
    groups, uncertain = _native_composition(view, indexed, choices)
    selected, conflicts = _resolve_activity_choices(indexed, choices, uncertain)
    current, excluded = _partition_activities(
        view, indexed, selected, conflicts, reviewed
    )
    current.extend(row for row in rows if row.get("_evidence") is None)
    if uncertain:
        diagnostics.append(
            {
                "code": "cost-aggregate-composition-unproven",
                "variants": sorted(uncertain),
            }
        )
    if conflicts - uncertain:
        diagnostics.append(
            {
                "code": "cost-activity-selection-conflict",
                "variants": sorted(conflicts - uncertain),
            }
        )
    return {
        "rows": current,
        "excluded": excluded,
        "roleRows": _activity_role_rows(current, indexed, groups),
    }


def _activity_choices(store, view, known):
    choices, reviewed = defaultdict(set), set()
    for decision in _active_decisions(view["reconciliations"]):
        if decision["relation"] not in {"same-activity", "covers-rollup", "allocation"}:
            continue
        validate_reconciliation(decision, known_refs=known)
        if decision["relation"] == "allocation":
            _allocation_choices(
                decision, choices, store.identity()["accountingVideoId"]
            )
            continue
        members = {
            ref["id"] for ref in decision["references"] if ref["kind"] == "evidence"
        }
        selected = _decision_selection(decision)
        reviewed.update(members)
        for identity in members - selected:
            choices[identity].add(frozenset(selected))
    return choices, reviewed


def _decision_selection(decision):
    plural = decision.get("selectedRepresentations")
    if plural is not None:
        return {item["id"] for item in plural}
    selected = decision["selectedRepresentation"]
    return {selected["id"]} if selected else set()


def _allocation_choices(decision, choices, accounting_id):
    for allocation in decision.get("allocations", []):
        if allocation["accountingVideoId"] != accounting_id:
            choices[allocation["reference"]["id"]].add(frozenset())


def _native_composition(view, indexed, choices):
    profiles = {item["profileId"]: item for item in view["profiles"]}
    keys = {
        _key_tuple(row["_evidence"]["key"]): identity
        for identity, row in indexed.items()
    }
    groups, uncertain = {}, set()
    dependencies, parents = _activity_dependencies(indexed, choices)
    canonical = _activity_terminals(dependencies, parents, choices)
    for identity, row in indexed.items():
        metadata = row["_evidence"]
        aggregate = metadata.get("aggregateScope", {})
        if aggregate.get("kind", "request") == "request":
            continue
        related = _aggregate_related(row, indexed)
        members = _aggregate_members(aggregate, keys)
        if not _composition_proven(metadata, profiles, members, related):
            if related:
                uncertain.update({identity, *related, *members})
            continue
        groups[identity] = members
        if any(set(selected) == members for selected in choices.get(identity, ())):
            continue
        if not _cover_representatives(identity, members, canonical, choices):
            uncertain.update({identity, *members})
    return groups, uncertain


def _cover_representatives(identity, members, canonical, choices):
    destination = canonical.get(identity)
    if destination is None:
        destination = frozenset({identity})
    for member in members:
        selected = canonical.get(member)
        if selected is None:
            selected = frozenset({member})
        if not selected and destination:
            return False
        if selected == destination:
            continue
        if selected & destination:
            return False
        for target in selected - destination:
            choices[target].add(destination)
    return True


def _aggregate_members(aggregate, keys):
    return {
        keys[_key_tuple(key)]
        for key in aggregate.get("members", [])
        if _key_tuple(key) in keys
    }


def _key_tuple(key):
    return key["observationId"], key["sourceDigest"]


def _aggregate_related(row, indexed):
    return {
        identity
        for identity, candidate in indexed.items()
        if candidate is not row
        and _rollup_key(candidate, parent=True) == _rollup_key(row)
    }


def _composition_proven(metadata, profiles, members, related):
    aggregate = metadata["aggregateScope"]
    frozen = profiles.get(metadata.get("profileId"), {})
    return bool(
        aggregate["members"]
        and aggregate["proofRefs"]
        and len(members) == len(aggregate["members"])
        and related <= members
        and frozen.get("capability") == "qualified"
        and frozen.get("semantics", {}).get("aggregateScope") == aggregate["kind"]
    )


def _resolve_activity_choices(indexed, choices, uncertain):
    dependencies, parents = _activity_dependencies(indexed, choices)
    resolved = _activity_terminals(dependencies, parents, choices)
    conflicts = _activity_conflicts(indexed, dependencies, parents, resolved, uncertain)
    selected = set().union(
        *(
            terminals
            for identity, terminals in resolved.items()
            if identity not in conflicts and terminals is not None
        )
    )
    return selected & indexed.keys(), conflicts & indexed.keys()


def _activity_dependencies(indexed, choices):
    dependencies, parents = defaultdict(set), defaultdict(set)
    for identity in set(indexed) | choices.keys():
        for selected in choices.get(identity, ()):
            dependencies[identity].update(selected)
        for target in dependencies[identity]:
            parents[target].add(identity)
    for identity in list(parents):
        dependencies[identity]
    return dependencies, parents


def _activity_terminals(dependencies, parents, choices):
    remaining = {identity: len(targets) for identity, targets in dependencies.items()}
    ready = deque(identity for identity, count in remaining.items() if not count)
    resolved = {}
    while ready:
        identity = ready.popleft()
        resolved[identity] = _terminal_choice(identity, choices, resolved)
        for parent in parents[identity]:
            remaining[parent] -= 1
            if not remaining[parent]:
                ready.append(parent)
    return {identity: resolved.get(identity) for identity in dependencies}


def _terminal_choice(identity, choices, resolved):
    results = {
        _terminal_set(selected, resolved) for selected in choices.get(identity, ())
    }
    if not results:
        return frozenset({identity})
    return next(iter(results)) if len(results) == 1 else None


def _terminal_set(selected, resolved):
    terminals = [resolved[target] for target in selected]
    return None if None in terminals else frozenset().union(*terminals)


def _activity_conflicts(indexed, dependencies, parents, resolved, uncertain):
    conflicts = set(uncertain) | {
        identity
        for identity, value in resolved.items()
        if value is None or identity not in indexed
    }
    pending = deque(conflicts)
    while pending:
        identity = pending.popleft()
        for adjacent in dependencies[identity] | parents[identity]:
            if adjacent not in conflicts:
                conflicts.add(adjacent)
                pending.append(adjacent)
    return conflicts


def _partition_activities(view, indexed, selected, conflicts, reviewed):
    profiles = {item["profileId"]: item for item in view["profiles"]}
    bounded = _inherited_boundaries(view)
    current, excluded = [], []
    for identity, row in indexed.items():
        if identity in conflicts:
            current.append(
                {
                    **row,
                    "_attributionState": "conflict",
                    "_representationConflict": True,
                }
            )
        elif identity not in selected:
            excluded.append(row)
        elif identity not in reviewed and _copied_history(row, profiles, bounded):
            current.append({**row, "_attributionState": "unallocated"})
        else:
            current.append(row)
    return current, excluded


def _copied_history(row, profiles, bounded):
    frozen = profiles.get(row["_evidence"].get("profileId"), {})
    key = (row["_evidence"].get("profileId"), *_key_tuple(row["_evidence"]["key"]))
    return bool(
        row.get("parentSessionId")
        and row["parentSessionId"] != row["sourceSessionId"]
        and frozen.get("semantics", {}).get("fork") == "copied-history"
        and key not in bounded
    )


def _inherited_boundaries(view):
    bindings = {
        item["bindingId"]
        for item in view["bindings"]
        if item["boundary"] != "beginning"
    }
    return {
        (receipt["profileId"], *_key_tuple(key))
        for batch in view["batches"]
        for receipt in batch.get("receipts", [])
        if receipt["bindingId"] in bindings
        for key in receipt["observationKeys"]
    }


def _conflict_summary(rows, prices):
    known = [row for row in rows if not row.get("_representationConflict")]
    result = _group_report(known, prices)
    if len(known) != len(rows):
        result["tokens"]["total"] = None
    return result


def _representation_conflicts(rows, prices):
    return [
        {
            "evidenceId": row["_evidence"]["evidenceId"],
            "key": row["_evidence"]["key"],
            **_group_report([row], prices),
        }
        for row in rows
        if row.get("_representationConflict")
    ]


def _activity_role_rows(rows, indexed, groups):
    result = []
    for row in rows:
        if row["_attributionState"] != "assigned":
            continue
        identity = row["_evidence"]["evidenceId"]
        members = groups.get(identity)
        if members:
            result.extend(indexed[member] for member in members)
        else:
            result.append(row)
    return result


def _baseline_scope(row):
    return (
        (row.get("_evidence") or {}).get("profileId"),
        row["sourceInstanceId"],
        row["sourceSessionId"],
        row.get("counterEpoch"),
    )


def _accepted_baselines(batches):
    result = defaultdict(set)
    for batch in batches:
        for receipt in batch.get("receipts", []):
            baseline = receipt["baseline"]
            if baseline["status"] == "accepted" and baseline["reference"] is not None:
                key = tuple(
                    receipt[field]
                    for field in (
                        "profileId",
                        "sourceInstanceId",
                        "sourceSessionId",
                        "counterEpoch",
                    )
                )
                result[key].add(baseline["reference"])
    return result


def _observation_metadata(store, batches):
    metadata = [item for batch in batches for item in batch.get("evidence", [])]
    legacy = {}
    for batch in batches:
        if batch["schemaVersion"] != "1.0.0":
            continue
        keys = batch.get("observationKeys") or store.keys_for(batch["observations"])
        for key in keys:
            identity = legacy_evidence_id(key)
            legacy[identity] = {
                "evidenceId": identity,
                "key": key,
                "nature": "legacy-unknown",
            }
    return metadata + list(legacy.values())


def _projected_observation(row, metadata):
    result = {
        **row,
        "_nature": metadata["nature"] if metadata else "legacy-unknown",
        "_evidence": metadata,
        "_attributionState": metadata.get("attribution", {}).get("status", "assigned")
        if metadata
        else "conflict",
    }
    if (
        metadata
        and metadata["nature"] != "legacy-unknown"
        and metadata["modelBasis"] != "served"
    ):
        result.update(model=None, _prices=[])
    return result


def _active_decisions(decisions):
    superseded = {identity for item in decisions for identity in item["supersedes"]}
    return [item for item in decisions if item["reconciliationId"] not in superseded]


def _replacement_choices(view, known):
    choices = defaultdict(set)
    for decision in _active_decisions(view["reconciliations"]):
        if decision["relation"] != "replaces-estimate":
            continue
        validate_reconciliation(decision, known_refs=known)
        selected = decision["selectedRepresentation"]
        for ref in decision["references"]:
            if ref["kind"] == "estimate":
                choices[ref["id"]].add((selected["kind"], selected["id"]))
    return choices


def _estimate_views(store, view, rows, diagnostics, known):
    selected = {row["_evidence"]["evidenceId"] for row in rows}
    choices = _replacement_choices(view, known)
    result = []
    for item in sorted(view["estimates"], key=lambda value: value["estimateId"]):
        candidates = choices.get(item["estimateId"], set())
        status, representation = _estimate_selection(candidates, selected)
        if status == "active" and _estimate_overlap(item, view["estimates"], rows):
            status = "conflict"
        if status == "conflict":
            diagnostics.append(
                {
                    "code": "cost-estimate-overlap-unresolved",
                    "variants": [item["estimateId"]],
                }
            )
        result.append(
            _estimate_view(item, view["prices"], status, representation, store)
        )
    return result


def _estimate_selection(candidates, selected):
    if not candidates:
        return "active", None
    if len(candidates) == 1:
        kind, identity = next(iter(candidates))
        if kind == "evidence" and identity in selected:
            return "replaced", {"kind": kind, "id": identity}
    return "conflict", None


def _estimate_overlap(item, estimates, rows):
    others = [value for value in estimates if value["estimateId"] != item["estimateId"]]
    others.extend(
        {
            "participationId": row["_evidence"].get("participationId"),
            "scope": row["_evidence"].get("attribution", {}).get("scope", {}),
        }
        for row in rows
    )
    return any(
        _same_estimate_subject(item, value)
        and _scopes_may_overlap(item["scope"], value["scope"])
        for value in others
    )


def _same_estimate_subject(left, right):
    if left["participationId"] == right["participationId"]:
        return True
    fields = ("sourceInstanceId", "sourceSessionId", "counterEpoch")
    return all(
        left["scope"].get(key) is not None
        and left["scope"].get(key) == right["scope"].get(key)
        for key in fields
    )


def _scopes_may_overlap(left, right):
    for field in ("sourceInstanceId", "sourceSessionId", "counterEpoch"):
        if left.get(field) and right.get(field) and left[field] != right[field]:
            return False
    return not (_scope_precedes(left, right) or _scope_precedes(right, left))


def _scope_precedes(left, right):
    ending, beginning = left.get("ending", {}), right.get("beginning", {})
    if ending.get("at") and beginning.get("at"):
        return _time(ending["at"]) <= _time(beginning["at"])
    return bool(ending.get("reference") and ending == beginning and left != right)


def _estimate_view(item, prices, status, representation, store):
    result = {
        key: item[key]
        for key in (
            "estimateId",
            "participationId",
            "scope",
            "method",
            "methodVersion",
            "inputManifest",
            "tokens",
            "ranges",
            "assumptions",
            "limitations",
        )
    }
    result.update(
        status=status,
        selectedRepresentation=representation,
        priceScheduleIds=item.get("priceScheduleIds", []),
    )
    if "manualBasis" in item:
        result["manualBasis"] = item["manualBasis"]
    return {**result, **_estimate_finances(item, prices, store)}


def _estimate_finances(item, prices, store):
    context = item.get("pricingContext")
    empty = {
        "amounts": [],
        "amountRanges": [],
        "missingPrerequisites": [],
        "pricingContext": context,
        "selectedPriceScheduleId": None,
        "valuationEffectiveAt": None,
    }
    if not context:
        return {**empty, "missingPrerequisites": ["pricing-context-missing"]}
    model = item["inputManifest"]["model"]
    if model is not None and model != context["model"]:
        return {**empty, "missingPrerequisites": ["estimate-model-mismatch"]}
    frozen = [
        price
        for price in prices
        if store.digest(price) in item.get("priceScheduleIds", [])
    ]
    row = {**context, "pricingDimensions": context["dimensions"]}
    price = _matching_price(row, frozen)
    if price is None:
        return {**empty, "missingPrerequisites": ["frozen-price-unavailable"]}
    empty.update(
        selectedPriceScheduleId=store.digest(price),
        valuationEffectiveAt=price["effectiveAt"],
    )
    values = _estimate_values(item, price)
    if values is None:
        return {**empty, "missingPrerequisites": ["estimate-categories-unpriceable"]}
    amount = {
        "basis": price["basis"],
        "unit": price["unit"],
        "provenance": price["provenance"],
    }
    if item["ranges"] is not None:
        return {
            **empty,
            "amountRanges": [
                {
                    **amount,
                    "min": values[0],
                    "max": values[1],
                    "priceScheduleId": store.digest(price),
                }
            ],
        }
    return {**empty, "amounts": [{**amount, "amount": values[0]}]}


def _estimate_values(item, price):
    counts = item["ranges"] if item["ranges"] is not None else item["tokens"]
    categories = set(counts or {}) - {"total"}
    if not categories or not categories <= {"input", "output"}:
        return None
    if any(key not in price["rates"] or counts[key] is None for key in categories):
        return None
    endpoints = ("minimum", "maximum") if item["ranges"] is not None else (None,)
    return [
        _estimate_value(counts, categories, price, endpoint) for endpoint in endpoints
    ]


def _estimate_value(counts, categories, price, endpoint):
    buckets = {
        key: counts[key][endpoint] if endpoint else counts[key] for key in categories
    }
    rates = {key: price["rates"][key] for key in categories}
    value = _tariff_value(rates, buckets, price["denominator"])
    return format(value, "f")


def _financial_views(rows, prices, store, amounts):
    groups = defaultdict(list)
    for row in rows:
        values = row["amounts"] or _estimate(row, row.get("_prices", prices))
        for value in values:
            groups[(value["basis"], value["unit"])].append(
                _valuation_detail(row, value, store)
            )
    totals = {(value["basis"], value["unit"]): value["amount"] for value in amounts}
    return [
        {
            "basis": basis,
            "unit": unit,
            "amount": totals[(basis, unit)],
            "interpretation": _financial_interpretation(basis),
            "valuations": values,
        }
        for (basis, unit), values in sorted(groups.items())
    ]


def _valuation_detail(row, value, store):
    metadata = row["_evidence"]
    price = None if row["amounts"] else _matching_price(row, row.get("_prices", []))
    return {
        "reference": {"kind": "evidence", "id": metadata["evidenceId"]},
        "amount": value["amount"],
        "provenance": value["provenance"],
        "model": row["model"],
        "serviceProvider": row["serviceProvider"],
        "modelBasis": metadata.get("modelBasis", "unknown"),
        "occurredAt": row["occurredAt"],
        "priceScheduleId": store.digest(price) if price else None,
        "effectiveAt": price["effectiveAt"] if price else None,
        "dimensions": row.get("pricingDimensions", {}),
    }


def _financial_interpretation(basis):
    return {
        "source-reported": "reported amount; charge interpretation unverified",
        "calculated-estimate": "calculated estimate",
        "api-equivalent": "API reference equivalent",
        "manual": "manual allocation/declaration",
    }[basis]


def _usage_by_nature(rows, estimates, prices, tokens):
    groups = defaultdict(list)
    for row in rows:
        groups[row["_nature"]].append(row)
    result = {
        kind: tokens
        if rows and len(groups[kind]) == len(rows)
        else _aggregate(groups[kind], prices)[0]
        for kind in ("measured", "manual", "legacy-unknown")
    }
    estimated = [
        {
            "tokens": item["tokens"],
            "semantics": {},
            "amounts": [],
            "model": None,
            "serviceProvider": None,
            "occurredAt": None,
            "_prices": [],
        }
        for item in estimates
        if item["tokens"] is not None
    ]
    result["estimated"] = _aggregate(estimated, [])[0]
    return result


def _pending(states):
    return next(
        (state for state in ("open", "settling", "unknown") if state in states), "none"
    )


def _receipt_pending(receipt):
    state = receipt["lifecycle"]["state"]
    if state == "closed":
        settled = (
            receipt["lifecycle"]["reference"]
            and receipt["flush"]["status"] == "accepted"
            and receipt["flush"]["reference"]
        )
        return "none" if settled else "settling"
    return state


def _source_coverage(store, view, projection):
    groups = defaultdict(dict)
    for batch in view["batches"]:
        for receipt in batch.get("receipts", []):
            key = tuple(
                receipt[field]
                for field in (
                    "profileId",
                    "sourceInstanceId",
                    "sourceSessionId",
                    "counterEpoch",
                    "bindingId",
                )
            )
            groups[key][receipt["receiptId"]] = receipt
    if not groups:
        return []
    owners = defaultdict(set)
    for item in projection["metadata"]:
        if "participationId" in item:
            owners[(item["profileId"], store.digest(item["key"]))].add(
                item["participationId"]
            )
    knowledge = _coverage_knowledge(view, projection)
    return [
        _source_summary(store, key, receipts, owners, knowledge)
        for key, receipts in sorted(groups.items(), key=lambda item: repr(item[0]))
    ]


def _source_summary(store, key, receipts, owners, knowledge):
    frontier = _receipt_frontier(receipts)
    pending, baseline, gaps = _source_finality(frontier, receipts)
    source_scope = _source_scope(key, frontier)
    reasons = _source_coverage_gaps(
        key, receipts, frontier, knowledge, pending, source_scope
    )
    return {
        "participationId": _source_participation(store, key, receipts, owners),
        "profileId": key[0],
        "bindingId": key[4],
        "coverage": "complete-for-declared-sources"
        if not gaps and not reasons
        else "partial",
        "pendingState": pending,
        "baselineStatus": baseline,
        "receiptIds": sorted(receipts),
        "gaps": sorted(set(gaps) | set(reasons)),
        "sourceScope": source_scope,
        "lastCollectedAt": max(
            (item["collectedAt"] for item in receipts.values()), key=_time
        ),
    }


def _coverage_knowledge(view, projection):
    return {
        "profiles": {item["profileId"]: item for item in view["profiles"]},
        "metadata": {
            (item.get("profileId"), *_key_tuple(item["key"])): item
            for item in projection["selected"]
        },
        "raw": {
            (row["observationId"], row["_sourceDigest"]): row
            for row in projection["raw"]
        },
        "states": {
            _key_tuple(row["_evidence"]["key"]): state
            for state in ("assigned", "unallocated", "conflict", "excluded")
            for row in projection[state]
            if row.get("_evidence")
        },
    }


def _source_scope(key, frontier):
    if len(frontier) != 1:
        return {"runAliases": [], "beginning": {"kind": "unknown"}}
    interval = frontier[0]["interval"]
    return {
        "runAliases": [],
        "sourceInstanceId": key[1],
        "sourceSessionId": key[2],
        "counterEpoch": key[3],
        "beginning": interval["start"],
        "ending": interval["end"],
    }


def _source_coverage_gaps(key, receipts, frontier, knowledge, pending, scope):
    profile = knowledge["profiles"].get(key[0], {})
    reasons = []
    if profile.get("capability") != "qualified":
        reasons.append("source-profile-unqualified")
    if profile.get("semantics", {}).get("finality") != "source-flush":
        reasons.append("source-finality-unproven")
    if pending != "none":
        reasons.append("source-usage-pending")
    if not _bounded_scope(scope):
        reasons.append("source-bounds-unproven")
    if not _source_baseline_known(profile, frontier, key, knowledge):
        reasons.append("baseline-unavailable")
    if not _source_counts_known(key, receipts, knowledge):
        reasons.append("source-count-coverage-incomplete")
    return reasons


def _source_baseline_known(profile, frontier, source_key=None, knowledge=None):
    if len(frontier) != 1:
        return False
    baseline = frontier[0]["baseline"]
    counter = profile.get("semantics", {}).get("counter")
    if counter == "cumulative":
        return baseline["status"] == "accepted" and _native_baseline_snapshot(
            baseline["reference"], source_key, knowledge
        )
    return counter == "request" and baseline["status"] == "not-applicable"


def _native_baseline_snapshot(reference, source_key, knowledge):
    if reference is None or source_key is None or knowledge is None:
        return False
    for key, metadata in knowledge["metadata"].items():
        row = knowledge["raw"].get(key[1:])
        if (
            key[0] == source_key[0]
            and metadata.get("nature") == "measured"
            and row is not None
            and _baseline_snapshot_matches(row, metadata, reference, source_key)
        ):
            return True
    return False


def _baseline_snapshot_matches(row, metadata, reference, source_key):
    lineage = (row["sourceInstanceId"], row["sourceSessionId"], row.get("counterEpoch"))
    return (
        row.get("measurementKind") == "cumulative"
        and lineage == source_key[1:4]
        and reference in {row["requestId"], metadata.get("sourceEventId")}
        and _token_total(row) is not None
    )


def _source_counts_known(key, receipts, knowledge):
    keys = {
        _key_tuple(item)
        for receipt in receipts.values()
        for item in receipt["observationKeys"]
    }
    baselines = {
        receipt["baseline"]["reference"]
        for receipt in receipts.values()
        if receipt["baseline"]["status"] == "accepted"
    }
    if not keys:
        return False
    return all(_source_key_known(key[0], item, baselines, knowledge) for item in keys)


def _source_key_known(profile_id, key, baselines, knowledge):
    metadata = knowledge["metadata"].get((profile_id, *key), {})
    row = knowledge["raw"].get(key)
    if metadata.get("nature") != "measured" or row is None or _token_total(row) is None:
        return False
    if row.get("measurementKind") == "cumulative" and row["requestId"] in baselines:
        return True
    return (
        knowledge["states"].get(key) in {"assigned", "excluded"}
        and metadata.get("attribution", {}).get("status") == "assigned"
    )


def _bounded_scope(scope):
    return _known_boundary(scope["beginning"]) and _known_boundary(
        scope.get("ending", {})
    )


def _known_boundary(boundary):
    return boundary.get("kind") in {"event", "turn", "declared"} and bool(
        boundary.get("reference") or boundary.get("at")
    )


def _matching_scope(covered, expected):
    for name in ("sourceInstanceId", "sourceSessionId", "counterEpoch"):
        if expected.get(name) is not None and covered.get(name) != expected[name]:
            return False
    return _matching_boundary(
        covered.get("beginning", {}), expected["beginning"]
    ) and _matching_boundary(covered.get("ending", {}), expected.get("ending", {}))


def _matching_boundary(actual, expected):
    if not _known_boundary(actual) or not _known_boundary(expected):
        return False
    if actual["kind"] != expected["kind"]:
        return False
    if actual.get("reference") and expected.get("reference"):
        return actual["reference"] == expected["reference"]
    return bool(
        actual.get("at")
        and expected.get("at")
        and _time(actual["at"]) == _time(expected["at"])
    )


def _overall_coverage(view, projection, participants, sources):
    if not any(view[name] for name in ("batches", "participations", "estimates")):
        return "not-recorded"
    if not sources or not participants:
        return "partial"
    if _coverage_blocked(projection):
        return "partial"
    return (
        "complete-for-declared-sources"
        if _complete_records(participants + sources)
        else "partial"
    )


def _coverage_blocked(projection):
    return bool(
        projection["unallocated"]
        or projection["conflict"]
        or any(item["status"] != "replaced" for item in projection["estimateViews"])
    )


def _complete_records(records):
    return bool(records) and all(
        item["coverage"] == "complete-for-declared-sources" for item in records
    )


def _receipt_frontier(receipts):
    predecessors = {item["predecessorReceiptId"] for item in receipts.values()}
    return [item for identity, item in receipts.items() if identity not in predecessors]


def _source_participation(store, key, receipts, owners):
    participants = {
        owner
        for item in receipts.values()
        for observation in item["observationKeys"]
        for owner in owners[(item["profileId"], store.digest(observation))]
    }
    return (
        next(iter(participants))
        if len(participants) == 1
        else "unallocated-source:" + store.digest(key)
    )


def _source_finality(frontier, receipts):
    gaps = {gap for item in receipts.values() for gap in item["gaps"]}
    if len(frontier) != 1:
        gaps.add("receipt-predecessor-conflict")
    baseline = {item["baseline"]["status"] for item in frontier}
    states = [_receipt_pending(item) for item in frontier]
    if gaps:
        states.append("unknown")
    return (
        _pending(states),
        next(iter(baseline)) if len(baseline) == 1 else "missing",
        sorted(gaps),
    )


def _participation_summaries(view, projection, sources, diagnostics):
    from avo.cost_participation import expected_participation_intervals

    graph = project_participation_facts(view["participations"])
    intervals = expected_participation_intervals(view["participations"])
    diagnostics.extend(graph["conflicts"])
    result = []
    for state in graph["participations"]:
        summary = _participant_summary(
            state,
            projection["assigned"],
            sources,
            intervals.get(state["participationId"], []),
        )
        diagnostics.extend(summary["diagnostics"])
        result.append(summary)
    if not result and view["batches"]:
        diagnostics.append({"code": "historical-host-coverage-unknown"})
    return result


def _has_participant_usage(identity, rows):
    return any(
        row["_evidence"] and row["_evidence"].get("participationId") == identity
        for row in rows
    )


def _participant_diagnostics(identity, declaration, agent, assigned):
    if declaration["mode"] == "human-ci":
        return [{"code": "no-external-agent-declared", "participationId": identity}]
    if agent and agent["role"] == "driver" and not assigned:
        return [{"code": "host-agent-unaccounted", "participationId": identity}]
    return []


def _participant_tracking(declaration, agent, observed):
    if not agent or declaration["mode"] == "identity-unknown":
        return "identity-unknown"
    return "active" if observed else "needs-setup"


def _participant_summary(declaration, rows, sources, intervals):
    identity, agent = declaration["participationId"], declaration["agent"]
    matching = [item for item in sources if item["participationId"] == identity]
    assigned = _has_participant_usage(identity, rows)
    expected = [
        _interval_summary(item, matching, declaration["mode"]) for item in intervals
    ]
    observed = bool(matching or assigned)
    return {
        "participationId": identity,
        "agent": agent,
        "scope": declaration["scope"],
        "coverage": _participant_coverage(declaration, expected, observed),
        "pendingState": _expected_pending(expected),
        "expectedIntervals": expected,
        "trackingState": _participant_tracking(declaration, agent, observed),
        "diagnostics": declaration.get("diagnostics", [])
        + _participant_diagnostics(
            identity,
            declaration,
            agent,
            assigned or _complete_records(matching),
        ),
    }


def _interval_summary(interval, sources, mode):
    matching = [
        source
        for source in sources
        if _matching_scope(source["sourceScope"], interval["scope"])
    ]
    complete = _interval_complete(interval, matching, mode)
    human = mode == "human-ci" and complete
    return {
        **interval,
        "coverage": "complete-for-declared-sources" if complete else "partial",
        "pendingState": "none" if human else _interval_pending(matching),
    }


def _interval_complete(interval, matching, mode):
    if interval["conflicted"] or not _bounded_scope(interval["scope"]):
        return False
    return mode == "human-ci" or _complete_records(matching)


def _participant_coverage(declaration, expected, observed):
    if (
        not declaration["conflicted"]
        and declaration["mode"] != "identity-unknown"
        and _complete_records(expected)
    ):
        return "complete-for-declared-sources"
    return "partial" if observed else "not-recorded"


def _expected_pending(expected):
    return _pending([item["pendingState"] for item in expected] or ["unknown"])


def _interval_pending(sources):
    if not sources:
        return "unknown"
    states = []
    for source in sources:
        state = source["pendingState"]
        if "source-profile-unqualified" in source["gaps"]:
            state = "unknown"
        elif state == "none" and "source-finality-unproven" in source["gaps"]:
            state = "settling"
        states.append(state)
    return _pending(states)


def _role_breakdowns(rows, participants, prices, *, total_rows, total):
    roles = {
        item["participationId"]: item["agent"]["role"]
        for item in participants
        if item["agent"] is not None
    }
    groups = defaultdict(list)
    for row in rows:
        if row["serviceClass"] == "host-agent":
            identity = (row.get("_evidence") or {}).get("participationId")
            groups[roles.get(identity, "unknown")].append(row)
    return {
        role: total
        if len(group) == len(total_rows)
        and all(left is right for left, right in zip(group, total_rows))
        else _group_report(group, prices)
        for role, group in sorted(groups.items())
    }


def _safe_diagnostic(item):
    allowed = {
        key: value
        for key, value in item.items()
        if key
        in {
            "code",
            "participationId",
            "profileId",
            "bindingId",
            "observationId",
            "evidenceId",
            "count",
            "variants",
        }
    }
    for key in ("evidenceIds", "receiptIds", "factIds"):
        if key in item:
            allowed["variants"] = item[key]
    return allowed


def _membership(view, store):
    return {
        kind: sorted(
            v["contentHash"] if kind == "batches" else store.digest(v) for v in docs
        )
        for kind, docs in view.items()
    }


def _last_collected(batches):
    return max((b["createdAt"] for b in batches), default=None)


def _watermarks(rows):
    values = {}
    for row in rows:
        key = (row["sourceInstanceId"], row["sourceSessionId"])
        values[key] = {
            "sourceInstanceId": key[0],
            "sourceSessionId": key[1],
            "lastImportedRequestId": row["requestId"],
            "occurredAt": row["occurredAt"],
        }
    return [value for _, value in sorted(values.items())]


def _cutoff(rows):
    return max(
        (r["occurredAt"] for r in rows if r["occurredAt"]), key=_time, default=None
    )


def _time(value):
    return datetime.fromisoformat(value)


def render_summary(report):
    if not report:
        return "Cost data not recorded for this video."
    if report.get("persistence") == "failed":
        return report["message"]
    amounts = (
        "; ".join(
            f"{a['amount']} {a['unit']} ({a['basis']})" for a in report["amounts"]
        )
        or "unknown cost"
    )
    total = report["tokens"].get("total")
    return (
        f"Recorded video cost: {amounts}. Tokens: {total if total is not None else 'unknown'}. "
        f"Coverage: {report['coverage']}. Through: {report.get('cutoff') or 'not recorded'}. "
        f"Collected: {report.get('lastCollectedAt') or 'not recorded'}. "
        "Closing/current turn may still be pending; this is not an invoice."
    )


def _render_current_summary(report):
    roles = report["breakdowns"].get("agentRole", {})
    parts = []
    if _declared_without_external_agent(report):
        parts.append("No external driving agent declared for this scope.")
    else:
        parts.append(f"Executor: {_render_values(roles.get('driver'))}.")
        if _unaccounted_driver(report):
            parts.append("agente executor não contabilizado.")
    for role, label in (
        ("subagent", "Subagents"),
        ("unknown", "Host usage with unknown role"),
    ):
        if role in roles:
            parts.append(f"{label}: {_render_values(roles[role])}.")
    service = report["breakdowns"]["serviceClass"].get("pipeline-service")
    if service:
        parts.append(f"Pipeline services: {_render_values(service)}.")
    parts.extend(_render_evidence(report["usageByNature"]))
    parts.extend(_render_unassigned(report))
    parts.extend(
        _render_representation_conflicts(report.get("representationConflicts", []))
    )
    parts.extend(_render_financial_views(report.get("financialViews", [])))
    parts.extend(_render_estimate(item) for item in report.get("estimateViews", []))
    parts.append(
        f"Observed subtotal: {_render_values(report)}. Coverage: {report['coverage']}."
    )
    parts.append(
        f"Through: {report.get('cutoff') or 'not recorded'}. "
        f"Collected: {report.get('lastCollectedAt') or 'not recorded'}. "
        f"{_render_activity(report.get('pendingState', 'unknown'))}. This is not an invoice."
    )
    return " ".join(parts)


def _render_values(values):
    values = values or {"tokens": {}, "amounts": []}
    total = values["tokens"].get("total")
    amounts = (
        "; ".join(
            f"{item['amount']} {item['unit']} ({item['basis']})"
            for item in values["amounts"]
        )
        or "unknown cost"
    )
    return f"{total if total is not None else 'unknown'} tokens; {amounts}"


def _render_financial_views(views):
    return [
        f"Financial view: {item['amount']} {item['unit']} ({item['interpretation']})."
        for item in views
    ]


def _render_unassigned(report):
    result = []
    for key, label in (
        ("unallocated", "Unallocated usage"),
        ("conflicts", "Conflicting usage"),
    ):
        values = report.get(key, {"tokens": {}, "amounts": []})
        if values["amounts"] or any(
            value is not None for value in values["tokens"].values()
        ):
            result.append(f"{label}: {_render_values(values)}.")
    return result


def _render_representation_conflicts(alternatives):
    return [
        f"Conflicting alternative {item['evidenceId'][:12]}: {_render_values(item)}; unique subtotal unknown."
        for item in alternatives
    ]


def _render_estimate(item):
    counts = _render_estimate_counts(item)
    if item["missingPrerequisites"]:
        valuation = "valuation unavailable: " + ", ".join(item["missingPrerequisites"])
    else:
        valuation = _render_estimate_amounts(item)
    basis = f" Basis: {item['manualBasis']}." if item.get("manualBasis") else ""
    return (
        f"Estimate {item['estimateId'][:12]} ({item['method']} {item['methodVersion']}, {item['status']}): "
        f"{counts}. {valuation}. Limits: {'; '.join(item['limitations'])}.{basis}"
    )


def _render_estimate_counts(item):
    if item["ranges"] is not None:
        return "; ".join(
            f"{key} {value['minimum']}–{value['maximum']} tokens"
            for key, value in item["ranges"].items()
        )
    return (
        "; ".join(
            f"{key} {value if value is not None else 'unknown'} tokens"
            for key, value in (item["tokens"] or {}).items()
        )
        or "unknown tokens"
    )


def _render_estimate_amounts(item):
    values = [
        f"{value['amount']} {value['unit']} ({_financial_interpretation(value['basis'])})"
        for value in item["amounts"]
    ]
    values.extend(
        f"{value['min']}–{value['max']} {value['unit']} ({_financial_interpretation(value['basis'])})"
        for value in item["amountRanges"]
    )
    return "; ".join(values) or "valuation unavailable"


def _render_evidence(buckets):
    labels = {
        "measured": "measured usage",
        "manual": "manual usage",
        "legacy-unknown": "legacy usage (measurement unverified)",
        "estimated": "estimated usage",
    }
    return [
        f"{labels[kind]}: {tokens.get('total') if tokens.get('total') is not None else 'unknown'} tokens."
        for kind, tokens in buckets.items()
        if any(value is not None for value in tokens.values())
    ]


def _render_activity(state):
    return {
        "open": "Activity status: active",
        "settling": "Activity ended; usage settlement is pending",
        "unknown": "Activity status: unknown",
        "none": "Activity status: closed",
    }.get(state, "Activity status: unknown")


def _declared_without_external_agent(report):
    participants = report["participations"]
    return bool(participants) and all(
        any(
            item["code"] == "no-external-agent-declared"
            for item in participant["diagnostics"]
        )
        for participant in participants
    )


def _unaccounted_driver(report):
    declared = any(
        item["agent"] and item["agent"]["role"] == "driver"
        for item in report["participations"]
    )
    return not declared or any(
        item["code"] == "host-agent-unaccounted" for item in report["diagnostics"]
    )
