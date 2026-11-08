"""Reference metadata cannot acquire finishing or approval authority."""

from copy import deepcopy

import pytest

from avo.timeline.bmap_service import BMapService
from avo.timeline.cmap_service import CMapService
from avo.timeline.lineage import LineageError
from tests.test_timeline_import_evidence import _activate, _prepare_evidence


def test_unimplemented_finishing_proposal_is_blocked_before_activation(
    tmp_path, monkeypatch
):
    service, ready = _prepare_evidence(tmp_path)
    build = service._proposal

    def unsupported(session, checks):
        proposal = build(session, checks)
        proposal["provisionalFinishing"] = [
            {"kind": "captions", "text": "Exported note is not implemented captions"}
        ]
        return proposal

    monkeypatch.setattr(service, "_proposal", unsupported)
    result = service.validate(ready["importId"])
    assert result["status"] == "blocked"
    assert any(
        row["code"] == "OTIO_TREATMENT_UNSUPPORTED" for row in result["findings"]
    )
    assert service.head_hash() == "empty"


def test_finishing_uses_exact_actually_selected_cut_and_never_old_import_approval(
    tmp_path,
):
    service, ready = _prepare_evidence(tmp_path)
    first = _activate(service, ready)
    store = service.workspace.store("cmap")
    with pytest.raises(LineageError, match="approved CMap"):
        BMapService(service.workspace).current_basis()
    # Deliberately synthetic low-level fixture approval, not creator review.
    store.approve(
        first["revisionId"], revision_hash=first["contentHash"], candidate_hash="f" * 64
    )
    basis, _, candidate = BMapService(service.workspace).current_basis()
    assert basis["sha256"] == first["contentHash"] and candidate == "f" * 64
    snapshot = deepcopy(first["snapshot"])
    snapshot["segments"][0]["out"]["ticks"] -= 1
    CMapService(service.workspace).author(
        snapshot,
        actor="fixture",
        reason="Requested trim",
        expected_head_hash=first["contentHash"],
    )
    with pytest.raises(LineageError, match="approved CMap"):
        BMapService(service.workspace).current_basis()
