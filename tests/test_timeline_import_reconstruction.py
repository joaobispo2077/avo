"""Reconstruction retains referenced handoffs and records external originals."""

import json

import pytest

from avo.adapters.media.otio_reader import read_otio
from avo.timeline.contracts import content_hash, file_fingerprint
from avo.timeline.import_retention import retained_import_paths
from avo.timeline.import_service import TimelineImportService
from avo.timeline.reconstruction import (
    ReconstructionError,
    _external_original,
    build_reconstruction_bundle,
    verify_reconstruction_bundle,
)
from tests.test_timeline_import_service import _approve_fixture_sync, _probe, _trial
from tests.test_timeline_import_service import import_project as _project


@pytest.mark.parametrize("relative", [False, True])
def test_legacy_fingerprint_locator_retains_and_revalidates_external_original(
    tmp_path, relative
):
    raw = tmp_path / "footage"
    raw.mkdir()
    original = tmp_path / "original.mov"
    original.write_bytes(b"legacy source bytes")
    source = {"sourceId": "legacy", "fingerprint": file_fingerprint(original)}
    if relative:
        source["fingerprint"]["locator"] = "../original.mov"
    ref = _external_original(raw, source)
    assert ref["locator"] == str(original.resolve())
    assert ref["sha256"] == source["fingerprint"]["sha256"]
    original.write_bytes(b"changed original bytes")
    with pytest.raises(ReconstructionError, match="fingerprint changed"):
        _external_original(raw, source)


def _imported(tmp_path, *, external=False):
    project, provider, original = _project.__wrapped__(tmp_path)
    if external:
        outside = tmp_path / "outside" / "original.mov"
        outside.parent.mkdir()
        original.replace(outside)
        original = outside
    service = TimelineImportService(
        project, provider_root=provider, reader=read_otio, probe=_probe
    )
    prepared = _trial(service, original)
    waiting = service.validate(prepared["importId"])
    _approve_fixture_sync(service, waiting["proposal"])
    ready = service.validate(prepared["importId"])
    service.activate(
        ready["importId"],
        validation_hash=ready["validationHash"],
        expected_head="empty",
        actor="fixture",
        reason="Synthetic imported draft",
    )
    raw = service.workspace.raw_dir
    basename = "import-master-v001"
    master = raw / "edit/masters" / (basename + ".mp4")
    master.parent.mkdir(parents=True)
    master.write_bytes(b"synthetic master, no audiovisual fidelity claim")
    transcript = raw / "edit/transcripts" / (basename + ".json")
    transcript.parent.mkdir(parents=True)
    transcript.write_text(
        json.dumps(
            {"source": {"sha256": file_fingerprint(master)["sha256"]}, "words": []}
        )
    )
    transcript.with_suffix(".txt").write_text("Fixture transcript")
    (transcript.parent / "initial.json").write_text("{}")
    return service, basename, original


def test_bundle_covers_exact_historical_import_evidence_and_detects_removed_coverage(
    tmp_path,
):
    service, basename, _ = _imported(tmp_path)
    workspace = service.workspace
    bundle = build_reconstruction_bundle(
        workspace, master_basename=basename, actor="fixture"
    )
    paths = {workspace.raw_dir / row["path"] for row in bundle["files"]}
    expected = set(retained_import_paths(workspace))
    assert expected <= paths
    omitted = next(path for path in expected if path.name == "source.otio")
    bundle["files"] = [
        row for row in bundle["files"] if workspace.raw_dir / row["path"] != omitted
    ]
    bundle["bundleSha256"] = content_hash(
        {key: value for key, value in bundle.items() if key != "bundleSha256"}
    )
    path = workspace.timeline_dir / "reconstruction-bundle.json"
    path.write_text(json.dumps(bundle))
    with pytest.raises(ReconstructionError, match="coverage"):
        verify_reconstruction_bundle(workspace.raw_dir)


def test_external_originals_are_verified_references_not_local_bundle_copies(tmp_path):
    service, basename, original = _imported(tmp_path, external=True)
    workspace = service.workspace
    bundle = build_reconstruction_bundle(
        workspace, master_basename=basename, actor="fixture"
    )
    assert bundle["rawSources"] == []
    assert bundle["externalSources"][0]["locator"] == str(original.resolve())
    assert all(not row["path"].startswith("..") for row in bundle["files"])
    verify_reconstruction_bundle(workspace.raw_dir)
    original.write_bytes(b"changed outside original")
    with pytest.raises(ReconstructionError, match="external|original"):
        verify_reconstruction_bundle(workspace.raw_dir)
