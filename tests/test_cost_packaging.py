"""Same no-inference accounting surface through engine, CLI and optional MCP."""

import builtins
import json

import pytest

from avo import engine_cli
from avo.mcp.bridge import run_cli
from avo.mcp.registry import get_tool
from avo.paths import schema_path


@pytest.fixture(autouse=True)
def isolated_accounting_locations(monkeypatch, tmp_path):
    from avo import avo_state, cost_history

    monkeypatch.setattr(avo_state, "state_dir", lambda: tmp_path / "state")
    monkeypatch.setattr(cost_history, "providers_dir", lambda: tmp_path / "providers")


def _private_legacy_projection(store):
    from avo.cost_store import content_hash

    path = next(store.path("batches").glob("*.json"))
    batch = json.loads(path.read_text("utf-8"))
    batch["PRIVATE-LEGACY-FIELD"] = {
        "text": "PRIVATE-PREIMAGE",
        "path": "H:/PRIVATE-SOURCE/location",
    }
    batch["observations"][0]["PRIVATE-OBSERVATION-FIELD"] = "PRIVATE-TRANSCRIPT"
    batch["observations"][0]["amounts"][0]["PRIVATE-AMOUNT-FIELD"] = "PRIVATE-TOOL-ARGS"
    batch["observationKeys"] = store.keys_for(batch["observations"])
    batch["contentHash"] = content_hash(
        {k: v for k, v in batch.items() if k != "contentHash"}
    )
    path.write_text(json.dumps(batch), encoding="utf-8")
    return path, batch


def _legacy_projection_store(tmp_path):
    from avo.cost_store import CostStore
    from test_costs import fact

    store = CostStore(tmp_path / "production")
    store.initialize("channel", "video")
    store.ingest([fact()])
    path, original = _private_legacy_projection(store)
    return store, path, original


def _json_bytes(root):
    return {
        p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*.json")
    }


@pytest.mark.parametrize("relation", ["same", "ancestor", "descendant"])
def test_portable_export_rejects_overlapping_destination_before_mutation(
    tmp_path, relation
):
    from avo.cost_store import CostError, CostStore
    from test_costs import fact

    store = CostStore(tmp_path / "production")
    store.initialize("channel", "video")
    store.ingest([fact()])
    destinations = {
        "same": store.root,
        "ancestor": store.root.parent,
        "descendant": store.root / "nested",
    }
    before = _json_bytes(store.raw_dir)
    with pytest.raises(CostError, match="destination|overlap|source|canonical"):
        store.export(destinations[relation])
    assert _json_bytes(store.raw_dir) == before


@pytest.mark.parametrize("existing", ["raw-binding", "unmanaged"])
def test_portable_projection_refuses_existing_private_target_without_deleting_it(
    tmp_path, existing
):
    from avo.cost_store import CostError

    store, _, _ = _legacy_projection_store(tmp_path)
    destination = tmp_path / "portable"
    relative = (
        "bindings/old-grant.json" if existing == "raw-binding" else "unmanaged.json"
    )
    path = destination / relative
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {"source": "Q:/PRIVATE-OLD-GRANT", "PRIVATE-UNKNOWN": "PRIVATE-CONTENT"}
        ),
        encoding="utf-8",
    )
    before = _json_bytes(destination)
    with pytest.raises(CostError) as error:
        store.export(destination)
    assert "PRIVATE-" not in str(error.value)
    assert _json_bytes(destination) == before


