"""Read-only completeness uses source-bound evidence and never calls an analyser."""

from copy import deepcopy

import pytest

from avo.timeline.contracts import content_hash, validate_document
from avo.timeline.preparation import coverage_protections, inspect_speech_coverage


def evidence():
    request = {
        "source_ref": {"locator": "original-camera.mkv", "sha256": "a" * 64},
        "source_range": {
            "sourceId": "camera",
            "startTicks": 1000,
            "endTicksExclusive": 6000,
            "timebase": {"num": 1, "den": 1000},
        },
        "routing": {"streamIndex": 2, "channels": [0]},
        "sync_ref": {"locator": "sync-0001", "sha256": "b" * 64},
    }
    analysis = {
        "sourceRef": deepcopy(request["source_ref"]),
        "routing": deepcopy(request["routing"]),
        "syncRef": deepcopy(request["sync_ref"]),
        "preprocessing": {"sourceRange": deepcopy(request["source_range"])},
        "status": "pass",
        "coverage": {"observed": True, "start": 1, "end": 6},
        "vad": [{"start": 1, "end": 2}, {"start": 3, "end": 4}, {"start": 5, "end": 6}],
        "words": [
            {"text": "first take", "start": 1, "end": 2, "alignmentStatus": "aligned"},
            {"text": "last take", "start": 5, "end": 6, "alignmentStatus": "aligned"},
        ],
        "alignment": {"status": "pass", "characters": []},
        "tools": [{"modelId": "approved-fixture", "runtimeHash": "c" * 64}],
    }
    return analysis, request


def test_omitted_repeated_take_is_visible_and_protected_in_original_source_clock():
    analysis, request = evidence()
    before = deepcopy((analysis, request))
    result = inspect_speech_coverage(analysis, **request)
    validate_document(result, "avo.preparation.schema.json#/$defs/coverage")
    assert result["status"] == "needs-review"
    assert [
        {key: value for key, value in row.items() if key != "observationId"}
        for row in result["observations"]
    ] == [
        {
            "kind": "possible-speech-without-reliable-words",
            "sourceRange": {
                **request["source_range"],
                "startTicks": 3000,
                "endTicksExclusive": 4000,
            },
            "speechConfirmed": False,
            "disposition": "unresolved",
        }
    ]
    assert result["protectedRanges"] == [result["observations"][0]["sourceRange"]]
    assert result["binding"]["routingHash"] == content_hash(request["routing"])
    assert (analysis, request) == before
    assert inspect_speech_coverage(analysis, **request) == result


def test_false_acoustic_positive_does_not_become_speech_or_automatic_recovery():
    analysis, request = evidence()
    analysis["words"] = []
    result = inspect_speech_coverage(analysis, **request)
    assert result["status"] == "needs-review"
    assert all(row["speechConfirmed"] is False for row in result["observations"])
    assert result["authorization"] == "none"
    assert result["automaticRecovery"] is False


@pytest.mark.parametrize("change", ["source", "stream", "channel", "sync", "range"])
def test_wrong_source_stream_channel_sync_or_range_cannot_supply_current_coverage(
    change,
):
    analysis, request = evidence()
    if change == "source":
        analysis["sourceRef"]["sha256"] = "d" * 64
    elif change == "stream":
        analysis["routing"]["streamIndex"] = 3
    elif change == "channel":
        analysis["routing"]["channels"] = [1]
    elif change == "sync":
        analysis["syncRef"]["sha256"] = "e" * 64
    else:
        analysis["preprocessing"]["sourceRange"]["startTicks"] = 2000
    result = inspect_speech_coverage(analysis, **request)
    assert result["status"] == "stale"
    assert result["protectedRanges"] == [request["source_range"]]
    assert result["issues"]


