"""Native and bridged proposal commands share one immutable sound request."""

import json

from avo.mcp.bridge import run_bridged, run_cli
from tests.test_sfx_cli import definition
from tests.test_sound_proposals import prepared


def test_sound_propose_native_and_mcp_freeze_the_same_metadata(tmp_path, monkeypatch):
    from avo.adapters import registry

    workspace, catalogue, request = prepared(tmp_path)
    path = tmp_path / "sound-request.json"
    path.write_text(json.dumps(request), encoding="utf-8")
    calls = []

    def build(selected, **kwargs):
        assert selected.video_id == workspace.video_id
        calls.append(kwargs)
        return catalogue

    monkeypatch.setattr(registry, "build_sfx_catalog", build)
    args = {
        "project": str(workspace.project_path),
        "video_id": workspace.video_id,
        "request": str(path),
        "as_json": True,
    }
    native = run_cli(
        [
            "sfx",
            "propose",
            "--project",
            args["project"],
            "--video-id",
            args["video_id"],
            "--request",
            str(path),
            "--json",
        ]
    )
    bridged = run_bridged(definition("propose").cli_prefix, args)
    assert native.exit_code == bridged.exit_code == 0, (native.stderr, bridged.stderr)
    assert native.parsed_json == bridged.parsed_json
    assert native.parsed_json["effect"] == "metadata-write"
    assert (
        native.parsed_json["proposal"]["generationId"] == request["expectedGeneration"]
    )
    assert all(not call["analyze"] and not call["semantic"] for call in calls)
    assert not definition("propose").spec.destructive


def test_sound_propose_rejects_mismatched_operation_before_catalogue_access(
    tmp_path, monkeypatch
):
    from avo.adapters import registry

    workspace, _, request = prepared(tmp_path)
    request["operation"] = "search"
    path = tmp_path / "sound-request.json"
    path.write_text(json.dumps(request), encoding="utf-8")

    def forbidden(*args, **kwargs):
        raise AssertionError("Invalid sound request opened a catalogue")

    monkeypatch.setattr(registry, "build_sfx_catalog", forbidden)
    result = run_cli(
        [
            "sfx",
            "propose",
            "--project",
            str(workspace.project_path),
            "--video-id",
            workspace.video_id,
            "--request",
            str(path),
            "--json",
        ]
    )
    assert result.exit_code == 2
    assert "operation" in result.stderr
