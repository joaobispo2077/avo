"""Transcript-evidence choices never grant editorial cut approval."""

from copy import deepcopy

import pytest

from avo.timeline.preparation_recovery import PreparationError
from tests.test_speech_recovery import recovery


def decision(service, shown, choice, *, operation_id="choose-one", previous=None):
    return {
        "contractVersion": "1.0.0",
        "operation": "recover-decide",
        "operationId": operation_id,
        "actor": "creator",
        "reason": "Review the source evidence",
        "resultRef": shown["results"][0]["resultRef"],
        "requestRef": shown["requestRef"],
        "intervalIndex": shown["results"][0]["intervalIndex"],
        "choice": choice,
        "expectedLedgerHash": service.store.head_hash(),
        "expectedDecisionRefs": [] if previous is None else [previous],
    }


def evidence(service, request):
    context = service._source_context(request)
    return service.source_evidence(
        context["source"],
        source_range=context["binding"]["sourceRange"],
        routing=context["routing"],
        sync_ref=context["syncRef"],
    )


@pytest.mark.parametrize("choice", ["original", "recovered", "reject", "defer"])
def test_explicit_alternative_choice_preserves_originals_and_cut_authority(
    tmp_path, choice
):
    cutting, cmap, service, port, request = recovery(tmp_path)
    shown = service.recover(request)
    original = cutting.store.load_document(request["analysisRef"])
    recovered = cutting.store.load_document(shown["results"][0]["resultRef"])
    selected = service.decide(decision(service, shown, choice))
    assert selected["choice"] == choice
    assert selected["cutApproval"] == "not-granted"
    assert cutting.workspace.store("cmap").head_hash() == cmap["contentHash"]
    assert cutting.store.load_document(request["analysisRef"]) == original
    assert cutting.store.load_document(shown["results"][0]["resultRef"]) == recovered
    assert len(port.calls) == 1


def test_selected_unaligned_text_remains_protected_and_cannot_authorize_word_anchors(
    tmp_path,
):
    cutting, _, service, port, request = recovery(tmp_path)
    shown = service.recover(request)
    selected = service.decide(decision(service, shown, "recovered"))
    observed = evidence(service, request)
    assert selected["wordAnchorsEligible"] is False
    assert observed["status"] == "selected"
    assert observed["decisionRefs"] == [selected["decisionRef"]]
    assert request["ranges"][0] in observed["protectedRanges"]
    assert any(word["text"] == "recovered" for word in observed["analysis"]["words"])
    assert len(port.calls) == 1
    assert (
        cutting.store.load_document(request["analysisRef"])["payload"]["words"]
        != observed["analysis"]["words"]
    )


def test_exact_decision_replay_is_idempotent_and_changed_identity_cannot_overwrite_it(
    tmp_path,
):
    _, _, service, _, request = recovery(tmp_path)
    shown = service.recover(request)
    choose = decision(service, shown, "original")
    first = service.decide(choose)
    head = service.store.head_hash()
    again = service.decide(choose)
    assert again["decisionRef"] == first["decisionRef"]
    assert service.store.head_hash() == head
    with pytest.raises(PreparationError, match="identity|operation"):
        service.decide({**choose, "choice": "recovered"})
    assert service.store.head_hash() == head


def test_conflicting_alternative_requires_its_exact_predecessor(tmp_path):
    cutting, _, service, _, request = recovery(tmp_path)
    shown = service.recover(request)
    first = service.decide(decision(service, shown, "original"))
    historical = deepcopy(cutting.store.load_document(first["decisionRef"]))
    replacement = decision(service, shown, "recovered", operation_id="choose-another")
    with pytest.raises(PreparationError, match="decision|conflict|predecessor"):
        service.decide(replacement)
    second = service.decide(
        {**replacement, "expectedDecisionRefs": [first["decisionRef"]]}
    )
    assert second["decisionRef"] != first["decisionRef"]
    assert cutting.store.load_document(first["decisionRef"]) == historical


def test_changed_model_blocks_recovered_evidence_selection_without_new_inference(
    tmp_path,
):
    _, _, service, port, request = recovery(tmp_path)
    shown = service.recover(request)
    choose = decision(service, shown, "recovered")
    head = service.store.head_hash()
    port.bindings["transcription"]["files"]["model.bin"] = "b" * 64
    with pytest.raises(PreparationError, match="stale|changed"):
        service.decide(choose)
    assert service.store.head_hash() == head
    assert len(port.calls) == 1


