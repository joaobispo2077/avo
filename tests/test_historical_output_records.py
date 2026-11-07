from __future__ import annotations

import json

import pytest

from avo.timeline import migration
from avo.timeline.contracts import content_hash, file_fingerprint
from avo.timeline.media_admission import (
    MediaAdmissionError,
    require_no_forbidden_outputs,
)


def _record(tmp_path, kind="cut-proof", *, output=None):
    output = output or {
        "sha256": "a" * 64,
        "sizeBytes": 100,
        "locator": str(tmp_path / "deleted-output.mkv"),
    }
    value = {
        "schemaVersion": "1.0.0",
        "kind": kind,
        "materializationId": "cut-proof-r1-" + output["sha256"][:12],
        "canonicalInputLock": {"source:camera": "b" * 64},
        "renderProfile": "proof",
        "projectionHash": "c" * 64,
        "output": output,
        "producer": {"name": "fixture", "version": "1"},
        "createdAt": "2026-11-03T00:00:00Z",
        "cmapRevisionId": "r1",
    }
    if kind == "proof-plan":
        value.pop("cmapRevisionId")
        value.pop("projectionHash")
        value.update(
            checkpoint="pre-master",
            materializationId="proof-build-plan-" + output["sha256"][:12],
            proofPlanId="proof-plan-fixture",
            proofPlanHash="c" * 64,
            preflightHash="d" * 64,
            microproofGateHash="e" * 64,
        )
    value["materializationHash"] = content_hash(value)
    return value


