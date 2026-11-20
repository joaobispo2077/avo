"""Declared evidence exercises omission protection, not actual ASR or creator QC."""

import pytest

from tests.integration.test_cutting_retakes_service import (
    RepeatedTakeAnalysis,
    service_with_takes,
)


class CoverageAnalysis(RepeatedTakeAnalysis):
    def __init__(self, *, uncertain=False, noise_after=False):
        self.uncertain = uncertain
        self.noise_after = noise_after

    def analyze(self, source, **request):
        value = super().analyze(source, **request)
        value["coverage"].update(start=0, end=1)
        value["alignment"] = {"status": "pass", "characters": []}
        value["tools"] = [{"modelId": "declared-completeness-fixture"}]
        for word in value["words"]:
            word["alignmentStatus"] = "aligned"
        value["vad"] = [{"start": 0.1, "end": 0.3}, {"start": 0.5, "end": 0.7}]
        if self.uncertain:
            value["words"][-1]["alignmentStatus"] = "unsupported"
        if self.noise_after:
            value["vad"].append({"start": 0.8, "end": 0.9})
        return value


class UnavailableAnalysis(RepeatedTakeAnalysis):
    def analyze(self, source, **request):
        value = super().analyze(source, **request)
        value.pop("vad")
        return value


def test_incomplete_word_coverage_protects_an_otherwise_selected_rejected_take(
    tmp_path,
):
    service, original = service_with_takes(tmp_path)
    service.analysis_port = CoverageAnalysis(uncertain=True)
    result = service.analyze()
    proposal = service.status(result["proposalRef"])["proposal"]
    assert result["coverage"]["speech"][0]["status"] == "needs-review"
    assert proposal["edits"] == []
    assert any(
        any(
            identity.startswith("speech-coverage-")
            for identity in item.get("protections", [])
        )
        for item in proposal["occurrences"]
    )
    assert service.workspace.store("cmap").head_hash() == original["contentHash"]


def test_unavailable_completeness_cannot_justify_text_only_retake_rejection(tmp_path):
    service, original = service_with_takes(tmp_path)
    service.analysis_port = UnavailableAnalysis()
    result = service.analyze()
    assert result["coverage"]["speech"][0]["status"] == "unavailable"
    assert service.status(result["proposalRef"])["proposal"]["edits"] == []
    assert service.workspace.store("cmap").head_hash() == original["contentHash"]


@pytest.mark.parametrize("noise_after", [False, True])
def test_available_coverage_and_separate_uncertainty_preserve_an_unaffected_take_proposal(
    tmp_path, noise_after
):
    service, original = service_with_takes(tmp_path)
    service.analysis_port = CoverageAnalysis(noise_after=noise_after)
    result = service.analyze()
    proposal = service.status(result["proposalRef"])["proposal"]
    assert len(proposal["edits"]) == 1
    assert proposal["edits"][0]["removeRange"]["startTicks"] == 24000
    assert proposal["edits"][0]["removeRange"]["endTicksExclusive"] == 33600
    assert service.workspace.store("cmap").head_hash() == original["contentHash"]
