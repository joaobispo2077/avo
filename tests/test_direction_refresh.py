"""Creator dispositions and explicit refresh preserve authorship and history."""

from __future__ import annotations

import copy
import json

import pytest

from avo.direction.rules import DirectionError
from avo.direction.store import DirectionStore
from tests.test_direction_service import (
    decide_request,
    prepare_candidate,
    profile_state,
    provider_fixture,
)


def _accepted(tmp_path):
    root = provider_fixture(tmp_path)
    service, _, _, request = prepare_candidate(root)
    proposal = service.propose(request)
    service.decide(decide_request(proposal))
    return root, service, proposal, request


def _decision(service, proposal, action, **fields):
    request = decide_request(proposal, action=action)
    request["expectedIndexHash"] = service.catalog()["expectedIndexHash"]
    request.update(fields)
    return service.decide(request)


def _refresh_request(root, prepared, original, request_id="fresh-proposal"):
    packet = DirectionStore(root / "direction").load_document(
        prepared["refs"]["packet"]["path"]
    )
    request = copy.deepcopy(original)
    request.update(
        requestId=request_id,
        packetRef=prepared["refs"]["packet"],
        expectedIndexHash=prepared["expectedIndexHash"],
    )
    request["synthesisProvenance"]["packetHash"] = prepared["refs"]["packet"][
        "documentHash"
    ]
    return packet, request


@pytest.mark.parametrize("duplicate_field", ["statementId", "lineageId"])
def test_candidate_rejects_ambiguous_statement_identity(tmp_path, duplicate_field):
    root = provider_fixture(tmp_path)
    service, _, _, request = prepare_candidate(root)
    original = request["candidate"]["statements"][0]
    duplicate = copy.deepcopy(original)
    for field in ("statementId", "lineageId"):
        if field != duplicate_field:
            duplicate[field] += "-different"
    request["candidate"]["statements"].append(duplicate)
    with pytest.raises(DirectionError, match="unique"):
        service.propose(request)
    assert service.catalog()["profiles"] == {}


@pytest.mark.parametrize("kind", ["unknown", "duplicate"])
def test_decision_rejects_ambiguous_statement_dispositions(tmp_path, kind):
    root = provider_fixture(tmp_path)
    service, _, _, request = prepare_candidate(root)
    proposal = service.propose(request)
    statement_id = request["candidate"]["statements"][0]["statementId"]
    changes = [{"statementId": statement_id, "action": "accept"}]
    if kind == "unknown":
        changes[0]["statementId"] = "absent-statement"
    else:
        changes.append(copy.deepcopy(changes[0]))
    with pytest.raises(DirectionError, match="statement"):
        _decision(service, proposal, "accept", statementDispositions=changes)
    assert profile_state(root)["acceptedRef"] is None


def test_profile_retry_reuses_exact_uncommitted_body_with_changing_clock(
    tmp_path, monkeypatch
):
    root = provider_fixture(tmp_path)
    service, _, _, request = prepare_candidate(root)
    original_write = service.store.write_document

    def crash_after_body(relative, document, schema_ref=None):
        reference = original_write(relative, document, schema_ref)
        if relative.startswith("profiles/"):
            raise RuntimeError("simulated process interruption")
        return reference

    monkeypatch.setattr(service.store, "write_document", crash_after_body)
    with pytest.raises(RuntimeError, match="interruption"):
        service.propose(request)
    orphan = root / "direction/profiles/editorial/r0001.json"
    original_bytes = orphan.read_bytes()
    assert service.catalog()["profiles"] == {}
    monkeypatch.setattr(service.store, "write_document", original_write)
    service.clock = lambda: "2026-10-17T12:00:00Z"
    result = service.propose(request)
    assert result["status"] == "needs-review"
    assert orphan.read_bytes() == original_bytes
    assert (
        result["refs"]["proposal"]["documentHash"]
        == json.loads(original_bytes)["documentHash"]
    )
    assert profile_state(root)["acceptedRef"] is None


