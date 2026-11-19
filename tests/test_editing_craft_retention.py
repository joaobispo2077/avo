"""Verify the shared reconstruction and cleanup inventory on selected craft data."""

import pytest

from avo.project_inventory import _fallback_reconstruction_metadata
from avo.timeline.reconstruction import ReconstructionError, _required_files
from tests.integration.test_word_sound_anchor_flow import word_application


def _closures(workspace):
    return (
        set(_required_files(workspace.raw_dir, [], workspace=workspace)),
        set(
            _fallback_reconstruction_metadata(
                workspace.raw_dir, workspace.timeline_dir, workspace
            )
        ),
    )


def test_selected_word_sound_dependencies_are_exact_for_reconstruction_and_cleanup(
    tmp_path, monkeypatch
):
    workspace, service, request, shown, analysis, _ = word_application(
        tmp_path, monkeypatch
    )
    applied = service.apply(request)
    unselected = (
        workspace.timeline_dir / "cutting/preparation-results" / ("f" * 64 + ".json")
    )
    unselected.parent.mkdir(exist_ok=True)
    unselected.write_text('{"unfinished": true}', encoding="utf-8")
    generation = (
        service.catalogue.directory
        / "generations"
        / (request["expectedGeneration"] + ".json")
    )
    selected = {
        workspace.raw_dir / shown["proposalRef"]["path"],
        workspace.raw_dir / applied["receiptRef"]["path"],
        analysis,
        generation,
    }
    for closure in _closures(workspace):
        assert selected <= closure
        assert unselected not in closure
    assert unselected.is_file()

    analysis.unlink()
    for payload in (None, b"{}"):
        if payload is not None:
            analysis.write_bytes(payload)
        with pytest.raises(ReconstructionError, match="evidence"):
            _required_files(workspace.raw_dir, [], workspace=workspace)
        with pytest.raises((ValueError, RuntimeError), match="evidence"):
            _fallback_reconstruction_metadata(
                workspace.raw_dir, workspace.timeline_dir, workspace
            )
