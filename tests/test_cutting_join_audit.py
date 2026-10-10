"""Every join is an obligation; short duration alone is never removal evidence."""

from copy import deepcopy

from avo.timeline.cutting_audit import audit_joins


def snapshot(lengths=(300, 2, 300, 9, 300, 15, 300)):
    segments = []
    offset = 0
    for index, length in enumerate(lengths):
        segments.append(
            {
                "segmentId": f"unit-{index}",
                "sourceId": "raw",
                "reason": "inherited selection",
                "in": {
                    "domain": "raw-source",
                    "sourceId": "raw",
                    "ticks": offset,
                    "timebase": {"num": 1, "den": 30},
                },
                "out": {
                    "domain": "raw-source",
                    "sourceId": "raw",
                    "ticks": offset + length,
                    "timebase": {"num": 1, "den": 30},
                },
            }
        )
        offset += length + 60
    return {
        "sources": [
            {
                "sourceId": "raw",
                "kind": "raw",
                "fingerprint": {"sha256": "a" * 64, "sizeBytes": 1},
            }
        ],
        "segments": segments,
    }


def test_all_inherited_joins_and_residual_islands_are_accounted_for():
    source = snapshot()
    original = deepcopy(source)
    joins = audit_joins(source, {"num": 30, "den": 1})
    assert len(joins) == len(source["segments"]) - 1
    assert {join["programFrame"] for join in joins} == {300, 302, 602, 611, 911, 926}
    assert all(join["disposition"] == "needs-review" for join in joins)
    assert all(join["deletionAuthorized"] is False for join in joins)
    assert all("source-discontinuity" in join["flags"] for join in joins)
    assert source == original


def test_short_legitimate_interjection_is_flagged_without_deletion_permission():
    joins = audit_joins(snapshot((300, 3, 300)), {"num": 30, "den": 1})
    assert "short-right-island" in joins[0]["flags"]
    assert "short-left-island" in joins[1]["flags"]
    assert not any(join["deletionAuthorized"] for join in joins)


def test_join_identity_does_not_depend_on_earlier_program_duration():
    source = snapshot((300, 30, 300))
    before = audit_joins(source, {"num": 30, "den": 1})[1]
    source["segments"][0]["out"]["ticks"] = 200
    after = audit_joins(source, {"num": 30, "den": 1})[1]
    assert before["joinId"] == after["joinId"]
    assert before["programFrame"] != after["programFrame"]


def test_source_overlap_is_not_hidden_by_program_continuity():
    source = snapshot((300, 300))
    source["segments"][1]["in"]["ticks"] = 250
    joins = audit_joins(source, {"num": 30, "den": 1})
    assert "source-overlap" in joins[0]["flags"]


def test_contiguous_source_join_still_requires_inspection():
    source = snapshot((300, 300))
    source["segments"][1]["in"]["ticks"] = 300
    joins = audit_joins(source, {"num": 30, "den": 1})
    assert joins[0]["flags"] == []
    assert joins[0]["disposition"] == "needs-review"
