"""Supported source capabilities and explicit, private-data-free imports."""

import json
from pathlib import Path

import pytest

from avo.cost_sources import capabilities, collect, import_file
from avo.cost_store import CostError, CostStore
from test_costs import fact

AGENT_FIXTURES = Path(__file__).parent / "fixtures" / "costs" / "agents"
SURFACES = json.loads((AGENT_FIXTURES / "surfaces.json").read_text("utf-8"))[
    "environments"
]


@pytest.fixture(autouse=True)
def local_history_state(monkeypatch, tmp_path):
    from avo import avo_state, cost_history

    root = tmp_path / "state"
    monkeypatch.setattr(avo_state, "state_dir", lambda: root)
    monkeypatch.setattr(cost_history, "providers_dir", lambda: tmp_path / "providers")
    return root


@pytest.mark.parametrize("surface", SURFACES, ids=lambda item: item["environment"])
def test_surface_capabilities_require_native_qualification_and_offer_actionable_fallback(
    surface,
):
    row = next(v for v in capabilities() if v["environment"] == surface["environment"])
    assert (row["agent"], row["surface"], row["capability"]) == (
        surface["agent"],
        surface["surface"],
        surface["nativeCapability"],
    )
    assert row["versions"] == []
    assert row["qualificationEvidence"] == []
    assert {
        "context",
        "typed-packet",
        "normalized-import",
        "manual",
        "estimate",
    } <= set(row["modes"])
    assert (
        row["requiredIntervention"] and row["limitations"] and row["obtainableFields"]
    )
    assert row["fallback"]["commands"] == [
        "context",
        "report-manual",
        "observe",
        "estimate",
    ]
    assert row["fallback"]["reasonCode"] == "native-source-unqualified"


def _manual_surface_packet(tmp_path, surface):
    from test_cost_continuity import (
        evidence,
        packet,
        participation_fact,
        production,
        profile,
        receipt,
    )

    store, _ = production(tmp_path)
    family = "my-custom-executor" if surface["agent"] == "unknown" else surface["agent"]
    supplied_profile = profile(
        agent=family,
        surface=surface["surface"],
        versions=[],
        capability="candidate",
        qualification={"kind": "synthetic", "evidenceRefs": []},
    )
    store.append_record("profiles", supplied_profile)
    declared = participation_fact(
        store,
        agent={
            "family": family,
            "surface": surface["surface"],
            "version": "not-qualified",
            "role": "driver",
        },
    )
    store.append_record("participations", declared)
    row = fact(agent=family, agentVersion="not-qualified", model=None)
    metadata = evidence(
        row,
        profile_id=supplied_profile["profileId"],
        participationFactId=declared["factId"],
        nature="manual",
        modelBasis="unknown",
    )
    collected = receipt(
        profile_id=supplied_profile["profileId"], keys=store.keys_for([row])
    )
    value = packet(store, [row], evidence_rows=[metadata], receipts=[collected])
    value["profileId"] = supplied_profile["profileId"]
    return store, value, family