def test_profile_retry_never_reuses_foreign_orphan_content(tmp_path, monkeypatch):
    from avo.timeline.contracts import document_hash_excluding

    root = provider_fixture(tmp_path)
    service, _, _, request = prepare_candidate(root)
    original_publish = service.store.publish

    def stop_after_body(**fields):
        relative, document, schema_ref = fields["documents"][0]
        service.store.write_document(relative, document, schema_ref)
        raise RuntimeError("simulated process interruption")

    monkeypatch.setattr(service.store, "publish", stop_after_body)
    with pytest.raises(RuntimeError):
        service.propose(request)
    orphan = root / "direction/profiles/editorial/r0001.json"
    foreign = json.loads(orphan.read_text(encoding="utf-8"))
    foreign["summary"] = "Foreign content with a recomputed valid hash."
    foreign["documentHash"] = document_hash_excluding(foreign, "documentHash")
    orphan.write_text(json.dumps(foreign), encoding="utf-8")
    foreign_bytes = orphan.read_bytes()
    monkeypatch.setattr(service.store, "publish", original_publish)
    with pytest.raises(DirectionError):
        service.propose(request)
    assert orphan.read_bytes() == foreign_bytes
    assert service.catalog()["profiles"] == {}


@pytest.mark.parametrize("action", ["accept", "edit"])
def test_creator_decision_retries_index_interruption_with_changing_clock(
    tmp_path, monkeypatch, action
):
    import avo.direction.store as store_module

    root = provider_fixture(tmp_path)
    service, _, _, original = prepare_candidate(root)
    proposal = service.propose(original)
    request = decide_request(proposal, action=action)
    if action == "edit":
        request["edits"] = copy.deepcopy(original["candidate"])
        request["edits"]["statements"][0]["text"] = (
            "Exact edited wording after recovery."
        )
    original_write = store_module.atomic_write_json

    def interrupt_index(*args, **kwargs):
        raise RuntimeError("simulated index interruption")

    monkeypatch.setattr(store_module, "atomic_write_json", interrupt_index)
    with pytest.raises(RuntimeError, match="interruption"):
        service.decide(request)
    before = {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in (root / "direction").rglob("*.json")
    }
    assert profile_state(root)["acceptedRef"] is None
    assert len(profile_state(root)["revisionRefs"]) == 1
    monkeypatch.setattr(store_module, "atomic_write_json", original_write)
    service.clock = lambda: "2026-10-17T12:00:00Z"
    result = service.decide(request)
    assert result["status"] == ("accepted" if action == "accept" else "needs-review")
    state = profile_state(root)
    assert len(state["decisionRefs"]) == 1
    for relative, contents in before.items():
        if relative.endswith("direction/index.json"):
            continue
        assert (root / relative).read_bytes() == contents
    if action == "edit":
        assert state["acceptedRef"] is None
        assert len(state["revisionRefs"]) == 2


def test_committed_retries_return_original_result_after_later_actions(tmp_path):
    root = provider_fixture(tmp_path)
    service, _, _, request = prepare_candidate(root)
    proposal = service.propose(request)
    decision_request = decide_request(proposal)
    decision = service.decide(decision_request)
    prepared = service.prepare("editorial", refresh_from="editorial@r0001")
    _, later = _refresh_request(root, prepared, request)
    service.propose(later)
    proposal_retry = service.propose(request)
    decision_retry = service.decide(decision_request)
    assert proposal_retry["refs"]["proposal"] == proposal["refs"]["proposal"]
    assert proposal_retry["expectedIndexHash"] == proposal["expectedIndexHash"]
    assert decision_retry["refs"]["decision"] == decision["refs"]["decision"]
    assert decision_retry["expectedIndexHash"] == decision["expectedIndexHash"]