def test_portable_manifest_separates_original_membership_and_omitted_preimage(tmp_path):
    from avo.cost_store import content_hash

    store, original_path, original = _legacy_projection_store(tmp_path)
    before = original_path.read_bytes()
    destination = tmp_path / "portable"
    store.export(destination)
    manifest = json.loads((destination / "portable.json").read_text("utf-8"))
    assert manifest["verification"] == "metadata-projection"
    assert manifest["sourceReauthorizationRequired"] is True
    assert {
        "omitted-preimages-not-verifiable",
        "source-reauthorization-required",
    } <= set(manifest["limitations"])
    assert manifest["manifestId"] == content_hash(
        {k: v for k, v in manifest.items() if k != "manifestId"}
    )
    record = next(r for r in manifest["records"] if r["kind"] == "batches")
    assert record["originalDigest"] == content_hash(original)
    assert record["originalMembershipDigest"] == original["contentHash"]
    projected = json.loads((destination / record["path"]).read_text("utf-8"))
    assert record["projectedDigest"] == content_hash(projected)
    assert record["originalDigest"] != record["projectedDigest"]
    assert "unrecognized-fields" in record["omissions"]
    assert projected["observationKeys"] == original["observationKeys"]
    assert original_path.read_bytes() == before
    all_json = b"\n".join(_json_bytes(destination).values())
    assert b"PRIVATE-" not in all_json
    assert b"PRIVATE-SOURCE" not in all_json


def test_portable_collection_refuses_before_source_or_locator_access(
    tmp_path, monkeypatch
):
    from avo import cost_history, cost_sources
    from avo.cost_store import CostError, CostStore
    from test_costs import fact

    store = CostStore(tmp_path / "production")
    store.initialize("channel", "video")
    source = tmp_path / "PRIVATE-SOURCE.json"
    source.write_text(json.dumps([fact()]), encoding="utf-8")
    store.bind(source=source, agent="codex", session_id="session", boundary="beginning")
    store.export(tmp_path / "portable")
    archive = CostStore(tmp_path / "portable", archive=True)

    def forbidden(*args, **kwargs):
        raise AssertionError("portable metadata is not source authorization")

    monkeypatch.setattr(cost_sources, "import_file", forbidden)
    monkeypatch.setattr(cost_history, "remember", forbidden)
    with pytest.raises(CostError, match="portable|read-only|reauthoriz"):
        cost_sources.collect(archive)
    assert not archive.path("bindings").exists()
    assert all("source" not in v for v in archive.documents("bindings"))


def test_exact_canonical_snapshot_lookup_ignores_unrelated_corrupt_snapshot(tmp_path):
    from avo.cost_store import CostStore
    from avo.costs import summarize
    from test_costs import fact

    store = CostStore(tmp_path / "production")
    store.initialize("channel", "video")
    store.ingest([fact()])
    first = store.snapshot(summarize(store), "draft")
    store.ingest([fact("late")])
    second = store.snapshot(summarize(store), "draft")
    store.path(f"snapshots/{second['snapshotId']}.json").write_text(
        "invalid unrelated snapshot", encoding="utf-8"
    )
    assert store.read_snapshot(first["snapshotId"]) == first


def test_portable_history_registration_does_not_grant_or_block_source_reauthorization(
    tmp_path,
):
    from avo import cost_history
    from avo.cost_store import CostStore
    from test_costs import fact

    store = CostStore(tmp_path / "production")
    store.initialize("channel", "video")
    source = tmp_path / "PRIVATE-REAUTHORIZE.json"
    source.write_text(json.dumps([fact()]), encoding="utf-8")
    binding = store.bind(
        source=source, agent="codex", session_id="session", boundary="beginning"
    )
    store.close_binding(binding["bindingId"], "r1")
    store.export(tmp_path / "portable")
    archive = CostStore(tmp_path / "portable", archive=True)
    cost_history.remember(archive)
    candidates = cost_history._history_sources(
        None, include_provider_exports=False, include_portable=False
    )
    assert candidates and all(
        candidate.root != archive.root for candidate in candidates
    )
    target = CostStore(tmp_path / "another-production")
    target.initialize("channel", "another-video")
    reauthorized = target.bind(
        source=source, agent="codex", session_id="session", boundary="r1"
    )
    assert reauthorized["source"] == str(source.resolve())


