"""Shared service lifecycle under resume, stale media and bounded retries."""

import pytest

from avo.timeline.cutting_service import CuttingService
from avo.timeline.lineage import LineageError
from test_cutting_service import CheckedPreview, ObservedAnalysis, fixture_service


def test_third_selection_attempt_is_rejected_across_resume(tmp_path):
    preview = CheckedPreview(tmp_path / "candidate.json")
    service, _ = fixture_service(
        tmp_path,
        analysis_port=ObservedAnalysis(),
        preview_port=preview,
        verification_port=preview,
    )
    proposal = service.analyze()["proposalRef"]
    service.preview(proposal)
    preview.path.write_text("invalidate prior rendered bytes", encoding="utf-8")
    resumed = CuttingService(
        service.workspace,
        policy=service.policy,
        preview_port=preview,
        verification_port=preview,
    )
    resumed.preview(proposal)
    preview.path.write_text("invalidate second rendered bytes", encoding="utf-8")
    result = resumed.preview(proposal)
    assert result["status"] == "needs-human"
    assert preview.calls == 2


def test_failed_render_consumes_reservation_and_does_not_mutate_cmap(tmp_path):
    class FailedPreview:
        def render(self, *args, **kwargs):
            raise RuntimeError("decoder failure after reservation")

    service, revision = fixture_service(
        tmp_path, analysis_port=ObservedAnalysis(), preview_port=FailedPreview()
    )
    proposal = service.analyze()["proposalRef"]
    identity = service.status(proposal)["proposal"]["occurrences"][0]["occurrenceId"]
    with pytest.raises(RuntimeError, match="decoder"):
        service.preview(proposal)
    assert len(service.store.reservations(identity)) == 1
    assert service.workspace.store("cmap").head_hash() == revision["contentHash"]


def test_changed_original_invalidates_old_proposal(tmp_path):
    service, _ = fixture_service(tmp_path)
    proposal = service.analyze()["proposalRef"]
    source = service.workspace.raw_dir / "original.wav"
    source.write_bytes(source.read_bytes() + b"changed")
    with pytest.raises(LineageError, match="fingerprint"):
        service.preview(proposal)
