"""Reference timing uses retained words from the explicitly selected original route."""

from avo.timeline import sound_word_evidence
from avo.timeline.reference_words import add_reference_words
from tests.test_sound_word_evidence import original_word


def test_selected_prepared_word_keeps_its_original_clock_and_discloses_missing_evidence(
    tmp_path, monkeypatch
):
    workspace, models, anchor = original_word(tmp_path)
    monkeypatch.setattr(
        sound_word_evidence, "workspace_speech_dependencies", lambda _: models
    )
    reader = sound_word_evidence.WordEvidenceReader(workspace)
    retained = reader._analysis(anchor["spokenEvidence"]["analysisRef"])
    _, source, routing, _, _ = reader._view(retained)
    other = {**anchor, "spokenEvidence": {**anchor["spokenEvidence"], "wordIndex": 99}}
    clip = {
        "source": {
            "sourceId": source["sourceId"],
            "sha256": source["fingerprint"]["sha256"],
        },
        "sourceRange": {
            "startTicks": 2000,
            "endTicks": 2200,
            "timebase": {"num": 1, "den": 1000},
        },
        "audio": {
            "streamIndex": routing["streamIndex"],
            "channelIndex": routing["channels"][0],
        },
        "wordAnchors": [anchor, other],
    }
    observation = {
        "coverage": {"minimumGapTicks": 40},
        "interpretation": {
            "availableEvidence": {"prepared-words": "not-selected"},
            "audioTiming": {
                "sampleRate": 48_000,
                "streamOriginSample": 96_000,
                "startSample": 96_000,
                "endSampleExclusive": 105_600,
                "clockUncertaintySamples": 48,
            },
            "timingCandidates": [
                {"kind": "reveal", "startTicks": 2000, "endTicks": 2040}
            ],
        },
    }
    add_reference_words(workspace, clip, observation)
    first, second = observation["interpretation"]["wordTiming"]
    assert first["status"] == "observed"
    assert first["startSample"] == 96_000
    assert first["clockUncertaintySamples"] == 49
    assert first["revealWindows"] == [{"startTicks": 2000, "endTicks": 2040}]
    assert len(first["anchor"]["spokenEvidence"]["wordHash"]) == 64
    assert second == {"status": "unavailable", "reason": "unverified-word-evidence"}
    clip["audio"]["streamIndex"] += 1
    add_reference_words(workspace, clip, observation)
    assert observation["interpretation"]["wordTiming"] == [second, second]