@pytest.mark.parametrize("projection", ["binding-only", "omitted-legacy-preimage"])
def test_portable_known_activity_reserves_assignment_when_canonical_ledger_is_offline(
    tmp_path, projection
):
    from avo import cost_history
    from avo.cost_store import CostError, CostStore
    from avo.costs import summarize
    from test_cost_continuity import evidence, packet, registered_ledger
    from test_costs import fact

    if projection == "binding-only":
        original = registered_ledger(tmp_path / "first")
        row = fact("retained-native")
        source = tmp_path / "PRIVATE-RETAINED-SOURCE.json"
        source.write_text(json.dumps([row]), encoding="utf-8")
        binding = original.bind(
            source=source, agent="codex", session_id="session", boundary="beginning"
        )
        original.close_binding(binding["bindingId"], row["requestId"])
        original.ingest_packet(packet(original, [row]), allow_synthetic=True)
    else:
        original, _, _ = _legacy_projection_store(tmp_path / "first")
        row = fact()
    destination = tmp_path / "portable"
    original.export(destination)
    archive = CostStore(destination, archive=True)
    cost_history.remember(archive)
    identity = original.path("identity.json")
    identity.rename(identity.with_suffix(".offline"))
    second = registered_ledger(tmp_path / "second")
    before = second.capture()
    with pytest.raises(CostError, match="assigned|production|claim|allocation"):
        second.ingest_packet(packet(second, [row]), allow_synthetic=True)
    assert second.capture() == before
    unallocated = evidence(
        row,
        attribution={
            "status": "unallocated",
            "basis": "retained activity belongs to another production",
            "scope": evidence(row)["attribution"]["scope"],
        },
    )
    second.ingest_packet(
        packet(
            second,
            [row],
            evidence_rows=[unallocated],
            operation_id="retained-unallocated",
        ),
        allow_synthetic=True,
    )
    report = summarize(second)
    assert report["activityEvidenceIds"] == []
    assert report["unallocated"]["tokens"]["total"] == 120


def test_portable_reader_detects_projection_tamper_with_recomputed_batch_hash(tmp_path):
    from avo.cost_store import CostError, CostStore, content_hash
    from avo.costs import summarize

    store, _, _ = _legacy_projection_store(tmp_path)
    destination = tmp_path / "portable"
    store.export(destination)
    manifest = json.loads((destination / "portable.json").read_text("utf-8"))
    record = next(r for r in manifest["records"] if r["kind"] == "batches")
    path = destination / record["path"]
    projected = json.loads(path.read_text("utf-8"))
    projected["observations"][0]["tokens"]["input"] = 999
    projected["contentHash"] = content_hash(
        {k: v for k, v in projected.items() if k != "contentHash"}
    )
    path.write_text(json.dumps(projected), encoding="utf-8")
    with pytest.raises(CostError, match="projection|integrity|portable"):
        summarize(CostStore(destination, archive=True))


@pytest.mark.parametrize(
    "tamper",
    ["path", "reauthorization", "private-field", "record-kind", "record-omissions"],
)
def test_portable_manifest_rejects_unsafe_index_without_echo(tmp_path, tamper):
    from avo.cost_store import CostError, CostStore, content_hash

    store, _, _ = _legacy_projection_store(tmp_path)
    destination = tmp_path / "portable"
    store.export(destination)
    path = destination / "portable.json"
    manifest = json.loads(path.read_text("utf-8"))
    if tamper == "path":
        manifest["records"][0]["path"] = "../PRIVATE-OUTSIDE.json"
    elif tamper == "reauthorization":
        manifest["sourceReauthorizationRequired"] = False
    elif tamper == "private-field":
        manifest["PRIVATE-UNKNOWN-KEY"] = "PRIVATE-UNKNOWN-CONTENT"
    elif tamper == "record-kind":
        manifest["records"][0]["kind"] = {"PRIVATE-KEY": "PRIVATE-CONTENT"}
    else:
        manifest["records"][0]["omissions"] = [{"PRIVATE-KEY": "PRIVATE-CONTENT"}]
    manifest["manifestId"] = content_hash(
        {k: v for k, v in manifest.items() if k != "manifestId"}
    )
    path.write_text(json.dumps(manifest), encoding="utf-8")
    (
        destination / "portable-manifests" / (manifest["manifestId"] + ".json")
    ).write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(CostError) as error:
        CostStore(destination, archive=True).capture()
    assert "PRIVATE-" not in str(error.value)


