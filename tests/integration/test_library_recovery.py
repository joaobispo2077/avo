"""Crash boundaries preserve exact approved media and support reversal."""

from uuid import uuid4

import pytest

from avo.adapters.media import library_moves
from avo.library.rules import source_lock
from avo.library.service import LibraryService
from avo.timeline.store import now_iso
from library_fixtures import install_provider

pytestmark = pytest.mark.integration


def approved(service, proposal_ref):
    proposal = service.store.get(proposal_ref)
    selection = {
        "actionIds": [a["actionId"] for a in proposal["actions"]],
        "unboundSourceIds": [a["recordingId"] for a in proposal["actions"]],
    }
    packet = service.prepare(
        proposal_ref["id"] + "@" + str(proposal["revision"]), selection
    )["packetRef"]
    head = service.store.head()
    decision = {
        "schemaVersion": 1,
        "kind": "decision",
        "requestId": uuid4().hex,
        "libraryId": head["libraryId"],
        "expectedHeadHash": head["headHash"],
        "packetId": packet["id"],
        "packetHash": packet["sha256"],
        "approvedIds": selection["actionIds"],
        "decision": "approved",
        "actor": "fixture-creator",
        "creatorInstruction": "Apply these exact disposable test moves",
        "createdAt": now_iso(),
    }
    return service.approve(decision)["decisionRef"]["id"]


def fixture_service(tmp_path, monkeypatch):
    support = library_moves.capability(tmp_path)
    if not support["available"]:
        pytest.skip(support["reason"])
    install_provider(tmp_path / "install")
    monkeypatch.setenv("AVO_ROOT", str(tmp_path / "install"))
    root = tmp_path / "footage"
    root.mkdir()
    (root / "xpto-01.mp4").write_bytes(b"original media")
    return LibraryService(root, "example", probe=lambda _: {"durationSeconds": 2})


@pytest.mark.parametrize(
    "stage", ["after-intent", "after-move", "after-verification", "before-head"]
)
def test_resume_each_crash_boundary_and_reverse(tmp_path, monkeypatch, stage):
    service = fixture_service(tmp_path, monkeypatch)
    first = service.scan()
    before = source_lock(service.root / "xpto-01.mp4")
    decision = approved(service, first["proposalRef"])

    def crash(actual, _action):
        if actual == stage:
            raise RuntimeError("simulated process interruption")

    with pytest.raises(RuntimeError, match="interruption"):
        service.apply(decision, fault=crash)
    operation = service.store.head()["activeOperation"]
    result = service.resume(operation)
    assert result["status"] == "ok"
    target = service.root / "xpto/xpto-01.mp4"
    assert source_lock(target)["sha256"] == before["sha256"]
    assert source_lock(target)["fileId"] == before["fileId"]
    inverse = service.reverse(operation)
    assert target.exists()  # reversal only proposes
    result = service.apply(approved(service, inverse["proposalRef"]))
    assert result["status"] == "ok"
    assert (service.root / "xpto-01.mp4").read_bytes() == b"original media"


def test_occupied_target_after_approval_is_never_overwritten(tmp_path, monkeypatch):
    service = fixture_service(tmp_path, monkeypatch)
    decision = approved(service, service.scan()["proposalRef"])
    target = service.root / "xpto/xpto-01.mp4"
    target.parent.mkdir()
    target.write_bytes(b"new unrelated file")
    result = service.apply(decision)
    assert result["status"] == "partial"
    assert target.read_bytes() == b"new unrelated file"
    assert (service.root / "xpto-01.mp4").read_bytes() == b"original media"
