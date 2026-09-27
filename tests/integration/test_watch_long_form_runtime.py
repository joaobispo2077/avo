from __future__ import annotations

import pytest

from avo.adapters.understand.watch_skill import execute_bounded_passes
from avo.timeline.vision_review import VisionReviewError


def _snapshot(context: int = 16_384):
    return {
        "servedModel": "qwen3.5-4b",
        "effectiveContextTokens": context,
        "identityHash": "a" * 64,
    }


def test_long_form_passes_reuse_one_index_and_persist_exact_frame_outcomes() -> None:
    calls = []

    def invoke(index, review_pass):
        calls.append((index, review_pass["passId"]))
        frames = review_pass["sampleFrames"]
        return {
            "status": "pass",
            "model": "qwen3.5-4b",
            "requestedFrames": frames,
            "decodedFrames": frames,
            "failedFrames": [],
            "observedFrames": frames,
            "findings": [],
            "rawArtifactRefs": [],
        }

    result = execute_bounded_passes(
        candidate_index="candidate-index-1",
        passes=[
            {
                "passId": "sparse",
                "sampleFrames": [0, 90, 180],
                "requiredFrames": [0, 180],
                "detail": "high",
                "transcriptHandleFrames": 30,
                "maxAttempts": 3,
            }
        ],
        capability_snapshot=_snapshot(),
        invoke=invoke,
    )
    assert calls == [("candidate-index-1", "sparse")]
    assert result["requestedSamples"] == [0, 90, 180]
    assert result["observedSamples"] == [0, 90, 180]


def test_model_mismatch_fails_closed_and_overflow_retry_is_bounded() -> None:
    with pytest.raises(VisionReviewError, match="model"):
        execute_bounded_passes(
            candidate_index="idx",
            passes=[
                {
                    "passId": "p",
                    "sampleFrames": [1],
                    "requiredFrames": [1],
                    "maxAttempts": 1,
                }
            ],
            capability_snapshot=_snapshot(),
            invoke=lambda *_: {
                "status": "pass",
                "model": "wrong",
                "requestedFrames": [1],
                "decodedFrames": [1],
                "failedFrames": [],
                "observedFrames": [1],
            },
        )

    attempts = []

    def overflow_then_pass(_index, review_pass):
        attempts.append(review_pass.copy())
        if len(attempts) == 1:
            return {"status": "overflow", "model": "qwen3.5-4b"}
        frames = review_pass["sampleFrames"]
        return {
            "status": "pass",
            "model": "qwen3.5-4b",
            "requestedFrames": frames,
            "decodedFrames": frames,
            "failedFrames": [],
            "observedFrames": frames,
        }

    result = execute_bounded_passes(
        candidate_index="idx",
        passes=[
            {
                "passId": "p",
                "sampleFrames": [1, 1, 2],
                "requiredFrames": [1, 2],
                "detail": "high",
                "transcriptHandleFrames": 30,
                "maxAttempts": 2,
            }
        ],
        capability_snapshot=_snapshot(8_192),
        invoke=overflow_then_pass,
    )
    assert len(attempts) == 2
    assert attempts[1]["sampleFrames"] == [1, 2]
    assert (
        result["passResults"][0]["retryHistory"][0]["reduction"] == "deduplicate-frames"
    )


@pytest.mark.parametrize("failure", ["malformed", "timeout", "oom"])
def test_retryable_runtime_failures_are_bounded_without_model_substitution(
    failure: str,
) -> None:
    attempts = []

    def always_fails(_index, review_pass):
        attempts.append(review_pass)
        return {"status": failure, "model": "qwen3.5-4b"}

    result = execute_bounded_passes(
        candidate_index="idx",
        passes=[
            {
                "passId": "dense-risk",
                "sampleFrames": [10, 11],
                "requiredFrames": [10, 11],
                "detail": "high",
                "transcriptHandleFrames": 20,
                "maxAttempts": 2,
            }
        ],
        capability_snapshot=_snapshot(8_192),
        invoke=always_fails,
    )
    assert len(attempts) == 2
    assert result["model"] == "qwen3.5-4b"
    assert result["passResults"][0]["status"] == "blocked"
    assert result["failedSamples"] == [10, 11]