def test_portable_replay_and_additive_amendment_preserve_prior_manifests_and_snapshots(
    tmp_path,
):
    from avo.cost_store import CostStore
    from avo.costs import summarize
    from test_costs import fact

    store, original_path, _ = _legacy_projection_store(tmp_path)
    original_bytes = original_path.read_bytes()
    final = store.snapshot(
        summarize(store),
        "final",
        closure={
            "mode": "cleanup",
            "receiptPath": "edit/cleanup/synthetic-result.json",
            "receiptHash": "a" * 64,
        },
    )
    final_bytes = store.path(f"snapshots/{final['snapshotId']}.json").read_bytes()
    destination = tmp_path / "portable"
    store.export(destination)
    first_bytes = _json_bytes(destination)
    first = json.loads(first_bytes["portable.json"])
    store.export(destination)
    assert _json_bytes(destination) == first_bytes
    store.ingest([fact("late")])
    store.export(destination)
    second = json.loads((destination / "portable.json").read_text("utf-8"))
    assert second["manifestId"] != first["manifestId"]
    assert second["predecessorManifestId"] == first["manifestId"]
    assert (
        json.loads(
            (
                destination / "portable-manifests" / (first["manifestId"] + ".json")
            ).read_text("utf-8")
        )
        == first
    )
    assert (
        destination / f"snapshots/{final['snapshotId']}.json"
    ).read_bytes() == final_bytes
    archive = CostStore(destination, archive=True)
    assert summarize(archive)["tokens"] == summarize(store)["tokens"]
    assert summarize(archive)["membership"] == summarize(store)["membership"]
    assert (
        store.path(f"snapshots/{final['snapshotId']}.json").read_bytes() == final_bytes
    )
    assert original_path.read_bytes() == original_bytes
    copied = tmp_path / "copied-portable"
    archive.export(copied)
    assert _json_bytes(copied) == _json_bytes(destination)


def test_portable_capture_freezes_one_manifest_while_additive_index_advances(
    tmp_path, monkeypatch
):
    from avo import cost_history
    from avo.cost_store import CostStore
    from test_costs import fact

    source, _, _ = _legacy_projection_store(tmp_path)
    destination = tmp_path / "portable"
    source.export(destination)
    archive = CostStore(destination, archive=True)
    expected = archive.capture()
    original = cost_history._portable_documents
    manifests = []
    advanced = False

    def advance_after_capture(store, kind, manifest):
        nonlocal advanced
        manifests.append(manifest["manifestId"])
        if not advanced:
            advanced = True
            source.ingest([fact("late")])
            source.export(destination)
        return original(store, kind, manifest)

    monkeypatch.setattr(cost_history, "_portable_documents", advance_after_capture)
    assert archive.capture() == expected
    assert len(manifests) == 8 and len(set(manifests)) == 1
    assert len(archive.capture()["batches"]) == 2


def test_portable_index_commit_failure_keeps_prior_membership_until_retry(
    tmp_path, monkeypatch
):
    from avo.cost_store import CostStore
    from test_costs import fact

    source, _, _ = _legacy_projection_store(tmp_path)
    destination = tmp_path / "portable"
    source.export(destination)
    archive = CostStore(destination, archive=True)
    original_view = archive.capture()
    source.ingest([fact("late")])
    publish = CostStore._publish_locked

    def interrupted(path, value):
        if path.name == "portable.json":
            raise OSError("synthetic index commit interruption")
        return publish(path, value)

    monkeypatch.setattr(CostStore, "_publish_locked", staticmethod(interrupted))
    with pytest.raises(OSError):
        source.export(destination)
    assert archive.capture() == original_view
    monkeypatch.setattr(CostStore, "_publish_locked", staticmethod(publish))
    source.export(destination)
    assert len(archive.capture()["batches"]) == 2


