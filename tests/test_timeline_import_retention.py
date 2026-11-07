"""Cleanup retains only import evidence reachable from canonical history/recovery."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from avo.timeline import import_retention
from avo.timeline.contracts import content_hash, file_fingerprint
from avo.timeline.import_evidence import verify_import_origin
from avo.timeline.import_retention import retained_import_paths, retained_return_paths
from avo.timeline.lineage import LineageError
from avo.timeline.workspace import TimelineWorkspace
from tests.test_timeline_import_evidence import _activate, _prepare_evidence
from tests.test_timeline_import_reimport import _commit, _replacement, _scoped_edit
from tests.test_timeline_import_service import _trial
from tests.test_timeline_import_service import import_project as _project


def _write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def _files(root):
    return {path: path.read_bytes() for path in root.rglob("*") if path.is_file()}


def _active(tmp_path):
    service, ready = _prepare_evidence(tmp_path)
    return service, ready, _activate(service, ready)


def test_no_import_history_or_pending_packet_never_initializes_or_scans_staged_tree(
    tmp_path,
):
    project, _, _ = _project.__wrapped__(tmp_path)
    workspace = TimelineWorkspace.from_project(project)
    before = _files(tmp_path)
    assert retained_import_paths(workspace) == []
    assert _files(tmp_path) == before


def test_active_import_retains_exact_chain_current_refs_and_snapshot_not_original_media(
    tmp_path,
):
    service, ready, revision = _active(tmp_path)
    expected = set(verify_import_origin(service.workspace, revision))
    snapshot = service.root / ready["importId"] / "snapshot.json"
    before = _files(service.workspace.raw_dir)
    retained = set(retained_import_paths(service.workspace))
    assert retained == expected | {snapshot}
    assert all(path.is_relative_to(service.root) for path in retained)
    assert not any(path.suffix == ".mov" for path in retained)
    assert _files(service.workspace.raw_dir) == before


def test_scoped_history_and_later_mutable_receipt_keep_original_activation_chain(
    tmp_path,
):
    service, ready, revision = _active(tmp_path)
    original = set(verify_import_origin(service.workspace, revision))
    _scoped_edit(service, revision)
    latest = service.validate(ready["importId"])
    assert latest["validationHash"] != ready["validationHash"]
    retained = set(retained_import_paths(service.workspace))
    assert original <= retained
    for ref in service.load(ready["importId"])["refs"].values():
        assert service.root / ready["importId"] / ref["path"] in retained


def test_unreferenced_stage_and_orphan_files_are_disposable(tmp_path):
    service, ready, revision = _active(tmp_path)
    original = revision["snapshot"]["sources"][0]["locator"]
    document = json.loads(
        (service.root / ready["importId"] / "source.otio").read_text()
    )
    document["name"] = "Unselected stage"
    export = tmp_path / "unselected.otio"
    _write(export, document)
    orphan = _trial(service, original, export=export)
    scratch = service.root / ready["importId"] / "orphan.json"
    _write(scratch, {"unused": True})
    retained = set(retained_import_paths(service.workspace))
    assert scratch not in retained
    assert not any(
        path.is_relative_to(service.root / orphan["importId"]) for path in retained
    )


def _activated_repair(tmp_path):
    service, ready = _prepare_evidence(tmp_path)
    source = service.root / ready["importId"] / "source.otio"
    prepared = service.prepare(
        source,
        supersedes_import_id=ready["importId"],
        actor="fixture",
        reason="Same-export repair retains predecessor evidence",
    )
    repaired = service.validate(prepared["importId"])
    assert repaired["status"] == "ready-to-activate"
    revision = _activate(service, repaired)
    return service, ready, repaired, revision


def test_repair_preserves_hash_bound_predecessor_without_selecting_other_stages(
    tmp_path,
):
    service, prior, repaired, _ = _activated_repair(tmp_path)
    retained = set(retained_import_paths(service.workspace))
    for import_id in (prior["importId"], repaired["importId"]):
        packet = service.root / import_id
        assert packet / "index.json" in retained
        assert packet / "source.otio" in retained
        assert packet / "snapshot.json" in retained
        for ref in service.load(import_id)["refs"].values():
            assert packet / ref["path"] in retained


def test_predecessor_referenced_bytes_are_verified_before_cleanup(tmp_path):
    service, prior, _, _ = _activated_repair(tmp_path)
    packet = service.root / prior["importId"]
    proposal = service.load(prior["importId"])["refs"]["proposal"]
    (packet / proposal["path"]).write_bytes(
        (packet / proposal["path"]).read_bytes() + b" "
    )
    with pytest.raises(LineageError, match="fingerprint|hash|bytes"):
        retained_import_paths(service.workspace)


def test_mutable_latest_reference_cannot_escape_packet_even_with_matching_hash(
    tmp_path,
):
    service, ready, _ = _active(tmp_path)
    packet = service.root / ready["importId"]
    foreign = service.root / "foreign.json"
    _write(foreign, {"notPacketEvidence": True})
    session = service.load(ready["importId"])
    fingerprint = file_fingerprint(foreign)
    session["refs"]["foreign"] = {
        "path": "../foreign.json",
        "sha256": fingerprint["sha256"],
        "sizeBytes": fingerprint["sizeBytes"],
    }
    _write(packet / "index.json", session)
    with pytest.raises(LineageError, match="escape|contained"):
        retained_import_paths(service.workspace)


def test_semantic_filenames_are_not_confused_with_file_byte_fingerprints(tmp_path):
    service, ready, _ = _active(tmp_path)
    packet = service.root / ready["importId"]
    session = service.load(ready["importId"])
    ref = session["refs"]["proposal"]
    assert (packet / ref["path"]).stem != ref["sha256"]
    assert packet / ref["path"] in retained_import_paths(service.workspace)


def test_pending_precommit_activation_preserves_only_its_exact_recovery_packet(
    tmp_path,
):
    service, ready = _prepare_evidence(tmp_path)
    intent = service._activation_intent(
        service.load(ready["importId"]),
        ready["validationHash"],
        "empty",
        "fixture",
        "Pending fixture",
    )
    marker = service._pending_path()
    _write(
        marker, {"importId": ready["importId"], "operationId": intent["operationId"]}
    )
    retained = set(retained_import_paths(service.workspace))
    assert marker in retained
    packet = service.root / ready["importId"]
    assert packet / "activation" / (intent["operationId"] + ".json") in retained
    assert packet / "validations" / (ready["validationHash"] + ".json") in retained
    assert (
        packet / "proposals" / (content_hash(ready["proposal"]) + ".json") in retained
    )


@pytest.mark.parametrize(
    "marker",
    [
        {},
        {"importId": "../escape", "operationId": "a" * 64},
        {"importId": "a" * 64, "operationId": "b" * 64},
    ],
)
def test_invalid_or_unresolvable_pending_marker_fails_closed(tmp_path, marker):
    service, _ = _prepare_evidence(tmp_path)
    _write(service._pending_path(), marker)
    with pytest.raises(LineageError):
        retained_import_paths(service.workspace)


def test_retention_budget_does_not_fall_back_to_partial_preserved_paths(
    tmp_path, monkeypatch
):
    service, _, _ = _active(tmp_path)
    monkeypatch.setattr(import_retention, "MAX_TOTAL_BYTES", 1)
    monkeypatch.setattr(
        Path,
        "open",
        lambda *args, **kwargs: pytest.fail(
            "retention opened evidence after byte budget was exhausted"
        ),
    )
    with pytest.raises(LineageError, match="limit|budget"):
        retained_import_paths(service.workspace)


@pytest.mark.parametrize("location", ["sibling", "same-packet"])
def test_pending_packet_index_cannot_redirect_to_an_aliased_file(tmp_path, location):
    service, ready = _prepare_evidence(tmp_path)
    intent = service._activation_intent(
        service.load(ready["importId"]),
        ready["validationHash"],
        "empty",
        "fixture",
        "Pending fixture",
    )
    _write(
        service._pending_path(),
        {"importId": ready["importId"], "operationId": intent["operationId"]},
    )
    index = service.root / ready["importId"] / "index.json"
    sibling = (
        service.root if location == "sibling" else index.parent
    ) / "foreign-index.json"
    sibling.write_bytes(index.read_bytes())
    index.unlink()
    try:
        index.symlink_to(sibling)
    except OSError as exc:
        pytest.skip(f"Native symlink unavailable: {exc}")
    with pytest.raises(LineageError, match="escape|contained|alias"):
        retained_import_paths(service.workspace)


def test_return_intent_and_result_remain_reachable_after_restoring_prior_origin(
    tmp_path,
):
    service, _, before, ready = _replacement(tmp_path)
    replacement = _commit(service, ready, before["contentHash"])["revision"]
    returned = service.rollback(
        replacement["snapshot"]["originRef"]["activationId"],
        expected_head=replacement["contentHash"],
        actor="fixture",
        reason="Return retention fixture",
    )["revision"]
    retained = retained_import_paths(service.workspace)
    assert any(path.parent.name == "returns" for path in retained)
    assert any(path.parent.name == "return-results" for path in retained)
    assert set(verify_import_origin(service.workspace, replacement)) <= set(retained)
    assert set(verify_import_origin(service.workspace, returned)) <= set(retained)
    closing_paths = retained_return_paths(service.workspace, returned)
    assert any(path.parent.name == "returns" for path in closing_paths)
    assert any(path.parent.name == "return-results" for path in closing_paths)


@pytest.mark.parametrize("category", ["returns", "return-results"])
def test_return_evidence_corruption_blocks_cleanup_even_when_origin_is_prior_import(
    tmp_path, category
):
    service, _, before, ready = _replacement(tmp_path)
    replacement = _commit(service, ready, before["contentHash"])["revision"]
    returned = service.rollback(
        replacement["snapshot"]["originRef"]["activationId"],
        expected_head=replacement["contentHash"],
        actor="fixture",
        reason="Return retention fixture",
    )["revision"]
    path = next(
        path
        for path in retained_import_paths(service.workspace)
        if path.parent.name == category
    )
    data = json.loads(path.read_text())
    data["reason"] = "Corrupted after canonical return"
    _write(path, data)
    with pytest.raises(LineageError):
        retained_import_paths(service.workspace)
    with pytest.raises(LineageError):
        retained_return_paths(service.workspace, returned)


def test_return_closing_guard_does_not_scan_unrelated_historical_origin(tmp_path):
    service, _, before, ready = _replacement(tmp_path)
    replacement = _commit(service, ready, before["contentHash"])["revision"]
    returned = service.rollback(
        replacement["snapshot"]["originRef"]["activationId"],
        expected_head=replacement["contentHash"],
        actor="fixture",
        reason="Return retention fixture",
    )["revision"]
    # Explicit low-level fixture: a different canonical revision contains a
    # broken import origin. It must block cleanup, not this exact return closure.
    service.workspace.store("cmap").append_revision(
        snapshot={"originRef": {"unrelated": True}},
        actor="fixture",
        reason="Unrelated invalid-origin fixture",
    )
    assert retained_return_paths(service.workspace, returned)
    with pytest.raises(LineageError):
        retained_import_paths(service.workspace)
