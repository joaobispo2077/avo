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
