"""Deterministic token accounting and frozen decimal valuations."""

from __future__ import annotations
from collections import defaultdict
from datetime import datetime
from decimal import Decimal
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






def _render_financial_views(views):
    return [
        f"Financial view: {item['amount']} {item['unit']} ({item['interpretation']})."
        for item in views
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








