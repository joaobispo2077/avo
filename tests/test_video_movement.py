from __future__ import annotations

from avo.adapters.media.video_tracks import compose_media_layer, verify_video_movement


def test_moving_video_requires_frame_variation_but_intentional_still_does_not() -> None:
    moving = verify_video_movement("insert", ["a", "b", "c"], expected_motion=True)
    assert moving["status"] == "pass"
    frozen = verify_video_movement("insert", ["a", "a", "a"], expected_motion=True)
    assert frozen["status"] == "fail"
    still = verify_video_movement("photo", ["a", "a", "a"], expected_motion=False)
    assert still["status"] == "pass"


def test_uncertain_variation_routes_to_human() -> None:
    result = verify_video_movement(
        "dark-shot", ["a", "a", "b"], expected_motion=True, confidence=0.25
    )
    assert result["status"] == "needs-human-judgment"


def test_vertical_video_uses_mirrored_background_and_images_stay_direct() -> None:
    vertical = compose_media_layer(
        {
            "layerId": "phone",
            "eventId": "phone-entry",
            "kind": "video",
            "width": 1080,
            "height": 1920,
            "locator": "phone.mp4",
            "programFrame": 30,
            "visibleRange": {"startFrame": 30, "endFrameExclusive": 90},
            "sourceRange": {"startFrame": 0, "endFrameExclusive": 60},
        },
        canvas={"width": 1920, "height": 1080},
    )
    assert vertical["background"]["mode"] == "mirrored-fill"
    assert vertical["foreground"]["preserveMotion"] is True
    assert vertical["timing"] == {
        "eventId": "phone-entry",
        "programFrame": 30,
        "visibleRange": {"startFrame": 30, "endFrameExclusive": 90},
        "sourceRange": {"startFrame": 0, "endFrameExclusive": 60},
    }
    image = compose_media_layer(
        {
            "layerId": "card",
            "kind": "image",
            "width": 800,
            "height": 600,
            "locator": "card.png",
        },
        canvas={"width": 1920, "height": 1080},
    )
    assert image["background"] is None
    assert image["foreground"]["preserveMotion"] is False
