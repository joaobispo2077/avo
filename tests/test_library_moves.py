"""Move approval binds concrete sources/actions, never a review's existence."""

from __future__ import annotations

import hashlib
import json
import shutil
from copy import deepcopy
from uuid import uuid4

import pytest

from avo.library.rules import LibraryError
from avo.library.service import LibraryService
from library_fixtures import install_provider, make_library
from test_library_proposals import edit_request, source_snapshot


@pytest.fixture
def library(tmp_path, monkeypatch, repo_root):
    install = tmp_path / "install"
    install_provider(install)
    schemas = install / "schemas"
    schemas.mkdir(exist_ok=True)
    shutil.copyfile(
        repo_root / "schemas" / "avo.library.schema.json",
        schemas / "avo.library.schema.json",
    )
    monkeypatch.setenv("AVO_ROOT", str(install))
    fixture = make_library(tmp_path / "footage")
    service = LibraryService(fixture.root, "example", probe=fixture.probe)
    initial = service.scan(recursive=True)
    proposal = service.store.get(initial["proposalRef"])
    group = next(group for group in proposal["groups"] if group["path"] == "camera-a")
    result = service.propose(
        edit_request(
            service,
            initial["proposalRef"],
            [{"type": "rename-group", "groupId": group["id"], "label": "organized-a"}],
        )
    )
    return service, fixture, result["proposalRef"]


def proposal_identifier(service, ref):
    return f"{ref['id']}@{service.store.get(ref)['revision']}"


def move_actions(service, ref):
    return [
        action
        for action in service.store.get(ref)["actions"]
        if action["status"] == "move"
    ]


def selection(actions):
    return {
        "actionIds": [action["actionId"] for action in actions],
        "unboundSourceIds": [action["recordingId"] for action in actions],
    }


def prepare_one(service, ref):
    action = move_actions(service, ref)[0]
    prepared = service.prepare(proposal_identifier(service, ref), selection([action]))
    return action, prepared["packetRef"]


def decision_request(service, packet_ref, *, decision="approved"):
    head = service.store.head()
    packet = service.store.get(packet_ref)
    return {
        "schemaVersion": 1,
        "kind": "decision",
        "requestId": uuid4().hex,
        "libraryId": head["libraryId"],
        "expectedHeadHash": head["headHash"],
        "packetId": packet_ref["id"],
        "packetHash": packet_ref["sha256"],
        "approvedIds": [action["actionId"] for action in packet["selected"]],
        "decision": decision,
        "actor": "creator",
        "creatorInstruction": "Apply exactly the displayed selected move.",
        "createdAt": "2026-10-30T12:00:00Z",
    }


def publish_actions(service, ref, actions):
    """Publish a bounded native fixture to test preparation's own validation."""
    proposal = deepcopy(service.store.get(ref))
    proposal["actions"] = actions
    successor = service.store.put("proposal", proposal)
    with service.store.exclusive():
        head = service.store.head()
        service.store.publish({**head, "proposalRef": successor}, head["headHash"])
    return successor


def test_prepare_locks_only_selected_sources_without_moving(library):
    service, fixture, ref = library
    before = source_snapshot(fixture.root)
    action, packet_ref = prepare_one(service, ref)
    packet = service.store.get(packet_ref)

    assert packet["kind"] == "moves"
    assert packet["proposalRef"] == ref
    assert packet["root"] == str(fixture.root)
    assert packet["provider"] == "example"
    assert packet["selected"] == [action]
    assert len(packet["locks"]) == 1
    expected_hash = hashlib.sha256(
        (fixture.root / action["from"]).read_bytes()
    ).hexdigest()
    assert expected_hash in json.dumps(packet["locks"])
    assert source_snapshot(fixture.root) == before
    assert not (fixture.root / action["to"]).exists()


