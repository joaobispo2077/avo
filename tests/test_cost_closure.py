"""Closure reporting must match saved evidence and preserve cleanup gates."""

import json

import pytest

import test_cost_continuity
from avo.cost_closure import close_costs
from avo.cost_store import CostError, CostStore
from avo.costs import summarize
from test_costs import fact

offline_accounting = test_cost_continuity.offline_accounting


def _bounded_source(tmp_path, *, lifecycle="open", flush="unknown"):
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

    store, project_path = production(tmp_path)
    descriptor = host_descriptor("first")
    descriptor["scope"]["ending"] = {"kind": "event", "reference": "finish"}
    participant = register_context(store, descriptor)
    frozen = store.append_record("profiles", profile())
    row = fact(
        sourceInstanceId="first-source", sourceSessionId="first-session", amounts=[]
    )
    metadata = evidence(
        row,
        participation_id=participant["participationId"],
        profile_id=frozen["profileId"],
        participationFactId=participant["factId"],
        attribution={
            "status": "assigned",
            "basis": "qualified synthetic bounded source",
            "scope": descriptor["scope"],
        },
    )
    terminal_proof = "a" * 64
    received = receipt(
        profile_id=frozen["profileId"],
        sourceInstanceId="first-source",
        sourceSessionId="first-session",
        keys=[observation_key(row)],
        lifecycle={
            "state": lifecycle,
            "reference": terminal_proof if lifecycle == "closed" else None,
        },
        flush={
            "status": flush,
            "reference": terminal_proof if flush == "accepted" else None,
        },
        interval={
            "sourceSessionId": "first-session",
            "counterEpoch": None,
            "start": descriptor["scope"]["beginning"],
            "end": descriptor["scope"]["ending"],
        },
        watermark={"kind": "event", "value": "finish"},
    )
    incoming = packet(store, [row], evidence_rows=[metadata], receipts=[received])
    incoming["profileId"] = frozen["profileId"]
    store.ingest_packet(incoming, allow_synthetic=True)
    return store, project_path, received


@pytest.mark.parametrize(
    "lifecycle,flush,pending,flag",
    [
        ("open", "unknown", "open", True),
        ("closed", "missing", "settling", True),
        ("unknown", "unknown", "unknown", None),
        ("closed", "accepted", "none", False),
    ],
)
def test_qualified_source_pending_is_evidence_based(
    tmp_path, offline_accounting, lifecycle, flush, pending, flag
):
    store, _, _ = _bounded_source(tmp_path, lifecycle=lifecycle, flush=flush)
    report = summarize(store)
    assert report["pendingState"] == pending
    assert report["pendingTurn"] is flag
    assert report["coverage"] == (
        "complete-for-declared-sources" if pending == "none" else "partial"
    )
    assert report["tokens"]["total"] == 120


def test_receipt_only_terminal_flush_settles_without_fake_usage(
    tmp_path, offline_accounting
):
    from test_cost_continuity import packet, receipt

    store, _, previous = _bounded_source(tmp_path)
    before_count = summarize(store)["observationCount"]
    proof = "a" * 64
    terminal = receipt(
        profile_id=previous["profileId"],
        predecessor=previous["receiptId"],
        sourceInstanceId="first-source",
        sourceSessionId="first-session",
        lifecycle={"state": "closed", "reference": proof},
        flush={"status": "accepted", "reference": proof},
        interval=previous["interval"],
        watermark={"kind": "event", "value": "finish"},
    )
    incoming = packet(store, receipts=[terminal], operation_id="terminal-only")
    incoming["profileId"] = previous["profileId"]
    store.ingest_packet(incoming, allow_synthetic=True)
    report = summarize(store)
    assert report["pendingTurn"] is False
    assert report["coverage"] == "complete-for-declared-sources"
    assert report["observationCount"] == before_count
    assert report["tokens"]["total"] == 120


def _late_service(store, kind):
    from avo.cost_estimates import create_estimate
    from avo.cost_participation import (
        reconcile_costs,
        register_context,
        transition_context,
    )
    from test_cost_continuity import (
        context_descriptor,
        host_descriptor,
        reconcile_request,
        transition_request,
    )
    from test_cost_estimates import estimate_request

    if kind == "context":
        request = context_descriptor(operationId="late-context")
        return lambda: register_context(store, request)
    if kind == "estimate":
        request = estimate_request(store, operationId="late-estimate")
        return lambda: create_estimate(store, request)
    if kind == "transition":
        first = register_context(store, host_descriptor("before-close"))
        second = register_context(store, host_descriptor("after-close"))
        request = transition_request(
            store, first["participationId"], second["participationId"]
        )
        return lambda: transition_context(store, request)
    from test_cost_continuity import evidence, packet

    row = fact()
    variants = [
        evidence(row, nature="manual", modelBasis="unknown", acquisition=acquisition)
        for acquisition in ("manual", "imported")
    ]
    for index, metadata in enumerate(variants):
        store.ingest_packet(
            packet(
                store,
                [row],
                evidence_rows=[metadata],
                operation_id="before-close-" + str(index),
            ),
            allow_synthetic=True,
        )
    request = reconcile_request(store, *variants)
    return lambda: reconcile_costs(store, request)


