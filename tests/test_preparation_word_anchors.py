"""Word anchors need current measured, aligned evidence in original source time."""

from copy import deepcopy
from fractions import Fraction

import pytest

from avo.timeline import preparation_words
from avo.timeline.contracts import content_hash
from tests.test_speech_coverage import evidence


def prepared_word():
    analysis, request = evidence()
    analysis["words"][0]["eligibleEdge"] = True
    models = {
        "transcription": {"status": "observed", "files": {"asr.bin": "c" * 64}},
        "alignment": {"status": "observed", "files": {"align.bin": "d" * 64}},
    }
    return analysis, {
        **request,
        "model_bindings": models,
        "current_bindings": deepcopy(models),
        "word_index": 0,
        "word_hash": content_hash(analysis["words"][0]),
        "frame_rate": Fraction(24),
    }


def test_word_start_uses_measured_source_time_without_altering_evidence():
    analysis, request = prepared_word()
    before = deepcopy((analysis, request))
    assert preparation_words.word_source_time(analysis, **request) == {
        "ticks": 1000,
        "timebase": {"num": 1, "den": 1000},
    }
    assert (analysis, request) == before


def test_unrelated_uncertainty_does_not_block_the_selected_reliable_word():
    analysis, request = prepared_word()
    request["protected_ranges"] = [
        {**request["source_range"], "startTicks": 3000, "endTicksExclusive": 4000}
    ]
    assert preparation_words.word_source_time(analysis, **request)["ticks"] == 1000


@pytest.mark.parametrize(
    "change",
    [
        "source",
        "routing",
        "sync",
        "model",
        "unprepared",
        "unaligned",
        "ineligible",
        "text",
        "index",
        "unmeasured",
        "protected",
    ],
)
def test_stale_or_unqualified_word_evidence_cannot_supply_an_exact_anchor(change):
    analysis, request = prepared_word()
    if change == "source":
        analysis["sourceRef"]["sha256"] = "e" * 64
    elif change == "routing":
        analysis["routing"]["channels"] = [1]
    elif change == "sync":
        analysis["syncRef"]["sha256"] = "e" * 64
    elif change == "model":
        request["current_bindings"]["transcription"]["files"]["asr.bin"] = "e" * 64
    elif change == "unprepared":
        request["model_bindings"]["alignment"]["status"] = "unknown"
        request["current_bindings"] = deepcopy(request["model_bindings"])
    elif change == "unaligned":
        analysis["words"][0]["alignmentStatus"] = "unsupported"
    elif change == "ineligible":
        analysis["words"][0]["eligibleEdge"] = False
    elif change == "text":
        analysis["words"][0]["text"] = "a different word"
    elif change == "index":
        request["word_index"] = 99
    elif change == "unmeasured":
        analysis["coverage"]["observed"] = False
    else:
        request["protected_ranges"] = [request["source_range"]]
    with pytest.raises(ValueError):
        preparation_words.word_source_time(analysis, **request)


def test_word_start_rounds_once_to_native_ticks_within_one_program_frame():
    analysis, request = prepared_word()
    word = analysis["words"][0]
    word["start"] = 1.25051
    analysis["vad"][0]["start"] = word["start"]
    request["word_hash"] = content_hash(word)
    assert preparation_words.word_source_time(analysis, **request)["ticks"] == 1251


def test_a_source_clock_coarser_than_program_frames_is_not_word_exact():
    analysis, request = prepared_word()
    request["source_range"].update(
        startTicks=1, endTicksExclusive=6, timebase={"num": 1, "den": 1}
    )
    analysis["preprocessing"]["sourceRange"] = deepcopy(request["source_range"])
    with pytest.raises(ValueError, match="clock"):
        preparation_words.word_source_time(analysis, **request)
