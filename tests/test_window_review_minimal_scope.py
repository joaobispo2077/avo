import pytest

from avo.adapters.understand.cutting_context import CuttingContextAdapter
from avo.adapters.understand.watch_policy import build_watch_prompt
from avo.adapters.understand.watch_skill import _native_pass_instruction
from avo.timeline.cutting_policy import resolve_cutting_policy
from avo.timeline.cutting_service import CuttingService
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


def contextual_call_count(duration_us, sections=None):
    service = object.__new__(CuttingService)
    service.policy = resolve_cutting_policy(
        project_settings={
            "enabled": True,
            "family": "analysis-review",
            "intensity": "conservative",
            **({"sections": sections} if sections else {}),
        }
    )
    calls = []

    class Context:
        def analyze_pause(self, *args, **kwargs):
            calls.append(1)
            return {}

    service.context_port = Context()
    analysis = {
        "sourceRef": {"locator": "original", "sha256": "a" * 64},
        "routing": {"streamIndex": 2},
        "pauseCandidates": [
            {
                "sourceRange": {
                    "sourceId": "s",
                    "startTicks": 0,
                    "endTicksExclusive": duration_us,
                    "timebase": {"num": 1, "den": 1000000},
                },
                "evidence": {},
            }
        ],
    }
    result = service._contextual_analysis({}, analysis, {})
    assert result == analysis
    return len(calls)


def test_policy_retained_pause_needs_no_visual_context():
    assert contextual_call_count(100000) == 0
    assert contextual_call_count(600000) == 0


def test_potential_cut_still_requires_visual_context():
    assert contextual_call_count(2000000) == 1


def test_section_policy_keeps_existing_context_path():
    assert contextual_call_count(600000, {"dense": {"intensity": "dynamic"}}) == 1


def test_source_context_can_report_observations_without_changing_normal_review():
    assert "findings must be an empty list" in _native_pass_instruction("pass-1")
    instruction = _native_pass_instruction("pass-1", source_context=True)
    assert "including on pass" in instruction
    assert "preserve unknown whenever uncertain" in instruction
    assert "findings must be an empty list" not in instruction


def test_pause_prompt_includes_bounded_quoted_transcript(tmp_path):
    captured = []

    class Watch:
        def review(self, source, **request):
            captured.append(request)
            return {}

    adapter = CuttingContextAdapter(
        tmp_path, {"purpose": "Preserve natural pauses"}, watch=Watch()
    )
    adapter._review(
        tmp_path / "original.mkv",
        {
            "pauseId": "pause-1",
            "sourceRange": {
                "sourceId": "original",
                "startTicks": 100000,
                "endTicksExclusive": 103000,
                "timebase": {"num": 1, "den": 1000},
            },
        },
        {
            "words": [
                {"text": "before", "start": 99.0, "end": 100.0},
                {"text": "after", "start": 104.0, "end": 105.0},
                {"text": "outside", "start": 500.0, "end": 501.0},
            ]
        },
    )
    request = captured[0]
    prompt = build_watch_prompt(
        checkpoint="cut-proof",
        scope=request["scope"],
        windows=request["windows"],
        context=request["context"],
    )
    assert request["context"]["sourceContextObservation"] is True
    assert "before" in prompt and "after" in prompt
    assert "outside" not in prompt
    assert "pauseId=pause-1; decision=unknown" in prompt