@pytest.mark.parametrize("change", ["remove", "replace"])
def test_portable_export_cannot_remove_or_change_prior_record_projection(
    tmp_path, change
):
    from avo.cost_store import CostError, content_hash

    store, path, original = _legacy_projection_store(tmp_path)
    destination = tmp_path / "portable"
    store.export(destination)
    before = _json_bytes(destination)
    if change == "remove":
        path.unlink()
    else:
        original["observations"][0]["tokens"]["input"] = 200
        original["observationKeys"] = store.keys_for(original["observations"])
        original["contentHash"] = content_hash(
            {k: v for k, v in original.items() if k != "contentHash"}
        )
        path.write_text(json.dumps(original), encoding="utf-8")
    with pytest.raises(CostError, match="immutable|prior|projection|portable"):
        store.export(destination)
    assert _json_bytes(destination) == before


def test_portable_projection_retains_all_new_families_and_exact_safe_snapshot_offline(
    tmp_path,
):
    import shutil

    from avo import project_inventory
    from avo.cost_store import CostStore
    from avo.costs import summarize
    from test_cost_continuity import (
        evidence,
        packet,
        participation_fact,
        profile,
        reconciliation,
    )
    from test_costs import _financial_estimate, fact
    from test_project_inventory import FIXTURE, MASTER_BASENAME

    store, _, _ = _legacy_projection_store(tmp_path)
    store.append_record("profiles", profile())
    store.append_record("participations", participation_fact(store))
    row = fact("v2-new", agentVersion="fixture-1")
    old, new = evidence(row), evidence(row, nature="manual")
    store.ingest_packet(packet(store, [row], evidence_rows=[old]), allow_synthetic=True)
    store.ingest_packet(
        packet(store, [row], evidence_rows=[new], operation_id="new-metadata")
    )
    store.append_record("estimates", _financial_estimate(store))
    store.append_record("reconciliations", reconciliation(store, old, new))
    shutil.copytree(FIXTURE, store.raw_dir, dirs_exist_ok=True)
    temporary_source = store.raw_dir / "edit/temporary-host-usage.json"
    temporary_source.write_text(json.dumps([row]), encoding="utf-8")
    store.bind(
        source=temporary_source,
        agent="codex",
        session_id="session",
        boundary="beginning",
    )
    view = store.capture()
    assert all(
        view[k] for k in ("profiles", "participations", "estimates", "reconciliations")
    )
    snapshot = store.snapshot(summarize(store), "draft")
    snapshot_bytes = store.path(f"snapshots/{snapshot['snapshotId']}.json").read_bytes()

    def remove_fixture_file(path):
        assert path.resolve().is_relative_to(store.raw_dir / "edit")
        path.unlink()

    cleaned = project_inventory.run_cleanup(
        store.raw_dir,
        MASTER_BASENAME,
        rimraf_runner=remove_fixture_file,
        purge_session=False,
    )
    assert temporary_source in cleaned.paths
    assert not temporary_source.exists()
    assert not cleaned.leftover
    assert store.capture() == view
    assert store.read_snapshot(snapshot["snapshotId"]) == snapshot
    destination = tmp_path / "portable"
    store.export(destination)
    archive = CostStore(destination, archive=True)
    assert all(
        archive.capture()[k] == view[k]
        for k in ("profiles", "participations", "estimates", "reconciliations")
    )
    assert (
        archive.path(f"snapshots/{snapshot['snapshotId']}.json").read_bytes()
        == snapshot_bytes
    )
    assert summarize(archive)["tokens"] == summarize(store)["tokens"]
    assert summarize(archive)["membership"] == summarize(store)["membership"]
    assert (
        archive.observations()[0][0]["_sourceDigest"]
        == store.observations()[0][0]["_sourceDigest"]
    )


