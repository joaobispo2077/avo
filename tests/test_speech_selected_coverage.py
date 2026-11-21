"""Disjoint measured recovery windows leave their unmeasured gaps protected."""

from copy import deepcopy

import pytest

from avo.timeline.preparation import inspect_speech_coverage
from tests.test_speech_coverage import evidence


def test_disjoint_measured_windows_do_not_invent_coverage_between_them():
    analysis, request = evidence()
    analysis["coverage"] = {
        "observed": True,
        "intervals": [{"start": 1, "end": 2}, {"start": 5, "end": 6}],
    }
    analysis["vad"] = [analysis["vad"][0], analysis["vad"][-1]]
    before = deepcopy(analysis)
    result = inspect_speech_coverage(analysis, **request)
    assert result["status"] == "needs-review"
    assert [
        (
            row["kind"],
            row["sourceRange"]["startTicks"],
            row["sourceRange"]["endTicksExclusive"],
        )
        for row in result["observations"]
    ] == [("unmeasured", 2000, 5000)]
    assert analysis == before


@pytest.mark.parametrize(
    "windows", [[], [{"start": 0, "end": 2}], [{"start": 5, "end": 7}]]
)
def test_invalid_measurement_windows_remain_unavailable_instead_of_being_clipped(
    windows,
):
    analysis, request = evidence()
    analysis["coverage"] = {"observed": True, "intervals": windows}
    result = inspect_speech_coverage(analysis, **request)
    assert result["status"] == "unavailable"
    assert result["protectedRanges"] == [request["source_range"]]


def test_activity_outside_the_actual_measured_windows_is_not_accepted():
    analysis, request = evidence()
    analysis["coverage"] = {
        "observed": True,
        "intervals": [{"start": 1, "end": 2}, {"start": 5, "end": 6}],
    }
    result = inspect_speech_coverage(analysis, **request)
    assert result["status"] == "unavailable"
    assert result["protectedRanges"] == [request["source_range"]]


def test_multiple_unreliable_words_produce_one_issue_and_conservative_protection():
    analysis, request = evidence()
    for word in analysis["words"]:
        word["alignmentStatus"] = "unsupported"
    result = inspect_speech_coverage(analysis, **request)
    assert result["status"] == "needs-review"
    assert result["issues"].count("word-timing-unreliable") == 1
    assert result["protectedRanges"]
