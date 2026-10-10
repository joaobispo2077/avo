"""Injected evidence tests service selection, not real speech or listening QC."""

from copy import deepcopy

from avo.timeline.contracts import content_hash
from test_cutting_service import CheckedPreview, fixture_service


class RepeatedTakeAnalysis:
    def analyze(self, source, **request):
        return {
            "sourceRef": {
                "locator": str(source),
                "sha256": request["fingerprint"]["sha256"],
            },
            "syncRef": request["sync_ref"],
            "routing": request["selection"],
            "preprocessing": {"sourceRange": request["source_range"]},
            "status": "pass",
            "coverage": {"observed": True},
            "pauseCandidates": [],
            "words": [
                {"text": "Uma", "start": 0.1, "end": 0.2},
                {"text": "ideia.", "start": 0.2, "end": 0.3},
                {"text": "Uma", "start": 0.5, "end": 0.6},
                {"text": "ideia.", "start": 0.6, "end": 0.7},
            ],
        }


class InjectedCompleteTakeEvidence:
    """Synthetic complete-unit observations; no production inspector is fabricated."""

    def __init__(self, *, intentional=False):
        self.intentional = intentional

    def analyze_group(self, source, group, analysis, **request):
        attempts = deepcopy(group["attempts"])
        for attempt in attempts:
            attempt.update(complete=True, intentionalRepetition=self.intentional)
        return {
            "sourceRef": analysis["sourceRef"],
            "syncRef": request["sync_ref"],
            "routing": analysis["routing"],
            "groupHash": content_hash(group),
            "status": "corroborated",
            "verifiedAttempts": attempts,
            "semanticEquivalence": True,
            "restartConfirmed": True,
            "evidenceRefs": [request["analysis_ref"]],
            "perTake": {
                attempt["takeId"]: {
                    "acousticComplete": True,
                    "intelligible": True,
                    "intelligibility": 0.95 if index == 0 else 0.7,
                    "cadence": 0.9,
                    "visualUsability": 0.9,
                }
                for index, attempt in enumerate(attempts)
            },
        }


def service_with_takes(tmp_path, *, intentional=False):
    preview = CheckedPreview(tmp_path / "injected-candidate.json")
    return fixture_service(
        tmp_path,
        analysis_port=RepeatedTakeAnalysis(),
        retake_port=InjectedCompleteTakeEvidence(intentional=intentional),
        preview_port=preview,
        verification_port=preview,
    )


def test_stronger_earlier_take_proposes_whole_later_removal_without_authoring(tmp_path):
    service, revision = service_with_takes(tmp_path)
    ref = service.analyze()["proposalRef"]
    proposal = service.status(ref)["proposal"]
    repair = next(
        item for item in proposal["occurrences"] if item["disposition"] == "replace"
    )
    assert repair["selectedAlternativeId"] == repair["alternatives"][0]["takeId"]
    assert (
        proposal["edits"][0]["removeRange"] == repair["alternatives"][1]["sourceRange"]
    )
    assert service.apply(ref)["status"] == "needs-review"
    assert service.workspace.store("cmap").head_hash() == revision["contentHash"]


def test_intentional_repetition_remains_unchanged(tmp_path):
    service, revision = service_with_takes(tmp_path, intentional=True)
    ref = service.analyze()["proposalRef"]
    assert service.status(ref)["proposal"]["edits"] == []
    assert service.apply(ref)["status"] == "no-op"
    assert service.workspace.store("cmap").head_hash() == revision["contentHash"]


def test_injected_verified_retake_requires_exact_human_preview_choice(tmp_path):
    service, revision = service_with_takes(tmp_path)
    ref = service.analyze()["proposalRef"]
    proposal = service.status(ref)["proposal"]
    repair = next(
        item for item in proposal["occurrences"] if item["disposition"] == "replace"
    )
    preview = service.preview(ref)
    assert service.workspace.store("cmap").head_hash() == revision["contentHash"]
    service.decide(
        ref,
        {
            "previewRef": preview["verificationRef"],
            "decisions": [
                {
                    "occurrenceId": repair["occurrenceId"],
                    "disposition": "replace",
                    "reason": "injected lifecycle choice",
                }
            ],
        },
    )
    assert service.apply(ref)["status"] == "applied"