def test_refresh_reports_changed_source_and_preserves_accepted_revision(tmp_path):
    root, service, proposal, original = _accepted(tmp_path)
    store = DirectionStore(root / "direction")
    old_bytes = (root / "direction" / proposal["refs"]["proposal"]["path"]).read_bytes()
    source = root / "learndowns/20260101-neutral-tutorial/learndown.json"
    value = json.loads(source.read_text())
    value["summary"] = "A new contextual observation about explanatory support."
    source.write_text(json.dumps(value), encoding="utf-8")
    prepared = service.prepare("editorial", refresh_from="editorial@r0001")
    report = store.load_document(prepared["refs"]["refreshReport"]["path"])
    assert report["changedEntries"] == ["20260101-neutral-tutorial"]
    assert report["bookkeepingOnly"] is False
    assert report["impactedStatements"]
    assert profile_state(root)["acceptedRef"] == proposal["refs"]["proposal"]
    assert (
        root / "direction" / proposal["refs"]["proposal"]["path"]
    ).read_bytes() == old_bytes
    packet, request = _refresh_request(root, prepared, original)
    evidence = packet["evidenceRecords"][0]
    request["candidate"]["statements"][0]["evidenceIds"] = [evidence["evidenceId"]]
    updated = service.propose(request)
    assert updated["status"] == "needs-review"
    assert profile_state(root)["acceptedRef"] == proposal["refs"]["proposal"]


def test_bookkeeping_only_reformat_does_not_invent_artistic_change(tmp_path):
    root, service, _, _ = _accepted(tmp_path)
    path = root / "learndowns/20260101-neutral-tutorial/learndown.json"
    path.write_text(
        json.dumps(json.loads(path.read_text()), indent=4), encoding="utf-8"
    )
    prepared = service.prepare("editorial", refresh_from="editorial@r0001")
    report = DirectionStore(root / "direction").load_document(
        prepared["refs"]["refreshReport"]["path"]
    )
    assert report["bookkeepingOnly"] is True
    assert report["changedEntries"]


def test_edit_creates_exact_unaccepted_proposal_before_another_acceptance(tmp_path):
    root, service, proposal, original = _accepted(tmp_path)
    changes = copy.deepcopy(original["candidate"])
    changes["summary"] = "The creator's edited, quieter direction."
    changes["statements"][0]["text"] = "Keep explanatory support quiet and deliberate."
    result = _decision(service, proposal, "edit", edits=changes)
    assert result["status"] == "needs-review"
    assert result["refs"]["proposal"] != proposal["refs"]["proposal"]
    assert profile_state(root)["acceptedRef"] == proposal["refs"]["proposal"]
    target = {
        "refs": {"proposal": result["refs"]["proposal"]},
        "expectedIndexHash": result["expectedIndexHash"],
    }
    accepted = _decision(service, target, "accept", requestId="accept-edited-exact")
    assert accepted["status"] == "accepted"
    assert profile_state(root)["acceptedRef"] == result["refs"]["proposal"]


def test_qualification_is_kept_as_contextual_new_proposal(tmp_path):
    root, service, proposal, original = _accepted(tmp_path)
    result = _decision(
        service,
        proposal,
        "qualify",
        statementDispositions=[
            {
                "statementId": original["candidate"]["statements"][0]["statementId"],
                "action": "qualify",
                "qualification": "Only for tutorial explanations.",
            }
        ],
    )
    assert result["status"] == "needs-review"
    edited = DirectionStore(root / "direction").load_document(
        result["refs"]["proposal"]["path"]
    )
    assert (
        "Only for tutorial explanations."
        in edited["statements"][0]["applicability"]["conditions"]
    )
    assert profile_state(root)["acceptedRef"] == proposal["refs"]["proposal"]


def test_defer_is_a_real_event_without_false_acceptance(tmp_path):
    root = provider_fixture(tmp_path)
    service, _, _, original = prepare_candidate(root)
    proposal = service.propose(original)
    result = _decision(service, proposal, "defer")
    assert result["status"] == "ok"
    assert result["disposition"] == "deferred"
    assert service.show("editorial@r0001")["reviewState"] == "deferred"
    assert profile_state(root)["acceptedRef"] is None


def test_refresh_cannot_resurrect_rejected_known_lineage(tmp_path):
    root, service, proposal, original = _accepted(tmp_path)
    _decision(service, proposal, "reject")
    prepared = service.prepare("editorial", refresh_from="editorial@r0001")
    packet, request = _refresh_request(root, prepared, original)
    assert packet["statementLineages"][0]["creatorDispositionRef"]
    with pytest.raises(DirectionError):
        service.propose(request)
    # A genuinely unmatched suggestion stays proposed until fresh human review.
    request["requestId"] = "new-unreviewed-lineage"
    request["candidate"]["statements"][0].update(
        statementId="new-suggestion", lineageId="new-lineage"
    )
    result = service.propose(request)
    assert result["status"] == "needs-review"
    assert profile_state(root)["acceptedRef"] is None