def _write(tmp_path, value, *, timeline_dir=None):
    directory = (timeline_dir or tmp_path / "edit" / "timeline") / "materializations"
    path = directory / value["kind"] / (value["materializationId"] + ".json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def _assembly_record(tmp_path):
    value = _record(tmp_path)
    value.pop("cmapRevisionId")
    lock = {"rawFingerprints": {"camera": "b" * 64}}
    for kind in ("cmap", "sync", "bmap", "tracks"):
        lock[kind + "RevisionId"] = "r1"
        lock[kind + "RevisionHash"] = "c" * 64
    contract = {
        "width": 64,
        "height": 48,
        "frameRate": {"num": 24, "den": 1, "tolerance": 0},
        "allowedTransformations": [],
    }
    nodes = [
        {
            "nodeId": node_id,
            "kind": kind,
            "role": role,
            "mediaClass": role,
            "locator": locator,
            "sha256": sha,
            "pictureCarrying": True,
            "media": {},
        }
        for node_id, kind, role, locator, sha in (
            ("raw", "source", "source", "camera.mov", "b" * 64),
            ("result", "output", "proof", value["output"]["locator"], "a" * 64),
        )
    ]
    lineage = {
        "schemaVersion": "1.0.0",
        "canonicalInputLock": lock,
        "projectionHash": "c" * 64,
        "nodes": nodes,
        "edges": [
            {
                "edgeId": "render",
                "from": "raw",
                "to": "result",
                "operation": "render",
                "order": 0,
                "parameters": {},
            }
        ],
        "rootIds": ["result"],
        "pictureLineageHash": "d" * 64,
    }
    policy = {
        "policyId": "fixture",
        "profileId": "proof",
        "settingSources": {},
        "renderContract": contract,
        "prohibitedBaseClasses": ["proof"],
        "roleRules": {},
        "policyHash": "e" * 64,
    }
    value.update(
        schemaVersion="1.1.0",
        kind="assembly",
        materializationId="assembly-fixture",
        canonicalInputLock=lock,
        renderContract=contract,
        renderContractHash="c" * 64,
        renderHash="c" * 64,
        pictureLineage=lineage,
        pictureLineageHash="d" * 64,
        deliveryFidelityPolicy=policy,
        deliveryFidelityPolicyHash="e" * 64,
    )
    value["materializationHash"] = content_hash(
        {key: item for key, item in value.items() if key != "materializationHash"}
    )
    return value


def test_valid_assembly_output_does_not_quarantine_raw_lineage_or_lock(tmp_path):
    _write(tmp_path, _assembly_record(tmp_path))
    known = migration.inventory_historical_output_fingerprints(tmp_path)
    assert {item["sha256"] for item in known} == {"a" * 64}


@pytest.mark.parametrize(
    "fault", ["unknown-field", "missing-field", "version", "empty-lock"]
)
def test_native_proof_record_rejects_malformed_shape_even_with_rehashed_body(
    tmp_path, fault
):
    value = _record(tmp_path, "proof-plan")
    if fault == "unknown-field":
        value["sourceOutput"] = {"sha256": "f" * 64}
    elif fault == "missing-field":
        del value["microproofGateHash"]
    elif fault == "version":
        value["schemaVersion"] = "2.0.0"
    else:
        value["canonicalInputLock"] = {}
    value["materializationHash"] = content_hash(
        {key: item for key, item in value.items() if key != "materializationHash"}
    )
    _write(tmp_path, value)
    with pytest.raises(ValueError, match="historical materialization"):
        migration.inventory_historical_output_fingerprints(tmp_path)


@pytest.mark.parametrize("kind", ["cut-proof", "proof-plan"])
def test_deleted_canonical_output_stays_quarantined_after_copy_rename(tmp_path, kind):
    relocated = tmp_path / "camera.mov"
    relocated.write_bytes(b"previously rendered picture and audio")
    output = {**file_fingerprint(relocated), "locator": str(tmp_path / "deleted.mkv")}
    record = _record(tmp_path, kind, output=output)
    path = _write(tmp_path, record)
    known = migration.inventory_historical_output_fingerprints(tmp_path)
    assert len(known) == 1
    assert known[0]["sha256"] == output["sha256"]
    assert known[0]["recordPath"] == str(path)
    with pytest.raises(MediaAdmissionError, match="PROOF_FORBIDDEN_ANCESTOR"):
        require_no_forbidden_outputs(
            [{**file_fingerprint(relocated), "mediaClass": "source"}],
            known_outputs=known,
        )


def test_only_output_fingerprint_is_quarantined_never_source_lock_hashes(tmp_path):
    record = _record(tmp_path)
    _write(tmp_path, record)
    unrelated = (
        tmp_path / "edit" / "timeline" / "materializations" / "cut-proof" / "notes.json"
    )
    unrelated.write_text(json.dumps({"source": {"sha256": "f" * 64}}))
    known = migration.inventory_historical_output_fingerprints(tmp_path)
    assert {item["sha256"] for item in known} == {"a" * 64}
    require_no_forbidden_outputs(
        [{"sha256": "b" * 64, "mediaClass": "source"}], known_outputs=known
    )


def test_existing_roles_and_canonical_outputs_are_combined(tmp_path):
    for directory in ("masters", "delivery", "previews", "proxies"):
        path = tmp_path / "edit" / directory / "old.mkv"
        path.parent.mkdir(parents=True)
        path.write_bytes(directory.encode())
    _write(tmp_path, _record(tmp_path))
    known = migration.inventory_historical_output_fingerprints(tmp_path)
    assert {item["role"] for item in known} == {
        "proof",
        "master",
        "delivery",
        "preview",
        "proxy",
    }


def test_explicit_canonical_root_includes_deleted_output_records(tmp_path):
    root = tmp_path / "custom-canonical-root"
    record = _record(tmp_path)
    _write(tmp_path, record, timeline_dir=root)
    assert migration.inventory_historical_output_fingerprints(tmp_path) == []
    assert (
        migration.inventory_historical_output_fingerprints(tmp_path, timeline_dir=root)[
            0
        ]["sha256"]
        == "a" * 64
    )


@pytest.mark.parametrize(
    "fault", ["hash", "output", "id", "kind", "nonfinite", "duplicate", "syntax"]
)
def test_corrupt_claimed_materialization_fails_closed(tmp_path, fault):
    value = _record(tmp_path)
    path = _write(tmp_path, value)
    if fault == "hash":
        value["output"]["sha256"] = "f" * 64
    elif fault == "output":
        value["output"]["sizeBytes"] = -1
        value["materializationHash"] = content_hash(
            {key: item for key, item in value.items() if key != "materializationHash"}
        )
    elif fault == "id":
        value["materializationId"] = "other"
    elif fault == "kind":
        value["kind"] = "source"
    text = json.dumps(value)
    if fault == "nonfinite":
        text = text.replace('"sizeBytes": 100', '"sizeBytes": NaN')
    elif fault == "duplicate":
        text = text.replace(
            '"kind": "cut-proof"', '"kind": "cut-proof", "kind": "source"'
        )
    elif fault == "syntax":
        text = text[:-2]
    path.write_text(text, encoding="utf-8")
    with pytest.raises(ValueError, match="historical materialization"):
        migration.inventory_historical_output_fingerprints(tmp_path)


def test_mutable_reuse_cache_is_not_an_output_record(tmp_path):
    directory = tmp_path / "edit" / "timeline" / "materializations" / "cut-proof"
    directory.mkdir(parents=True)
    (directory / "reuse-cache.json").write_text("not provenance JSON")
    assert migration.inventory_historical_output_fingerprints(tmp_path) == []


def test_hash_verified_record_can_keep_a_historical_filename(tmp_path):
    path = _write(tmp_path, _record(tmp_path))
    path.rename(path.with_name("retained-historical-record.json"))
    assert (
        migration.inventory_historical_output_fingerprints(tmp_path)[0]["sha256"]
        == "a" * 64
    )


@pytest.mark.parametrize("contradictory", [False, True])
def test_legacy_path_alias_is_hash_bound_and_cannot_disagree_with_locator(
    tmp_path, contradictory
):
    record = _record(tmp_path)
    output = record["output"]
    output["path"] = output.pop("locator")
    if contradictory:
        output["locator"] = "different-output.mov"
    record["materializationHash"] = content_hash(
        {key: item for key, item in record.items() if key != "materializationHash"}
    )
    _write(tmp_path, record)
    if contradictory:
        with pytest.raises(ValueError, match="historical materialization.*disagree"):
            migration.inventory_historical_output_fingerprints(tmp_path)
    else:
        known = migration.inventory_historical_output_fingerprints(tmp_path)
        assert known[0]["locator"] == output["path"]


def test_materialization_byte_and_count_limits_fail_closed(tmp_path, monkeypatch):
    _write(tmp_path, _record(tmp_path))
    monkeypatch.setattr(migration, "MAX_HISTORICAL_RECORD_BYTES", 20)
    with pytest.raises(ValueError, match="historical materialization.*limit"):
        migration.inventory_historical_output_fingerprints(tmp_path)
    monkeypatch.setattr(migration, "MAX_HISTORICAL_RECORD_BYTES", 1024 * 1024)
    monkeypatch.setattr(migration, "MAX_HISTORICAL_RECORDS", 0)
    with pytest.raises(ValueError, match="historical materialization.*limit"):
        migration.inventory_historical_output_fingerprints(tmp_path)
    monkeypatch.setattr(migration, "MAX_HISTORICAL_RECORDS", 10)
    monkeypatch.setattr(migration, "MAX_HISTORICAL_TOTAL_BYTES", 20)
    with pytest.raises(ValueError, match="historical materialization.*limit"):
        migration.inventory_historical_output_fingerprints(tmp_path)


def test_resolved_record_cannot_escape_canonical_root(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    path = _write(tmp_path, _record(tmp_path), timeline_dir=outside)
    directory = tmp_path / "edit" / "timeline" / "materializations" / "cut-proof"
    directory.mkdir(parents=True)
    link = directory / path.name
    try:
        link.symlink_to(path)
    except OSError:
        pytest.skip("Native symlink creation unavailable")
    with pytest.raises(ValueError, match="historical materialization.*escape"):
        migration.inventory_historical_output_fingerprints(tmp_path)
