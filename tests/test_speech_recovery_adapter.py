"""Real routed PCM with declared transcription; no ASR quality claim."""

from copy import deepcopy
from types import SimpleNamespace

import pytest

from avo.adapters.media.cutting_acoustics import CuttingAcousticsAdapter
from avo.adapters.media.cutting_analysis import CuttingAnalysisAdapter
from avo.timeline.ports import ToolError
from tests.test_speech_recovery import interval, recovery


@pytest.mark.parametrize("aligned", [False, True])
def test_recovery_preserves_source_offsets_and_pending_review_with_optional_alignment(
    tmp_path, monkeypatch, aligned
):
    cutting, _, service, bindings, request = recovery(tmp_path)
    request["ranges"] = [interval(12000, 24000)]
    adapter = CuttingAnalysisAdapter(cutting.workspace, SimpleNamespace(effective={}))
    observed = []

    class Transcriber:
        def transcribe_audio(
            self, audio, fingerprint, *, source_start, analysis_provenance
        ):
            assert audio.is_file()
            observed.append((source_start, deepcopy(analysis_provenance)))
            return {
                "text": "selected words",
                "words": [
                    {
                        "text": "selected",
                        "start": source_start,
                        "end": source_start + 0.1,
                    }
                ],
                "sourceStart": source_start,
                "analysisProvenance": analysis_provenance,
            }

    def acoustic(**kwargs):
        return CuttingAcousticsAdapter(
            **kwargs, vad_model=lambda padded: [0] * (len(padded) // 512)
        )

    monkeypatch.setattr(
        "avo.adapters.media.cutting_analysis.CuttingAcousticsAdapter", acoustic
    )
    monkeypatch.setattr(adapter, "_transcriber", lambda language: Transcriber())
    monkeypatch.setattr(adapter, "dependency_bindings", bindings.dependency_bindings)
    adapter._model_bindings["en"] = {"engine": "declared-test-transcriber"}

    def missing():
        raise ToolError(
            "missing-alignment", "separately configured alignment is unavailable"
        )

    class Aligner:
        def align(self, audio, *, segments, source_start, language):
            assert audio.is_file() and source_start == 0.25 and language == "en"
            assert segments == [{"start": 0, "end": 0.25, "text": "selected"}]
            return {
                "words": [
                    {
                        "text": "selected",
                        "start": source_start,
                        "end": source_start + 0.1,
                        "alignmentStatus": "aligned",
                        "eligibleEdge": True,
                    }
                ],
                "chars": [],
                "bindings": {"engine": "declared-test-aligner"},
            }

    if aligned:
        bindings.bindings["alignment"] = {
            "status": "observed",
            "engine": "declared-test-aligner",
        }
    monkeypatch.setattr(
        adapter, "_alignment", (lambda: Aligner()) if aligned else missing
    )
    service.recovery_port = adapter
    shown = service.recover(request)
    assert shown["status"] == "pending-review"
    payload = cutting.store.load_document(shown["results"][0]["resultRef"])["payload"]
    recovered = payload["recovered"]
    assert recovered["transcript"]["text"] == "selected words"
    assert recovered["analysis"]["words"][0]["start"] == 0.25
    assert observed[0][0] == 0.25
    assert observed[0][1]["sourceRange"] == request["ranges"][0]
    assert recovered["analysis"]["coverage"] == {
        "observed": True,
        "start": 0.25,
        "end": 0.5,
    }
    assert recovered["analysis"]["alignment"]["status"] == (
        "pass" if aligned else "missing"
    )
    assert payload["wordAnchorsEligible"] is aligned
    assert payload["selection"] == "pending" and shown["approval"] == "not-granted"
    assert recovered["analysis"]["recoveryContext"]["previousText"] is False
    assert recovered["analysis"]["recoveryContext"]["scope"] == "selected-interval-only"