def test_new_native_provider_instruction_is_available_without_learndown_reexport(
    tmp_path,
):
    root = provider_fixture(tmp_path)
    service, _, _, original = prepare_candidate(root)
    proposal = service.propose(original)
    instruction = {
        "text": "Keep demonstrations intelligible for future videos.",
        "applicability": {
            "formats": ["step-by-step"],
            "sections": [],
            "conditions": [],
            "exclusions": [],
        },
        "exclusions": ["Music performances"],
    }
    _decision(service, proposal, "accept", providerInstruction=instruction)
    source = root / "learndowns/20260101-neutral-tutorial/learndown.json"
    source.write_text(
        json.dumps(json.loads(source.read_text()), indent=4), encoding="utf-8"
    )
    before = {
        str(path.relative_to(root)): path.read_bytes()
        for path in (root / "learndowns").rglob("*")
        if path.is_file()
    }
    prepared = service.prepare("editorial", refresh_from="editorial@r0001")
    packet, request = _refresh_request(root, prepared, original)
    assert packet["providerDecisionRefs"]
    report = DirectionStore(root / "direction").load_document(
        prepared["refs"]["refreshReport"]["path"]
    )
    assert report["bookkeepingOnly"] is False
    record = next(
        record
        for record in packet["evidenceRecords"]
        if record.get("explicitInstruction")
    )
    assert record["selector"]["pointer"] == "/providerInstruction/text"
    item = request["candidate"]["statements"][0]
    item.update(
        basis="creator-instruction",
        rationaleKind="creator-recorded",
        evidenceIds=[record["evidenceId"]],
        independentProjectIds=[],
        exclusions=record["applicability"]["exclusions"],
    )
    result = service.propose(request)
    assert result["status"] == "needs-review"
    after = {
        str(path.relative_to(root)): path.read_bytes()
        for path in (root / "learndowns").rglob("*")
        if path.is_file()
    }
    assert after == before


def test_existing_native_directive_is_not_a_new_semantic_change_on_ordinary_accept(
    tmp_path,
):
    root = provider_fixture(tmp_path)
    service, _, _, original = prepare_candidate(root)
    proposal = service.propose(original)
    instruction = {
        "text": "Keep later explanations clear.",
        "applicability": {
            "formats": [],
            "sections": [],
            "conditions": [],
            "exclusions": [],
        },
        "exclusions": [],
    }
    _decision(service, proposal, "accept", providerInstruction=instruction)
    prepared = service.prepare("editorial", refresh_from="editorial@r0001")
    _, request = _refresh_request(root, prepared, original)
    updated = service.propose(request)
    _decision(service, updated, "accept", requestId="accept-updated-native-context")
    source = root / "learndowns/20260101-neutral-tutorial/learndown.json"
    source.write_text(
        json.dumps(json.loads(source.read_text()), indent=4), encoding="utf-8"
    )
    next_prepared = service.prepare("editorial", refresh_from="editorial@r0002")
    report = DirectionStore(root / "direction").load_document(
        next_prepared["refs"]["refreshReport"]["path"]
    )
    assert report["bookkeepingOnly"] is True


def test_refresh_preserves_pending_creator_edit_instead_of_old_parent_wording(tmp_path):
    root, service, proposal, original = _accepted(tmp_path)
    changes = copy.deepcopy(original["candidate"])
    changes["statements"][0]["text"] = "A precise creator-requested wording."
    _decision(service, proposal, "edit", edits=changes)
    prepared = service.prepare("editorial", refresh_from="editorial@r0001")
    packet, request = _refresh_request(root, prepared, original)
    with pytest.raises(DirectionError):
        service.propose(request)
    request["requestId"] = "preserve-requested-edit"
    request["candidate"]["statements"][0]["text"] = packet["statementLineages"][0][
        "text"
    ]
    assert service.propose(request)["status"] == "needs-review"
    assert profile_state(root)["acceptedRef"] == proposal["refs"]["proposal"]


