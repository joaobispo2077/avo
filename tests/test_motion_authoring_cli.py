"""Typed motion planning routes through native owners with exact request binding."""

import hashlib
import json
from pathlib import Path

import pytest

from avo.editing_craft import resolve_editing_craft_selection
from avo.mcp.bridge import run_cli


def request(workspace, operation="plan-propose"):
    return {
        "contractVersion": "1.0.0",
        "operation": operation,
        "operationId": "concept-one",
        "actor": "creator",
        "reason": "Explain contrast",
        "expectedBasis": {
            key: None for key in ("cmap", "bmap", "tracks", "animation", "sync-map")
        },
        "selection": resolve_editing_craft_selection(),
        "proposal": {
            "items": [
                {
                    "itemId": "mo04",
                    "label": "mo04",
                    "sectionId": "opening",
                    "purpose": "Explain contrast",
                    "concept": "Compare both choices",
                    "treatment": "static",
                }
            ]
        },
    }


def invoke(workspace, path, operation):
    return run_cli(
        [
            "animation",
            operation,
            "--project",
            str(workspace.project_path),
            "--request",
            str(path),
            "--json",
        ]
    )


def definition(operation):
    from avo.mcp.tools.cli_tools import all_bridge_defs

    return next(
        value
        for value in all_bridge_defs()
        if value.spec.name == "avo_animation_" + operation.replace("-", "_")
    )


def test_propose_select_and_default_review_preserve_provisional_identity(
    footage_project_factory, tmp_path, monkeypatch
):
    from avo.timeline.pipeline import TimelinePipeline

    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "home"))
    workspace = footage_project_factory()
    path = tmp_path / "request.json"
    body = request(workspace)
    path.write_text(json.dumps(body), encoding="utf-8")
    proposed = invoke(workspace, path, "plan-propose")
    assert proposed.exit_code == 0, proposed.stderr
    assert proposed.parsed_json["proposal"]["items"][0]["label"] == "mo04"
    select = {
        key: body[key]
        for key in ("contractVersion", "actor", "reason", "expectedBasis")
    }
    select.update(
        operation="plan-select",
        operationId="select-concept-one",
        selection={
            "proposalHash": proposed.parsed_json["proposalRef"]["sha256"],
            "dispositions": [
                {"itemId": "mo04", "status": "selected", "reason": "Clearer"}
            ],
        },
    )
    path.write_text(json.dumps(select), encoding="utf-8")
    selected = invoke(workspace, path, "plan-select")
    assert selected.exit_code == 0, selected.stderr
    view = TimelinePipeline(workspace).status()["motionPlan"]
    assert any(item["itemId"] == "mo04" for item in view["items"])
    assert any(card["itemId"] == "mo04" for card in view["storyboardCards"])
    assert workspace.store("bmap").load_index()["headRevisionId"] is None


def test_authoring_request_decoder_rejects_duplicate_keys_before_mutation(
    footage_project_factory, tmp_path
):
    workspace = footage_project_factory()
    path = tmp_path / "request.json"
    path.write_text('{"operation":"plan-propose","operation":"plan-apply"}')
    before = {p: p.read_bytes() for p in workspace.raw_dir.rglob("*") if p.is_file()}
    result = invoke(workspace, path, "plan-propose")
    assert result.exit_code == 2
    assert "Duplicate" in result.stderr
    assert {
        p: p.read_bytes() for p in workspace.raw_dir.rglob("*") if p.is_file()
    } == before


def test_show_a_specific_unselected_draft_is_pure(footage_project_factory, tmp_path):
    workspace = footage_project_factory()
    path = tmp_path / "proposal.json"
    path.write_text(json.dumps(request(workspace)), encoding="utf-8")
    proposed = invoke(workspace, path, "plan-propose")
    assert proposed.exit_code == 0, proposed.stderr
    before = {p: p.read_bytes() for p in workspace.raw_dir.rglob("*") if p.is_file()}
    result = run_cli(
        [
            "animation",
            "plan-show",
            "--project",
            str(workspace.project_path),
            "--proposal-hash",
            proposed.parsed_json["proposalRef"]["sha256"],
            "--json",
        ]
    )
    assert result.exit_code == 0, result.stderr
    assert result.parsed_json["snapshot"]["items"][0]["itemId"] == "mo04"
    assert result.parsed_json["snapshot"]["items"][0]["timing"] is None
    assert {
        p: p.read_bytes() for p in workspace.raw_dir.rglob("*") if p.is_file()
    } == before


def test_apply_confirmation_binds_the_exact_request_bytes(tmp_path):
    from avo.mcp.tools.cli_tools import _decision_gate_args

    tool = definition("plan-apply")
    assert tool.spec.destructive is True
    path = tmp_path / "apply.json"
    path.write_bytes(b'{"operation":"plan-apply"}')
    first = _decision_gate_args(tool, {"request": str(path)})
    assert (
        first["_decisionDocumentSha256"]
        == hashlib.sha256(path.read_bytes()).hexdigest()
    )
    path.write_bytes(b'{"operation":"plan-propose"}')
    assert _decision_gate_args(tool, {"request": str(path)}) != first


def test_apply_confirmation_uses_the_native_request_size_limit(tmp_path):
    from avo.editing_craft_requests import MAX_REQUEST_BYTES
    from avo.mcp.tools.cli_tools import _decision_gate_args

    path = tmp_path / "apply.json"
    path.write_bytes(b" " * (MAX_REQUEST_BYTES + 1))
    with pytest.raises(ValueError, match="exceeds"):
        _decision_gate_args(definition("plan-apply"), {"request": str(path)})


@pytest.mark.parametrize("operation", ["plan-propose", "plan-select", "plan-apply"])
def test_authoring_tools_require_an_explicit_typed_request(operation):
    tool = definition(operation)
    assert any(param.name == "request" and param.required for param in tool.params)


def test_changed_confirmation_digest_is_rejected_before_any_authoring(
    footage_project_factory, tmp_path
):
    workspace = footage_project_factory()
    path = tmp_path / "apply.json"
    path.write_text(json.dumps(request(workspace)), encoding="utf-8")
    result = run_cli(
        [
            "animation",
            "plan-apply",
            "--project",
            str(workspace.project_path),
            "--request",
            str(path),
            "--request-sha256",
            "0" * 64,
            "--json",
        ]
    )
    assert result.exit_code == 2
    assert "changed" in result.stderr.lower()
