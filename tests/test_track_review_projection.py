"""The linked motion review exposes canonical contribution lanes in both views."""

from avo.timeline.contracts import content_hash
from avo.timeline.motion_review import MotionReviewService, render_html, render_text
from tests.test_motion_review_projection import cue, install, workspace

__all__ = ["workspace"]


def track(layer_id, role, order, cue_id, **fields):
    return {
        "layerId": layer_id,
        "role": role,
        "order": order,
        "source": {
            "sha256": "a" * 64,
            "sizeBytes": 15,
            "locator": f"/assets/{layer_id}.mkv",
        },
        "regions": [
            {
                "regionId": f"region-{layer_id}",
                "startTicks": 12,
                "endTicks": 24,
                "timebase": {"num": 1, "den": 24},
                "cueIds": [cue_id],
            }
        ],
        **fields,
    }


def test_track_review_shows_named_lanes_exact_ranges_and_linked_items(
    workspace, monkeypatch
):
    sound = track(
        "original-dialogue", "dialogue", 10, "speech", channels=[1], gainDb=-3
    )
    music = track("reference-bed", "music", 104, "speech", mute=True)
    overlay = track("opening-graphic", "graphic", 4, "graphic", zOrder=11)
    base = track("presenter-source", "base", 90, "unknown", zOrder=2)
    absent = track(
        "caption-planned", "caption", 15, "graphic", source={}, status="disabled"
    )
    install(
        workspace,
        monkeypatch,
        {
            "bmap": {
                "cues": [cue("speech"), cue("graphic", componentRef="opening-title")]
            },
            "tracks": {
                "audioTracks": {"layers": [music, sound]},
                "videoTracks": {"layers": [overlay, absent, base]},
            },
        },
    )
    snapshot = MotionReviewService(workspace).project()
    review = snapshot["trackReview"]
    assert [row["laneId"] for row in review["audio"]] == [
        "original-dialogue",
        "reference-bed",
    ]
    assert [row["laneId"] for row in review["video"]] == [
        "presenter-source",
        "opening-graphic",
        "caption-planned",
    ]
    dialogue, muted = review["audio"]
    assert dialogue["state"] == "declared"
    assert dialogue["channels"] == [1]
    assert dialogue["gainDb"] == -3
    assert muted["state"] == "muted"
    unresolved, graphic, disabled = review["video"]
    assert unresolved["regions"][0]["missingCueIds"] == ["unknown"]
    assert disabled["state"] == "disabled"
    region = graphic["regions"][0]
    assert region["timebase"] == {"num": 1, "den": 24}
    assert (region["startTicks"], region["endTicks"]) == (12, 24)
    assert region["componentRefs"] == ["opening-title"]
    text, html = render_text(snapshot), render_html(snapshot)
    for label in (
        "Production audio",
        "Picture tracks",
        "original-dialogue",
        "opening-title",
        "Muted",
        "unknown",
    ):
        assert label in text and label in html
    assert f'href="#item-{content_hash("graphic")}"' in html


def test_absent_track_evidence_remains_visible_with_older_report_compatibility(
    workspace,
):
    snapshot = MotionReviewService(workspace).project()
    assert snapshot["trackReview"]["state"] == "unavailable"
    assert "Track evidence unavailable" in render_text(snapshot)
    assert "Track evidence unavailable" in render_html(snapshot)
    snapshot.pop("trackReview")
    assert '"video": []' in render_text(snapshot)
    assert "Production audio" not in render_html(snapshot)


def test_stale_track_evidence_keeps_declared_lanes_for_review(workspace, monkeypatch):
    layer = track("old-dialogue", "dialogue", 4, "first")
    install(
        workspace,
        monkeypatch,
        {"tracks": {"audioTracks": {"layers": [layer]}}},
        states={"tracks": "stale"},
    )
    snapshot = MotionReviewService(workspace).project()
    assert snapshot["trackReview"]["state"] == "stale"
    assert snapshot["trackReview"]["audio"][0]["laneId"] == "old-dialogue"
    assert "Tracks need review against the current edit" in render_html(snapshot)
