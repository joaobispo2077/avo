from __future__ import annotations

import pytest

from avo.timeline.review import (
    aggregate_watch_passes,
    normalize_watch_findings,
    render_human_review_package,
)
from avo.timeline.vision_review import (
    VisionReviewError,
    aggregate_finding_status,
    validate_vision_finding,
)


def _finding(**overrides):
    return {
        "schemaVersion": "1.0.0",
        "findingId": "finding-layout-1",
        "category": "layout",
        "severity": "warning",
        "confidence": 0.8,
        "programRange": {"startFrame": 10, "endFrameExclusive": 20},
        "evidenceRefs": [
            {"kind": "observed-frame", "artifactId": "frame-10", "sha256": "a" * 64}
        ],
        "criterionIds": ["layout-safe"],
        "obligationIds": [],
        "observed": "card overlaps face",
        "expected": "clear face",
        "whyItMatters": "obscures the speaker",
        "alternativeExplanations": [],
        "message": "card overlaps face",
        "suggestedAction": None,
        "requiresHuman": False,
        "status": "open",
        "humanDisposition": None,
        **overrides,
    }


def test_strict_finding_and_false_positive_human_lifecycle() -> None:
    assert validate_vision_finding(_finding())["findingId"] == "finding-layout-1"
    raw = _finding(
        evidenceRefs=[
            {"kind": "raw-response", "artifactId": "watch-response", "sha256": "d" * 64}
        ]
    )
    assert validate_vision_finding(raw)["evidenceRefs"][0]["kind"] == "raw-response"
    with pytest.raises(VisionReviewError, match="evidence"):
        validate_vision_finding(_finding(evidenceRefs=[]))
    dismissed = _finding(
        status="dismissed",
        humanDisposition={
            "decision": "dismissed",
            "actor": "editor",
            "rationale": "known reflection",
            "decidedAt": "2026-09-27T13:00:00Z",
            "candidateSha256": "b" * 64,
            "reviewContractHash": "c" * 64,
        },
    )
    assert (
        aggregate_finding_status([dismissed], required_passes_complete=True) == "pass"
    )


def test_aggregation_precedence_and_stale_contract_block() -> None:
    blocking = _finding(severity="blocking", status="corroborated")
    assert aggregate_finding_status([blocking], required_passes_complete=True) == "fail"
    uncertain = _finding(status="needs-human", requiresHuman=True)
    assert (
        aggregate_finding_status([uncertain], required_passes_complete=True)
        == "needs-human-judgment"
    )
    assert (
        aggregate_finding_status([], required_passes_complete=True, stale_contract=True)
        == "blocked"
    )


def test_overlap_deduplication_preserves_real_contradictions() -> None:
    duplicate = _finding()
    overlap = _finding(
        findingId="finding-layout-2",
        programRange={"startFrame": 15, "endFrameExclusive": 25},
        evidenceRefs=[
            {
                "kind": "pass-result",
                "artifactId": "pass-2",
                "sha256": "b" * 64,
            }
        ],
    )
    contradiction = _finding(
        findingId="finding-layout-3",
        observed="card does not overlap face",
        message="layout is clear",
        severity="info",
        status="corroborated",
    )
    normalized = normalize_watch_findings([duplicate, overlap, contradiction])
    assert len(normalized["findings"]) == 2
    assert len(normalized["findings"][0]["evidenceRefs"]) == 2
    assert normalized["contradictions"]

    aggregate = aggregate_watch_passes(
        [
            {"passId": "sparse", "status": "pass", "findings": [duplicate]},
            {
                "passId": "dense",
                "status": "pass",
                "findings": [overlap, contradiction],
            },
        ],
        required_pass_ids=["sparse", "dense"],
    )
    assert aggregate["kind"] == "watch"
    assert aggregate["status"] == "needs-human-judgment"


def test_human_package_orders_identities_coverage_findings_and_actions() -> None:
    markdown = render_human_review_package(
        {
            "candidateSha256": "a" * 64,
            "proofPlanHash": "b" * 64,
            "transcriptHash": "c" * 64,
            "modelIdentity": "qwen3.5-4b",
            "reviewContractHash": "d" * 64,
            "status": "needs-human-judgment",
            "coverage": {
                "samplingMode": "sparse-by-section+dense-risk",
                "requestedSamples": 20,
                "observedSamples": 17,
                "failedSamples": 1,
                "uninspectedRanges": [{"startFrame": 500, "endFrameExclusive": 550}],
                "coverageHoles": [{"windowId": "risk-2", "reason": "decode-failed"}],
            },
            "regressions": [{"obligationId": "speech-1", "status": "unresolved"}],
            "findings": [
                {
                    "findingId": "later",
                    "sectionId": "body",
                    "category": "pacing",
                    "programRange": {"startFrame": 200, "endFrameExclusive": 220},
                    "message": "card rushed",
                    "suggestedAction": "hold card",
                },
                {
                    "findingId": "earlier",
                    "sectionId": "teaser",
                    "category": "layout",
                    "programRange": {"startFrame": 10, "endFrameExclusive": 20},
                    "message": "title clipped",
                    "suggestedAction": None,
                },
            ],
            "contradictions": [{"findingIds": ["earlier", "layout-pass"]}],
            "humanQuestions": ["Is the reflection a face?"],
        }
    )
    assert markdown.index("## Exact identities") < markdown.index(
        "## Truthful coverage"
    )
    assert markdown.index("earlier") < markdown.index("later")
    assert "[later] hold card" in markdown
    assert "Is the reflection a face?" in markdown
