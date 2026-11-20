"""Read-only coverage and explicitly selected native/MCP recovery commands."""

import json

from avo.mcp.bridge import run_bridged, run_cli
from avo.mcp.tools.cli_tools import all_bridge_defs
from tests.test_speech_recovery import recovery


def definition(operation):
    return next(
        item
        for item in all_bridge_defs()
        if item.cli_prefix == ("preparation", operation)
    )


def test_engine_preparation_alias_uses_the_shared_cli(monkeypatch):
    from avo import engine_cli

    calls = []
    monkeypatch.setattr(
        engine_cli, "_invoke", lambda verb, rest: calls.append((verb, rest)) or 0
    )
    assert engine_cli.main(["preparation", "coverage", "--help"]) == 0
    assert calls == [("cli", ["preparation", "coverage", "--help"])]


def test_nonobject_request_is_rejected_before_workspace_loading(tmp_path):
    request = tmp_path / "request.json"
    request.write_text("[]", encoding="utf-8")
    result = run_cli(
        [
            "preparation",
            "coverage",
            "--project",
            str(tmp_path / "absent.json"),
            "--request",
            str(request),
        ]
    )
    assert result.exit_code == 2
    assert "object" in result.stderr


def test_native_and_mcp_coverage_read_only_retained_metadata(tmp_path, monkeypatch):
    cutting, _, _, _, request = recovery(tmp_path)
    path = tmp_path / "coverage.json"
    path.write_text(
        json.dumps(
            {
                "contractVersion": "1.0.0",
                "operation": "coverage",
                "analysisRef": request["analysisRef"],
            }
        ),
        encoding="utf-8",
    )
    before = {
        p: p.read_bytes() for p in cutting.workspace.raw_dir.rglob("*") if p.is_file()
    }

    def forbidden(*args, **kwargs):
        raise AssertionError("coverage started source verification or model execution")

    monkeypatch.setattr("avo.timeline.cmap_service.CMapService._verify_raw", forbidden)
    monkeypatch.setattr(
        "avo.adapters.media.cutting_analysis.CuttingAnalysisAdapter.dependency_bindings",
        forbidden,
    )
    args = {
        "project": str(cutting.workspace.project_path),
        "request": str(path),
        "as_json": True,
    }
    native = run_cli(
        [
            "preparation",
            "coverage",
            "--project",
            args["project"],
            "--request",
            str(path),
            "--json",
        ]
    )
    assert native.exit_code == 0, native.stderr
    bridge = run_bridged(definition("coverage").cli_prefix, args)
    assert bridge.exit_code == 0, bridge.stderr
    assert native.parsed_json == bridge.parsed_json
    assert native.parsed_json["effect"] == "metadata-read"
    assert native.parsed_json["coverage"]["status"] == "needs-review"
    assert {
        p: p.read_bytes() for p in cutting.workspace.raw_dir.rglob("*") if p.is_file()
    } == before


def test_recovery_is_explicitly_gated_and_exact_request_bytes_are_checked(
    tmp_path, monkeypatch
):
    _, _, _, _, request = recovery(tmp_path)
    path = tmp_path / "recover.json"
    path.write_text(json.dumps(request), encoding="utf-8")
    called = []
    monkeypatch.setattr(
        "avo.adapters.registry.build_preparation_service",
        lambda *a, **k: called.append(True),
    )
    result = run_cli(
        [
            "preparation",
            "recover",
            "--project",
            str(tmp_path / "project.json"),
            "--request",
            str(path),
            "--request-sha256",
            "f" * 64,
            "--json",
        ]
    )
    assert result.exit_code == 2
    assert called == []
    assert definition("recover").spec.destructive is True
    assert definition("coverage").spec.destructive is False
