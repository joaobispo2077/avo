"""Explicit sound publication shares native/MCP request and recovery boundaries."""

import hashlib
import json

import pytest

from avo.mcp.bridge import run_bridged, run_cli
from tests.test_sfx_cli import definition
from tests.test_sound_application import application


def test_sound_apply_confirmation_binds_request_bytes_and_uses_the_native_budget(
    tmp_path,
):
    from avo.editing_craft_requests import MAX_REQUEST_BYTES
    from avo.mcp.tools.cli_tools import _decision_gate_args

    tool = definition("apply")
    assert tool.spec.destructive is True
    path = tmp_path / "apply.json"
    path.write_text('{"operation":"apply"}', encoding="utf-8")
    first = _decision_gate_args(tool, {"request": str(path)})
    assert (
        first["_decisionDocumentSha256"]
        == hashlib.sha256(path.read_bytes()).hexdigest()
    )
    path.write_text('{"operation":"propose"}', encoding="utf-8")
    assert _decision_gate_args(tool, {"request": str(path)}) != first
    path.write_bytes(b" " * (MAX_REQUEST_BYTES + 1))
    with pytest.raises(ValueError, match="exceeds"):
        _decision_gate_args(tool, {"request": str(path)})


@pytest.mark.parametrize("selected_scope", [False, True])
def test_native_and_bridged_sound_apply_share_exact_publication_without_analysis(
    tmp_path, monkeypatch, selected_scope
):
    from avo import sfx_cli
    from avo.adapters import registry

    workspace, catalogue, _, probe, request, shown = application(tmp_path)
    if selected_scope:
        request["productionScope"] = {
            "clock": {
                key: shown["proposal"]["clock"][key]
                for key in ("frameRate", "programEndFrame")
            },
            "chunks": [
                {"chunkId": "opening", "startFrame": 0, "endFrameExclusive": 12},
                {"chunkId": "answer", "startFrame": 12, "endFrameExclusive": 24},
            ],
            "selectedChunkIds": ["opening"],
        }

    def build(selected_workspace, *, roots, analyze, semantic):
        assert selected_workspace.video_id == workspace.video_id
        assert roots == catalogue.roots
        assert analyze is semantic is False
        return catalogue

    monkeypatch.setattr(sfx_cli, "resolve_sfx_roots", lambda _: catalogue.roots)
    monkeypatch.setattr(registry, "build_sfx_catalog", build)
    monkeypatch.setattr(registry, "build_sound_source_probe", lambda: probe)
    path = tmp_path / "apply.json"
    path.write_text(json.dumps(request), encoding="utf-8")
    native = run_cli(
        [
            "sfx",
            "apply",
            "--project",
            str(workspace.project_path),
            "--video-id",
            workspace.video_id,
            "--request",
            str(path),
            "--json",
        ]
    )
    assert native.exit_code == 0, native.stderr
    bridged = run_bridged(
        definition("apply").cli_prefix,
        {
            "project": str(workspace.project_path),
            "video_id": workspace.video_id,
            "request": str(path),
        },
    )
    assert bridged.exit_code == 0, bridged.stderr
    assert native.parsed_json == bridged.parsed_json
    assert native.parsed_json["effect"] == "canonical-write"
    assert native.parsed_json["acceptance"] == "pending-listening"
    if selected_scope:
        report = native.parsed_json["receipt"]["productionScope"]
        assert report["request"] == request["productionScope"]
        assert report["contributions"][0]["ownerChunkId"] == "opening"
    assert len(probe.calls) == 1
    from dataclasses import replace

    from avo.timeline import command_registry

    monkeypatch.setitem(
        command_registry.COMMANDS,
        "sound",
        replace(command_registry.COMMANDS["sound"], owns=frozenset()),
    )
    before = {p: p.read_bytes() for p in workspace.raw_dir.rglob("*") if p.is_file()}
    denied = run_bridged(
        definition("apply").cli_prefix,
        {
            "project": str(workspace.project_path),
            "video_id": workspace.video_id,
            "request": str(path),
        },
    )
    assert denied.exit_code == 2
    assert "cannot mutate" in denied.stderr
    assert len(probe.calls) == 1
    assert {
        p: p.read_bytes() for p in workspace.raw_dir.rglob("*") if p.is_file()
    } == before


def test_changed_sound_confirmation_is_rejected_before_source_or_project_work(
    footage_project_factory, tmp_path, monkeypatch
):
    from avo.adapters import registry

    workspace = footage_project_factory()
    path = tmp_path / "apply.json"
    path.write_text('{"operation":"apply"}', encoding="utf-8")

    def forbidden(*args, **kwargs):
        pytest.fail("Changed confirmation constructed sound execution")

    monkeypatch.setattr(registry, "build_sfx_catalog", forbidden)
    before = {p: p.read_bytes() for p in workspace.raw_dir.rglob("*") if p.is_file()}
    result = run_cli(
        [
            "sfx",
            "apply",
            "--project",
            str(workspace.project_path),
            "--request",
            str(path),
            "--request-sha256",
            "f" * 64,
            "--json",
        ]
    )
    assert result.exit_code == 2
    assert "changed after confirmation" in result.stderr
    assert {
        p: p.read_bytes() for p in workspace.raw_dir.rglob("*") if p.is_file()
    } == before


@pytest.mark.parametrize("state", ["recovery-needed", "committed"])
def test_sound_recovery_errors_report_actual_receipt_and_committed_heads(
    state, footage_project_factory, tmp_path, monkeypatch
):
    from types import SimpleNamespace

    from avo import sfx_cli
    from avo.adapters import registry
    from avo.timeline.sound_application import SoundApplicationError

    reference = {
        "path": f"edit/motion/sound/receipts/{'a' * 64}.json",
        "sha256": "a" * 64,
    }
    heads = {"bmap": {"revisionId": "bmap-r0002", "sha256": "b" * 64}}
    error = SoundApplicationError(
        "Exact retry required",
        receipt_ref=reference,
        committed_heads=heads,
        publication_state=state,
    )
    value = error.to_dict()
    assert value["receiptRef"] == reference
    assert value["committedHeads"] == heads
    assert value["publicationState"] == state
    assert value["blocking"] is True
    workspace = footage_project_factory()
    monkeypatch.setattr(sfx_cli, "_request", lambda *args, **kwargs: {})
    monkeypatch.setattr(
        registry, "build_sfx_catalog", lambda *a, **k: SimpleNamespace()
    )

    def interrupted(*args, **kwargs):
        raise error

    monkeypatch.setattr(sfx_cli, "_execute", interrupted)
    result = run_cli(
        [
            "sfx",
            "apply",
            "--project",
            str(workspace.project_path),
            "--request",
            str(tmp_path / "apply.json"),
            "--json",
        ]
    )
    assert result.exit_code == 2
    assert json.loads(result.stderr) == value


def test_failed_selected_source_probe_is_a_typed_request_failure(tmp_path, monkeypatch):
    import subprocess

    from avo.adapters.media.ffprobe import FfprobeMediaAdapter
    from avo.adapters.registry import build_sound_source_probe

    def unavailable(*args, **kwargs):
        raise subprocess.CalledProcessError(
            1, ["ffprobe"], stderr="fixture decode failure"
        )

    monkeypatch.setattr(FfprobeMediaAdapter, "inventory", unavailable)
    with pytest.raises(ValueError, match="selected sound source"):
        build_sound_source_probe()(tmp_path / "sound.wav", expected_sha256="f" * 64)