def test_deferred_ranges_remain_visible_and_need_explicit_resumption(tmp_path):
    _, _, service, _, request = recovery(tmp_path)
    shown = service.recover(request)
    deferred = service.decide(decision(service, shown, "defer"))
    observed = evidence(service, request)
    assert observed["status"] == "deferred"
    assert request["ranges"][0] in observed["protectedRanges"]
    resumed = service.decide(
        decision(
            service,
            shown,
            "recovered",
            operation_id="resume-choice",
            previous=deferred["decisionRef"],
        )
    )
    assert evidence(service, request)["decisionRefs"] == [resumed["decisionRef"]]


def test_cutting_consumes_selected_evidence_without_retranscribing_or_losing_protection(
    tmp_path,
):
    cutting, cmap, service, port, request = recovery(tmp_path)
    shown = service.recover(request)
    selected = service.decide(decision(service, shown, "recovered"))

    def forbidden(*args, **kwargs):
        pytest.fail("selected source evidence caused another ASR analysis")

    port.analyze = forbidden
    cutting.analysis_port = port
    analyzed = cutting.analyze()
    reference = analyzed["coverage"]["speech"][0]["analysisRef"]
    saved = cutting.store.load_document(reference)["payload"]
    assert any(word["text"] == "recovered" for word in saved["words"])
    assert selected["decisionRef"] in saved["preparationEvidence"]["decisionRefs"]
    protections = cutting._speech_protections({"selected": saved})
    assert any(item["sourceRange"] == request["ranges"][0] for item in protections)
    assert cutting.workspace.store("cmap").head_hash() == cmap["contentHash"]
    assert len(port.calls) == 1


def test_unavailable_recovery_can_be_deferred_and_reloaded_without_model_execution(
    tmp_path,
):
    from avo.timeline.preparation_recovery import PreparationService

    cutting, _, service, port, request = recovery(tmp_path)
    port.bindings["transcription"]["status"] = "unknown"
    shown = service.recover(request)
    assert shown["status"] == "unavailable"
    selected = service.decide(decision(service, shown, "defer"))
    resumed = PreparationService(cutting.workspace, recovery_port=port)
    observed = evidence(resumed, request)
    assert observed["status"] == "deferred"
    assert observed["decisionRefs"] == [selected["decisionRef"]]
    assert request["ranges"][0] in observed["protectedRanges"]
    assert port.calls == []


def test_accepted_choice_becomes_stale_after_model_change_and_replay_keeps_history(
    tmp_path,
):
    cutting, _, service, port, request = recovery(tmp_path)
    shown = service.recover(request)
    choose = decision(service, shown, "recovered")
    first = service.decide(choose)
    historical = cutting.store.load_document(first["decisionRef"])
    port.bindings["transcription"]["files"]["model.bin"] = "c" * 64
    again = service.decide(choose)
    assert again["status"] == "stale"
    assert again["wordAnchorsEligible"] is False
    assert again["decisionRef"] == first["decisionRef"]
    observed = evidence(service, request)
    assert observed["status"] == "stale"
    assert request["ranges"][0] in observed["protectedRanges"]
    assert cutting.store.load_document(first["decisionRef"]) == historical
    assert len(port.calls) == 1


def test_decision_with_an_old_journal_head_cannot_replace_newer_choices(tmp_path):
    _, _, service, _, request = recovery(tmp_path)
    shown = service.recover(request)
    old = decision(service, shown, "recovered", operation_id="old-choice")
    selected = service.decide(decision(service, shown, "original"))
    with pytest.raises(PreparationError, match="compare-and-swap|head|stale"):
        service.decide({**old, "expectedDecisionRefs": [selected["decisionRef"]]})
    assert evidence(service, request)["decisionRefs"] == [selected["decisionRef"]]


