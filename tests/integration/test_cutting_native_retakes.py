"""Encoded whole-retake continuity with explicitly supplied synthetic labels."""

import shutil

import pytest
from test_cutting_native_preview import native_workspace
from test_cutting_retakes_service import (
    InjectedCompleteTakeEvidence,
    RepeatedTakeAnalysis,
)

from avo.adapters.media.cutting_preview import CuttingPreviewAdapter
from avo.timeline.cutting_policy import resolve_cutting_policy
from avo.timeline.cutting_service import CuttingService


class SuppliedCompleteRetakes(RepeatedTakeAnalysis):
    def analyze(self, source, **request):
        result = super().analyze(source, **request)
        result["words"] = [
            {"text": "Uma", "start": 0.25, "end": 0.4, "eligibleEdge": True},
            {"text": "ideia.", "start": 0.4, "end": 0.65, "eligibleEdge": True},
            {"text": "Uma", "start": 2.25, "end": 2.4, "eligibleEdge": True},
            {"text": "ideia.", "start": 2.4, "end": 2.65, "eligibleEdge": True},
        ]
        return result


class SuppliedCompleteBounds(InjectedCompleteTakeEvidence):
    def analyze_group(self, source, group, analysis, **request):
        result = super().analyze_group(source, group, analysis, **request)
        for index, attempt in enumerate(result["verifiedAttempts"]):
            attempt["sourceRange"].update(
                startTicks=7200 if index == 0 else 100800,
                endTicksExclusive=36000 if index == 0 else 134400,
            )
        return result


@pytest.mark.integration
@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="FFmpeg required")
def test_encoded_retakes_keep_stronger_earlier_unit_without_later_residue(tmp_path):
    workspace, original = native_workspace(tmp_path, noise=False)
    native = CuttingPreviewAdapter(workspace)
    service = CuttingService(
        workspace,
        policy=resolve_cutting_policy(
            project_settings={"enabled": True, "family": "analysis-review"}
        ),
        analysis_port=SuppliedCompleteRetakes(),
        retake_port=SuppliedCompleteBounds(),
        preview_port=native,
        verification_port=native,
    )
    proposal_ref = service.analyze()["proposalRef"]
    proposal = service.status(proposal_ref)["proposal"]
    repair = next(
        item for item in proposal["occurrences"] if item["disposition"] == "replace"
    )
    assert repair["selectedAlternativeId"] == repair["alternatives"][0]["takeId"]
    assert len(proposal["edits"]) == 1
    assert (
        proposal["edits"][0]["removeRange"] == repair["alternatives"][1]["sourceRange"]
    )
    rendered = service.preview(proposal_ref)
    verified = service.store.load_document(rendered["verificationRef"])["payload"]
    assert rendered["status"] == "pass", verified["checks"]
    assert repair["occurrenceId"] in verified["occurrenceCoverage"]
    assert all(check["status"] == "pass" for check in verified["checks"])
    assert workspace.store("cmap").head_hash() == original["contentHash"]
    service.decide(
        proposal_ref,
        {
            "previewRef": rendered["verificationRef"],
            "decisions": [
                {
                    "occurrenceId": repair["occurrenceId"],
                    "disposition": "replace",
                    "reason": "synthetic fixture choice",
                }
            ],
        },
    )
    applied = service.apply(proposal_ref)
    assert applied["status"] == "applied"
    intervals = applied["revision"]["snapshot"]["segments"]
    assert intervals[0]["in"]["ticks"] == 0
    assert intervals[0]["out"]["ticks"] == 100800
    assert intervals[1]["in"]["ticks"] == 134400
    assert intervals[1]["out"]["ticks"] == 144000
