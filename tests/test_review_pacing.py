from __future__ import annotations

from avo.adapters.understand.watch_policy import (
    build_watch_prompt,
    resolve_watch_policy,
)
from avo.timeline.vision_review import review_section_pacing


def test_hybrid_pacing_respects_section_purpose_and_protected_pause() -> None:
    sections = [
        {
            "sectionId": "teaser",
            "formatRole": "dense-teaser",
            "purpose": "preview",
            "targetDensity": 5,
            "protectedPauses": [],
        },
        {
            "sectionId": "conversation",
            "formatRole": "talking-head",
            "purpose": "connect",
            "targetDensity": 2,
            "protectedPauses": [{"startFrame": 100, "endFrameExclusive": 130}],
        },
        {
            "sectionId": "gameplay",
            "formatRole": "gameplay-explanation",
            "purpose": "teach",
            "targetDensity": 3,
            "protectedPauses": [],
        },
        {
            "sectionId": "lifestyle",
            "formatRole": "lifestyle-detour",
            "purpose": "breathe",
            "targetDensity": 1,
            "protectedPauses": [],
        },
        {
            "sectionId": "payoff",
            "formatRole": "gameplay",
            "purpose": "payoff",
            "targetDensity": 2,
            "protectedPauses": [],
        },
        {
            "sectionId": "conclusion",
            "formatRole": "reflective-conclusion",
            "purpose": "reflect",
            "targetDensity": 1,
            "protectedPauses": [],
        },
    ]
    metrics = {
        "teaser": {"visualChangesPerMinute": 30},
        "conversation": {
            "silenceRanges": [{"startFrame": 105, "endFrameExclusive": 120}]
        },
        "gameplay": {"repeatedContentSeconds": 9},
        "lifestyle": {"visualChangesPerMinute": 3},
        "payoff": {"cardDurationSeconds": 1, "requiredReadingSeconds": 3},
        "conclusion": {"visualChangesPerMinute": 2},
    }
    findings = review_section_pacing(sections, metrics)
    codes = {(item["sectionId"], item["code"]) for item in findings}
    assert ("gameplay", "repetition") in codes
    assert ("payoff", "rushed-comprehension") in codes
    assert ("conversation", "dead-air") not in codes
    assert all("formatRole" in item and "purpose" in item for item in findings)


def test_watch_policy_carries_section_diagnosis_and_deterministic_metrics() -> None:
    section = {
        "sectionId": "teaser",
        "formatRole": "dense-teaser",
        "purpose": "preview",
        "payoff": "show the result",
        "targetDensity": 5,
        "protectedPauses": [],
        "riskClasses": ["promise"],
    }
    policy = resolve_watch_policy(
        scopes=[
            (
                "project",
                {
                    "sections": [section],
                    "pacingMetrics": {"teaser": {"visualChangesPerMinute": 30}},
                },
            )
        ]
    )
    assert policy.context["sections"] == [section]
    assert policy.context["pacingMetrics"]["teaser"]["visualChangesPerMinute"] == 30
    prompt = build_watch_prompt(
        checkpoint="cut-proof",
        scope="full",
        windows=[],
        context=policy.context,
    )
    assert "format=dense-teaser" in prompt
    assert "Deterministic pacing metrics for teaser" in prompt
