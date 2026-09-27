from __future__ import annotations

import pytest

from avo.timeline.vision_review import VisionReviewError, schedule_review_resources


def test_cpu_transcription_can_share_with_one_7gb_gpu_watch_but_gpu_jobs_serialize() -> (
    None
):
    schedule = schedule_review_resources(
        [
            {"jobId": "transcribe", "device": "cpu", "ramBytes": 2 * 1024**3},
            {
                "jobId": "watch",
                "device": "gpu",
                "vramBytes": 7 * 1024**3,
                "model": "qwen3.5-4b",
            },
            {
                "jobId": "other-gpu",
                "device": "gpu",
                "vramBytes": 2 * 1024**3,
                "model": "qwen3.5-4b",
            },
        ],
        vram_ceiling_bytes=7 * 1024**3,
        allowed_co_residency=["cpu-transcription"],
        concurrency=1,
        operator_managed_lifecycle=True,
    )
    assert schedule["batches"][0] == ["transcribe", "watch"]
    assert schedule["batches"][1] == ["other-gpu"]
    assert schedule["lifecycleActions"] == []


def test_scheduler_rejects_second_model_or_vram_overflow() -> None:
    with pytest.raises(VisionReviewError):
        schedule_review_resources(
            [
                {
                    "jobId": "watch",
                    "device": "gpu",
                    "vramBytes": 8 * 1024**3,
                    "model": "qwen3.5-4b",
                }
            ],
            vram_ceiling_bytes=7 * 1024**3,
            allowed_co_residency=[],
            concurrency=1,
            operator_managed_lifecycle=True,
        )
    with pytest.raises(VisionReviewError, match="second model"):
        schedule_review_resources(
            [
                {
                    "jobId": "watch-a",
                    "device": "gpu",
                    "vramBytes": 3 * 1024**3,
                    "model": "qwen3.5-4b",
                },
                {
                    "jobId": "watch-b",
                    "device": "gpu",
                    "vramBytes": 3 * 1024**3,
                    "model": "other",
                },
            ],
            vram_ceiling_bytes=7 * 1024**3,
            allowed_co_residency=[],
            concurrency=1,
            operator_managed_lifecycle=True,
        )