@pytest.mark.parametrize(
    "receipt_path", ["Q:/PRIVATE-RECEIPT/cleanup.json", "/PRIVATE-RECEIPT/cleanup.json"]
)
def test_portable_unsafe_snapshot_has_derived_identity_and_no_original_lookup_alias(
    tmp_path, receipt_path
):
    from avo.cost_store import CostError, CostStore, content_hash
    from avo.costs import summarize
    from test_costs import fact

    store = CostStore(tmp_path / "production")
    store.initialize("channel", "video")
    store.ingest([fact()])
    original = store.snapshot(
        summarize(store),
        "final",
        closure={
            "mode": "cleanup",
            "receiptPath": receipt_path,
            "receiptHash": "a" * 64,
        },
    )
    original_bytes = store.path(f"snapshots/{original['snapshotId']}.json").read_bytes()
    destination = tmp_path / "portable"
    store.export(destination)
    assert b"PRIVATE-RECEIPT" not in b"\n".join(_json_bytes(destination).values())
    manifest = json.loads((destination / "portable.json").read_text("utf-8"))
    record = next(r for r in manifest["records"] if r["kind"] == "snapshots")
    assert record["id"] == original["snapshotId"]
    assert record["originalDigest"] == content_hash(original)
    projected = json.loads((destination / record["path"]).read_text("utf-8"))
    assert projected["snapshotId"] != original["snapshotId"]
    assert record["omissions"]
    archive = CostStore(destination, archive=True)
    with pytest.raises(CostError, match="preimage|omitted|unavailable|projection"):
        archive.read_snapshot(original["snapshotId"])
    assert archive.read_snapshot(projected["snapshotId"]) == projected
    assert archive.portable_status()["verification"] == "metadata-projection"
    assert store.read_snapshot(original["snapshotId"]) == original
    assert (
        store.path(f"snapshots/{original['snapshotId']}.json").read_bytes()
        == original_bytes
    )


@pytest.mark.parametrize("kind", ["profiles", "participations"])
def test_portable_export_rejects_private_extras_in_strict_new_families_without_echo(
    tmp_path, kind
):
    from avo.cost_store import CostError
    from test_cost_continuity import registered_ledger

    store = registered_ledger(tmp_path)
    path = next(store.path(kind).glob("*.json"))
    invalid = json.loads(path.read_text("utf-8"))
    invalid["PRIVATE-UNKNOWN-KEY"] = "PRIVATE-NEW-FAMILY-CONTENT"
    path.write_text(json.dumps(invalid), encoding="utf-8")
    destination = tmp_path / "portable"
    with pytest.raises(CostError) as error:
        store.export(destination)
    assert "PRIVATE-" not in str(error.value)
    assert b"PRIVATE-" not in b"\n".join(_json_bytes(destination).values())


def test_engine_capabilities_routes_to_same_command(capsys):
    assert engine_cli.main(["costs", "capabilities", "--json"]) == 0
    first = json.loads(capsys.readouterr().out)
    assert engine_cli.main(["metrics", "capabilities", "--json"]) == 0
    assert first == json.loads(capsys.readouterr().out)


def test_mcp_reads_and_mutations_are_classified():
    assert not get_tool("avo_costs_report").destructive
    assert not get_tool("avo_costs_capabilities").destructive
    assert get_tool("avo_costs_import").destructive
    assert get_tool("avo_costs_bind").destructive
    assert get_tool("avo_costs_snapshot").destructive
    assert run_cli(["costs", "capabilities", "--json"]).parsed_json["agents"]


def test_shipped_schema_paths_exist():
    for kind in (
        "identity",
        "binding",
        "observation",
        "batch",
        "price",
        "correction",
        "snapshot",
    ):
        assert schema_path(f"avo.cost-{kind}.schema.json").is_file()