@pytest.mark.parametrize("surface", SURFACES, ids=lambda item: item["environment"])
def test_every_surface_can_contribute_typed_manual_usage_without_native_access(
    tmp_path, capsys, surface
):
    from avo import engine_cli
    from test_cost_continuity import (
        context_descriptor,
        evidence,
        packet,
        production,
        receipt,
    )

    store, project = production(tmp_path)
    family = "my-custom-executor" if surface["agent"] == "unknown" else surface["agent"]
    descriptor = context_descriptor()
    descriptor["agent"].update(
        family=family, surface=surface["surface"], version="not-qualified"
    )
    descriptor_file = tmp_path / "context.json"
    descriptor_file.write_text(json.dumps(descriptor), encoding="utf-8")
    assert (
        engine_cli.main(
            [
                "costs",
                "context",
                "--project",
                str(project),
                "--descriptor",
                str(descriptor_file),
                "--json",
            ]
        )
        == 0
    )
    context = json.loads(capsys.readouterr().out)
    assert not store.capture()["profiles"]
    row = fact(agent=family, agentVersion="not-qualified", model=None)
    source = tmp_path / "manual-metadata.json"
    source.write_text(json.dumps([row]), encoding="utf-8")
    argv = [
        "costs",
        "report-manual",
        "--project",
        str(project),
        "--file",
        str(source),
        "--participation-fact-id",
        context["factId"],
        "--operation-id",
        "manual-bootstrap",
        "--json",
    ]
    assert engine_cli.main(argv) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["imported"] == 1
    profile_id = result["profileId"]
    assert engine_cli.main(argv) == 0
    assert json.loads(capsys.readouterr().out)["replayed"] is True
    row2 = fact(
        "next-manual",
        agent=family,
        agentVersion="not-qualified",
        model=None,
        measurementKind="manual",
    )
    metadata = evidence(
        row2,
        participation_id=context["participationId"],
        participationFactId=context["factId"],
        profile_id=profile_id,
        nature="manual",
        modelBasis="unknown",
    )
    value = packet(
        store,
        [row2],
        evidence_rows=[metadata],
        operation_id="typed-after-bootstrap",
        receipts=[receipt(profile_id=profile_id, keys=store.keys_for([row2]))],
    )
    value["profileId"] = profile_id
    supplied = tmp_path / "typed-packet.json"
    supplied.write_text(json.dumps(value), encoding="utf-8")
    assert (
        engine_cli.main(
            [
                "costs",
                "observe",
                "--project",
                str(project),
                "--file",
                str(supplied),
                "--json",
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["imported"] == 1
    view = store.capture()
    assert (
        len(view["profiles"]) == 1
        and view["profiles"][0]["capability"] == "manual-only"
    )
    assert not view["profiles"][0]["versions"]
    assert all(r["agent"] == family for r in store.observations()[0])
    assert all(
        e["nature"] == "manual" and e["modelBasis"] == "unknown"
        for b in view["batches"]
        for e in b["evidence"]
    )


def test_public_manual_bootstrap_rejects_foreign_custom_family_before_profile_mutation(
    tmp_path, capsys
):
    from avo import engine_cli
    from test_cost_continuity import context_descriptor, production

    store, project = production(tmp_path)
    descriptor = context_descriptor()
    descriptor["agent"]["family"] = "my-custom-executor"
    descriptor_file = tmp_path / "context.json"
    descriptor_file.write_text(json.dumps(descriptor), encoding="utf-8")
    assert (
        engine_cli.main(
            [
                "costs",
                "context",
                "--project",
                str(project),
                "--descriptor",
                str(descriptor_file),
                "--json",
            ]
        )
        == 0
    )
    context = json.loads(capsys.readouterr().out)
    row = fact(agent="another-family", model="PRIVATE-MANUAL-SENTINEL")
    source = tmp_path / "manual-metadata.json"
    source.write_text(json.dumps([row]), encoding="utf-8")
    before = store.capture()
    assert (
        engine_cli.main(
            [
                "costs",
                "report-manual",
                "--project",
                str(project),
                "--file",
                str(source),
                "--participation-fact-id",
                context["factId"],
                "--operation-id",
                "denied-manual",
                "--json",
            ]
        )
        != 0
    )
    captured = capsys.readouterr()
    assert "PRIVATE-MANUAL-SENTINEL" not in captured.out + captured.err
    assert store.capture() == before


@pytest.mark.parametrize("surface", SURFACES, ids=lambda item: item["environment"])
def test_every_surface_rejects_unqualified_measured_usage_before_mutation(
    tmp_path, surface
):
    from avo.cost_participation import evidence_id

    store, value, _ = _manual_surface_packet(tmp_path, surface)
    metadata = value["evidence"][0]
    metadata["nature"] = "measured"
    metadata["evidenceId"] = evidence_id(metadata)
    before = store.capture()
    with pytest.raises(CostError, match="not qualified"):
        store.ingest_packet(value)
    assert store.capture() == before


def test_codex_synthetic_contract_fixture_does_not_certify_per_turn_or_finality(
    tmp_path,
):
    fixture = json.loads(
        (AGENT_FIXTURES / "codex-native-contract.json").read_text("utf-8")
    )
    source = tmp_path / "exec.jsonl"
    source.write_text(
        "\n".join(json.dumps(v) for v in fixture["events"]), encoding="utf-8"
    )
    with pytest.raises(CostError, match="normalized|qualified|cumulative"):
        import_file(source, "codex", session_id="thread-fixture")


def test_claude_sdk_temporal_tree_results_are_not_silently_request_events(tmp_path):
    fixture = json.loads(
        (AGENT_FIXTURES / "claude-native-contract.json").read_text("utf-8")
    )
    source = tmp_path / "sdk.json"
    source.write_text(json.dumps(fixture["sdkResults"]), encoding="utf-8")
    with pytest.raises(CostError, match="normalized|completed request|qualified"):
        import_file(source, "claude", session_id="claude-fixture")


def test_opencode_legacy_projection_preserves_native_ids_without_inventing_fork_dedup(
    tmp_path,
):
    fixture = json.loads(
        (AGENT_FIXTURES / "opencode-native-contract.json").read_text("utf-8")
    )
    source = tmp_path / "export.json"
    source.write_text(json.dumps(fixture["export"]), encoding="utf-8")
    rows = import_file(source, "opencode", session_id="opencode-fixture")
    assert [r["requestId"] for r in rows] == [
        "original-message",
        "copied-new-message-id",
        "new-work",
    ]
    assert len(rows) == 3
    assert rows[0]["semantics"]["reasoning"] == "disjoint"
    assert rows[0]["agentVersion"] == "unknown"
    assert (
        rows[-1]["model"] == "model-b" and rows[-1]["serviceProvider"] == "provider-b"
    )
    assert "PRIVATE" not in json.dumps(rows)


def test_all_named_agents_and_unknown_have_honest_fallback():
    values = capabilities()
    assert {v["agent"] for v in values} == {
        "claude",
        "codex",
        "gemini",
        "opencode",
        "cursor",
        "cline",
        "windsurf",
        "chatgpt",
        "unknown",
    }
    assert all("manual" in v["modes"] for v in values)


def test_codex_events_without_qualified_temporal_proof_require_fallback(tmp_path):
    source = tmp_path / "source.jsonl"
    source.write_text(
        json.dumps({"type": "thread.started", "thread_id": "t1"})
        + "\n"
        + json.dumps({"type": "item.completed", "text": "PRIVATE"})
        + "\n"
        + json.dumps(
            {
                "type": "turn.completed",
                "usage": {
                    "input_tokens": 100,
                    "cached_input_tokens": 60,
                    "output_tokens": 20,
                },
            }
        )
        + "\n"
    )
    with pytest.raises(CostError, match="normalized|qualified|cumulative") as error:
        import_file(source, "codex", session_id="t1")
    assert "PRIVATE" not in str(error.value)


def test_open_code_import_preserves_provider_switches(tmp_path):
    source = tmp_path / "source.json"
    messages = [
        {
            "info": {
                "role": "assistant",
                "id": f"m{i}",
                "sessionID": "s",
                "modelID": f"model-{i}",
                "providerID": f"service-{i}",
                "time": {"created": 1792684800000, "completed": 1792684801000},
                "tokens": {
                    "input": 100,
                    "output": 20,
                    "reasoning": 4,
                    "cache": {"read": 30, "write": 5},
                },
                "cost": 0.1,
            },
            "parts": [{"text": "PRIVATE"}],
        }
        for i in range(2)
    ]
    source.write_text(json.dumps({"messages": messages}))
    rows = import_file(source, "opencode", session_id="s")
    assert [r["serviceProvider"] for r in rows] == ["service-0", "service-1"]
    assert "PRIVATE" not in json.dumps(rows)


def test_collect_bound_source_skips_before_boundary(tmp_path):
    store = CostStore(tmp_path)
    store.initialize("channel", "video")
    source = tmp_path / "usage.json"
    source.write_text(json.dumps([fact("before"), fact("start"), fact("after")]))
    binding = store.bind(
        source=source, agent="codex", session_id="session", boundary="start"
    )
    collect(store)
    assert {r["requestId"] for r in store.observations()[0]} == {"after"}
    assert binding["bindingId"]


def test_unavailable_source_does_not_erase_usage(tmp_path):
    store = CostStore(tmp_path)
    store.initialize("channel", "video")
    source = tmp_path / "usage.json"
    source.write_text(json.dumps([fact()]))
    store.bind(source=source, agent="codex", session_id="session", boundary="beginning")
    collect(store)
    source.unlink()
    assert collect(store)["status"] == "partial"
    assert len(store.observations()[0]) == 1


def test_unknown_format_fails(tmp_path):
    with pytest.raises(CostError):
        import_file(tmp_path / "none", "private-unverified-format")


def test_opencode_tiny_charge_keeps_plain_decimal(tmp_path):
    source = tmp_path / "usage.json"
    source.write_text(
        json.dumps(
            {
                "messages": [
                    {
                        "info": {
                            "role": "assistant",
                            "id": "small",
                            "sessionID": "s",
                            "time": {"completed": 1792684801000},
                            "cost": 0.000001,
                        }
                    }
                ]
            }
        )
    )
    rows = import_file(source, "opencode", session_id="s")
    assert rows[0]["amounts"][0]["amount"] == "0.000001"
    store = CostStore(tmp_path / "video")
    store.initialize("channel", "tiny")
    store.ingest(rows)


@pytest.mark.parametrize("agent", ["claude", "gemini"])
def test_projected_telemetry_preserves_model_switch_and_strips_content(tmp_path, agent):
    name = "claude_code.api_request" if agent == "claude" else "gemini_cli.api_response"
    events = [
        {
            "name": name,
            "timestamp": "2026-10-22T16:00:00Z",
            "attributes": {
                "session.id": "s",
                "request_id": f"r{i}",
                "model": f"model-{i}",
                "input_tokens": 100,
                "output_tokens": 20,
                "cache_read_tokens": 10,
                "cache_creation_tokens": 0,
                "cost_usd_micros": 1,
                "prompt": "PRIVATE",
            },
        }
        for i in range(2)
    ]
    source = tmp_path / "events.json"
    source.write_text(json.dumps(events))
    rows = import_file(source, agent, session_id="s")
    assert [r["model"] for r in rows] == ["model-0", "model-1"]
    assert all(r["serviceProvider"] is None for r in rows)
    assert "PRIVATE" not in json.dumps(rows)
    store = CostStore(tmp_path / "video")
    store.initialize("channel", "video")
    store.ingest(rows)
    from avo.costs import summarize

    assert summarize(store)["tokens"]["total"] == (260 if agent == "claude" else None)


def test_malformed_native_container_is_safe_error(tmp_path):
    source = tmp_path / "bad.json"
    source.write_text('["PRIVATE"]')
    with pytest.raises(CostError, match="invalid"):
        import_file(source, "claude", session_id="s")


def _automatic_context(
    tmp_path,
    rows=None,
    *,
    synthetic=False,
    counter="request",
    source_shape="normalized",
    boundary="beginning",
    fork="new-activities",
    unknown_epoch=False,
):
    from avo.cost_participation import register_context
    from test_cost_continuity import context_descriptor, production, profile

    store, _ = production(tmp_path)
    rows = rows if rows is not None else [fact(agent="fixture-executor")]
    source = store.raw_dir / "authorized-requests.json"
    _write_collection_source(source, rows, source_shape)
    binding = store.bind(
        source=source,
        agent="fixture-executor",
        session_id="session",
        boundary=boundary,
        source_format="normalized",
    )
    supplied_profile = profile(
        agent="fixture-executor",
        sourceFormat=source_shape,
        qualification={
            "kind": "synthetic" if synthetic else "native",
            "evidenceRefs": ["c" * 64],
        },
    )
    supplied_profile["semantics"]["counter"] = counter
    supplied_profile["semantics"]["aggregateScope"] = (
        "thread" if counter == "cumulative" else "request"
    )
    supplied_profile["semantics"]["fork"] = fork
    supplied_profile.pop("profileId")
    supplied_profile["profileId"] = store.digest(supplied_profile)
    store.append_record("profiles", supplied_profile)
    descriptor = context_descriptor(
        sourceAttachment={
            "bindingId": binding["bindingId"],
            "profileId": supplied_profile["profileId"],
        }
    )
    descriptor["agent"]["family"] = "fixture-executor"
    descriptor["scope"]["beginning"]["reference"] = boundary
    if counter == "cumulative" and not unknown_epoch:
        descriptor["scope"].pop("counterEpoch", None)
    context = register_context(store, descriptor)
    return store, context, source, descriptor


def _write_collection_source(source, rows, shape="normalized-jsonl"):
    text = (
        "".join(json.dumps(row) + "\n" for row in rows)
        if shape == "normalized-jsonl"
        else json.dumps(rows)
    )
    source.write_text(text, encoding="utf-8", newline="\n")


def test_collect_context_accepts_exact_authorized_requests_with_unknown_finality(
    tmp_path,
):
    from avo.cost_sources import collect_context

    store, context, _, _ = _automatic_context(tmp_path)
    result = collect_context(store, context)
    assert result["status"] == "ok"
    assert result["imported"] == 1
    batch = store.capture()["batches"][0]
    metadata = batch["evidence"][0]
    assert metadata["participationId"] == context["participationId"]
    assert metadata["nature"] == "measured"
    assert metadata["acquisition"] == "automatic"
    assert metadata["sourceEventId"] == "r1"
    assert metadata["interval"]["start"]["reference"] == "r1"
    assert metadata["interval"]["end"]["reference"] == "r1"
    assert batch["receipts"][0]["lifecycle"] == {"state": "unknown", "reference": None}
    assert batch["receipts"][0]["flush"] == {"status": "unknown", "reference": None}
    assert batch["receipts"][0]["baseline"]["status"] == "not-applicable"


def test_collect_context_replay_adds_nothing_and_new_requests_extend_receipt_lineage(
    tmp_path,
):
    from avo.cost_sources import collect_context

    store, context, source, _ = _automatic_context(tmp_path)
    assert collect_context(store, context)["imported"] == 1
    first = store.capture()["batches"][0]["receipts"][0]
    before = store.capture()
    assert collect_context(store, context)["imported"] == 0
    assert store.capture() == before
    source.write_text(
        json.dumps(
            [
                fact(agent="fixture-executor"),
                fact("r2", agent="fixture-executor"),
            ]
        ),
        encoding="utf-8",
    )
    assert collect_context(store, context)["imported"] == 1
    receipts = [
        item for batch in store.capture()["batches"] for item in batch["receipts"]
    ]
    assert len(receipts) == 2
    assert any(item["predecessorReceiptId"] == first["receiptId"] for item in receipts)
    assert len(store.observations()[0]) == 2


def test_collect_context_without_attachment_never_uses_previous_host(
    tmp_path, monkeypatch
):
    from avo import cost_sources
    from avo.cost_participation import register_context

    store, _, _, _ = _automatic_context(tmp_path)
    unknown = register_context(
        store, None, run_alias="new-run", operation_id="unknown-entry"
    )

    def forbidden(*args, **kwargs):
        raise AssertionError("unknown current context must not read an old host source")

    monkeypatch.setattr(cost_sources, "import_file", forbidden)
    assert cost_sources.collect_context(store, unknown)["imported"] == 0
    assert not store.capture()["batches"]


@pytest.mark.parametrize(
    "synthetic,counter", [(True, "request"), (False, "cumulative")]
)
def test_collect_context_does_not_bypass_qualification_or_old_cumulative_adapters(
    tmp_path, monkeypatch, synthetic, counter
):
    from avo import cost_sources

    store, context, _, _ = _automatic_context(
        tmp_path, synthetic=synthetic, counter=counter
    )

    def forbidden(*args, **kwargs):
        raise AssertionError("ineligible profile must be rejected before source reads")

    monkeypatch.setattr(cost_sources, "import_file", forbidden)
    result = cost_sources.collect_context(store, context)
    assert result["status"] == "partial"
    assert result["diagnostics"]
    assert not store.capture()["batches"]


@pytest.mark.parametrize("failure", ["missing", "denied"])
def test_collect_context_source_failure_is_scoped_and_preserves_accepted_data(
    tmp_path, monkeypatch, failure
):
    from avo import cost_sources

    store, context, source, _ = _automatic_context(tmp_path)
    assert cost_sources.collect_context(store, context)["imported"] == 1
    before = store.capture()
    if failure == "missing":
        source.unlink()
    else:

        def denied(*args, **kwargs):
            raise PermissionError("PRIVATE-SOURCE-PATH")

        from pathlib import Path

        original_open = Path.open

        def source_denied(path, *args, **kwargs):
            if path == source:
                return denied()
            return original_open(path, *args, **kwargs)

        monkeypatch.setattr(Path, "open", source_denied)
    result = cost_sources.collect_context(store, context)
    assert result["status"] == "partial"
    assert result["imported"] == 0
    assert result["diagnostics"]
    assert "PRIVATE-SOURCE-PATH" not in json.dumps(result)
    assert store.capture() == before


@pytest.mark.parametrize("problem", ["missing-id", "scope", "category", "version"])
def test_collect_context_rejects_inconsistent_source_rows_without_partial_publication(
    tmp_path, problem
):
    from avo.cost_sources import collect_context

    row = fact(agent="fixture-executor")
    if problem == "missing-id":
        row.pop("requestId")
    elif problem == "scope":
        row["sourceInstanceId"] = "another-source"
    elif problem == "version":
        row["agentVersion"] = "unknown-version"
    else:
        row["semantics"]["reasoning"] = "disjoint"
    store, context, _, _ = _automatic_context(tmp_path, [row])
    result = collect_context(store, context)
    assert result["status"] == "partial"
    assert result["diagnostics"]
    assert not store.capture()["batches"]


def test_collect_context_requires_exact_fact_and_honors_effective_closed_grant(
    tmp_path,
):
    from avo.cost_sources import collect_context

    store, context, _, _ = _automatic_context(tmp_path)
    assert (
        collect_context(store, {**context, "factId": "f" * 64})["status"] == "partial"
    )
    fact_record = next(
        item
        for item in store.capture()["participations"]
        if item["factId"] == context["factId"]
    )
    store.close_binding(fact_record["sourceAttachment"]["bindingId"], "r1")
    result = collect_context(store, context)
    assert result["status"] == "ok"
    assert result["imported"] == 1
    assert _collection_receipts(store)[-1]["lifecycle"]["state"] == "unknown"


def test_collect_context_remembers_ledger_without_source_attachment(
    tmp_path, local_history_state
):
    from avo.cost_participation import register_context
    from avo.cost_sources import collect_context

    store, _, _, _ = _automatic_context(tmp_path)
    unknown = register_context(
        store, None, run_alias="new-run", operation_id="unknown-entry"
    )
    assert collect_context(store, unknown)["imported"] == 0
    locators = list((local_history_state / "cost-locators").glob("*.json"))
    assert len(locators) == 1
    assert json.loads(locators[0].read_text("utf-8"))["rawDir"] == str(store.raw_dir)


def test_collect_context_history_locator_failure_does_not_block_editing(
    tmp_path, monkeypatch
):
    from avo import cost_history, cost_sources
    from avo.cost_participation import register_context

    store, _, _, _ = _automatic_context(tmp_path)
    unknown = register_context(
        store, None, run_alias="new-run", operation_id="unknown-entry"
    )

    def denied(*args, **kwargs):
        raise PermissionError("PRIVATE-HISTORY-PATH")

    monkeypatch.setattr(cost_history, "remember", denied)
    result = cost_sources.collect_context(store, unknown)
    assert result["status"] == "partial"
    assert result["imported"] == 0
    assert result["diagnostics"]
    assert "PRIVATE-HISTORY-PATH" not in json.dumps(result)
    assert not store.capture()["batches"]


def _collection_receipts(store):
    from avo.cost_store import content_hash

    receipts = [
        receipt
        for batch in store.capture()["batches"]
        for receipt in batch.get("receipts", [])
    ]
    cursors = {
        content_hash(json.loads(r["watermark"]["value"])): json.loads(
            r["watermark"]["value"]
        )
        for r in receipts
    }

    def depth(receipt):
        cursor = json.loads(receipt["watermark"]["value"])
        count = 0
        while cursor.get("previous") in cursors:
            cursor = cursors[cursor["previous"]]
            count += 1
        return count

    return sorted(receipts, key=depth)


def test_incremental_jsonl_record_budget_and_committed_frontier_resume(
    tmp_path, monkeypatch
):
    from avo import cost_sources

    rows = [fact(f"r{i}", agent="fixture-executor") for i in range(5)]
    store, context, _, _ = _automatic_context(
        tmp_path, rows, source_shape="normalized-jsonl"
    )
    monkeypatch.setattr(cost_sources, "COLLECTION_RECORD_LIMIT", 2)
    first = cost_sources.collect_context(store, context)
    assert first["imported"] == 2
    assert first["status"] == "partial"
    assert "budget-incomplete" in _collection_receipts(store)[-1]["gaps"]
    assert cost_sources.collect_context(store, context)["imported"] == 2
    assert cost_sources.collect_context(store, context)["imported"] == 1
    before = store.capture()
    assert cost_sources.collect_context(store, context)["imported"] == 0
    assert store.capture() == before
    assert {row["requestId"] for row in store.observations()[0]} == {
        f"r{i}" for i in range(5)
    }
    cursors = [
        json.loads(receipt["watermark"]["value"])
        for receipt in _collection_receipts(store)
    ]
    assert all(
        receipt["watermark"]["kind"] == "normalized-cursor-v1"
        for receipt in _collection_receipts(store)
    )
    assert [cursor["offset"] for cursor in cursors] == sorted(
        cursor["offset"] for cursor in cursors
    )
    assert all(
        receipt["lifecycle"]["state"] == "unknown"
        for receipt in _collection_receipts(store)
    )


def test_incremental_jsonl_keeps_partial_record_before_frontier(tmp_path):
    from avo.cost_sources import collect_context

    first = fact("complete", agent="fixture-executor")
    partial = json.dumps(fact("later", agent="fixture-executor"))
    store, context, source, _ = _automatic_context(
        tmp_path, [first], source_shape="normalized-jsonl"
    )
    with source.open("a", encoding="utf-8") as stream:
        stream.write(partial[: len(partial) // 2])
    assert collect_context(store, context)["imported"] == 1
    cursor = json.loads(_collection_receipts(store)[-1]["watermark"]["value"])
    assert cursor["offset"] == len((json.dumps(first) + "\n").encode())
    assert "source-partial-record" in _collection_receipts(store)[-1]["gaps"]
    with source.open("a", encoding="utf-8") as stream:
        stream.write(partial[len(partial) // 2 :] + "\n")
    assert collect_context(store, context)["imported"] == 1
    assert len(store.observations()[0]) == 2


@pytest.mark.parametrize("change", ["rotation", "truncation", "reexport"])
def test_incremental_jsonl_replacement_never_recounts_known_native_ids(
    tmp_path, change
):
    from avo.cost_sources import collect_context

    rows = [fact("r1", agent="fixture-executor"), fact("r2", agent="fixture-executor")]
    store, context, source, _ = _automatic_context(
        tmp_path, rows, source_shape="normalized-jsonl"
    )
    assert collect_context(store, context)["imported"] == 2
    third = fact("r3", agent="fixture-executor")
    if change == "rotation":
        replacement = source.with_suffix(".replacement")
        _write_collection_source(replacement, [*rows, third])
        replacement.replace(source)
    else:
        _write_collection_source(
            source, [third] if change == "truncation" else [rows[1], rows[0], third]
        )
    result = collect_context(store, context)
    assert result["imported"] == 1
    assert result["status"] == "partial"
    assert _collection_receipts(store)[-1]["gaps"]
    assert len(store.observations()[0]) == 3


def test_incremental_byte_budget_counts_probes_and_reads(tmp_path, monkeypatch):
    from pathlib import Path

    from avo import cost_sources

    rows = [fact(f"r{i}", agent="fixture-executor") for i in range(5)]
    store, context, source, _ = _automatic_context(
        tmp_path, rows, source_shape="normalized-jsonl"
    )
    limit = len((json.dumps(rows[0]) + "\n").encode()) * 2 + 50
    monkeypatch.setattr(cost_sources, "COLLECTION_BYTE_LIMIT", limit)
    original_open = Path.open
    read_bytes = [0]

    class MeasuredSource:
        def __init__(self, stream):
            self.stream = stream

        def __getattr__(self, name):
            return getattr(self.stream, name)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return self.stream.__exit__(*args)

        def read(self, *args):
            data = self.stream.read(*args)
            read_bytes[0] += len(data)
            return data

        def readline(self, *args):
            data = self.stream.readline(*args)
            read_bytes[0] += len(data)
            return data

    def measured_open(path, *args, **kwargs):
        stream = original_open(path, *args, **kwargs)
        return MeasuredSource(stream) if path == source and "b" in args[0] else stream

    monkeypatch.setattr(Path, "open", measured_open)
    for _ in range(10):
        read_bytes[0] = 0
        cost_sources.collect_context(store, context)
        assert read_bytes[0] <= limit
        if len(store.observations()[0]) == len(rows):
            break
    assert len(store.observations()[0]) == len(rows)


def test_incremental_record_size_rejection_retains_prior_complete_records(
    tmp_path, monkeypatch
):
    from avo import cost_sources

    first = fact("safe", agent="fixture-executor")
    store, context, source, _ = _automatic_context(
        tmp_path, [first], source_shape="normalized-jsonl"
    )
    limit = len((json.dumps(first) + "\n").encode()) + 20
    monkeypatch.setattr(cost_sources, "COLLECTION_RECORD_BYTE_LIMIT", limit)
    with source.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps({"secret": "PRIVATE-RECORD" * limit}) + "\n")
    result = cost_sources.collect_context(store, context)
    assert result["imported"] == 1
    assert result["status"] == "partial"
    assert "source-record-too-large" in _collection_receipts(store)[-1]["gaps"]
    assert "PRIVATE-RECORD" not in json.dumps(store.capture())


def test_incremental_frontier_never_advances_if_packet_publication_fails(
    tmp_path, monkeypatch
):
    from avo import cost_sources

    store, context, _, _ = _automatic_context(tmp_path, source_shape="normalized-jsonl")
    original = store.ingest_packet

    def interrupted(*args, **kwargs):
        raise OSError("interrupted commit")

    monkeypatch.setattr(store, "ingest_packet", interrupted)
    assert cost_sources.collect_context(store, context)["status"] == "partial"
    assert not _collection_receipts(store)
    monkeypatch.setattr(store, "ingest_packet", original)
    assert cost_sources.collect_context(store, context)["imported"] == 1


def _counter(request, value, sequence, epoch="epoch-1", **changes):
    return fact(
        request,
        agent="fixture-executor",
        measurementKind="cumulative",
        counterEpoch=epoch,
        sequence=sequence,
        tokens={"input": value, "output": 0},
        semantics={},
        amounts=[],
        **changes,
    )


def test_cumulative_jsonl_preserves_explicit_baseline_and_raw_endpoints(tmp_path):
    from avo.cost_sources import collect_context
    from avo.costs import summarize

    rows = [_counter("baseline", 10000, 0), _counter("end", 11200, 1)]
    store, context, _, _ = _automatic_context(
        tmp_path,
        rows,
        counter="cumulative",
        source_shape="normalized-jsonl",
        boundary="baseline",
    )
    assert collect_context(store, context)["imported"] == 2
    assert _collection_receipts(store)[-1]["baseline"] == {
        "status": "accepted",
        "reference": "baseline",
    }
    assert [row["tokens"]["input"] for row in store.observations()[0]] == [10000, 11200]
    assert all(
        e["aggregateScope"]["kind"] == "thread"
        for b in store.capture()["batches"]
        for e in b["evidence"]
    )
    assert summarize(store)["tokens"]["total"] == 1200


def test_cumulative_missing_baseline_is_unallocated_not_implicit_zero(tmp_path):
    from avo.cost_sources import collect_context

    rows = [_counter("first", 10000, 5), _counter("end", 11200, 6)]
    store, context, _, _ = _automatic_context(
        tmp_path, rows, counter="cumulative", source_shape="normalized-jsonl"
    )
    assert collect_context(store, context)["imported"] == 2
    batches = store.capture()["batches"]
    assert all(
        item["attribution"]["status"] == "unallocated"
        for batch in batches
        for item in batch["evidence"]
    )
    assert _collection_receipts(store)[-1]["baseline"]["status"] == "missing"
    assert "baseline-missing" in _collection_receipts(store)[-1]["gaps"]


def test_cumulative_observed_zero_starts_each_native_epoch_without_fabricating_one(
    tmp_path,
):
    from avo.cost_sources import collect_context
    from avo.costs import summarize

    rows = [
        _counter("zero-1", 0, 0),
        _counter("end-1", 1000, 1),
        _counter("zero-2", 0, 0, "epoch-2"),
        _counter("end-2", 200, 1, "epoch-2"),
    ]
    store, context, _, _ = _automatic_context(
        tmp_path, rows, counter="cumulative", source_shape="normalized-jsonl"
    )
    assert collect_context(store, context)["imported"] == 4
    assert {receipt["counterEpoch"] for receipt in _collection_receipts(store)} == {
        "epoch-1",
        "epoch-2",
    }
    assert all(
        receipt["baseline"]["status"] == "accepted"
        for receipt in _collection_receipts(store)
    )
    assert summarize(store)["tokens"]["total"] == 1200


def test_cumulative_reduction_without_native_epoch_leaves_reset_activity_unallocated(
    tmp_path,
):
    from avo.cost_sources import collect_context

    rows = [
        _counter("zero", 0, 0),
        _counter("end", 1000, 1),
        _counter("reduced", 100, 2),
        _counter("later", 200, 3),
    ]
    store, context, _, _ = _automatic_context(
        tmp_path, rows, counter="cumulative", source_shape="normalized-jsonl"
    )
    assert collect_context(store, context)["imported"] == 4
    metadata = {
        item["sourceEventId"]: item
        for batch in store.capture()["batches"]
        for item in batch["evidence"]
    }
    assert metadata["reduced"]["attribution"]["status"] == "unallocated"
    assert metadata["later"]["attribution"]["status"] == "unallocated"
    assert "counter-epoch-required" in _collection_receipts(store)[-1]["gaps"]


def test_copied_request_history_requires_explicit_inheritance_boundary(tmp_path):
    from avo.cost_sources import collect_context

    rows = [
        fact("copied-new-id", agent="fixture-executor", parentSessionId="old-session"),
        fact("new-work", agent="fixture-executor", parentSessionId="old-session"),
    ]
    store, context, _, _ = _automatic_context(
        tmp_path, rows, source_shape="normalized-jsonl", fork="copied-history"
    )
    assert collect_context(store, context)["imported"] == 2
    assert all(
        item["attribution"]["status"] == "unallocated"
        for batch in store.capture()["batches"]
        for item in batch["evidence"]
    )
    assert "inheritance-boundary-missing" in _collection_receipts(store)[-1]["gaps"]


def test_packet_budget_and_compact_source_scopes_do_not_duplicate_run_alias_history(
    tmp_path, monkeypatch
):
    from avo import cost_sources
    from avo.cost_participation import register_context

    rows = [fact(f"r{i}", agent="fixture-executor") for i in range(8)]
    store, _, source, descriptor = _automatic_context(
        tmp_path, rows, source_shape="normalized-jsonl"
    )
    descriptor["operationId"] = "large-alias-context"
    descriptor["scope"]["runAliases"] = [f"run-{i}-" + "a" * 450 for i in range(200)]
    context = register_context(store, descriptor)
    monkeypatch.setattr(cost_sources, "COLLECTION_PACKET_BYTE_LIMIT", 7000)
    for _ in range(10):
        cost_sources.collect_context(store, context)
        if len(store.observations()[0]) == len(rows):
            break
    assert len(store.observations()[0]) == len(rows)
    for batch in store.capture()["batches"]:
        assert len(json.dumps(batch).encode()) < 8000
        assert all(
            item["attribution"]["scope"]["runAliases"] == []
            for item in batch["evidence"]
        )
    assert source.exists()


def test_standalone_collect_uses_only_unique_explicit_context_attachment(tmp_path):
    store, context, _, _ = _automatic_context(tmp_path, source_shape="normalized-jsonl")
    selected = next(
        item
        for item in store.capture()["participations"]
        if item["factId"] == context["factId"]
    )
    result = collect(store, selected["sourceAttachment"]["bindingId"])
    assert result["imported"] == 1
    assert (
        store.capture()["batches"][0]["evidence"][0]["participationId"]
        == context["participationId"]
    )


def test_standalone_collect_never_selects_last_of_conflicting_context_owners(tmp_path):
    from test_cost_continuity import participation_fact

    store, context, _, _ = _automatic_context(tmp_path, source_shape="normalized-jsonl")
    selected = next(
        item
        for item in store.capture()["participations"]
        if item["factId"] == context["factId"]
    )
    competing = participation_fact(
        store,
        operation_id="competing-owner",
        participationId="00000000-0000-4000-8000-000000000016",
        agent=selected["agent"],
        scope=selected["scope"],
        sourceAttachment=selected["sourceAttachment"],
    )
    store.append_record("participations", competing)
    result = collect(store, selected["sourceAttachment"]["bindingId"])
    assert result["status"] == "partial"
    assert result["imported"] == 0
    assert not store.capture()["batches"]


def test_incremental_boundary_scan_resumes_without_importing_prior_history(
    tmp_path, monkeypatch
):
    from avo import cost_sources

    rows = [fact(f"r{i}", agent="fixture-executor") for i in range(6)]
    store, context, _, _ = _automatic_context(
        tmp_path, rows, source_shape="normalized-jsonl", boundary="r3"
    )
    monkeypatch.setattr(cost_sources, "COLLECTION_RECORD_LIMIT", 2)
    assert cost_sources.collect_context(store, context)["imported"] == 0
    assert cost_sources.collect_context(store, context)["imported"] == 0
    assert cost_sources.collect_context(store, context)["imported"] == 2
    assert {r["requestId"] for r in store.observations()[0]} == {"r4", "r5"}
    assert not _collection_receipts(store)[-1]["gaps"]


def test_cumulative_baseline_survives_multiple_chunks_and_reexport(
    tmp_path, monkeypatch
):
    from avo import cost_sources

    rows = [
        _counter("zero", 0, 0),
        _counter("first", 100, 1),
        _counter("second", 200, 2),
    ]
    store, context, source, _ = _automatic_context(
        tmp_path, rows, counter="cumulative", source_shape="normalized-jsonl"
    )
    monkeypatch.setattr(cost_sources, "COLLECTION_RECORD_LIMIT", 1)
    for _ in rows:
        assert cost_sources.collect_context(store, context)["imported"] == 1
    _write_collection_source(source, [*rows, _counter("third", 300, 3)])
    for _ in range(5):
        cost_sources.collect_context(store, context)
    metadata = [e for b in store.capture()["batches"] for e in b["evidence"]]
    assert len(metadata) == 4
    assert all(e["attribution"]["status"] == "assigned" for e in metadata)
    assert all(
        r["baseline"] == {"status": "accepted", "reference": "zero"}
        for r in _collection_receipts(store)
    )


def test_native_epoch_after_reset_does_not_inherit_old_epoch_gap(tmp_path):
    from avo.cost_sources import collect_context

    rows = [
        _counter("zero", 0, 0),
        _counter("first", 100, 1),
        _counter("reset", 10, 2),
        _counter("zero-new", 0, 0, "new"),
        _counter("new-work", 20, 1, "new"),
    ]
    store, context, _, _ = _automatic_context(
        tmp_path, rows, counter="cumulative", source_shape="normalized-jsonl"
    )
    assert collect_context(store, context)["imported"] == 5
    receipts = _collection_receipts(store)
    assert (
        "counter-epoch-required"
        in next(r for r in receipts if r["counterEpoch"] == "epoch-1")["gaps"]
    )
    assert (
        "counter-epoch-required"
        not in next(r for r in receipts if r["counterEpoch"] == "new")["gaps"]
    )


def test_collection_uses_exact_revised_fact_and_retains_historical_provenance(tmp_path):
    from copy import deepcopy

    from avo.cost_participation import build_participation_fact
    from avo.cost_sources import collect_context

    store, original_context, source, _ = _automatic_context(tmp_path)
    view = store.capture()
    original = next(
        f for f in view["participations"] if f["factId"] == original_context["factId"]
    )
    revised_profile = deepcopy(view["profiles"][0])
    revised_profile["versions"] = ["fixture-2"]
    revised_profile.pop("profileId")
    revised_profile["profileId"] = store.digest(revised_profile)
    store.append_record("profiles", revised_profile)
    revision = deepcopy(original)
    revision.update(
        kind="revise",
        operationId="new-agent-version",
        predecessors=[original["factId"]],
    )
    revision.pop("factId")
    revision["agent"]["version"] = "fixture-2"
    revision["sourceAttachment"]["profileId"] = revised_profile["profileId"]
    revision = build_participation_fact(revision)
    store.append_record("participations", revision)
    _write_collection_source(
        source,
        [fact("new", agent="fixture-executor", agentVersion="fixture-2")],
        "normalized",
    )
    revised_context = {**original_context, "factId": revision["factId"]}
    assert collect_context(store, revised_context)["imported"] == 1
    _write_collection_source(
        source, [fact("historical", agent="fixture-executor")], "normalized"
    )
    assert collect_context(store, original_context)["imported"] == 1
    metadata = {
        e["sourceEventId"]: e for b in store.capture()["batches"] for e in b["evidence"]
    }
    assert metadata["new"]["participationFactId"] == revision["factId"]
    assert metadata["historical"]["participationFactId"] == original["factId"]


def test_explicit_known_baseline_starts_new_grant_without_requalifying_history(
    tmp_path,
):
    from avo.cost_participation import register_context
    from avo.cost_sources import collect_context

    rows = [_counter("zero", 0, 0), _counter("prior", 100, 1)]
    store, original_context, source, descriptor = _automatic_context(
        tmp_path,
        rows,
        counter="cumulative",
        source_shape="normalized-jsonl",
        boundary="zero",
    )
    assert collect_context(store, original_context)["imported"] == 2
    store.close_binding(descriptor["sourceAttachment"]["bindingId"], "prior")
    grant = store.bind(
        source=source,
        agent="fixture-executor",
        session_id="session",
        boundary="prior",
        source_format="normalized",
    )
    descriptor["operationId"] = "explicit-new-grant"
    descriptor["scope"]["beginning"]["reference"] = "prior"
    descriptor["sourceAttachment"]["bindingId"] = grant["bindingId"]
    context = register_context(store, descriptor)
    _write_collection_source(source, [*rows, _counter("new-work", 200, 2)])
    assert collect_context(store, context)["imported"] == 1
    metadata = [e for b in store.capture()["batches"] for e in b["evidence"]]
    assert len(metadata) == 3
    assert (
        next(e for e in metadata if e["sourceEventId"] == "new-work")["attribution"][
            "status"
        ]
        == "assigned"
    )
    receipt = next(
        r for r in _collection_receipts(store) if r["bindingId"] == grant["bindingId"]
    )
    assert receipt["baseline"] == {"status": "accepted", "reference": "prior"}


def test_cumulative_native_epoch_does_not_require_caller_to_know_epoch(tmp_path):
    from avo.cost_sources import collect_context

    store, context, _, _ = _automatic_context(
        tmp_path,
        [_counter("zero", 0, 0), _counter("work", 100, 1)],
        counter="cumulative",
        source_shape="normalized-jsonl",
        unknown_epoch=True,
    )
    result = collect_context(store, context)
    assert result["imported"] == 2
    assert {row["counterEpoch"] for row in store.observations()[0]} == {"epoch-1"}


def test_standalone_collect_never_falls_back_after_attachment_is_removed(tmp_path):
    from avo.cost_participation import build_participation_fact

    store, context, _, _ = _automatic_context(tmp_path)
    original = next(
        f for f in store.capture()["participations"] if f["factId"] == context["factId"]
    )
    revision = {
        **original,
        "kind": "revise",
        "operationId": "remove-attachment",
        "predecessors": [original["factId"]],
    }
    revision.pop("factId")
    attachment = revision.pop("sourceAttachment")
    store.append_record("participations", build_participation_fact(revision))
    result = collect(store, attachment["bindingId"])
    assert result["status"] == "partial"
    assert result["imported"] == 0
    assert not store.capture()["batches"]


def test_binding_narrowed_after_frontier_never_collects_later_rows(tmp_path):
    from avo.cost_sources import collect_context

    rows = [fact(f"r{i}", agent="fixture-executor") for i in range(3)]
    store, context, source, descriptor = _automatic_context(
        tmp_path, rows, source_shape="normalized-jsonl"
    )
    assert collect_context(store, context)["imported"] == 3
    store.close_binding(descriptor["sourceAttachment"]["bindingId"], "r1")
    _write_collection_source(source, [*rows, fact("later", agent="fixture-executor")])
    assert collect_context(store, context)["imported"] == 0
    assert "later" not in {r["requestId"] for r in store.observations()[0]}
    assert all(
        r["lifecycle"]["state"] == "unknown" for r in _collection_receipts(store)
    )