def test_prepare_requires_explicit_unbound_ownership(library):
    service, fixture, ref = library
    chosen = selection(move_actions(service, ref)[:1])
    chosen["unboundSourceIds"] = []
    before = source_snapshot(fixture.root)

    with pytest.raises(LibraryError) as error:
        service.prepare(proposal_identifier(service, ref), chosen)

    assert error.value.code == "LIB_OWNERSHIP_UNKNOWN"
    assert source_snapshot(fixture.root) == before


@pytest.mark.parametrize(
    "damage", ["empty", "unknown", "duplicate", "unselected-owner"]
)
def test_prepare_rejects_nonexact_selection(library, damage):
    service, fixture, ref = library
    actions = move_actions(service, ref)
    chosen = selection(actions[:1])
    if damage == "empty":
        chosen["actionIds"] = []
    elif damage == "unknown":
        chosen["actionIds"] = ["unknown-action"]
    elif damage == "duplicate":
        chosen["actionIds"] *= 2
    else:
        chosen["unboundSourceIds"].append(actions[1]["recordingId"])
    before = source_snapshot(fixture.root)

    with pytest.raises(LibraryError):
        service.prepare(proposal_identifier(service, ref), chosen)

    assert source_snapshot(fixture.root) == before


def test_changed_source_requires_refresh_before_preparation(library):
    service, fixture, ref = library
    action = move_actions(service, ref)[0]
    path = fixture.root / action["from"]
    path.write_bytes(b"recording changed since the reviewed inventory")

    with pytest.raises(LibraryError) as error:
        service.prepare(proposal_identifier(service, ref), selection([action]))

    assert error.value.code == "LIB_SOURCE_CHANGED"
    assert path.read_bytes() == b"recording changed since the reviewed inventory"
    assert not (fixture.root / action["to"]).exists()


