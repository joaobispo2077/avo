"""Native imported edits remain isolated by provider through revision and restart."""

from copy import deepcopy

import pytest
from tests.integration.test_otio_import_runtime import _native_trial, _render_import

from avo.timeline.bmap_service import BMapService
from avo.timeline.cmap_service import CMapService
from avo.timeline.contracts import file_fingerprint
from avo.timeline.import_service import TimelineImportService
from avo.timeline.lineage import LineageError
from avo.timeline.pipeline import TimelinePipeline
from avo.timeline.tracks import TracksService
from avo.timeline.workspace import TimelineWorkspace
from avo.video_context import VideoContext, merge_config

pytestmark = pytest.mark.integration


def _files(root):
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


def _bind_engine(pipeline):
    pipeline.run_store.bind_motion_selection(
        {
            "engine": "code-drawn",
            "source": "invocation",
            "advanced": True,
            "resolutionHash": "c" * 64,
            "maskedChoices": [],
        }
    )


def test_native_two_provider_scoped_edit_restart_and_finishing_gates(
    tmp_path, monkeypatch
):
    trials = []
    for name in ("channel-a", "channel-b"):
        root = tmp_path / name
        root.mkdir()
        trials.append(_native_trial(root, provider_name=name))
    service, source = trials[0]
    other, other_source = trials[1]
    pipeline = TimelinePipeline(service.workspace)
    _bind_engine(pipeline)
    before_other = _files(other.workspace.raw_dir)
    originals = [file_fingerprint(path)["sha256"] for path in (source, other_source)]
    before = service.workspace.store("cmap").load_index()
    initial = service.workspace.store("cmap").revision(before["headRevisionId"])
    revised = deepcopy(initial["snapshot"])
    revised["segments"][0]["in"]["ticks"] += 1
    authored = CMapService(service.workspace).author(
        revised,
        actor="fixture",
        reason="Requested one-frame trim",
        expected_head_hash=initial["contentHash"],
    )
    assert authored["snapshot"]["segments"][1] == initial["snapshot"]["segments"][1]
    assert authored["snapshot"]["importOutput"] == initial["snapshot"]["importOutput"]
    pipeline.enter_blocked(reason="Await creator review", blockers=[])
    restarted = TimelinePipeline(
        TimelineWorkspace.from_project(service.workspace.project_path)
    )
    restarted.resume(
        actor="fixture",
        reason="Resume existing draft",
        recovery_event="review-available",
    )
    shown = restarted.status()
    assert shown["timelineImport"]["provider"] == "channel-a"
    assert shown["timelineImport"]["compatibilityState"] == "verified-activation"
    assert shown["timelineImport"]["pendingFinishing"] == []
    assert (
        restarted.run_store.load()["executionChoices"]["motion"]["engine"]
        == "code-drawn"
    )
    assert service.workspace.store("cmap").effective_approval() is None
    with pytest.raises(LineageError, match="approved CMap"):
        BMapService(service.workspace).current_basis()
    with pytest.raises((ValueError, RuntimeError)):
        TracksService(service.workspace).author(
            {}, actor="fixture", reason="Cannot finish unapproved import"
        )
    output = _render_import(service, "provider-a-trim")
    assert output.is_file()
    assert _files(other.workspace.raw_dir) == before_other
    assert originals == [
        file_fingerprint(path)["sha256"] for path in (source, other_source)
    ]

    # Project transcription settings keep their normal precedence. They do not
    # change the recorded imported canvas, audio policy or chosen engine.
    monkeypatch.setattr(
        "avo.video_context.load_config",
        lambda root: {"transcription": {"language": "de"}},
    )
    for imported, _ in trials:
        provider = imported.provider
        context = VideoContext(
            provider,
            imported.workspace.video_id,
            imported.workspace.raw_dir,
            None,
            project={"transcription": {"language": "es"}},
        )
        monkeypatch.setattr(
            "avo.video_context._provider_manifest",
            lambda ctx, root: {
                "transcription": {
                    "language": "pt" if ctx.provider == "channel-a" else "en"
                }
            },
        )
        assert merge_config(context)["transcription"]["language"] == "es"


def test_native_provider_conflict_refuses_before_other_project_writes(tmp_path):
    root = tmp_path / "provider-a"
    root.mkdir()
    service, _ = _native_trial(root, provider_name="channel-a")
    before = _files(service.workspace.raw_dir)
    with pytest.raises(ValueError, match="Provider conflicts"):
        TimelineImportService(
            service.workspace.project_path,
            provider="channel-b",
            provider_root=service.provider_manifest_path.parent,
        )
    assert _files(service.workspace.raw_dir) == before
