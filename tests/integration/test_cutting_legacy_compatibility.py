from copy import deepcopy

import pytest

from avo.timeline.cmap_service import CMapService
from avo.timeline.initial_cut import initial_cut_proof_request
from avo.timeline.lineage import LineageError
from cutting_fixtures import cutting_workspace, source_snapshot

pytestmark = pytest.mark.integration


def test_no_policy_preserves_original_graph_and_canonical_approval(tmp_path):
    workspace, source = cutting_workspace(tmp_path)
    service = CMapService(workspace)
    revision = service.author(source_snapshot(source), actor="fixture", reason="keep")
    before = deepcopy(service.store.load_index())
    request = initial_cut_proof_request(
        workspace,
        iteration_id="iteration-0001",
        output=workspace.raw_dir / "edit" / "proof.mp4",
        frame_rate={"num": 60, "den": 1},
    )
    assert service.store.load_index() == before
    assert request["sourceFingerprints"] == {
        "dialogue": revision["snapshot"]["sources"][0]["fingerprint"]["sha256"]
    }
    audio = request["audioGraph"]["operations"][0]["parameters"]
    assert audio["source"]["locator"] == str(source)
    assert audio["fadeInSamples"] == audio["fadeOutSamples"] == 1440
    assert request["audioGraph"]["nodes"][0]["channelMap"] == [0, 0]
    assert service.store.effective_approval() is None


def test_derived_media_cannot_become_canonical_raw(tmp_path):
    workspace, _ = cutting_workspace(tmp_path)
    derived = workspace.raw_dir / "edit" / "proof.wav"
    derived.write_bytes(b"previous proof")
    with pytest.raises(LineageError, match="derived"):
        CMapService(workspace).author(
            source_snapshot(derived), actor="fixture", reason="bad"
        )


def test_legacy_half_sample_rounding_remains_characterized(tmp_path):
    workspace, source = cutting_workspace(tmp_path)
    snapshot = source_snapshot(source)
    snapshot["segments"][0]["in"].update(ticks=1, timebase={"num": 1, "den": 96000})
    snapshot["segments"][0]["out"].update(
        ticks=95999, timebase={"num": 1, "den": 96000}
    )
    CMapService(workspace).author(snapshot, actor="fixture", reason="legacy rounding")
    request = initial_cut_proof_request(
        workspace,
        iteration_id="iteration-0001",
        output=tmp_path / "proof.mp4",
        frame_rate={"num": 60, "den": 1},
    )
    assert request["audioGraph"]["nodes"][0]["sourceRange"]["startSample"] == 0
