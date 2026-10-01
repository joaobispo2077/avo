from __future__ import annotations

import pytest

from avo.timeline.vision_review import VisionReviewError, compile_context_budget


@pytest.mark.parametrize("context", [8_192, 16_384, 32_768])
def test_budget_accounts_for_every_text_reserve_and_visual_component(
    context: int,
) -> None:
    budget = compile_context_budget(
        effective_context_tokens=context,
        instruction_tokens=600,
        rubric_tokens=500,
        transcript_tokens=800,
        carry_forward_tokens=200,
        response_reserve_tokens=1_000,
        safety_margin_tokens=500,
        visual_tokens_per_frame=700,
        required_frames=40,
        backend_image_limit=20,
        safety_frame_ceiling=18,
    )
    assert budget["maxFrames"] <= 18
    assert budget["totalTokens"] <= context
    assert budget["visualTokens"] == budget["maxFrames"] * 700
    assert budget["estimator"] == {"name": "avo-visual-budget", "version": "1"}
    assert budget["imagePolicy"]["detail"] == "low"


def test_budget_fails_when_nonvisual_reserves_exhaust_context() -> None:
    with pytest.raises(VisionReviewError, match="non-visual"):
        compile_context_budget(
            effective_context_tokens=2_000,
            instruction_tokens=600,
            rubric_tokens=500,
            transcript_tokens=500,
            carry_forward_tokens=200,
            response_reserve_tokens=200,
            safety_margin_tokens=100,
            visual_tokens_per_frame=100,
            required_frames=1,
        )