def test_portable_binding_scope_omits_locator_and_cannot_grant_collection(tmp_path):
    from avo.cost_store import CostError, CostStore
    from avo.costs import summarize
    from test_costs import fact

    store = CostStore(tmp_path / "production")
    store.initialize("channel", "video")
    source = tmp_path / "PRIVATE-LOCATOR-SENTINEL.json"
    source.write_text(json.dumps([fact()]), encoding="utf-8")
    binding = store.bind(
        source=source, agent="codex", session_id="session", boundary="beginning"
    )
    store.close_binding(binding["bindingId"], "r1")
    store.ingest([fact()])
    original = {str(p): p.read_bytes() for p in store.root.rglob("*.json")}
    destination = tmp_path / "portable"
    store.export(destination)
    exported = "\n".join(
        p.read_text(encoding="utf-8") for p in destination.rglob("*.json")
    )
    assert "PRIVATE-LOCATOR-SENTINEL" not in exported
    assert str(source) not in exported
    manifest = json.loads((destination / "portable.json").read_text(encoding="utf-8"))
    assert manifest["sourceReauthorizationRequired"] is True
    assert manifest["verification"] == "metadata-projection"
    archive = CostStore(destination, archive=True)
    source.unlink()
    assert summarize(archive)["tokens"] == summarize(store)["tokens"]
    assert summarize(archive)["membership"] == summarize(store)["membership"]
    with pytest.raises(CostError, match="reauthoriz|read-only|portable"):
        archive.ingest([fact("forbidden")])
    assert {str(p): p.read_bytes() for p in store.root.rglob("*.json")} == original


def test_portable_legacy_projection_omits_unrecognized_preimage(tmp_path):
    from avo.cost_store import CostStore, content_hash
    from avo.costs import summarize
    from test_costs import fact

    store = CostStore(tmp_path / "production")
    store.initialize("channel", "video")
    store.ingest([fact()])
    path = next(store.path("batches").glob("*.json"))
    batch = json.loads(path.read_text(encoding="utf-8"))
    batch["legacyConversation"] = {"text": "PRIVATE-PREIMAGE-SENTINEL"}
    batch["contentHash"] = content_hash(
        {k: v for k, v in batch.items() if k != "contentHash"}
    )
    path.write_text(json.dumps(batch), encoding="utf-8")
    original = path.read_bytes()
    destination = tmp_path / "portable"
    store.export(destination)
    exported = "\n".join(
        p.read_text(encoding="utf-8") for p in destination.rglob("*.json")
    )
    assert "PRIVATE-PREIMAGE-SENTINEL" not in exported
    assert "legacyConversation" not in exported
    assert path.read_bytes() == original
    archive = CostStore(destination, archive=True)
    assert summarize(archive)["tokens"]["total"] == 120
    assert summarize(archive)["membership"] == summarize(store)["membership"]
    manifest = json.loads((destination / "portable.json").read_text(encoding="utf-8"))
    assert any(record["omissions"] for record in manifest["records"])


def test_v2_families_are_captured_and_exported_without_temporary_sources(tmp_path):
    from avo.cost_store import CostStore
    from test_cost_continuity import packet, registered_ledger
    from test_costs import fact

    store = registered_ledger(tmp_path / "production")
    store.ingest_packet(packet(store, [fact()]), allow_synthetic=True)
    view = store.capture()
    assert set(view) == {
        "batches",
        "prices",
        "bindings",
        "corrections",
        "participations",
        "profiles",
        "estimates",
        "reconciliations",
    }
    assert view["participations"] and view["profiles"] and view["batches"]
    store.export(tmp_path / "portable")
    archive = CostStore(tmp_path / "portable", archive=True)
    assert archive.identity() == store.identity()
    assert archive.capture() == view
    assert (
        archive.observations()[0][0]["_sourceDigest"]
        == store.observations()[0][0]["_sourceDigest"]
    )
