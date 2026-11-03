"""Explicit offline token estimates, with synthetic inputs and no account access."""

import json
from copy import deepcopy
from hashlib import sha256
from importlib.metadata import version

import pytest

import test_cost_continuity
from avo.cost_store import CostError
from avo.timeline.contracts import content_hash
from test_cost_continuity import registered_ledger

offline_accounting = test_cost_continuity.offline_accounting


def estimate_request(store, **changes):
    declaration = store.capture()["participations"][0]
    value = {
        "schemaVersion": "2.0.0",
        "operationId": "estimate-1",
        "participationId": declaration["participationId"],
        "scope": declaration["scope"],
        "method": "manual-range",
        "inputs": {
            "ranges": {"input": {"minimum": 100, "maximum": 200}},
            "basis": "counted synthetic sections with an explicitly stated uncertainty",
        },
        "assumptions": ["synthetic scope only"],
        "limitations": ["manual estimate, no hidden usage or invoice precision"],
        "provenance": {"producer": "synthetic-test", "reference": "offline-fixture"},
    }
    value.update(changes)
    return value


def tokenizer_request(store, tmp_path, *, content="hello world hello"):
    tokenizers = pytest.importorskip("tokenizers")
    tokenizer = tokenizers.Tokenizer(
        tokenizers.models.WordLevel(
            {"[UNK]": 0, "hello": 1, "world": 2}, unk_token="[UNK]"
        )
    )
    tokenizer.pre_tokenizer = tokenizers.pre_tokenizers.Whitespace()
    assets = tmp_path / "tokenizer.json"
    tokenizer.save(str(assets))
    declared = {
        "model": "synthetic-local-model",
        "encoding": "synthetic-wordlevel",
        "tokenizer": "tokenizers-json",
        "tokenizerVersion": version("tokenizers"),
        "assetsDigest": sha256(assets.read_bytes()).hexdigest(),
    }
    mapping = tmp_path / "mapping.json"
    mapping.write_text(
        json.dumps({"schemaVersion": "1.0.0", **declared}), encoding="utf-8"
    )
    return estimate_request(
        store,
        method="visible-content-tokenizer",
        inputs={
            **declared,
            "assetsPath": str(assets),
            "mappingPath": str(mapping),
            "content": content,
        },
    )


def test_manual_estimate_is_separate_justified_and_replayable(
    tmp_path, offline_accounting
):
    from avo.cost_estimates import create_estimate
    from avo.costs import summarize

    store = registered_ledger(tmp_path)
    request = estimate_request(store)
    result = create_estimate(store, request)
    saved = store.capture()["estimates"][0]
    assert result["estimateId"] == saved["estimateId"]
    assert saved["tokens"] is None
    assert saved["ranges"] == request["inputs"]["ranges"]
    assert saved["manualBasis"] == request["inputs"]["basis"]
    assert saved["inputManifest"]["model"] is None
    assert create_estimate(store, request)["replayed"] is True
    assert len(store.capture()["estimates"]) == 1
    assert summarize(store)["tokens"].get("total") in (None, 0)
    changed = deepcopy(request)
    changed["inputs"]["basis"] = "different justified declaration"
    with pytest.raises(CostError, match="operation|replay"):
        create_estimate(store, changed)


@pytest.mark.parametrize("bad", [True, 1.5, -1, 9007199254740992])
def test_bad_range_types_never_publish(tmp_path, offline_accounting, bad):
    from avo.cost_estimates import create_estimate

    store = registered_ledger(tmp_path)
    request = estimate_request(store)
    request["inputs"]["ranges"]["input"]["minimum"] = bad
    with pytest.raises(CostError):
        create_estimate(store, request)
    assert store.capture()["estimates"] == []


@pytest.mark.parametrize(
    "change", ["reversed", "blank-basis", "private-field", "wrong-input-type"]
)
def test_invalid_estimate_is_rejected_without_private_echo(
    tmp_path, offline_accounting, change
):
    from avo.cost_estimates import create_estimate

    store = registered_ledger(tmp_path)
    request = estimate_request(store)
    if change == "reversed":
        request["inputs"]["ranges"]["input"] = {"minimum": 20, "maximum": 10}
    elif change == "blank-basis":
        request["inputs"]["basis"] = "  "
    elif change == "private-field":
        request["prompt"] = "PRIVATE-SENTINEL"
    else:
        request["inputs"] = ["PRIVATE-SENTINEL"]
    with pytest.raises(CostError) as rejected:
        create_estimate(store, request)
    assert "PRIVATE-SENTINEL" not in str(rejected.value)
    assert store.capture()["estimates"] == []


def test_installed_offline_tokenizer_counts_only_supplied_text(
    tmp_path, offline_accounting
):
    from avo.cost_estimates import create_estimate

    store = registered_ledger(tmp_path)
    request = tokenizer_request(store, tmp_path, content="hello world PRIVATE-SENTINEL")
    result = create_estimate(store, request)
    assert result["status"] == "ok"
    saved = store.capture()["estimates"][0]
    assert saved["tokens"] == {"input": 5}
    assert saved["ranges"] is None
    assert (
        saved["inputManifest"]["contentDigest"]
        == sha256(request["inputs"]["content"].encode()).hexdigest()
    )
    persisted = "\n".join(
        path.read_text("utf-8") for path in store.root.rglob("*.json")
    )
    assert "PRIVATE-SENTINEL" not in persisted
    assert str(tmp_path) not in persisted
    assert create_estimate(store, request)["replayed"] is True