def test_supported_project_reference_blocks_even_declared_unbound_media(library):
    service, fixture, ref = library
    action = move_actions(service, ref)[0]
    (fixture.root / "avo.project.json").write_text(
        json.dumps(
            {
                "schemaVersion": "1.0.0",
                "provider": "example",
                "videoId": "existing",
                "rawDir": str(fixture.root),
                "sources": [action["from"]],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(LibraryError) as error:
        service.prepare(proposal_identifier(service, ref), selection([action]))

    assert error.value.code == "LIB_REFERENCE_OWNED"
    assert (fixture.root / action["from"]).is_file()


def test_prepare_discloses_platform_capability_before_approval(library, monkeypatch):
    service, _fixture, ref = library
    unsupported = {"available": False, "reason": "Unsupported fixture volume"}
    monkeypatch.setattr(
        "avo.adapters.media.library_moves.capability", lambda _: unsupported
    )
    actions = move_actions(service, ref)[:1]
    prepared = service.prepare(proposal_identifier(service, ref), selection(actions))
    assert prepared["capabilities"]["physicalMoves"] == unsupported
    assert service.status()["capabilities"]["paidTranscription"] is False
    packet = service.store.get(prepared["packetRef"])
    assert packet["config"]["capabilities"] == prepared["capabilities"]


def test_newly_occupied_destination_blocks_preparation(library):
    service, fixture, ref = library
    action = move_actions(service, ref)[0]
    destination = fixture.root / action["to"]
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(b"someone else's recording")

    with pytest.raises(LibraryError) as error:
        service.prepare(proposal_identifier(service, ref), selection([action]))

    assert error.value.code == "LIB_DESTINATION_EXISTS"
    assert destination.read_bytes() == b"someone else's recording"
    assert (fixture.root / action["from"]).is_file()


def test_stale_proposal_cannot_prepare_after_successor(library):
    service, fixture, ref = library
    action = move_actions(service, ref)[0]
    service.propose()

    with pytest.raises(LibraryError) as error:
        service.prepare(proposal_identifier(service, ref), selection([action]))

    assert error.value.code == "LIB_STALE_PROPOSAL"
    assert (fixture.root / action["from"]).is_file()


@pytest.mark.parametrize(
    "damage", ["same", "case-only", "duplicate-target", "chain", "cycle"]
)
def test_preparation_independently_rejects_unsafe_move_graph(library, damage):
    service, fixture, ref = library
    actions = deepcopy(move_actions(service, ref))
    if damage == "same":
        actions[0]["to"] = actions[0]["from"]
    elif damage == "case-only":
        actions[0]["to"] = actions[0]["from"].upper()
    elif damage == "duplicate-target":
        actions[1]["to"] = actions[0]["to"]
    elif damage == "chain":
        actions[0]["to"] = actions[1]["from"]
    else:
        actions[0]["to"], actions[1]["to"] = actions[1]["from"], actions[0]["from"]
    crafted_ref = publish_actions(service, ref, actions)
    before = source_snapshot(fixture.root)

    with pytest.raises(LibraryError):
        service.prepare(proposal_identifier(service, crafted_ref), selection(actions))

    assert source_snapshot(fixture.root) == before


def test_explicit_decision_is_packet_bound_and_does_not_execute_moves(library):
    service, fixture, ref = library
    action, packet_ref = prepare_one(service, ref)
    request = decision_request(service, packet_ref)
    before = source_snapshot(fixture.root)

    result = service.approve(request)
    saved = service.store.get(result["decisionRef"])

    assert saved["packetHash"] == packet_ref["sha256"]
    assert saved["approvedIds"] == [action["actionId"]]
    assert saved["actor"] == "creator"
    assert saved["creatorInstruction"] == request["creatorInstruction"]
    assert source_snapshot(fixture.root) == before
    assert not (fixture.root / action["to"]).exists()


@pytest.mark.parametrize(
    "damage",
    [
        "missing-instruction",
        "blank-actor",
        "packet-hash",
        "packet-id",
        "selected-ids",
        "stale-head",
    ],
)
def test_decision_rejects_inferred_or_mismatched_approval(library, damage):
    service, fixture, ref = library
    _, packet_ref = prepare_one(service, ref)
    request = decision_request(service, packet_ref)
    if damage == "missing-instruction":
        request["creatorInstruction"] = " "
    elif damage == "blank-actor":
        request["actor"] = ""
    elif damage == "packet-hash":
        request["packetHash"] = "0" * 64
    elif damage == "packet-id":
        request["packetId"] = "0" * 64
    elif damage == "selected-ids":
        request["approvedIds"] = ["unselected-action"]
    else:
        request["expectedHeadHash"] = "0" * 64
    before = source_snapshot(fixture.root)

    with pytest.raises(LibraryError):
        service.approve(request)

    assert source_snapshot(fixture.root) == before


def test_proposal_or_prepared_packet_cannot_be_used_as_execution_approval(library):
    service, fixture, ref = library
    _, packet_ref = prepare_one(service, ref)
    before = source_snapshot(fixture.root)

    for identifier in (ref["id"], packet_ref["id"]):
        with pytest.raises(LibraryError):
            service.apply(identifier)

    assert source_snapshot(fixture.root) == before


def test_rejected_decision_cannot_execute(library):
    service, fixture, ref = library
    _, packet_ref = prepare_one(service, ref)
    decision = service.approve(
        decision_request(service, packet_ref, decision="rejected")
    )
    before = source_snapshot(fixture.root)

    with pytest.raises(LibraryError) as error:
        service.apply(decision["decisionRef"]["id"])

    assert error.value.code == "LIB_APPROVAL_REQUIRED"
    assert source_snapshot(fixture.root) == before


def test_changed_proposal_cannot_reuse_previous_approval(library):
    service, fixture, ref = library
    _, packet_ref = prepare_one(service, ref)
    decision = service.approve(decision_request(service, packet_ref))
    service.propose()
    before = source_snapshot(fixture.root)

    with pytest.raises(LibraryError) as error:
        service.apply(decision["decisionRef"]["id"])

    assert error.value.code == "LIB_STALE_PROPOSAL"
    assert source_snapshot(fixture.root) == before
