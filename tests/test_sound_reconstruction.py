"""Reconstruction names selected external sound originals, including pending edits."""

import pytest

from avo.timeline.contracts import file_fingerprint
from avo.timeline.reconstruction import ReconstructionError, _external_original_refs
from tests.test_sound_application import application


def test_selected_external_sound_is_a_fingerprinted_reconstruction_input(tmp_path):
    workspace, catalogue, service, _, request, _ = application(tmp_path)
    service.apply(request)
    source = (catalogue.roots["test"] / "whoosh.wav").resolve()
    fingerprint = file_fingerprint(source)
    originals = _external_original_refs(workspace)
    assert any(
        row["locator"] == str(source)
        and row["sha256"] == fingerprint["sha256"]
        and row["sizeBytes"] == fingerprint["sizeBytes"]
        for row in originals
    )
    assert file_fingerprint(source) == fingerprint


def test_pending_sound_before_first_owner_write_keeps_its_external_original(
    tmp_path, monkeypatch
):
    from avo.timeline.bmap_service import BMapService

    workspace, catalogue, service, _, request, _ = application(tmp_path)
    monkeypatch.setattr(
        BMapService,
        "author",
        lambda *a, **k: (_ for _ in ()).throw(OSError("interrupted first owner write")),
    )
    with pytest.raises(ValueError, match="recovery"):
        service.apply(request)
    assert workspace.store("tracks").load_index()["headRevisionId"] is None
    source = (catalogue.roots["test"] / "whoosh.wav").resolve()
    assert any(
        row["locator"] == str(source) for row in _external_original_refs(workspace)
    )


def test_changed_selected_external_sound_blocks_reconstruction(tmp_path):
    workspace, catalogue, service, _, request, _ = application(tmp_path)
    service.apply(request)
    (catalogue.roots["test"] / "whoosh.wav").write_bytes(b"changed external sound")
    with pytest.raises(ReconstructionError, match="[Ss]ound|[Ee]xternal"):
        _external_original_refs(workspace)


def test_project_local_staged_sound_is_kept_as_a_fingerprinted_bundle_file(
    footage_project_factory, monkeypatch
):
    from avo.timeline import sound_sources
    from avo.timeline.reconstruction import _required_files

    workspace = footage_project_factory()
    source = workspace.raw_dir / "assets" / "accent.wav"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"selected local fixture")
    fingerprint = file_fingerprint(source)
    monkeypatch.setattr(
        sound_sources,
        "reconstruction_sound_sources",
        lambda selected: [
            {
                "sourceId": "sound-source-fixture",
                "locator": str(source),
                "fingerprint": fingerprint,
            }
        ],
    )
    assert (
        _required_files(workspace.raw_dir, [], workspace=workspace)[source]
        == fingerprint["sha256"]
    )