@pytest.mark.parametrize(
    "kind", ["context", "estimate", "transition", "reconciliation"]
)
def test_authorized_service_replay_repairs_postcommit_closure(
    tmp_path, monkeypatch, offline_accounting, kind
):
    from avo import cost_history
    from test_cost_continuity import registered_ledger

    monkeypatch.setattr(cost_history, "providers_dir", lambda: tmp_path / "providers")
    store = registered_ledger(tmp_path)
    mutate = _late_service(store, kind)
    final = store.snapshot(
        summarize(store), "final", closure={"receiptHash": "synthetic-verified-cleanup"}
    )
    final_path = store.path("snapshots/" + final["snapshotId"] + ".json")
    original_bytes = final_path.read_bytes()

    def post_commit_crash():
        raise OSError("synthetic postcommit crash before amendment")

    with monkeypatch.context() as interrupted:
        interrupted.setattr(store, "amend_if_closed", post_commit_crash)
        with pytest.raises(OSError):
            mutate()
    before_reads = {path: path.read_bytes() for path in store.root.rglob("*.json")}
    report = summarize(store)
    history = cost_history.history(store=store)
    assert "closure-stale" in json.dumps(
        [report["diagnostics"], history["diagnostics"]]
    )
    assert {
        path: path.read_bytes() for path in store.root.rglob("*.json")
    } == before_reads
    assert mutate()["replayed"] is True
    amendments = [
        item
        for item in store.documents("snapshots")
        if item["lifecycle"] == "amendment"
    ]
    assert len(amendments) == 1
    assert amendments[0]["previousClosureId"] == final["snapshotId"]
    mutate()
    assert (
        len(
            [
                item
                for item in store.documents("snapshots")
                if item["lifecycle"] == "amendment"
            ]
        )
        == 1
    )
    assert final_path.read_bytes() == original_bytes


def test_qualified_report_wrap_learndown_history_share_one_capture(
    tmp_path, monkeypatch, offline_accounting
):
    from avo import cost_history, learndown_export, wrap

    monkeypatch.setattr(cost_history, "providers_dir", lambda: tmp_path / "providers")
    store, _, _ = _bounded_source(tmp_path, lifecycle="closed", flush="accepted")
    cleanup = store.raw_dir / "edit/cleanup/cleanup-result.json"
    cleanup.parent.mkdir(parents=True)
    cleanup.write_text(
        json.dumps(
            {
                "status": "completed",
                "rawDir": str(store.raw_dir),
                "masterBasename": "master",
                "deleted": [],
                "freedBytes": 0,
            }
        ),
        encoding="utf-8",
    )
    report = summarize(store)
    payload = wrap.build_wrap_payload(
        {"rawDir": str(store.raw_dir), "space": {}},
        session_id="qualified-cost-fixture",
        provider="channel",
        master_basename="master",
        summary="Qualified synthetic accounting",
        status="final",
    )
    entry = learndown_export.export_provider_learndown(payload, root=tmp_path / "repo")
    exported = json.loads((entry / "learndown.json").read_text("utf-8"))["costs"]
    historical = cost_history.history(store=store)["videos"][0]
    fields = (
        "tokens",
        "amounts",
        "usageByNature",
        "financialViews",
        "coverage",
        "pendingState",
        "pendingTurn",
        "sourceWatermarks",
        "membership",
        "cutoff",
    )
    for view in (payload["costs"], exported, historical):
        assert {field: view[field] for field in fields} == {
            field: report[field] for field in fields
        }


