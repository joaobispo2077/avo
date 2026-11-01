import pytest

from avo.timeline.vision_review import VisionReviewError, compile_review_coverage


def coverage(**kwargs):
    return compile_review_coverage(
        duration_frames=64844,
        sections=[
            {"sectionId": "program", "startFrame": 0, "endFrameExclusive": 64844}
        ],
        required_windows=[
            {
                "windowId": "pause",
                "startFrame": 1236,
                "endFrameExclusive": 1479,
                "mandatory": True,
            }
        ],
        max_frames_per_pass=4,
        **kwargs,
    )


def test_full_review_keeps_global_coverage():
    result = coverage()
    frames = {n for p in result["passes"] for n in p["sampleFrames"]}
    assert {0, 64843} <= frames
    assert result["coverageBySection"]["program"]["planned"] == 3


def test_window_review_keeps_exact_window_without_global_overview():
    result = coverage(include_overview=False)
    frames = {n for p in result["passes"] for n in p["sampleFrames"]}
    assert frames == {1236, 1357, 1478}
    assert not result["coverageHoles"]
    assert result["coverageBySection"] == {}
    assert result["samplingMode"] == "dense-risk"


def test_empty_window_review_fails_closed():
    with pytest.raises(VisionReviewError, match="bounded window"):
        compile_review_coverage(
            duration_frames=100,
            sections=[{"sectionId": "p", "startFrame": 0, "endFrameExclusive": 100}],
            required_windows=[],
            max_frames_per_pass=4,
            include_overview=False,
        )
