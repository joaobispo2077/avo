"""Accounting invariants with synthetic usage, never paid inference."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy

import pytest

from avo.cost_store import CostError, CostStore
from avo.costs import summarize


def fact(request="r1", **changes):
    value = {
        "sourceInstanceId": "synthetic",
        "sourceSessionId": "session",
        "requestId": request,
        "agent": "codex",
        "agentVersion": "fixture-1",
        "model": "model-a",
        "serviceProvider": "service-a",
        "billingMode": "api",
        "serviceClass": "host-agent",
        "occurredAt": "2026-10-22T16:00:00Z",
        "phase": "motion",
        "tokens": {"input": 100, "output": 20, "cacheRead": 60, "reasoning": 5},
        "semantics": {"cacheRead": "input", "reasoning": "output"},
        "amounts": [
            {
                "basis": "source-reported",
                "unit": "USD",
                "amount": "0.10",
                "provenance": "synthetic fixture",
            }
        ],
    }
    value.update(changes)
    return value


def test_switch_and_replay(tmp_path):
    store = CostStore(tmp_path)
    store.initialize("channel", "video")
    store.ingest([fact(), fact("r2", model="model-b", serviceProvider="service-b")])
    store.ingest([fact()])
    report = summarize(store)
    assert report["tokens"]["total"] == 240
    assert report["amounts"][0]["amount"] == "0.20"
    assert len(report["breakdowns"]["model"]) == 2


def test_conflicting_observation_requires_explicit_correction(tmp_path):
    store = CostStore(tmp_path)
    store.initialize("channel", "video")
    a = fact()
    b = fact(tokens={"input": 200, "output": 20})
    store.ingest([a])
    store.ingest([b])
    report = summarize(store)
    assert report["coverage"] == "partial"
    assert report["observationCount"] == 0
    store.correct(
        store.observation_id(a), "select", "human", "verified", selected=store.digest(a)
    )
    assert summarize(store)["tokens"]["total"] == 120


@pytest.mark.parametrize(
    "tokens", [{"input": -1}, {"output": True}, {"input": float("nan")}]
)
def test_bad_counts_rejected(tmp_path, tokens):
    store = CostStore(tmp_path)
    store.initialize("channel", "video")
    with pytest.raises(CostError):
        store.ingest([fact(tokens=tokens)])
    assert store.observations()[0] == []


def test_private_fields_rejected(tmp_path):
    store = CostStore(tmp_path)
    store.initialize("channel", "video")
    with pytest.raises(CostError, match="invalid"):
        store.ingest([fact(prompt="private conversation")])


def test_concurrent_replay_counts_once(tmp_path):
    store = CostStore(tmp_path)
    with ThreadPoolExecutor(max_workers=4) as pool:
        identities = list(
            pool.map(lambda _: store.initialize("channel", "video"), range(4))
        )
        list(pool.map(lambda _: store.ingest([fact()]), range(8)))
    assert len({v["accountingVideoId"] for v in identities}) == 1
    assert summarize(store)["observationCount"] == 1


def test_snapshot_immutable_and_idempotent(tmp_path):
    store = CostStore(tmp_path)
    store.initialize("channel", "video")
    store.ingest([fact()])
    first = store.snapshot(summarize(store), "draft")
    assert (
        store.snapshot(summarize(store), "draft")["snapshotId"] == first["snapshotId"]
    )
    store.ingest([fact("late")])
    second = store.snapshot(summarize(store), "amendment")
    assert first["tokens"]["total"] == 120
    assert second["tokens"]["total"] == 240


def test_unknown_price_and_units_do_not_turn_into_zero(tmp_path):
    store = CostStore(tmp_path)
    store.initialize("channel", "video")
    store.ingest(
        [
            fact(amounts=[]),
            fact(
                "r2",
                amounts=[
                    {
                        "basis": "manual",
                        "unit": "credits",
                        "amount": "3",
                        "provenance": "fixture",
                    }
                ],
            ),
        ]
    )
    report = summarize(store)
    assert report["coverage"] == "partial"
    assert report["amounts"] == [{"basis": "manual", "unit": "credits", "amount": "3"}]


def test_read_only_report_does_not_initialize(tmp_path):
    report = summarize(CostStore(tmp_path))
    assert report["coverage"] == "not-recorded"
    assert report["tokens"]["total"] is None
    assert not (tmp_path / "edit").exists()


def test_two_videos_are_isolated(tmp_path):
    a, b = CostStore(tmp_path / "a"), CostStore(tmp_path / "b")
    for s in (a, b):
        s.initialize("channel", "video")
    a.ingest([fact()])
    assert summarize(b)["observationCount"] == 0


def test_cumulative_baseline_and_reset(tmp_path):
    store = CostStore(tmp_path)
    store.initialize("channel", "video")
    rows = [
        fact(
            "a",
            measurementKind="cumulative",
            counterEpoch="e1",
            sequence=1,
            tokens={"input": 100, "output": 10},
            amounts=[],
        ),
        fact(
            "b",
            measurementKind="cumulative",
            counterEpoch="e1",
            sequence=2,
            tokens={"input": 130, "output": 15},
            amounts=[],
        ),
    ]
    store.ingest(rows)
    assert summarize(store)["tokens"]["total"] == 35
    reset = deepcopy(rows[-1])
    reset.update(requestId="c", sequence=3, tokens={"input": 5, "output": 1})
    store.ingest([reset])
    assert summarize(store)["coverage"] == "partial"
    assert summarize(store)["tokens"]["total"] == 35


def test_frozen_price_and_revaluation(tmp_path):
    store = CostStore(tmp_path)
    store.initialize("channel", "video")
    price = {
        "schemaVersion": "1.0.0",
        "model": "model-a",
        "serviceProvider": "service-a",
        "unit": "USD",
        "basis": "calculated-estimate",
        "effectiveAt": "2026-10-22T00:00:00Z",
        "provenance": "synthetic rates",
        "denominator": 1000,
        "rates": {"input": "1", "output": "2", "cacheRead": "0.1"},
    }
    store.price(price)
    store.ingest(
        [fact(amounts=[], semantics={"cacheRead": "input", "reasoning": "output"})]
    )
    report = summarize(store)
    assert report["amounts"][0]["amount"] == "0.086"


def test_measured_total_can_be_known_without_input_output_breakdown(tmp_path):
    store = CostStore(tmp_path)
    store.initialize("channel", "video")
    store.ingest([fact(tokens={"total": 120}, semantics={})])
    assert summarize(store)["tokens"] == {"total": 120}


def test_current_v2_view_retains_legacy_counts_without_certifying_measurement(tmp_path):
    store = CostStore(tmp_path)
    store.initialize("channel", "video")
    store.ingest([fact()])
    original = {
        path: path.read_bytes() for path in (store.root / "batches").glob("*.json")
    }
    report = summarize(store)
    assert report["schemaVersion"] == "2.0.0"
    assert report["tokens"]["total"] == 120
    assert report["usageByNature"]["legacy-unknown"]["total"] == 120
    assert report["usageByNature"]["measured"]["total"] is None
    assert report["pendingState"] == "unknown"
    assert report["pendingTurn"] is None
    assert set(report["membership"]) == {
        "batches",
        "bindings",
        "prices",
        "corrections",
        "participations",
        "profiles",
        "estimates",
        "reconciliations",
    }
    assert {path: path.read_bytes() for path in original} == original
    assert store.snapshot(report, "draft")["schemaVersion"] == "2.0.0"


def test_v2_assigned_usage_excludes_unallocated_usage_and_money(tmp_path):
    from test_cost_continuity import evidence, packet, registered_ledger

    store = registered_ledger(tmp_path)
    first = fact()
    second = fact("r2", tokens={"input": 200, "output": 20})
    unallocated = evidence(second)
    unallocated["attribution"]["status"] = "unallocated"
    from avo.cost_participation import evidence_id

    unallocated["evidenceId"] = evidence_id(unallocated)
    store.ingest_packet(
        packet(store, [first, second], evidence_rows=[evidence(first), unallocated]),
        allow_synthetic=True,
    )
    report = summarize(store)
    assert report["tokens"]["total"] == 120
    assert report["usageByNature"]["measured"]["total"] == 120
    assert report["unallocated"]["tokens"]["total"] == 220
    assert report["amounts"][0]["amount"] == "0.10"
    assert report["unallocated"]["amounts"][0]["amount"] == "0.10"
    assert report["observationCount"] == 1
    assert report["coverage"] == "partial"


def test_v2_selected_model_hint_cannot_drive_historical_pricing(tmp_path):
    from test_cost_continuity import evidence, packet, registered_ledger

    store = registered_ledger(tmp_path)
    store.price(
        {
            "schemaVersion": "1.0.0",
            "model": "model-a",
            "serviceProvider": "service-a",
            "unit": "USD",
            "basis": "calculated-estimate",
            "effectiveAt": "2026-10-01T00:00:00Z",
            "provenance": "synthetic",
            "denominator": 1000,
            "rates": {"input": "1", "output": "2", "cacheRead": "0.1"},
        }
    )
    row = fact(amounts=[])
    store.ingest_packet(
        packet(store, [row], evidence_rows=[evidence(row, modelBasis="selected-only")]),
        allow_synthetic=True,
    )
    report = summarize(store)
    assert report["tokens"]["total"] == 120
    assert report["amounts"] == []
    assert set(report["breakdowns"]["model"]) == {"unknown"}


def test_v2_metadata_conflict_requires_exact_revision_before_reclassification(tmp_path):
    from test_cost_continuity import evidence, packet, reconciliation, registered_ledger

    store = registered_ledger(tmp_path)
    row = fact()
    old = evidence(row)
    new = evidence(row, nature="manual", acquisition="manual")
    for operation, metadata in (("original", old), ("revision", new)):
        store.ingest_packet(
            packet(store, [row], evidence_rows=[metadata], operation_id=operation),
            allow_synthetic=True,
        )
    unresolved = summarize(store)
    assert unresolved["tokens"]["total"] is None
    assert unresolved["conflicts"]["tokens"]["total"] == 120
    assert any(
        item["code"] == "cost-evidence-conflict" for item in unresolved["diagnostics"]
    )
    store.append_record("reconciliations", reconciliation(store, old, new))
    report = summarize(store)
    assert report["tokens"]["total"] == 120
    assert report["usageByNature"]["manual"]["total"] == 120
    assert report["usageByNature"]["measured"]["total"] is None
    assert report["selectedEvidenceIds"] == [new["evidenceId"]]


def test_v2_projection_exposes_expected_host_without_claiming_closed_work(tmp_path):
    from test_cost_continuity import PARTICIPATION_ID, registered_ledger

    store = registered_ledger(tmp_path)
    report = summarize(store)
    assert report["participations"][0]["participationId"] == PARTICIPATION_ID
    assert report["participations"][0]["coverage"] == "not-recorded"
    assert report["participations"][0]["trackingState"] == "needs-setup"
    assert report["pendingState"] == "unknown"
    assert any(
        item["code"] == "host-agent-unaccounted" for item in report["diagnostics"]
    )
    assert store.snapshot(report, "draft")["pendingTurn"] is None


def test_v2_projection_keeps_supplied_content_estimate_outside_legacy_tokens(tmp_path):
    from test_cost_continuity import (
        FIXED_TIME,
        PARTICIPATION_ID,
        evidence,
        packet,
        registered_ledger,
    )

    store = registered_ledger(tmp_path)
    row = fact()
    store.ingest_packet(packet(store, [row]), allow_synthetic=True)
    value = {
        "schemaVersion": "2.0.0",
        "accountingVideoId": store.identity()["accountingVideoId"],
        "operationId": "estimate-1",
        "participationId": PARTICIPATION_ID,
        "scope": evidence(row)["attribution"]["scope"],
        "method": "visible-content-tokenizer",
        "methodVersion": "fixture-1",
        "inputManifest": {
            "contentDigest": store.digest("synthetic-content"),
            "byteCount": 100,
            "itemCount": 1,
            "model": "model-a",
            "encoding": "fixture",
            "tokenizerVersion": "fixture-1",
            "assetsDigest": store.digest("fixture-assets"),
        },
        "tokens": {"total": 50},
        "ranges": None,
        "assumptions": [],
        "limitations": ["supplied visible content only"],
        "provenance": {"producer": "synthetic-test", "reference": "fixture"},
        "createdAt": FIXED_TIME,
    }
    value["estimateId"] = store.digest(value)
    store.append_record("estimates", value)
    report = summarize(store)
    assert report["tokens"]["total"] == 120
    assert report["usageByNature"]["estimated"]["total"] is None
    assert report["estimateViews"][0]["tokens"]["total"] == 50
    assert report["estimateViews"][0]["status"] == "conflict"
    assert report["activeEstimateIds"] == [value["estimateId"]]
    assert report["coverage"] != "complete-for-declared-sources"


def _financial_estimate(store, **changes):
    from test_cost_continuity import FIXED_TIME, PARTICIPATION_ID, evidence

    value = {
        "schemaVersion": "2.0.0",
        "accountingVideoId": store.identity()["accountingVideoId"],
        "operationId": "financial-estimate",
        "participationId": PARTICIPATION_ID,
        "scope": evidence(fact())["attribution"]["scope"],
        "method": "manual-range",
        "methodVersion": "fixture-1",
        "inputManifest": {
            "contentDigest": store.digest("synthetic-cost-input"),
            "byteCount": 0,
            "itemCount": 1,
            "model": None,
            "encoding": None,
            "tokenizerVersion": None,
            "assetsDigest": None,
        },
        "tokens": None,
        "ranges": {
            "input": {"minimum": 10, "maximum": 20},
            "output": {"minimum": 2, "maximum": 4},
        },
        "assumptions": ["bounded synthetic input and output categories"],
        "limitations": ["no hidden context or reasoning included"],
        "provenance": {"producer": "synthetic-test", "reference": "fixture"},
        "createdAt": FIXED_TIME,
    }
    value.update(changes)
    value.pop("estimateId", None)
    value["estimateId"] = store.digest(value)
    return value


def _replacement(store, estimate, selected, **changes):
    from test_cost_continuity import FIXED_TIME

    value = {
        "schemaVersion": "2.0.0",
        "accountingVideoId": store.identity()["accountingVideoId"],
        "operationId": "replace-estimate",
        "relation": "replaces-estimate",
        "references": [
            {"kind": "estimate", "id": estimate["estimateId"]},
            {"kind": "evidence", "id": selected["evidenceId"]},
        ],
        "scope": estimate["scope"],
        "selectedRepresentation": {"kind": "evidence", "id": selected["evidenceId"]},
        "actor": "synthetic-reviewer",
        "reason": "verified exact bounded source evidence",
        "proofRefs": [store.digest("synthetic-proof")],
        "supersedes": [],
        "createdAt": FIXED_TIME,
    }
    value.update(changes)
    value["reconciliationId"] = store.digest(value)
    return value


def test_financial_evidence_acquisition_and_billing_views_are_orthogonal(tmp_path):
    from avo.costs import render_summary
    from test_cost_continuity import evidence, packet, registered_ledger

    store = registered_ledger(tmp_path)
    rows = [
        fact(
            "imported",
            model=None,
            serviceProvider=None,
            tokens={"total": 100},
            amounts=[
                {
                    "basis": "source-reported",
                    "unit": "USD",
                    "amount": "1",
                    "provenance": "native amount; interpretation unspecified",
                }
            ],
        ),
        fact("declared", tokens={"total": 40}, amounts=[]),
        fact(
            "sdk",
            tokens={"total": 20},
            amounts=[
                {
                    "basis": "calculated-estimate",
                    "unit": "USD",
                    "amount": "0.25",
                    "provenance": "SDK estimator",
                }
            ],
        ),
        fact(
            "subscription",
            billingMode="subscription",
            tokens={"total": 10},
            amounts=[
                {
                    "basis": "manual",
                    "unit": "USD",
                    "amount": "2",
                    "provenance": "explicit subscription allocation",
                },
                {
                    "basis": "api-equivalent",
                    "unit": "USD",
                    "amount": "0.5",
                    "provenance": "reference API tariff",
                },
            ],
        ),
        fact(
            "credits",
            billingMode="credits",
            tokens={"total": 5},
            amounts=[
                {
                    "basis": "source-reported",
                    "unit": "credits",
                    "amount": "3",
                    "provenance": "native credits",
                },
                {
                    "basis": "source-reported",
                    "unit": "ACU",
                    "amount": "4",
                    "provenance": "native ACU",
                },
            ],
        ),
        fact("local", billingMode="local", tokens={"total": 7}, amounts=[]),
    ]
    metadata = [evidence(row, acquisition="imported") for row in rows]
    metadata[1] = evidence(rows[1], nature="manual", acquisition="manual")
    store.ingest_packet(
        packet(store, rows, evidence_rows=metadata), allow_synthetic=True
    )
    report = summarize(store)
    assert report["tokens"]["total"] == 182
    assert report["usageByNature"]["measured"]["total"] == 142
    assert report["usageByNature"]["manual"]["total"] == 40
    views = {(item["basis"], item["unit"]): item for item in report["financialViews"]}
    assert {key: item["amount"] for key, item in views.items()} == {
        ("source-reported", "USD"): "1",
        ("calculated-estimate", "USD"): "0.25",
        ("manual", "USD"): "2",
        ("api-equivalent", "USD"): "0.5",
        ("source-reported", "credits"): "3",
        ("source-reported", "ACU"): "4",
    }
    known = views[("source-reported", "USD")]["valuations"][0]
    assert known["reference"] == {"kind": "evidence", "id": metadata[0]["evidenceId"]}
    assert known["model"] is None
    assert known["priceScheduleId"] is None
    assert report["breakdowns"]["billingMode"]["local"]["amounts"] == []
    text = render_summary(report)
    assert "calculated estimate" in text
    assert "manual allocation/declaration" in text
    assert "API reference equivalent" in text
    assert store.snapshot(report, "draft")["financialViews"] == report["financialViews"]


def test_financial_decimal_sum_preserves_all_accepted_digits(tmp_path):
    from test_cost_continuity import registered_ledger

    store = registered_ledger(tmp_path)
    amounts = ("1234567890123456789012345678.12", "0.01")
    store.ingest(
        [
            fact(
                str(index),
                amounts=[
                    {
                        "basis": "source-reported",
                        "unit": "USD",
                        "amount": amount,
                        "provenance": "synthetic exact amount",
                    }
                ],
            )
            for index, amount in enumerate(amounts)
        ]
    )
    report = summarize(store)
    assert report["amounts"][0]["amount"] == "1234567890123456789012345678.13"
    assert report["financialViews"][0]["amount"] == report["amounts"][0]["amount"]


def test_tariff_products_preserve_exact_finite_decimal_digits(tmp_path):
    from test_cost_continuity import FIXED_TIME, registered_ledger

    store = registered_ledger(tmp_path)
    schedule = store.price(
        {
            "schemaVersion": "1.0.0",
            "model": "model-a",
            "serviceProvider": "service-a",
            "unit": "USD",
            "basis": "calculated-estimate",
            "effectiveAt": "2026-10-01T00:00:00Z",
            "provenance": "synthetic exact finite tariff",
            "denominator": 1000,
            "rates": {"input": "12345678901234567890.123456789", "output": "0"},
        }
    )
    store.ingest(
        [fact("finite-tariff", tokens={"input": 100, "output": 0}, amounts=[])]
    )
    estimate = _financial_estimate(
        store,
        tokens={"input": 100},
        ranges=None,
        pricingContext={
            "model": "model-a",
            "serviceProvider": "service-a",
            "occurredAt": FIXED_TIME,
            "dimensions": {},
        },
        priceScheduleIds=[schedule],
    )
    store.append_record("estimates", estimate)
    report = summarize(store)
    expected = "1234567890123456789.0123456789"
    assert report["amounts"][0]["amount"] == expected
    assert report["estimateViews"][0]["amounts"][0]["amount"] == expected


def test_v2_snapshot_keeps_derived_amount_beyond_raw_80_character_bound(tmp_path):
    from test_cost_continuity import FIXED_TIME, registered_ledger

    store = registered_ledger(tmp_path)
    rate, count = "9" * 80, 9007199254740991
    schedule = store.price(
        {
            "schemaVersion": "1.0.0",
            "model": "model-a",
            "serviceProvider": "service-a",
            "unit": "USD",
            "basis": "api-equivalent",
            "effectiveAt": "2026-10-01T00:00:00Z",
            "provenance": "synthetic bounded tariff",
            "denominator": 1,
            "rates": {"input": rate, "output": "0"},
        }
    )
    store.ingest(
        [
            fact(
                "largest-supported-product",
                tokens={"input": count, "output": 0},
                amounts=[],
            )
        ]
    )
    store.append_record(
        "estimates",
        _financial_estimate(
            store,
            tokens={"input": count},
            ranges=None,
            pricingContext={
                "model": "model-a",
                "serviceProvider": "service-a",
                "occurredAt": FIXED_TIME,
                "dimensions": {},
            },
            priceScheduleIds=[schedule],
        ),
    )
    report = summarize(store)
    expected = str(int(rate) * count)
    assert len(expected) > 80
    assert report["amounts"][0]["amount"] == expected
    assert report["estimateViews"][0]["amounts"][0]["amount"] == expected
    assert store.snapshot(report, "draft")["financialViews"] == report["financialViews"]


def test_unallocated_known_amount_is_visible_in_text_without_invented_tokens(tmp_path):
    from avo.costs import render_summary
    from test_cost_continuity import evidence, packet, registered_ledger

    store = registered_ledger(tmp_path)
    row = fact(
        "unallocated",
        tokens={"total": None},
        model=None,
        amounts=[
            {
                "basis": "source-reported",
                "unit": "USD",
                "amount": "1",
                "provenance": "native independent amount",
            }
        ],
    )
    attribution = {**evidence(row)["attribution"], "status": "unallocated"}
    store.ingest_packet(
        packet(store, [row], evidence_rows=[evidence(row, attribution=attribution)]),
        allow_synthetic=True,
    )
    report = summarize(store)
    assert report["tokens"]["total"] is None
    assert report["amounts"] == []
    assert "Unallocated usage: unknown tokens; 1 USD" in render_summary(report)


def test_selected_router_preserves_native_money_without_tariff_attribution(tmp_path):
    from test_cost_continuity import evidence, packet, registered_ledger

    store = registered_ledger(tmp_path)
    row = fact(
        "router",
        model="auto-router",
        tokens={"total": 120},
        amounts=[
            {
                "basis": "source-reported",
                "unit": "USD",
                "amount": "1",
                "provenance": "native reported aggregate",
            }
        ],
    )
    store.ingest_packet(
        packet(store, [row], evidence_rows=[evidence(row, modelBasis="selected-only")]),
        allow_synthetic=True,
    )
    report = summarize(store)
    assert report["tokens"]["total"] == 120
    assert report["amounts"] == [
        {"basis": "source-reported", "unit": "USD", "amount": "1"}
    ]
    assert report["financialViews"][0]["valuations"][0]["modelBasis"] == "selected-only"
    assert report["financialViews"][0]["valuations"][0]["model"] is None


def test_estimate_ranges_method_limits_and_unavailable_price_remain_visible(tmp_path):
    from avo.costs import render_summary
    from test_cost_continuity import registered_ledger

    store = registered_ledger(tmp_path)
    accepted = store.append_record("estimates", _financial_estimate(store))
    report = summarize(store)
    assert report["tokens"]["total"] is None
    assert report["amounts"] == []
    item = report["estimateViews"][0]
    assert item["estimateId"] == accepted["estimateId"]
    assert item["status"] == "active"
    assert item["ranges"] == accepted["ranges"]
    assert item["method"] == "manual-range"
    assert item["limitations"] == accepted["limitations"]
    assert item["amounts"] == item["amountRanges"] == []
    assert "pricing-context-missing" in item["missingPrerequisites"]
    text = render_summary(report)
    assert "manual-range" in text and "10–20" in text
    assert "no hidden context or reasoning included" in text
    assert "valuation unavailable" in text
    assert store.snapshot(report, "draft")["estimateViews"] == report["estimateViews"]


def test_estimate_valuation_uses_explicit_identity_and_frozen_prices(tmp_path):
    from test_cost_continuity import FIXED_TIME, registered_ledger

    store = registered_ledger(tmp_path)
    price = {
        "schemaVersion": "1.0.0",
        "model": "model-a",
        "serviceProvider": "service-a",
        "unit": "USD",
        "basis": "api-equivalent",
        "effectiveAt": "2026-10-01T00:00:00Z",
        "provenance": "synthetic reference",
        "denominator": 1000,
        "rates": {"input": "1", "output": "2"},
    }
    schedule = store.price(price)
    value = _financial_estimate(
        store,
        pricingContext={
            "model": "model-a",
            "serviceProvider": "service-a",
            "occurredAt": FIXED_TIME,
            "dimensions": {},
        },
        priceScheduleIds=[schedule],
    )
    store.append_record("estimates", value)
    report = summarize(store)
    item = report["estimateViews"][0]
    assert item["amountRanges"] == [
        {
            "basis": "api-equivalent",
            "unit": "USD",
            "min": "0.014",
            "max": "0.028",
            "provenance": "synthetic reference",
            "priceScheduleId": schedule,
        }
    ]
    assert item["missingPrerequisites"] == []
    snapshot = store.snapshot(report, "draft")
    store.price(
        {
            **price,
            "effectiveAt": "2026-10-20T00:00:00Z",
            "rates": {"input": "100", "output": "200"},
        }
    )
    assert summarize(store)["estimateViews"] == report["estimateViews"]
    assert (
        next(
            item
            for item in store.documents("snapshots")
            if item["snapshotId"] == snapshot["snapshotId"]
        )
        == snapshot
    )


@pytest.mark.parametrize("tokenizer_model", ["model-a", "different-model"])
def test_estimate_input_only_valuation_requires_matching_explicit_model(
    tmp_path, tokenizer_model
):
    from test_cost_continuity import FIXED_TIME, registered_ledger

    store = registered_ledger(tmp_path)
    schedule = store.price(
        {
            "schemaVersion": "1.0.0",
            "model": "model-a",
            "serviceProvider": "service-a",
            "unit": "USD",
            "basis": "api-equivalent",
            "effectiveAt": "2026-10-01T00:00:00Z",
            "provenance": "synthetic input reference",
            "denominator": 1000,
            "rates": {"input": "1", "output": "2"},
        }
    )
    value = _financial_estimate(
        store,
        method="visible-content-tokenizer",
        tokens={"input": 10},
        ranges=None,
        pricingContext={
            "model": "model-a",
            "serviceProvider": "service-a",
            "occurredAt": FIXED_TIME,
            "dimensions": {},
        },
        priceScheduleIds=[schedule],
    )
    value["inputManifest"].update(
        model=tokenizer_model,
        encoding="synthetic",
        tokenizerVersion="fixture-1",
        assetsDigest=store.digest("synthetic-assets"),
    )
    value.pop("estimateId")
    value["estimateId"] = store.digest(value)
    store.append_record("estimates", value)
    report = summarize(store)
    item = report["estimateViews"][0]
    assert item["tokens"] == {"input": 10}
    assert report["tokens"]["total"] is None
    assert report["amounts"] == []
    if tokenizer_model != "model-a":
        assert item["amounts"] == []
        assert "estimate-model-mismatch" in item["missingPrerequisites"]
    else:
        assert item["amounts"][0]["amount"] == "0.01"
        assert item["selectedPriceScheduleId"] == schedule


def test_exact_estimate_replacement_and_concurrent_choices_are_audited(tmp_path):
    from test_cost_continuity import evidence, packet, registered_ledger

    store = registered_ledger(tmp_path)
    estimate = store.append_record(
        "estimates", _financial_estimate(store, tokens={"total": 50}, ranges=None)
    )
    old = store.snapshot(summarize(store), "draft")
    rows = [fact("source-a"), fact("source-b")]
    metadata = [evidence(row) for row in rows]
    store.ingest_packet(
        packet(store, rows, evidence_rows=metadata), allow_synthetic=True
    )
    first = _replacement(store, estimate, metadata[0])
    store.append_record("reconciliations", first)
    report = summarize(store)
    assert report["tokens"]["total"] == 240
    assert report["usageByNature"]["estimated"]["total"] is None
    assert report["activeEstimateIds"] == []
    assert report["estimateViews"][0]["status"] == "replaced"
    assert (
        report["estimateViews"][0]["selectedRepresentation"]
        == first["selectedRepresentation"]
    )
    second = _replacement(
        store, estimate, metadata[1], operationId="alternative-choice"
    )
    store.append_record("reconciliations", second)
    disputed = summarize(store)
    assert disputed["activeEstimateIds"] == [estimate["estimateId"]]
    assert disputed["estimateViews"][0]["status"] == "conflict"
    assert disputed["estimateViews"][0]["selectedRepresentation"] is None
    resolved = _replacement(
        store,
        estimate,
        metadata[0],
        operationId="explicit-merge",
        supersedes=[first["reconciliationId"], second["reconciliationId"]],
    )
    store.append_record("reconciliations", resolved)
    assert summarize(store)["estimateViews"][0]["status"] == "replaced"
    assert (
        next(
            item
            for item in store.documents("snapshots")
            if item["snapshotId"] == old["snapshotId"]
        )
        == old
    )


def test_partial_measurement_cannot_prorate_estimate_and_is_not_summed(tmp_path):
    from test_cost_continuity import evidence, packet, registered_ledger

    store = registered_ledger(tmp_path)
    whole = {
        "runAliases": ["fixture-run"],
        "beginning": {"kind": "event", "reference": "a", "at": "2026-10-31T12:00:00Z"},
        "ending": {"kind": "event", "reference": "z", "at": "2026-10-31T13:00:00Z"},
    }
    estimate = store.append_record(
        "estimates",
        _financial_estimate(store, scope=whole, tokens={"total": 100}, ranges=None),
    )
    row = fact("partial")
    part = deepcopy(whole)
    part["ending"] = {"kind": "event", "reference": "m", "at": "2026-10-31T12:30:00Z"}
    metadata = evidence(
        row,
        attribution={
            "status": "assigned",
            "basis": "explicit bounded source",
            "scope": part,
        },
    )
    store.ingest_packet(
        packet(store, [row], evidence_rows=[metadata]), allow_synthetic=True
    )
    with pytest.raises(CostError, match="partial"):
        store.append_record("reconciliations", _replacement(store, estimate, metadata))
    report = summarize(store)
    assert report["tokens"]["total"] == 120
    assert report["usageByNature"]["estimated"]["total"] is None
    assert report["estimateViews"][0]["tokens"]["total"] == 100
    assert report["estimateViews"][0]["status"] == "conflict"
    assert any(
        item["code"] == "cost-estimate-overlap-unresolved"
        for item in report["diagnostics"]
    )


def _bounded_coverage_ledger(
    tmp_path, *, row_changes=None, finality="source-flush", ending=True
):
    from avo.cost_participation import register_context
    from test_cost_continuity import (
        evidence,
        host_descriptor,
        observation_key,
        packet,
        production,
        profile,
        receipt,
    )

    store, _ = production(tmp_path)
    descriptor = host_descriptor("first")
    descriptor["scope"]["ending"] = (
        {"kind": "event", "reference": "finish"} if ending else {"kind": "unknown"}
    )
    participant = register_context(store, descriptor)
    frozen = profile(semantics={**profile()["semantics"], "finality": finality})
    store.append_record("profiles", frozen)
    row = fact(
        sourceInstanceId="first-source",
        sourceSessionId="first-session",
        amounts=[],
        **(row_changes or {}),
    )
    metadata = evidence(
        row,
        participation_id=participant["participationId"],
        profile_id=frozen["profileId"],
        participationFactId=participant["factId"],
        modelBasis="served" if row["model"] else "unknown",
        attribution={
            "status": "assigned",
            "basis": "qualified exact source scope",
            "scope": descriptor["scope"],
        },
    )
    proof = store.digest("native-source-flush")
    terminal = receipt(
        profile_id=frozen["profileId"],
        sourceInstanceId="first-source",
        sourceSessionId="first-session",
        keys=[observation_key(row)],
        lifecycle={"state": "closed", "reference": proof},
        flush={"status": "accepted", "reference": proof},
        interval={
            "sourceSessionId": "first-session",
            "counterEpoch": None,
            "start": descriptor["scope"]["beginning"],
            "end": descriptor["scope"]["ending"],
        },
        watermark={"kind": "event", "value": "finish"},
    )
    incoming = packet(store, [row], evidence_rows=[metadata], receipts=[terminal])
    incoming["profileId"] = frozen["profileId"]
    store.ingest_packet(incoming, allow_synthetic=True)
    return store, row, metadata, terminal


@pytest.mark.parametrize(
    "tokens,complete", [({"total": 120}, True), ({"input": 100}, False)]
)
def test_coverage_needs_known_count_but_not_model_or_price(tmp_path, tokens, complete):
    store, _, _, _ = _bounded_coverage_ledger(
        tmp_path, row_changes={"tokens": tokens, "model": None, "serviceProvider": None}
    )
    report = summarize(store)
    assert report["coverage"] == (
        "complete-for-declared-sources" if complete else "partial"
    )
    assert report["tokens"].get("total") == (120 if complete else None)
    assert report["amounts"] == []


@pytest.mark.parametrize("changes", [{"finality": "best-effort"}, {"ending": False}])
def test_terminal_label_cannot_complete_unqualified_finality_or_unknown_bounds(
    tmp_path, changes
):
    store, _, _, _ = _bounded_coverage_ledger(tmp_path, **changes)
    report = summarize(store)
    assert report["coverage"] == "partial"
    assert report["participations"][0]["coverage"] != "complete-for-declared-sources"


def test_conflicting_metadata_never_certifies_source_coverage(tmp_path):
    from test_cost_continuity import evidence, packet

    store, row, original, terminal = _bounded_coverage_ledger(tmp_path)
    manual = evidence(
        row,
        participation_id=original["participationId"],
        profile_id=original["profileId"],
        participationFactId=original["participationFactId"],
        nature="manual",
        acquisition="manual",
        attribution=original["attribution"],
    )
    incoming = packet(
        store,
        [row],
        evidence_rows=[manual],
        receipts=[terminal],
        operation_id="disputed-quality",
    )
    incoming["profileId"] = original["profileId"]
    store.ingest_packet(incoming, allow_synthetic=True)
    report = summarize(store)
    assert report["coverage"] == "partial"
    assert report["coverageBySource"][0]["coverage"] == "partial"
    assert report["conflicts"]["tokens"]["total"] == 120


def test_phase_role_views_use_the_same_normalized_scope(tmp_path):
    from test_cost_continuity import evidence, packet, registered_ledger

    store = registered_ledger(tmp_path)
    rows = [
        fact("plan", phase="planning"),
        fact("review", phase="review"),
        fact("unphased", phase=None),
    ]
    metadata = [evidence(row) for row in rows]
    store.ingest_packet(
        packet(store, rows, evidence_rows=metadata), allow_synthetic=True
    )
    report = summarize(store, phase="planning")
    assert (
        report["tokens"]["total"] == report["usageByNature"]["measured"]["total"] == 120
    )
    assert report["breakdowns"]["agentRole"]["driver"]["tokens"]["total"] == 120
    assert report["activityEvidenceIds"] == [metadata[0]["evidenceId"]]


def test_cumulative_baseline_claim_requires_a_known_measured_native_snapshot():
    from avo.costs import _source_baseline_known
    from test_cost_continuity import evidence, observation_key

    frozen = {"semantics": {"counter": "cumulative"}}
    frontier = [{"baseline": {"status": "accepted", "reference": "unknown-snapshot"}}]
    assert _source_baseline_known(frozen, frontier) is False
    row = fact(
        "baseline", measurementKind="cumulative", counterEpoch="epoch", sequence=1
    )
    metadata = evidence(row)
    selected_key = observation_key(row)
    key_tuple = (selected_key["observationId"], selected_key["sourceDigest"])
    source_key = (metadata["profileId"], "synthetic", "session", "epoch", None)
    knowledge = {
        "metadata": {(metadata["profileId"], *key_tuple): metadata},
        "raw": {key_tuple: row},
    }
    frontier[0]["baseline"]["reference"] = "baseline"
    assert _source_baseline_known(frozen, frontier, source_key, knowledge) is True


def test_v2_renderer_names_unaccounted_host_even_with_large_service_subtotal(tmp_path):
    from avo.costs import render_summary
    from test_cost_continuity import evidence, packet, registered_ledger

    store = registered_ledger(tmp_path)
    row = fact(
        "service",
        serviceClass="pipeline-service",
        tokens={"total": 2100000},
        semantics={},
    )
    store.ingest_packet(
        packet(
            store,
            [row],
            evidence_rows=[
                evidence(row, participation_id="pipeline-service:synthetic")
            ],
        ),
        allow_synthetic=True,
    )
    report = summarize(store)
    text = render_summary(report)
    assert "agente executor não contabilizado" in text
    assert "Pipeline services: 2100000 tokens" in text
    assert report["participations"][0]["pendingState"] == "unknown"
    assert "Activity status: active" in text


def test_v2_role_subtotals_are_captured_views_without_double_counting(tmp_path):
    from avo.costs import render_summary
    from test_cost_continuity import (
        PARTICIPATION_ID,
        evidence,
        packet,
        participation_fact,
        registered_ledger,
    )

    store = registered_ledger(tmp_path)
    child_id = "00000000-0000-4000-8000-000000000016"
    store.append_record(
        "participations",
        participation_fact(
            store,
            operation_id="child",
            participationId=child_id,
            agent={
                "family": "codex",
                "surface": "synthetic-export",
                "version": "fixture-1",
                "role": "subagent",
                "parentParticipationId": PARTICIPATION_ID,
            },
        ),
    )
    rows = [
        fact(),
        fact("child", tokens={"input": 30, "output": 10}),
        fact(
            "service",
            serviceClass="pipeline-service",
            tokens={"input": 300, "output": 50},
        ),
    ]
    metadata = [
        evidence(rows[0]),
        evidence(rows[1], participation_id=child_id),
        evidence(rows[2], participation_id="pipeline-service:synthetic"),
    ]
    store.ingest_packet(
        packet(store, rows, evidence_rows=metadata), allow_synthetic=True
    )
    report = summarize(store)
    assert report["tokens"]["total"] == 510
    assert report["breakdowns"]["serviceClass"]["host-agent"]["tokens"]["total"] == 160
    assert report["breakdowns"]["agentRole"]["driver"]["tokens"]["total"] == 120
    assert report["breakdowns"]["agentRole"]["subagent"]["tokens"]["total"] == 40
    text = render_summary(report)
    assert "Executor: 120 tokens" in text
    assert "Subagents: 40 tokens" in text
    assert "Pipeline services: 350 tokens" in text
    assert "agente executor não contabilizado" not in text
    assert store.snapshot(report, "draft")["tokens"]["total"] == 510


def test_v2_renderer_keeps_usage_nature_and_financial_basis_independent(tmp_path):
    from avo.costs import render_summary
    from test_cost_continuity import evidence, packet, registered_ledger

    store = registered_ledger(tmp_path)
    row = fact(
        amounts=[
            {
                "basis": "api-equivalent",
                "unit": "USD",
                "amount": "2",
                "provenance": "synthetic reference",
            }
        ]
    )
    store.ingest_packet(
        packet(
            store,
            [row],
            evidence_rows=[evidence(row, nature="manual", acquisition="imported")],
        ),
        allow_synthetic=True,
    )
    text = render_summary(summarize(store))
    assert "manual usage: 120 tokens" in text
    assert "2 USD (api-equivalent)" in text
    assert "measured usage" not in text


@pytest.mark.parametrize(
    "state,expected",
    [
        ("open", "Activity status: active"),
        ("settling", "Activity ended; usage settlement is pending"),
        ("unknown", "Activity status: unknown"),
        ("none", "Activity status: closed"),
    ],
)
def test_v2_renderer_describes_known_pending_state(tmp_path, state, expected):
    from avo.costs import render_summary

    report = summarize(CostStore(tmp_path))
    report["pendingState"] = state
    assert expected in render_summary(report)


def test_v2_renderer_respects_bounded_no_external_agent_declaration(tmp_path):
    from avo.costs import render_summary
    from test_cost_continuity import participation_fact, production

    store, _ = production(tmp_path)
    store.append_record(
        "participations",
        participation_fact(
            store,
            kind="declare-no-external-agent",
            mode="human-ci",
            agent={
                "family": "human-ci",
                "surface": "direct-cli",
                "version": None,
                "role": "driver",
            },
        ),
    )
    text = render_summary(summarize(store))
    assert "No external driving agent declared for this scope" in text
    assert "agente executor não contabilizado" not in text


def _counter_source(tmp_path):
    from test_cost_continuity import profile, registered_ledger

    store = registered_ledger(tmp_path)
    semantics = {
        **profile()["semantics"],
        "counter": "cumulative",
        "resume": "baseline-required",
        "reset": "epoch-required",
    }
    accepted = store.append_record(
        "profiles", profile(sourceFormat="synthetic-cumulative-v2", semantics=semantics)
    )
    return store, accepted


def _ingest_counter_interval(
    store, accepted_profile, rows, *, owners=None, proven=True
):
    from test_cost_continuity import (
        PARTICIPATION_ID,
        evidence,
        observation_key,
        packet,
        receipt,
    )

    owners = owners or [PARTICIPATION_ID] * len(rows)
    metadata = []
    for row, owner in zip(rows, owners):
        start = (
            {"kind": "event", "reference": rows[0]["requestId"]}
            if proven
            else {"kind": "unknown"}
        )
        item = evidence(
            row,
            participation_id=owner,
            profile_id=accepted_profile["profileId"],
            interval={
                "sourceSessionId": row["sourceSessionId"],
                "counterEpoch": row["counterEpoch"],
                "start": start,
                "end": {"kind": "event", "reference": row["requestId"]},
            },
            attribution={
                "status": "assigned",
                "basis": "explicit synthetic interval",
                "scope": {"runAliases": ["fixture-run"], "beginning": start},
            },
        )
        metadata.append(item)
    received = receipt(
        profile_id=accepted_profile["profileId"],
        keys=[observation_key(row) for row in rows],
        counterEpoch=rows[0]["counterEpoch"],
        baseline={
            "status": "accepted" if proven else "missing",
            "reference": rows[0]["requestId"] if proven else None,
        },
    )
    incoming = packet(store, rows, evidence_rows=metadata, receipts=[received])
    incoming["profileId"] = accepted_profile["profileId"]
    store.ingest_packet(incoming, allow_synthetic=True)


def test_effective_participant_revision_and_boundary_do_not_rewrite_usage(tmp_path):
    from avo.cost_participation import register_context, transition_context
    from test_cost_continuity import host_descriptor, production, transition_request

    store, _ = production(tmp_path)
    first_descriptor = host_descriptor("first")
    first = register_context(store, first_descriptor)
    changed = deepcopy(first_descriptor)
    changed["operationId"] = "new-selected-model"
    changed["agent"]["selectedModel"] = "selected-only-model"
    register_context(store, changed)
    second = register_context(store, host_descriptor("second", "claude"))
    request = transition_request(
        store, first["participationId"], second["participationId"]
    )
    transition_context(store, request)
    report = summarize(store)
    participants = {item["participationId"]: item for item in report["participations"]}
    assert (
        participants[first["participationId"]]["scope"]["ending"] == request["boundary"]
    )
    assert (
        participants[first["participationId"]]["agent"]["selectedModel"]
        == "selected-only-model"
    )
    assert participants[first["participationId"]]["pendingState"] == "unknown"
    assert report["pendingTurn"] is None


def test_billing_breakdown_and_unphased_usage_survive_current_and_history_views(
    tmp_path,
):
    from avo.cost_history import _source_report

    store = CostStore(tmp_path)
    store.initialize("channel", "video")
    store.ingest(
        [
            fact("api", phase="planning", billingMode="api"),
            fact("sub", phase=None, billingMode="subscription"),
            fact("local", phase="review", billingMode="local"),
        ]
    )
    report = summarize(store)
    assert report["tokens"]["total"] == 360
    assert report["breakdowns"]["phase"]["unknown"]["tokens"]["total"] == 120
    assert set(report["breakdowns"]["billingMode"]) == {"api", "subscription", "local"}
    assert summarize(store, phase="planning")["tokens"]["total"] == 120
    historical = _source_report(store, "channel", "video")[1]
    assert historical["breakdowns"] == report["breakdowns"]
    assert (
        store.snapshot(report, "draft")["breakdowns"]["billingMode"]
        == report["breakdowns"]["billingMode"]
    )


def test_mixed_model_phase_counter_retains_provider_and_independent_money(tmp_path):
    store, accepted_profile = _counter_source(tmp_path)
    rows = [
        fact(
            "baseline",
            measurementKind="cumulative",
            counterEpoch="e1",
            sequence=1,
            phase="planning",
            tokens={"input": 100, "output": 10},
            semantics={},
            amounts=[],
        ),
        fact(
            "endpoint",
            measurementKind="cumulative",
            counterEpoch="e1",
            sequence=2,
            phase="review",
            model="model-b",
            tokens={"input": 130, "output": 15},
            semantics={},
            amounts=[
                {
                    "basis": "source-reported",
                    "unit": "USD",
                    "amount": "1",
                    "provenance": "independent interval charge",
                }
            ],
        ),
    ]
    _ingest_counter_interval(store, accepted_profile, rows)
    report = summarize(store)
    assert report["tokens"]["total"] == 35
    assert report["amounts"] == [
        {"basis": "source-reported", "unit": "USD", "amount": "1"}
    ]
    assert set(report["breakdowns"]["model"]) == {"unknown"}
    assert set(report["breakdowns"]["serviceProvider"]) == {"service-a"}
    assert report["breakdowns"]["phase"]["unknown"]["tokens"]["total"] == 35
    assert summarize(store, phase="review")["tokens"]["total"] is None


@pytest.mark.parametrize("proven", [False, True])
def test_counter_owner_change_requires_exact_interval_boundary(tmp_path, proven):
    from test_cost_continuity import PARTICIPATION_ID, participation_fact

    store, accepted_profile = _counter_source(tmp_path)
    second_id = "00000000-0000-4000-8000-000000000017"
    store.append_record(
        "participations",
        participation_fact(store, operation_id="second", participationId=second_id),
    )
    rows = [
        fact(
            "baseline",
            measurementKind="cumulative",
            counterEpoch="e1",
            sequence=1,
            tokens={"input": 100, "output": 10},
            semantics={},
            amounts=[],
        ),
        fact(
            "endpoint",
            measurementKind="cumulative",
            counterEpoch="e1",
            sequence=2,
            tokens={"input": 130, "output": 15},
            semantics={},
            amounts=[
                {
                    "basis": "source-reported",
                    "unit": "USD",
                    "amount": "1",
                    "provenance": "independent interval charge",
                }
            ],
        ),
    ]
    _ingest_counter_interval(
        store,
        accepted_profile,
        rows,
        owners=[PARTICIPATION_ID, second_id],
        proven=proven,
    )
    report = summarize(store)
    selected = report if proven else report["unallocated"]
    assert selected["tokens"]["total"] == 35
    assert selected["amounts"] == [
        {"basis": "source-reported", "unit": "USD", "amount": "1"}
    ]
    if not proven:
        assert report["tokens"]["total"] is None
        assert any(
            item["code"] == "counter-attribution-ambiguous"
            for item in report["diagnostics"]
        )


def test_counter_known_total_and_categories_survive_missing_details(tmp_path):
    store = CostStore(tmp_path)
    store.initialize("channel", "video")
    store.ingest(
        [
            fact(
                "base",
                measurementKind="cumulative",
                counterEpoch="e1",
                sequence=1,
                tokens={"input": 100, "output": None, "total": 120},
                semantics={},
                amounts=[],
            ),
            fact(
                "end",
                measurementKind="cumulative",
                counterEpoch="e1",
                sequence=2,
                tokens={"input": 140, "output": None, "total": 165},
                semantics={},
                amounts=[],
            ),
        ]
    )
    report = summarize(store)
    assert report["tokens"] == {"input": 40, "total": 45}


def test_invalid_counter_delta_keeps_known_money_unallocated(tmp_path):
    store = CostStore(tmp_path)
    store.initialize("channel", "video")
    store.ingest(
        [
            fact(
                "base",
                measurementKind="cumulative",
                counterEpoch="e1",
                sequence=1,
                tokens={"input": 100, "output": 10},
                semantics={},
                amounts=[],
            ),
            fact(
                "end",
                measurementKind="cumulative",
                counterEpoch="e1",
                sequence=2,
                tokens={"input": 5, "output": 1},
                semantics={},
                amounts=[
                    {
                        "basis": "source-reported",
                        "unit": "USD",
                        "amount": "1",
                        "provenance": "known charge, uncertain interval",
                    }
                ],
            ),
        ]
    )
    report = summarize(store)
    assert report["tokens"]["total"] is None
    assert report["unallocated"]["tokens"]["total"] is None
    assert report["unallocated"]["amounts"] == [
        {"basis": "source-reported", "unit": "USD", "amount": "1"}
    ]
