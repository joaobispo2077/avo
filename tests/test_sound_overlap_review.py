"""Scheduled sound overlap is metadata evidence, never a measured masking verdict."""

from copy import deepcopy

import pytest

from avo.timeline.sound_choices import _sound_choice_advisories
from tests.test_sound_choices import inputs, prepare


def layered(tmp_path, *, second_frame=45, count=2):
    entry, event, choice, context, clock = inputs(tmp_path)
    events = [event] + [
        {
            **event,
            "eventId": f"layer-{index}",
            "role": "tail",
            "programFrame": second_frame,
        }
        for index in range(1, count)
    ]
    for item in events:
        item["visibleRange"] = {"startFrame": 0, "endFrameExclusive": 90}
    choices = [{**deepcopy(choice), "eventId": item["eventId"]} for item in events]
    context["orderedEventIds"] = [item["eventId"] for item in events]
    return entry, events, choices, context, clock


def overlaps(result):
    return [row for row in result["advisories"] if row["code"] == "overlapping-sounds"]


def test_different_attacks_expose_exact_overlapping_tails_and_selected_roles(tmp_path):
    entry, events, choices, context, clock = layered(tmp_path)
    original = deepcopy((events, choices))
    result = prepare(entry, events, choices, [context], clock)
    assert overlaps(result) == [
        {
            "code": "overlapping-sounds",
            "eventIds": [events[0]["eventId"], events[1]["eventId"]],
            "roles": ["main", "tail"],
            "range": {
                "unit": "seconds",
                "start": {"num": 71, "den": 40},
                "end": {"num": 43, "den": 20},
            },
            "assessment": "timing-only",
        }
    ]
    assert "colliding-attacks" not in {row["code"] for row in result["advisories"]}
    assert (events, choices) == original
    assert result["acceptance"] == "pending-listening"
    assert "dialogue-masking" in result["reviewObligations"]


@pytest.mark.parametrize("second_frame", [54, 60])
def test_touching_or_separate_sound_ranges_do_not_claim_overlap(tmp_path, second_frame):
    entry, events, choices, context, clock = layered(
        tmp_path, second_frame=second_frame
    )
    result = prepare(entry, events, choices, [context], clock)
    assert overlaps(result) == []


def test_silence_never_contributes_to_overlap(tmp_path):
    entry, events, choices, context, clock = layered(tmp_path)
    choices[1].update(entryId=None, trimRange=None, mix=None)
    context["orderedEventIds"] = []
    result = prepare(entry, events, choices, [context], clock)
    assert overlaps(result) == []


def test_advisory_budget_reports_omitted_pairs_instead_of_silently_dropping_them(
    tmp_path,
):
    entry, events, choices, context, clock = layered(
        tmp_path, second_frame=30, count=12
    )
    result = prepare(entry, events, choices, [context], clock)
    assert len(overlaps(result)) == 64
    assert result["advisories"][-1] == {
        "code": "overlap-report-truncated",
        "shownPairs": 64,
        "totalPairs": 66,
    }


def test_overlap_and_attack_comparisons_keep_each_native_output_sample_rate(tmp_path):
    entry, event, choice, context, clock = inputs(tmp_path)
    first = prepare(entry, [event], [choice], [context], clock)["choices"]
    event["eventId"] = choice["eventId"] = "other-clock"
    second = prepare(
        entry, [event], [choice], [context], {**clock, "sampleRate": 24000}
    )["choices"]
    reports = _sound_choice_advisories(first + second)
    collision = next(row for row in reports if row["code"] == "colliding-attacks")
    assert collision["eventIds"] == [first[0]["eventId"], "other-clock"]
    overlap = next(row for row in reports if row["code"] == "overlapping-sounds")
    assert overlap["range"] == {
        "unit": "seconds",
        "start": {"num": 23, "den": 20},
        "end": {"num": 43, "den": 20},
    }


def test_unresolved_choices_cannot_claim_a_scheduled_overlap(tmp_path):
    entry, events, choices, context, clock = layered(tmp_path)
    entry["rights"]["status"] = "unknown"
    context["orderedEventIds"] = []
    result = prepare(entry, events, choices, [context], clock)
    assert all(choice["fit"]["status"] == "unresolved" for choice in result["choices"])
    assert overlaps(result) == []


def test_equal_sample_counts_at_different_rates_are_not_a_collision(tmp_path):
    entry, event, choice, context, clock = inputs(tmp_path)
    first = prepare(entry, [event], [choice], [context], clock)["choices"]
    event.update(
        eventId="later",
        programFrame=60,
        visibleRange={"startFrame": 0, "endFrameExclusive": 90},
    )
    choice["eventId"] = "later"
    second = prepare(
        entry, [event], [choice], [context], {**clock, "sampleRate": 24000}
    )["choices"]
    assert (
        first[0]["fit"]["event"]["resolvedImpactSample"]
        == second[0]["fit"]["event"]["resolvedImpactSample"]
    )
    reports = _sound_choice_advisories(first + second)
    assert not {"colliding-attacks", "overlapping-sounds"} & {
        row["code"] for row in reports
    }
