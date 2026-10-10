from __future__ import annotations

from fractions import Fraction

from avo.adapters.understand.watch_skill import _frame_windows
from avo.timeline.vision_review import compile_review_coverage


def test_sparse_sections_and_dense_risks_are_deterministic_and_deduplicated() -> None:
    sections = [
        {"sectionId": "teaser", "startFrame": 0, "endFrameExclusive": 100},
        {"sectionId": "body", "startFrame": 100, "endFrameExclusive": 300},
    ]
    windows = [
        {
            "windowId": "join-1",
            "startFrame": 95,
            "endFrameExclusive": 105,
            "riskClasses": ["changed-join"],
            "mandatory": True,
        },
        {
            "windowId": "tactile-1",
            "startFrame": 200,
            "endFrameExclusive": 205,
            "riskClasses": ["tactile"],
            "mandatory": True,
        },
    ]
    first = compile_review_coverage(
        duration_frames=300,
        sections=sections,
        required_windows=windows,
        max_frames_per_pass=8,
        story_checkpoints=[75, 250],
        repair_windows=[
            {"windowId": "repair-1", "startFrame": 40, "endFrameExclusive": 45}
        ],
        comparison_windows=[
            {"windowId": "compare-1", "startFrame": 260, "endFrameExclusive": 265}
        ],
    )
    second = compile_review_coverage(
        duration_frames=300,
        sections=sections,
        required_windows=windows,
        max_frames_per_pass=8,
        story_checkpoints=[75, 250],
        repair_windows=[
            {"windowId": "repair-1", "startFrame": 40, "endFrameExclusive": 45}
        ],
        comparison_windows=[
            {"windowId": "compare-1", "startFrame": 260, "endFrameExclusive": 265}
        ],
    )
    assert first == second
    all_sparse = [
        frame
        for item in first["passes"]
        if item["kind"] == "sparse-overview"
        for frame in item["sampleFrames"]
    ]
    assert {0, 75, 99, 100, 250, 299}.issubset(all_sparse)
    risk_frames = [
        frame
        for item in first["passes"]
        if item["kind"] == "dense-window"
        for frame in item["sampleFrames"]
    ]
    assert len(risk_frames) == len(set(risk_frames))
    assert {item["kind"] for item in first["passes"]} >= {"repair", "comparison"}
    assert first["coverageHoles"] == []


def test_mandatory_boundary_that_cannot_fit_is_reported_as_hole() -> None:
    result = compile_review_coverage(
        duration_frames=20,
        sections=[{"sectionId": "all", "startFrame": 0, "endFrameExclusive": 20}],
        required_windows=[
            {
                "windowId": "join",
                "startFrame": 4,
                "endFrameExclusive": 8,
                "mandatory": True,
            }
        ],
        max_frames_per_pass=1,
    )
    assert result["coverageHoles"] == [
        {
            "windowId": "join",
            "mandatory": True,
            "reason": "boundary-endpoints-exceed-pass-budget",
        }
    ]


def test_seconds_convert_to_half_open_frames_with_real_fractional_fps() -> None:
    windows = _frame_windows(
        [
            {"start": 0.0, "end": 37.07, "reason": "whole-short"},
            {"start": 18.10, "end": 18.90, "reason": "caption-seam"},
        ],
        fps=Fraction(30000, 1001),
        duration_frames=1111,
    )
    assert windows[0]["startFrame"] == 0
    assert windows[0]["endFrameExclusive"] == 1111
    assert windows[1]["startFrame"] == 542
    assert windows[1]["endFrameExclusive"] == 567
    assert windows[0]["windowId"] != windows[1]["windowId"]