@pytest.mark.parametrize("kind", ["receipt", "profile"])
def test_store_replay_repairs_metadata_only_closure_without_new_tokens(
    tmp_path, monkeypatch, offline_accounting, kind
):
    from functools import partial

    from test_cost_continuity import packet, profile, receipt

    store, _, previous = _bounded_source(tmp_path)
    final = store.snapshot(
        summarize(store), "final", closure={"receiptHash": "synthetic-verified-cleanup"}
    )
    target = store.path("snapshots/" + final["snapshotId"] + ".json")
    before = target.read_bytes()
    if kind == "profile":
        frozen = profile(parserVersion="fixture-parser-2")
        mutate = partial(store.append_record, "profiles", frozen)
    else:
        proof = "a" * 64
        terminal = receipt(
            profile_id=previous["profileId"],
            predecessor=previous["receiptId"],
            sourceInstanceId="first-source",
            sourceSessionId="first-session",
            lifecycle={"state": "closed", "reference": proof},
            flush={"status": "accepted", "reference": proof},
            interval=previous["interval"],
            watermark={"kind": "event", "value": "finish"},
        )
        incoming = packet(store, receipts=[terminal], operation_id="late-terminal-only")
        incoming["profileId"] = previous["profileId"]
        mutate = partial(store.ingest_packet, incoming, allow_synthetic=True)

    def crashed():
        raise OSError("synthetic accepted metadata before amendment")

    with monkeypatch.context() as interrupted:
        interrupted.setattr(store, "amend_if_closed", crashed)
        with pytest.raises(OSError):
            mutate()
    mutate()
    amendments = [
        item
        for item in store.documents("snapshots")
        if item["lifecycle"] == "amendment"
    ]
    assert len(amendments) == 1
    assert amendments[0]["previousClosureId"] == final["snapshotId"]
    assert amendments[0]["tokens"] == final["tokens"]
    if kind == "receipt":
        assert amendments[0]["pendingTurn"] is False
    assert target.read_bytes() == before


def test_draft_and_final_share_known_totals(tmp_path):
    store = CostStore(tmp_path)
    store.initialize("channel", "video")
    store.ingest([fact()])
    draft = close_costs(tmp_path, "draft")
    assert draft["tokens"] == summarize(store)["tokens"]
    receipt = tmp_path / "edit/cleanup/cleanup-result.json"
    receipt.parent.mkdir()
    receipt.write_text(json.dumps({"status": "completed"}))
    final = close_costs(tmp_path, "final")
    assert final["tokens"] == draft["tokens"]
    assert final["lifecycle"] == "final"
    assert final["coverage"] == "partial"


def test_failed_cleanup_never_finalizes(tmp_path):
    store = CostStore(tmp_path)
    store.initialize("channel", "video")
    with pytest.raises(CostError, match="cleanup"):
        close_costs(tmp_path, "final")


def test_portable_export_survives_source_removal(tmp_path):
    source = CostStore(tmp_path / "video")
    source.initialize("channel", "video")
    source.ingest([fact()])
    source.snapshot(summarize(source), "draft")
    destination = tmp_path / "archive"
    source.export(destination)
    archive = CostStore(destination, archive=True)
    assert summarize(source) == summarize(archive)
    snapshot = source.documents("snapshots")[0]
    assert archive.path(f"snapshots/{snapshot['snapshotId']}.json").is_file()


def test_cleanup_keeps_new_cost_files_after_inventory(tmp_path):
    from avo.project_inventory import PreservedSetResult, scan_delete_candidates

    cost = tmp_path / "edit/costs/batches/new.json"
    cost.parent.mkdir(parents=True)
    cost.write_text("{}")
    disposable = tmp_path / "edit/scratch.txt"
    disposable.write_text("scratch")
    preserved = PreservedSetResult([], None, [], [], [])
    paths, _ = scan_delete_candidates(tmp_path, preserved)
    assert cost not in paths
    assert disposable in paths


@pytest.mark.parametrize("stage", ["draft", "final"])
def test_wrap_export_and_report_use_identical_snapshot(tmp_path, monkeypatch, stage):
    from avo import avo_state, learndown_export, wrap

    monkeypatch.setattr(avo_state, "state_dir", lambda: tmp_path / "state")
    raw = tmp_path / "video"
    store = CostStore(raw)
    store.initialize("channel", "video")
    store.ingest([fact(), fact("switch", model="model-b", serviceProvider="service-b")])
    if stage == "final":
        receipt = raw / "edit/cleanup/cleanup-result.json"
        receipt.parent.mkdir()
        receipt.write_text(
            json.dumps(
                {
                    "status": "completed",
                    "rawDir": str(raw),
                    "masterBasename": "master",
                    "deleted": [],
                    "freedBytes": 0,
                }
            )
        )
    payload = wrap.build_wrap_payload(
        {"rawDir": str(raw), "space": {}},
        session_id="s",
        provider="channel",
        master_basename="master",
        summary="Synthetic fixture",
        status=stage,
    )
    entry = learndown_export.export_provider_learndown(payload, root=tmp_path / "repo")
    exported = json.loads((entry / "learndown.json").read_text())
    assert exported["costs"] == payload["costs"]
    assert payload["costs"]["tokens"] == summarize(store)["tokens"]
    assert payload["costs"]["pendingTurn"] is None
    snapshot_id = payload["costs"]["snapshotId"]
    assert (entry / "costs/snapshots" / f"{snapshot_id}.json").is_file()
    assert (
        learndown_export.export_provider_learndown(payload, root=tmp_path / "repo")
        == entry
    )
    index = json.loads((entry.parent / "index.json").read_text())
    assert len(index["entries"]) == 1
