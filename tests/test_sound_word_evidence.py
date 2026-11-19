"""Spoken accents choose retained current words without another inference."""

from copy import deepcopy
from fractions import Fraction

import pytest

from avo.timeline import sound_word_evidence
from avo.timeline.cutting_contracts import make_document
from tests.test_speech_recovery import recovery
from tests.test_speech_recovery_choices import decision, evidence
from tests.test_speech_selected_measurements import measured_recovery


def prepared_models(port):
    result = port.dependency_bindings()
    result["alignment"] = {"status": "observed", "files": {"alignment.bin": "b" * 64}}
    return result


def word_anchor(cmap, analysis, reference):
    return {
        "sourceId": analysis["preprocessing"]["sourceRange"]["sourceId"],
        "sourceSha256": analysis["sourceRef"]["sha256"],
        "segmentId": cmap["snapshot"]["segments"][0]["segmentId"],
        "spokenEvidence": {"analysisRef": reference, "wordIndex": 0},
    }


def original_word(tmp_path):
    cutting, cmap, service, port, request = recovery(tmp_path)
    models = prepared_models(port)
    analysis = deepcopy(service._analysis(request["analysisRef"]))
    analysis["speechDependencies"] = deepcopy(models)
    analysis["words"][0]["eligibleEdge"] = True
    reference = cutting.store.save_document(make_document("source-analysis", analysis))
    return cutting.workspace, models, word_anchor(cmap, analysis, reference)


def test_current_original_word_freezes_its_evidence_and_derived_source_start(tmp_path):
    workspace, models, anchor = original_word(tmp_path)
    before = deepcopy(anchor)
    result = sound_word_evidence.WordEvidenceReader(
        workspace, model_bindings=models
    ).anchor(anchor, frame_rate=Fraction(30))
    assert result["sourceTime"] == {"ticks": 0, "timebase": {"num": 1, "den": 48000}}
    assert len(result["spokenEvidence"]["wordHash"]) == 64
    assert len(result["spokenEvidence"]["selectionHash"]) == 64
    assert anchor == before


def test_changed_model_cannot_recertify_an_original_word(tmp_path):
    workspace, models, anchor = original_word(tmp_path)
    models["transcription"]["files"]["model.bin"] = "f" * 64
    with pytest.raises(ValueError, match="model"):
        sound_word_evidence.WordEvidenceReader(workspace, model_bindings=models).anchor(
            anchor, frame_rate=Fraction(30)
        )


def test_a_word_point_cannot_escape_its_retained_source_occurrence(tmp_path):
    workspace, models, anchor = original_word(tmp_path)
    anchor["segmentId"] = "removed-occurrence"
    with pytest.raises(ValueError, match="occurrence"):
        sound_word_evidence.WordEvidenceReader(workspace, model_bindings=models).anchor(
            anchor, frame_rate=Fraction(30)
        )


def test_non_word_intents_do_not_resolve_speech_dependencies(monkeypatch):
    from avo.timeline.sound_planning import SoundPlanningService
    from tests.test_sound_opportunities import intent

    def forbidden(*args, **kwargs):
        pytest.fail("An ordinary sound intent inspected speech model dependencies")

    monkeypatch.setattr(sound_word_evidence, "workspace_speech_dependencies", forbidden)
    service = object.__new__(SoundPlanningService)
    assert service._spoken_anchors([intent()], Fraction(24)) is None
    assert sound_word_evidence.load_word_anchors(None, [intent()], Fraction(24)) is None


def test_selected_recovery_word_reuses_actual_result_bindings_and_stales_after_defer(
    tmp_path, monkeypatch
):
    cutting, cmap, service, port, request = measured_recovery(tmp_path)
    port.bindings = prepared_models(port)
    shown = service.recover(request)
    selected = service.decide(decision(service, shown, "recovered"))
    merged = evidence(service, request)["analysis"]
    reference = cutting.store.save_document(make_document("source-analysis", merged))
    anchor = word_anchor(cmap, merged, reference)

    def forbidden(*args, **kwargs):
        pytest.fail("A word cue repeated source inference")

    monkeypatch.setattr(port, "recover", forbidden)
    result = sound_word_evidence.WordEvidenceReader(
        cutting.workspace, model_bindings=port.dependency_bindings()
    ).anchor(anchor, frame_rate=Fraction(30))
    assert result["sourceTime"]["ticks"] == 0
    assert (
        result["spokenEvidence"]["selectionHash"]
        == merged["preparationEvidence"]["selectionHash"]
    )
    deferred = decision(service, shown, "defer", previous=selected["decisionRef"])
    deferred["operationId"] = "defer-selected-word"
    service.decide(deferred)
    with pytest.raises(ValueError, match="selection|word"):
        sound_word_evidence.WordEvidenceReader(
            cutting.workspace, model_bindings=port.dependency_bindings()
        ).anchor(result, frame_rate=Fraction(30))