def test_store_rejects_an_overlapping_result_from_a_different_request(tmp_path):
    from avo.timeline.contracts import content_hash
    from avo.timeline.cutting_contracts import make_document
    from avo.timeline.cutting_store import CuttingStoreError
    from tests.test_speech_recovery import selection

    _, _, service, _, request = recovery(tmp_path)
    first = service.recover(request)
    another = deepcopy(request)
    another["operationId"] = "another-recovery"
    another["selection"] = selection(maxAttemptsPerInterval=2)
    second = service.recover(another)
    choose = decision(service, first, "recovered")
    choose["resultRef"] = second["results"][0]["resultRef"]
    interval = request["ranges"][0]
    document = make_document(
        "speech-recovery-decision",
        {
            "input": choose,
            "requestHash": content_hash(choose),
            "sourceRange": interval,
            "knownResultRefs": service.store.overlapping_recovery_results(
                first["requestRef"], interval
            ),
            "decidedAt": service.store.clock(),
        },
    )
    head = service.store.head_hash()
    with pytest.raises(CuttingStoreError, match="scope"):
        service.store.record_recovery_decision(document)
    assert service.store.head_hash() == head


def test_selected_text_drops_original_character_alignment_for_the_changed_interval(
    tmp_path,
):
    from avo.timeline.cutting_contracts import make_document

    cutting, _, service, _, request = recovery(tmp_path)
    original = deepcopy(service._analysis(request["analysisRef"]))
    original["alignment"]["characters"] = [
        {"text": "f", "start": 0, "end": 0.05},
        {"text": "l", "start": 0.75, "end": 0.8},
    ]
    request["analysisRef"] = cutting.store.save_document(
        make_document("source-analysis", original)
    )
    shown = service.recover(request)
    service.decide(decision(service, shown, "recovered"))
    selected = evidence(service, request)["analysis"]
    assert selected["alignment"]["characters"] == [
        {"text": "l", "start": 0.75, "end": 0.8}
    ]
    assert cutting.store.load_document(request["analysisRef"])["payload"] == original


def test_cross_boundary_original_word_blocks_partial_replacement_and_preserves_evidence(
    tmp_path,
):
    from avo.timeline.cutting_contracts import make_document

    cutting, _, service, _, request = recovery(tmp_path)
    original = deepcopy(service._analysis(request["analysisRef"]))
    original["words"][0]["end"] = 0.3
    request["analysisRef"] = cutting.store.save_document(
        make_document("source-analysis", original)
    )
    shown = service.recover(request)
    service.decide(decision(service, shown, "recovered"))
    observed = evidence(service, request)
    assert observed["status"] == "stale"
    assert request["ranges"][0] in observed["protectedRanges"]
    assert observed["analysis"]["words"] == original["words"]


def test_selected_range_replaces_an_unsupported_zero_duration_original_token():
    from fractions import Fraction

    from avo.timeline.preparation_selected import _selected_words

    base = [{"text": "old", "start": 0.1, "end": 0.1}]
    incoming = [{"text": "new", "start": 0, "end": 0.2}]
    assert _selected_words(base, incoming, (Fraction(0), Fraction(1, 4))) == incoming


def test_incoming_word_that_crosses_selection_is_not_silently_discarded():
    from fractions import Fraction

    from avo.timeline.preparation_selected import _selected_words

    incoming = [{"text": "crossing", "start": 0.2, "end": 0.3}]
    with pytest.raises(ValueError, match="boundary"):
        _selected_words([], incoming, (Fraction(0), Fraction(1, 4)))


def test_changed_source_unit_with_no_analysis_port_remains_protected(tmp_path):
    from avo.timeline.cmap_service import CMapService

    cutting, cmap, service, _, request = recovery(tmp_path)
    shown = service.recover(request)
    service.decide(decision(service, shown, "recovered"))
    changed = deepcopy(cmap["snapshot"])
    changed["segments"][0]["out"]["ticks"] = 43200
    CMapService(cutting.workspace).author(changed, actor="creator", reason="new unit")
    cutting.analysis_port = None
    observed = cutting.analyze()
    saved = cutting.store.load_document(
        observed["coverage"]["speech"][0]["analysisRef"]
    )["payload"]
    assert saved["preparationEvidence"]["status"] == "stale"
    protections = cutting._speech_protections({"source": saved})
    assert protections
    assert not any(word.get("text") == "recovered" for word in saved.get("words", []))