@pytest.mark.parametrize(
    "missing",
    ["assetsPath", "mappingPath", "version", "model", "assetsDigest", "library"],
)
def test_missing_or_mismatched_tokenizer_is_unavailable_without_record(
    tmp_path, monkeypatch, offline_accounting, missing
):
    from avo import cost_estimates

    store = registered_ledger(tmp_path)
    request = tokenizer_request(store, tmp_path)
    if missing in {"assetsPath", "mappingPath"}:
        request["inputs"].pop(missing)
    elif missing == "version":
        request["inputs"]["tokenizerVersion"] = "not-installed"
    elif missing == "model":
        request["inputs"]["model"] = "not-the-pinned-model"
    elif missing == "assetsDigest":
        request["inputs"]["assetsDigest"] = "f" * 64
    else:
        monkeypatch.setattr(cost_estimates, "_tokenizer_version", lambda: None)
    result = cost_estimates.create_estimate(store, request)
    assert result["status"] == "unavailable"
    assert result["missingPrerequisites"]
    assert store.capture()["estimates"] == []


def test_explicit_local_input_is_transient_and_paths_are_never_retained(
    tmp_path, offline_accounting
):
    from avo.cost_estimates import create_estimate

    store = registered_ledger(tmp_path)
    request = tokenizer_request(store, tmp_path)
    request["inputs"].pop("content")
    source = tmp_path / "private-source.txt"
    source.write_text("hello world", encoding="utf-8")
    request["inputs"]["inputPath"] = str(source)
    create_estimate(store, request)
    source.unlink()
    assert create_estimate(store, request)["replayed"] is True
    saved = store.capture()["estimates"][0]
    assert saved["tokens"] == {"input": 2}
    assert str(source) not in json.dumps(saved)
    assert "hello world" not in json.dumps(saved)


@pytest.mark.parametrize("path_key", ["inputPath", "assetsPath", "mappingPath"])
def test_path_transport_denial_precedes_any_estimate(
    tmp_path, offline_accounting, path_key
):
    from avo.cost_estimates import create_estimate

    store = registered_ledger(tmp_path)
    request = tokenizer_request(store, tmp_path)
    if path_key == "inputPath":
        request["inputs"].pop("content")
        request["inputs"]["inputPath"] = str(tmp_path / "not-read")
    with pytest.raises(CostError):
        create_estimate(store, request, allow_input_path=False)
    assert store.capture()["estimates"] == []


def test_estimate_freezes_only_explicit_pricing_context_and_prices(
    tmp_path, offline_accounting
):
    from avo.cost_estimates import create_estimate

    store = registered_ledger(tmp_path)
    request = estimate_request(
        store,
        pricingContext={
            "model": "fixture-model",
            "serviceProvider": "fixture-api",
            "occurredAt": "2026-10-31T12:00:00Z",
            "dimensions": {},
        },
    )
    create_estimate(store, request)
    saved = store.capture()["estimates"][0]
    assert saved["pricingContext"] == request["pricingContext"]
    assert saved["priceScheduleIds"] == []
    assert saved["requestDigest"] == content_hash(request)


@pytest.mark.parametrize(
    "change",
    [None, "partial", "unallocated", "other-participant", "observation-only", "legacy"],
)
def test_estimate_replacement_requires_exact_assigned_evidence(
    tmp_path, offline_accounting, change
):
    from avo.cost_estimates import create_estimate
    from avo.cost_participation import validate_reconciliation
    from test_cost_continuity import FIXED_TIME, evidence
    from test_costs import fact

    store = registered_ledger(tmp_path)
    create_estimate(store, estimate_request(store))
    estimate = store.capture()["estimates"][0]
    scope = deepcopy(estimate["scope"])
    if change == "partial":
        scope["ending"] = {"kind": "event", "reference": "only-part-of-scope"}
    metadata = evidence(
        fact(),
        participation_id=estimate["participationId"],
        nature="manual",
        attribution={
            "status": "unallocated" if change == "unallocated" else "assigned",
            "basis": "explicit synthetic verification",
            "scope": scope,
        },
    )
    if change == "other-participant":
        metadata["participationId"] = "00000000-0000-4000-8000-000000000099"
    if change == "legacy":
        metadata["nature"] = "legacy-unknown"
    selected = {
        "kind": "observation" if change == "observation-only" else "evidence",
        "id": metadata["evidenceId"],
    }
    if change == "observation-only":
        selected["key"] = metadata["key"]
    decision = {
        "schemaVersion": "2.0.0",
        "accountingVideoId": store.identity()["accountingVideoId"],
        "operationId": "replace-1",
        "relation": "replaces-estimate",
        "references": [{"kind": "estimate", "id": estimate["estimateId"]}, selected],
        "scope": estimate["scope"],
        "selectedRepresentation": selected,
        "actor": "synthetic-reviewer",
        "reason": "exact scope reviewed",
        "proofRefs": ["a" * 64],
        "supersedes": [],
        "createdAt": FIXED_TIME,
    }
    decision["reconciliationId"] = content_hash(decision)
    known = {estimate["estimateId"]: estimate, metadata["evidenceId"]: metadata}
    if change is None:
        assert validate_reconciliation(decision, known_refs=known) == decision
    else:
        with pytest.raises(CostError):
            validate_reconciliation(decision, known_refs=known)