def test_missing_acoustic_evidence_stays_unavailable_without_file_or_model_access(
    monkeypatch,
):
    analysis, request = evidence()
    analysis["coverage"] = {"observed": False}

    def forbidden(*_args, **_kwargs):
        raise AssertionError("metadata coverage must not access source/model/runtime")

    import subprocess
    from pathlib import Path

    original_open = Path.open

    def guarded(path, *args, **kwargs):
        if path.name == "original-camera.mkv":
            return forbidden()
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guarded)
    monkeypatch.setattr(subprocess, "run", forbidden)
    result = inspect_speech_coverage(analysis, **request)
    assert result["status"] == "unavailable"
    assert result["protectedRanges"] == [request["source_range"]]


def test_unreliable_word_timing_cannot_hide_a_possible_omission():
    analysis, request = evidence()
    analysis["words"].append(
        {"text": "guessed", "start": 3, "end": 4, "alignmentStatus": "unsupported"}
    )
    result = inspect_speech_coverage(analysis, **request)
    assert len(result["observations"]) == 1
    assert result["observations"][0]["sourceRange"]["startTicks"] == 3000


def test_only_available_observations_can_report_no_detected_gaps():
    analysis, request = evidence()
    analysis["words"].append(
        {"text": "middle take", "start": 3, "end": 4, "alignmentStatus": "aligned"}
    )
    result = inspect_speech_coverage(analysis, **request)
    assert result["status"] == "no-observed-gaps"
    assert result["protectedRanges"] == []
    assert result["assessment"] == "available-evidence-only"


def test_partial_observation_exposes_unmeasured_original_ranges():
    analysis, request = evidence()
    analysis["coverage"].update(start=2, end=5)
    analysis["vad"] = [{"start": 3, "end": 4}]
    analysis["words"] = []
    result = inspect_speech_coverage(analysis, **request)
    unmeasured = [
        row["sourceRange"]
        for row in result["observations"]
        if row["kind"] == "unmeasured"
    ]
    assert [(row["startTicks"], row["endTicksExclusive"]) for row in unmeasured] == [
        (1000, 2000),
        (5000, 6000),
    ]


@pytest.mark.parametrize("missing", ["vad", "words", "tools", "status", "routing"])
def test_absent_analysis_or_routing_never_means_an_empty_complete_observation(missing):
    analysis, request = evidence()
    if missing == "routing":
        analysis["routing"] = request["routing"] = {}
    else:
        analysis.pop(missing)
    result = inspect_speech_coverage(analysis, **request)
    assert result["status"] == "unavailable"
    assert result["protectedRanges"] == [request["source_range"]]


def test_a_word_spanning_two_acoustic_intervals_keeps_the_correct_uncovered_edges():
    analysis, request = evidence()
    analysis["words"] = [
        {"text": "long word", "start": 1.5, "end": 3.5, "alignmentStatus": "aligned"}
    ]
    result = inspect_speech_coverage(analysis, **request)
    assert [
        (row["startTicks"], row["endTicksExclusive"])
        for row in result["protectedRanges"]
    ] == [
        (1000, 1500),
        (3500, 4000),
        (5000, 6000),
    ]


def test_sub_tick_uncertainty_is_protected_outward_without_retiming_source():
    analysis, request = evidence()
    analysis["vad"] = [{"start": 3.0001, "end": 3.9999}]
    analysis["words"] = []
    result = inspect_speech_coverage(analysis, **request)
    assert result["protectedRanges"] == [
        {**request["source_range"], "startTicks": 3000, "endTicksExclusive": 4000}
    ]
    assert result["protectionRounding"] == "outward-to-source-ticks"


def test_forged_coverage_cannot_supply_cutting_protections():
    analysis, request = evidence()
    result = inspect_speech_coverage(analysis, **request)
    (event,) = coverage_protections(result)
    assert event["sourceRange"] == result["protectedRanges"][0]
    assert event["sourceFingerprint"] == request["source_ref"]
    result["protectedRanges"] = []
    with pytest.raises(ValueError, match="identity changed"):
        coverage_protections(result)
