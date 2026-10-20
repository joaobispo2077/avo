"""Bounded authoring packets and original-document verification."""

from __future__ import annotations

import copy
import json

import pytest

from avo.direction.rules import DirectionError, visible_word_count
from avo.direction.service import DirectionService
from avo.direction.store import DirectionStore
from avo.timeline.contracts import document_hash_excluding
from tests.test_direction_service import (
    NOW,
    decide_request,
    prepare_candidate,
    provider_fixture,
)


def test_partitioned_packets_preserve_every_evidence_id_and_global_coverage(
    tmp_path, monkeypatch
):
    import avo.direction.service as module

    root = provider_fixture(tmp_path)
    original = root / "learndowns/20260101-neutral-tutorial/learndown.json"
    template = json.loads(original.read_text(encoding="utf-8"))
    for index in range(8):
        value = {
            **template,
            "entryId": f"project-{index}",
            "rawDir": f"Z:/neutral/{index}",
            "summary": " ".join([f"word-{index}"] * 120),
        }
        target = root / "learndowns" / f"project-{index}" / "learndown.json"
        target.parent.mkdir()
        target.write_text(json.dumps(value), encoding="utf-8")
    monkeypatch.setattr(module, "PACKET_WORDS", 900, raising=False)
    result = DirectionService(root, "neutral", clock=lambda: NOW).prepare("editorial")
    store = DirectionStore(root / "direction")
    packet = store.load_document(result["refs"]["packet"]["path"])
    assert packet["partitionRefs"]
    assert packet["globalCoverage"]["discovered"] == 9
    evidence_ids = set()
    for ref in packet["partitionRefs"]:
        child = store.load_document(ref["path"])
        assert visible_word_count(json.dumps(child)) <= 900
        evidence_ids.update(item["evidenceId"] for item in child["evidenceRecords"])
    assert len(evidence_ids) == 18
    assert packet["evidenceRecords"] == []
    assert result["warnings"]


def test_packet_record_cannot_be_forged_even_if_its_envelope_is_rehashed(tmp_path):
    root = provider_fixture(tmp_path)
    service, _, packet, request = prepare_candidate(root)
    packet["evidenceRecords"][0]["excerpt"] = "Manufactured original meaning"
    packet["documentHash"] = document_hash_excluding(packet, "documentHash")
    store = DirectionStore(root / "direction")
    ref = store.write_document("collections/forged-packet.json", packet)
    request["packetRef"] = ref
    request["synthesisProvenance"]["packetHash"] = ref["documentHash"]
    with pytest.raises(DirectionError, match="evidence|selector|source"):
        service.propose(request)
    assert store.load_index() is None


def test_changed_original_prevents_proposal_and_brand_is_also_bound(tmp_path):
    root = provider_fixture(tmp_path)
    service, _, _, request = prepare_candidate(root)
    (root / "DESIGN.md").write_text("A different authored brand.", encoding="utf-8")
    with pytest.raises(DirectionError):
        service.propose(request)
    assert DirectionStore(root / "direction").load_index() is None


def test_service_retries_reuse_exact_profile_and_decision_without_new_revision(
    tmp_path,
):
    root = provider_fixture(tmp_path)
    service, _, _, request = prepare_candidate(root)
    first = service.propose(request)
    second = service.propose(copy.deepcopy(request))
    assert first["refs"]["proposal"] == second["refs"]["proposal"]
    decision = decide_request(first)
    accepted = service.decide(decision)
    retried = service.decide(copy.deepcopy(decision))
    assert accepted["refs"]["decision"] == retried["refs"]["decision"]
    index = DirectionStore(root / "direction").load_index()
    assert len(index["profiles"]["editorial"]["revisionRefs"]) == 1
    assert len(index["profiles"]["editorial"]["decisionRefs"]) == 1
    changed = copy.deepcopy(request)
    changed["candidate"]["summary"] = "Another request under the same identity."
    with pytest.raises(DirectionError):
        service.propose(changed)


def test_readonly_catalog_and_show_never_create_authoring_directories(tmp_path):
    root = tmp_path / "neutral"
    service = DirectionService(root, "neutral", clock=lambda: NOW)
    assert service.catalog()["profiles"] == {}
    assert not root.exists()
    with pytest.raises(DirectionError):
        service.show("editorial@r0001")
    assert not root.exists()


@pytest.mark.parametrize("basis", ["avo-default", "reference-suggestion"])
def test_provider_cannot_launder_uncited_defaults_or_reference_suggestions(
    tmp_path, basis
):
    root = provider_fixture(tmp_path)
    service, _, _, request = prepare_candidate(root)
    item = request["candidate"]["statements"][0]
    item.update(basis=basis, evidenceIds=[], independentProjectIds=[])
    with pytest.raises(DirectionError):
        service.propose(request)
    assert DirectionStore(root / "direction").load_index() is None