def test_accepting_edited_profile_keeps_exact_creator_constraint_on_refresh(tmp_path):
    root, service, proposal, original = _accepted(tmp_path)
    changes = copy.deepcopy(original["candidate"])
    changes["statements"][0]["text"] = "Exact creator wording must survive acceptance."
    edited = _decision(service, proposal, "edit", edits=changes)
    edited_proposal = {
        "refs": {"proposal": edited["refs"]["proposal"]},
        "expectedIndexHash": edited["expectedIndexHash"],
    }
    _decision(service, edited_proposal, "accept", requestId="accept-edited-body")
    prepared = service.prepare("editorial", refresh_from="editorial@r0002")
    _, request = _refresh_request(root, prepared, original)
    with pytest.raises(DirectionError, match="edits and qualifications"):
        service.propose(request)


def test_forged_packet_cannot_omit_native_disposition_history(tmp_path):
    from avo.timeline.contracts import document_hash_excluding

    root, service, _, original = _accepted(tmp_path)
    prepared = service.prepare("editorial", refresh_from="editorial@r0001")
    packet, request = _refresh_request(root, prepared, original)
    packet["providerDecisionRefs"] = []
    packet["statementLineages"] = []
    packet["documentHash"] = document_hash_excluding(packet, "documentHash")
    ref = DirectionStore(root / "direction").write_document(
        "collections/omitted-history.json", packet
    )
    request["packetRef"] = ref
    request["synthesisProvenance"]["packetHash"] = ref["documentHash"]
    with pytest.raises(DirectionError):
        service.propose(request)


def test_unavailable_learner_limits_refresh_without_mutating_old_profile(tmp_path):
    root, service, proposal, _ = _accepted(tmp_path)
    (root / "learndowns/20260101-neutral-tutorial/learndown.json").unlink()
    prepared = service.prepare("editorial", refresh_from="editorial@r0001")
    report = DirectionStore(root / "direction").load_document(
        prepared["refs"]["refreshReport"]["path"]
    )
    assert report["unavailableEntries"] == ["20260101-neutral-tutorial"]
    assert prepared["coverage"]["unavailable"] == 1
    shown = service.show("editorial@r0001", check_sources=True)
    assert shown["freshness"]["status"] == "unavailable"
    assert shown["refs"]["profile"] == proposal["refs"]["proposal"]
    assert profile_state(root)["acceptedRef"] == proposal["refs"]["proposal"]


def test_rejection_with_new_explicit_directive_keeps_instruction_separate(tmp_path):
    root = provider_fixture(tmp_path)
    service, _, _, original = prepare_candidate(root)
    proposal = service.propose(original)
    instruction = {
        "text": "Keep future tutorial explanations restrained.",
        "applicability": {
            "formats": ["step-by-step"],
            "sections": [],
            "conditions": [],
            "exclusions": [],
        },
        "exclusions": [],
    }
    _decision(service, proposal, "reject", providerInstruction=instruction)
    prepared = service.prepare("editorial", refresh_from="editorial@r0001")
    packet = DirectionStore(root / "direction").load_document(
        prepared["refs"]["packet"]["path"]
    )
    record = next(
        item for item in packet["evidenceRecords"] if item.get("explicitInstruction")
    )
    assert record["reportedState"] == "reject"
    assert record["normalizedState"] == "observed"
    assert record["useEvidence"] is None
    assert profile_state(root)["acceptedRef"] is None


def test_new_use_reports_changed_authored_brand_without_rewriting_profile(tmp_path):
    root, service, proposal, _ = _accepted(tmp_path)
    (root / "DESIGN.md").write_text(
        "A newly authored brand direction.", encoding="utf-8"
    )
    shown = service.show("editorial@r0001", check_sources=True)
    assert shown["freshness"]["status"] == "changed"
    assert "authored-brand" in shown["freshness"]["affectedInputs"]
    assert profile_state(root)["acceptedRef"] == proposal["refs"]["proposal"]
