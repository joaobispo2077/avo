"""Independent provider journeys using documented evidence, never source media."""

from __future__ import annotations

import copy
import json
import shutil
import socket
import subprocess
from pathlib import Path

import pytest

from avo.direction.rules import DirectionError
from avo.direction.service import DirectionService
from avo.direction.store import DirectionStore
from tests.test_direction_contracts import DIMENSIONS, statement

FIXTURES = Path(__file__).parent / "fixtures" / "direction"
NOW = "2026-10-16T12:00:00Z"


def provider_fixture(tmp_path: Path) -> Path:
    root = tmp_path / "neutral"
    entry = root / "learndowns" / "20260101-neutral-tutorial"
    entry.mkdir(parents=True)
    shutil.copyfile(FIXTURES / "legacy.json", entry / "learndown.json")
    legacy = json.loads((FIXTURES / "legacy.json").read_text(encoding="utf-8"))
    (root / "learndowns/index.json").write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "provider": "neutral",
                "updatedAt": NOW,
                "entries": [
                    {
                        key: legacy[key]
                        for key in (
                            "entryId",
                            "masterBasename",
                            "rawDir",
                            "title",
                            "status",
                            "generatedAt",
                        )
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (root / "DESIGN.md").write_text(
        "# Authored guide\nUse restrained evidence-led demonstrations.\n",
        encoding="utf-8",
    )
    return root


def prepare_candidate(root: Path, *, summary: str | None = None):
    service = DirectionService(root, "neutral", clock=lambda: NOW)
    prepared = service.prepare("editorial")
    packet_ref = prepared["refs"]["packet"]
    store = DirectionStore(root / "direction")
    packet = store.load_document(packet_ref["path"])
    evidence = packet["evidenceRecords"][0]
    choice = statement()
    choice["evidenceIds"] = [evidence["evidenceId"]]
    choice["independentProjectIds"] = (
        [evidence["sourceProjectId"]] if evidence.get("sourceProjectId") else []
    )
    request = {
        "requestId": "propose-neutral-001",
        "packetRef": packet_ref,
        "expectedIndexHash": prepared["expectedIndexHash"],
        "candidate": {
            "summary": summary or "Clear speech and selective explanatory support.",
            "statements": [choice],
            "variants": [],
            "avoidances": [],
            "dimensionCoverage": {
                name: "inferred" if name == "sound" else "unknown"
                for name in DIMENSIONS
            },
            "changeSummary": "Initial evidence-qualified direction proposal.",
        },
        "synthesisProvenance": {
            "executionKind": "driving-agent",
            "agentId": "neutral-author",
            "modelId": None,
            "packetHash": packet_ref["documentHash"],
            "promptHash": None,
        },
    }
    return service, prepared, packet, request


def decide_request(proposed: dict, *, action="accept", scope="provider") -> dict:
    return {
        "requestId": f"decide-neutral-{action}",
        "targetRef": proposed["refs"]["proposal"],
        "expectedIndexHash": proposed["expectedIndexHash"],
        "action": action,
        "scope": scope,
        "actor": {"type": "human", "id": "neutral-creator"},
        "reason": "Reviewed this exact direction for future demonstrations.",
        "humanInstruction": {
            "source": "session:message-neutral",
            "text": f"{action} this exact proposed provider direction.",
        },
    }


def profile_state(root: Path) -> dict:
    value = DirectionStore(root / "direction").load_index()
    return value["profiles"]["editorial"] if value else {}


def test_prepare_preserves_history_and_brand_without_creating_index(tmp_path: Path):
    root = provider_fixture(tmp_path)
    protected = {path: path.read_bytes() for path in root.rglob("*") if path.is_file()}
    service, prepared, packet, _ = prepare_candidate(root)
    assert prepared["status"] == "needs-authoring"
    assert prepared["expectedIndexHash"] == "absent"
    assert packet["provider"] == "neutral"
    assert packet["coverage"]["discovered"] == 1
    assert packet["coverage"]["distinctProjects"] == 1
    assert DirectionStore(root / "direction").load_index() is None
    assert service.catalog()["provider"] == "neutral"
    assert all(path.read_bytes() == encoded for path, encoded in protected.items())


def test_propose_is_unaccepted_until_exact_creator_decision(tmp_path: Path):
    root = provider_fixture(tmp_path)
    service, _, _, request = prepare_candidate(root)
    proposed = service.propose(request)
    assert proposed["status"] == "needs-review"
    assert profile_state(root).get("acceptedRef") is None
    before = (root / "DESIGN.md").read_bytes()
    shown = service.show("editorial@r0001")
    assert shown["provider"] == "neutral"
    assert profile_state(root).get("acceptedRef") is None
    result = service.decide(decide_request(proposed))
    assert result["status"] == "accepted"
    assert profile_state(root)["acceptedRef"] == proposed["refs"]["proposal"]
    assert (root / "DESIGN.md").read_bytes() == before


def test_profile_preserves_unknown_dimensions_and_tentative_basis(tmp_path: Path):
    root = provider_fixture(tmp_path)
    service, _, _, request = prepare_candidate(root)
    proposed = service.propose(request)
    profile = DirectionStore(root / "direction").load_document(
        proposed["refs"]["proposal"]["path"]
    )
    assert profile["dimensionCoverage"]["color"] == "unknown"
    assert profile["statements"][0]["basis"] == "tentative-inference"
    assert profile["statements"][0]["rationaleKind"] == "agent-inferred"
    assert profile["statements"][0].get("creatorDispositionRef") is None


def test_summary_larger_than_500_words_is_not_published(tmp_path: Path):
    root = provider_fixture(tmp_path)
    service, _, _, request = prepare_candidate(root, summary=" ".join(["word"] * 501))
    with pytest.raises(DirectionError):
        service.propose(request)
    assert DirectionStore(root / "direction").load_index() is None


def test_missing_dimension_is_not_silently_defaulted(tmp_path: Path):
    root = provider_fixture(tmp_path)
    service, _, _, request = prepare_candidate(root)
    del request["candidate"]["dimensionCoverage"]["color"]
    with pytest.raises(DirectionError):
        service.propose(request)
    assert profile_state(root).get("acceptedRef") is None


@pytest.mark.parametrize("tampered", ["packet", "target", "scope"])
def test_forged_packet_target_or_scope_cannot_accept(tmp_path: Path, tampered: str):
    root = provider_fixture(tmp_path)
    service, _, _, request = prepare_candidate(root)
    if tampered == "packet":
        request["packetRef"]["documentHash"] = "0" * 64
        with pytest.raises(DirectionError):
            service.propose(request)
    else:
        proposed = service.propose(request)
        decision = decide_request(proposed)
        if tampered == "target":
            decision["targetRef"] = {
                **decision["targetRef"],
                "documentHash": "0" * 64,
            }
        else:
            decision["scope"] = "project"
        with pytest.raises(DirectionError):
            service.decide(decision)
    assert profile_state(root).get("acceptedRef") is None


def test_reject_retains_proposal_and_exact_decision_history(tmp_path: Path):
    root = provider_fixture(tmp_path)
    service, _, _, request = prepare_candidate(root)
    proposed = service.propose(request)
    target = copy.deepcopy(proposed["refs"]["proposal"])
    result = service.decide(decide_request(proposed, action="reject"))
    assert result["refs"]["decision"]["documentHash"]
    state = profile_state(root)
    assert state.get("acceptedRef") is None
    assert target in state["revisionRefs"]
    event_ref = state["decisionRefs"][-1]
    event = DirectionStore(root / "direction").load_document(event_ref["path"])
    assert event["action"] == "reject"
    assert event["targetRef"] == target
    assert event["scope"] == "provider"


def test_native_provider_journey_never_starts_processes_or_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    root = provider_fixture(tmp_path)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("Direction metadata must not invoke media/model/network")

    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    service, _, _, request = prepare_candidate(root)
    proposed = service.propose(request)
    service.decide(decide_request(proposed))
    assert profile_state(root)["acceptedRef"]
