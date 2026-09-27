"""Characterization locks for the pre-iteration-proofing AVO boundaries.

These tests intentionally describe current behavior.  The iteration-aware
implementation may extend the contracts, but must not silently replace the
canonical timeline, Watch, provider-animation, Learndown, reconstruction, or
CLI surfaces captured here.
"""

from __future__ import annotations

import importlib.util
import json
import shutil
from pathlib import Path

import pytest

from avo.adapters.understand.watch_policy import resolve_watch_policy
from avo.adapters.understand.watch_skill import _coverage_payload, _review_request
from avo.cli import build_parser
from avo.learndown_export import export_provider_learndown
from avo.timeline.contracts import file_fingerprint
from avo.timeline.materialize import materialize_cut_proof
from avo.timeline.provider_animation import ProviderAnimationService
from avo.timeline.reconstruction import build_reconstruction_bundle
from tests.test_timeline_cmap_service import snapshot, workspace

REQUIRED_FIXTURE_SCENARIOS = {
    "proof-ancestry",
    "speech-joins",
    "sfx-transient",
    "moving-overlay",
    "vfr-stills",
    "hybrid-pacing",
    "caption-privacy",
    "long-form-watch",
}


def _load_fixture_builder(path: Path):
    spec = importlib.util.spec_from_file_location("iteration_fixture_builder", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_iteration_fixture_manifest_is_synthetic_and_covers_known_risks(
    iteration_proofing_manifest: dict[str, object],
):
    fixtures = iteration_proofing_manifest["fixtures"]
    assert REQUIRED_FIXTURE_SCENARIOS <= set(fixtures)
    serialized = json.dumps(iteration_proofing_manifest)
    assert "synthetic" in serialized.lower()
    assert "H:\\" not in serialized
    assert "/home/" not in serialized


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is required")
def test_fixture_builder_is_deterministic_and_models_prohibited_ancestry(
    tmp_path: Path, iteration_proofing_fixture_dir: Path
):
    builder = _load_fixture_builder(
        iteration_proofing_fixture_dir / "build_fixtures.py"
    )
    first = builder.build_fixture_set(tmp_path / "one")
    second = builder.build_fixture_set(tmp_path / "two")
    assert first == second
    assert set(first["scenarios"]) == REQUIRED_FIXTURE_SCENARIOS
    assert (
        first["files"]["original-source.mp4"]["sha256"]
        == first["files"]["prior-proof.mp4"]["sha256"]
    )


def test_shared_fixture_helpers_use_canonical_hash_and_timeline_layout(
    canonical_json_hash, footage_project_factory
):
    assert canonical_json_hash({"b": 2, "a": 1}) == canonical_json_hash(
        {"a": 1, "b": 2}
    )
    ws = footage_project_factory(video_id="characterization")
    assert {kind for kind in ("cmap", "bmap", "tracks", "animation", "sync-map")} == {
        kind
        for kind in ("cmap", "bmap", "tracks", "animation", "sync-map")
        if ws.artifact_path(kind).is_file()
    }


class _FakeRender:
    def render(self, projection, output, **request):
        Path(output).write_bytes(b"proof")
        return {
            "status": "pass",
            "output": {"sha256": "c" * 64, "sizeBytes": 5, "locator": str(output)},
            "path": str(output),
            "renderProfile": request["profile"],
            "producer": {"name": "fake", "version": "1"},
        }


def test_materialization_remains_bound_to_current_cmap_revision(tmp_path: Path):
    from avo.timeline.cmap_service import CMapService

    ws = workspace(tmp_path)
    raw = ws.raw_dir / "raw.bin"
    raw.write_bytes(b"raw")
    revision = CMapService(ws).author(snapshot(raw), actor="agent", reason="cut")
    record = materialize_cut_proof(
        workspace=ws,
        cmap_revision_id=revision["revisionId"],
        output_path=ws.raw_dir / "edit" / "proof.mp4",
        render_port=_FakeRender(),
    )
    assert record["canonicalInputLock"]["cmapRevisionHash"] == revision["contentHash"]
    assert record["output"]["sha256"] == "c" * 64


def test_watch_full_scope_keeps_frame_ceiling_without_inventing_coverage(
    tmp_path: Path,
):
    candidate = tmp_path / "candidate.mp4"
    candidate.write_bytes(b"candidate")
    windows = [{"start": 0.0, "end": 1200.0, "reason": "whole-program"}]
    policy = resolve_watch_policy(raw_dir=tmp_path)
    review = _review_request(
        candidate,
        {
            "scope": "full",
            "windows": windows,
            "policy": policy.payload(),
            "artifact_dir": tmp_path / "review",
        },
    )
    coverage = _coverage_payload(review, [{"attempt": 1}], {})
    assert coverage["mode"] == "full"
    assert coverage["windows"] == []
    assert coverage["requestedWindows"] == windows
    assert coverage["maxFrames"] == 18


def _provider_pattern() -> dict[str, object]:
    return {
        "patternId": "iteration-proofing-pattern",
        "name": "Sanitized proofing pattern",
        "version": "1.0.0",
        "behavior": {"sequence": ["enter", "hold", "exit"]},
        "contexts": ["talking-head-review"],
        "exclusions": ["evidence-fullscreen"],
        "requiredAssets": [],
        "accessibility": {"reducedMotion": True, "flashingSafe": True},
        "provenance": {
            "sourceVideoId": "synthetic",
            "candidateSha256": "a" * 64,
            "sectionRefs": ["synthetic-section"],
        },
    }


def test_provider_animation_still_promotes_only_after_explicit_decision(tmp_path: Path):
    service = ProviderAnimationService(
        tmp_path / "animation.json",
        provider="example",
        clock=lambda: "2026-09-27T00:00:00Z",
    )
    service.initialize()
    proposal = service.propose(
        _provider_pattern(), actor="creator", intent_reference="explicit"
    )
    assert service.load()["patterns"] == []
    service.decide(
        Path(proposal["path"]),
        decision="approved",
        actor="creator",
        reason="approved sanitized abstraction",
    )
    assert service.load()["patterns"][0]["patternId"] == "iteration-proofing-pattern"


def test_learndown_reuses_entry_and_preserves_first_editlog_lock(tmp_path: Path):
    raw_dir = tmp_path / "footage"
    raw_dir.mkdir()
    (raw_dir / "EDITLOG.md").write_text("first lock\n", encoding="utf-8")
    payload = {
        "provider": "example",
        "masterBasename": "20260927-demo-master-v001",
        "rawDir": str(raw_dir),
        "status": "draft",
        "generatedAt": "2026-09-27T00:00:00Z",
        "title": "Demo",
        "summary": "Synthetic characterization.",
        "sessionId": "session",
        "space": {},
        "learning": {},
    }
    first = export_provider_learndown(payload, root=tmp_path)
    assert first is not None
    (raw_dir / "EDITLOG.md").write_text("later lock\n", encoding="utf-8")
    second = export_provider_learndown({**payload, "status": "final"}, root=tmp_path)
    assert second == first
    assert (second / "EDITLOG.md").read_text(encoding="utf-8") == "first lock\n"


def test_reconstruction_bundle_keeps_all_five_canonical_artifacts(
    footage_project_factory,
):
    ws = footage_project_factory(video_id="reconstruct")
    (ws.raw_dir / "source.mp4").write_bytes(b"raw-source")
    for kind in ("cmap", "bmap", "tracks", "animation", "sync-map"):
        ws.store(kind).append_revision(
            snapshot={"kind": kind}, actor="agent", reason="fixture"
        )
    basename = "20260927-reconstruct-master-v001"
    master = ws.raw_dir / "edit" / "masters" / f"{basename}.mp4"
    master.parent.mkdir(parents=True)
    master.write_bytes(b"master")
    transcript = ws.raw_dir / "edit" / "transcripts" / f"{basename}.json"
    transcript.parent.mkdir(parents=True)
    transcript.write_text(
        json.dumps(
            {"source": {"sha256": file_fingerprint(master)["sha256"]}, "words": []}
        ),
        encoding="utf-8",
    )
    bundle = build_reconstruction_bundle(ws, master_basename=basename, actor="creator")
    assert len(bundle["canonicalArtifacts"]) == 5


@pytest.mark.parametrize(
    ("argv", "command", "subcommand"),
    [
        (["pipeline", "status"], "pipeline", "status"),
        (["timeline", "validate"], "timeline", "validate"),
        (["review", "policy"], "review", "policy"),
    ],
)
def test_existing_cli_commands_remain_parseable(
    tmp_path: Path, argv: list[str], command: str, subcommand: str
):
    parsed = build_parser().parse_args([*argv, "--project", str(tmp_path)])
    assert parsed.command == command
    assert getattr(parsed, f"{command}_command") == subcommand
