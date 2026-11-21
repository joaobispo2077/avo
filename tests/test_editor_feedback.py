"""Feedback keeps independent current edits and reports uncertain return identity."""

from copy import deepcopy

from avo.timeline.editor_feedback import compare_editor_feedback


def occurrence(identity, start, raw_in):
    return {
        "id": identity,
        "fileId": "file-one",
        "start": start,
        "end": start + 12,
        "in": raw_in,
        "out": raw_in + 12,
        "sourceTrack": 1,
        "enabled": True,
        "markers": [],
        "rangeStatus": "observed",
        "unknown": {},
    }


def state(*clips):
    return {
        "sources": {"file-one": {"locator": "local-original.mov", "sha256": "a" * 64}},
        "tracks": [
            {
                "kind": "video",
                "index": 1,
                "enabled": True,
                "outputChannel": None,
                "clips": list(clips),
            }
        ],
        "markers": [],
        "unknown": {},
    }


def test_three_way_fields_keep_local_changes_propose_return_and_flag_divergence():
    base = state(occurrence("one", 0, 0), occurrence("two", 24, 24))
    current, returned = deepcopy(base), deepcopy(base)
    current["tracks"][0]["clips"][0].update(end=13, enabled=False)
    returned["tracks"][0]["clips"][0].update(end=14, out=13, enabled=False)
    current["tracks"][0]["clips"][1]["in"] = 26
    returned["markers"].append(
        {"name": "Reviewer", "comment": "Trim", "in": 10, "out": -1}
    )
    result = compare_editor_feedback(base, current, returned)
    assert [(row["id"], row["field"]) for row in result["proposals"]] == [
        ("one", "out"),
        ("sequence", "markers"),
    ]
    assert [(row["id"], row["field"]) for row in result["conflicts"]] == [
        ("one", "end")
    ]
    assert [(row["id"], row["field"]) for row in result["preserved"]] == [("two", "in")]


def test_missing_or_duplicated_ids_do_not_authorize_replacements_or_deletions():
    base = state(occurrence("first", 0, 0), occurrence("repeat", 24, 0))
    returned = state(occurrence(None, 0, 0))
    result = compare_editor_feedback(base, base, returned)
    assert result["proposals"] == []
    assert {row["id"] for row in result["unresolved"]} == {"first", "repeat", None}
    duplicate = state(occurrence("first", 0, 0), occurrence("first", 24, 0))
    assert compare_editor_feedback(base, base, duplicate)["proposals"] == []


def test_new_returned_occurrence_remains_visible_for_manual_review():
    base = state(occurrence("first", 0, 0))
    returned = state(occurrence("first", 0, 0), occurrence("new-from-editor", 24, 12))
    result = compare_editor_feedback(base, base, returned)
    assert result["proposals"] == []
    assert result["unresolved"] == [
        {
            "id": "new-from-editor",
            "reason": "unmatched-returned-occurrence",
            "lane": ["video", 1],
            "start": 24,
            "end": 36,
        }
    ]


def test_unique_fallback_is_reviewable_and_external_finishing_is_preserved():
    base = state(occurrence("first", 0, 0), occurrence("second", 24, 24))
    returned = deepcopy(base)
    candidate = returned["tracks"][0]["clips"][1]
    candidate.update(id=None, start=25, end=37, unknown={"filter": 1})
    returned["unknown"] = {"filter": 1}
    result = compare_editor_feedback(base, base, returned)
    assert {(row["field"], row["identity"]) for row in result["proposals"]} == {
        ("start", "suggested"),
        ("end", "suggested"),
    }
    assert result["external"]["filter"] == 1


def test_unobserved_markers_and_channel_fields_stay_unresolved():
    base = state(occurrence("first", 0, 0))
    base["markers"] = [{"name": "Proof boundary", "in": 0, "out": -1}]
    base["tracks"][0]["outputChannel"] = 2
    returned = deepcopy(base)
    returned["markers"] = []
    returned["tracks"][0].update(outputChannel=None)
    returned["tracks"][0]["clips"][0]["sourceTrack"] = None
    review = compare_editor_feedback(base, base, returned)
    assert review["proposals"] == review["conflicts"] == []
    assert {(row["id"], row["field"]) for row in review["unresolved"]} == {
        ("first", "sourceTrack"),
        ("first", "outputChannel"),
        ("sequence", "markers"),
    }


def test_explicit_gain_and_camera_values_follow_independent_three_way_rules():
    base = state(occurrence("first", 0, 0))
    base["tracks"][0]["clips"][0].update(gainDb=0, camera={"scale": 1})
    current, returned = deepcopy(base), deepcopy(base)
    current["tracks"][0]["clips"][0]["gainDb"] = -5
    returned["tracks"][0]["clips"][0].update(gainDb=-6, camera={"scale": 1.1})
    result = compare_editor_feedback(base, current, returned)
    assert [row["field"] for row in result["proposals"]] == ["camera"]
    assert [row["field"] for row in result["conflicts"]] == ["gainDb"]


def test_divergent_camera_and_markers_preserve_all_three_values_for_review():
    base = state(occurrence("first", 0, 0))
    base["tracks"][0]["clips"][0]["camera"] = {"scale": 1}
    base["markers"] = [{"name": "Keep", "in": 2, "out": -1}]
    current, returned = deepcopy(base), deepcopy(base)
    current["tracks"][0]["clips"][0]["camera"] = {"scale": 1.1}
    returned["tracks"][0]["clips"][0]["camera"] = {"scale": 1.2}
    current["markers"][0]["in"] = 4
    returned["markers"][0]["in"] = 6

    result = compare_editor_feedback(base, current, returned)

    assert result["proposals"] == result["unresolved"] == []
    assert {(row["id"], row["field"]) for row in result["conflicts"]} == {
        ("first", "camera"),
        ("sequence", "markers"),
    }
    rows = {row["field"]: row for row in result["conflicts"]}
    assert [
        rows["camera"][side]["scale"] for side in ("base", "current", "returned")
    ] == [
        1,
        1.1,
        1.2,
    ]
    assert [
        rows["markers"][side][0]["in"] for side in ("base", "current", "returned")
    ] == [
        2,
        4,
        6,
    ]
