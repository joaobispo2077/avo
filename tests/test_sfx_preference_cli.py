"""Native/MCP provider favorites require exact explicit requests, without media work."""

import json

import pytest

from avo.mcp.bridge import run_bridged, run_cli
from avo.mcp.tools.cli_tools import _decision_gate_args
from avo.sfx_catalog import SfxCatalogService
from tests.test_sfx_catalog import Facts
from tests.test_sfx_cli import definition
from tests.test_sfx_preferences import context as favorite_context
from tests.test_sfx_preferences import prepared

context = pytest.fixture(name="context")(favorite_context.__wrapped__)


def selected(context, monkeypatch):
    workspace, service, generation, request = prepared(context)
    monkeypatch.setattr(
        "avo.sfx_preferences.repo_root", lambda start=None: context.root
    )
    path = context.raw / "favorite-request.json"
    path.write_text(json.dumps(request), encoding="utf-8")
    args = {"project": str(workspace.project_path), "as_json": True}
    return workspace, service, generation, request, path, args


def test_native_and_mcp_inspection_share_a_metadata_only_view(context, monkeypatch):
    _, _, _, _, _, args = selected(context, monkeypatch)

    def forbidden(*a, **k):
        pytest.fail("Favorite inspection started source analysis")

    monkeypatch.setattr("avo.sfx_catalog.file_fingerprint", forbidden)
    native = run_cli(["sfx", "favorites-show", "--project", args["project"], "--json"])
    bridged = run_bridged(definition("favorites-show").cli_prefix, args)
    assert native.exit_code == bridged.exit_code == 0, (native.stderr, bridged.stderr)
    assert native.parsed_json == bridged.parsed_json
    assert native.parsed_json["effect"] == "metadata-read"
    assert native.parsed_json["favorites"] == []


def test_confirmed_bytes_bind_provider_promotion_before_any_write(context, monkeypatch):
    _, _, _, request, path, args = selected(context, monkeypatch)
    tool = definition("favorite-promote")
    assert tool.spec.destructive is True
    gate = _decision_gate_args(tool, {**args, "request": str(path)})
    before = context.provider.read_bytes()
    request["reason"] = "Changed after confirmation"
    path.write_text(json.dumps(request), encoding="utf-8")
    result = run_cli(
        [
            "sfx",
            "favorite-promote",
            "--project",
            args["project"],
            "--request",
            str(path),
            "--request-sha256",
            gate["_decisionDocumentSha256"],
            "--json",
        ]
    )
    assert result.exit_code != 0
    assert context.provider.read_bytes() == before


def test_native_promotion_and_mcp_removal_preserve_local_catalogue(
    context, monkeypatch
):
    _, service, generation, _, path, args = selected(context, monkeypatch)
    promoted = run_cli(
        [
            "sfx",
            "favorite-promote",
            "--project",
            args["project"],
            "--request",
            str(path),
            "--json",
        ]
    )
    assert promoted.exit_code == 0, promoted.stderr
    result = promoted.parsed_json
    assert result["effect"] == "provider-metadata-write"
    path.write_text(
        json.dumps(
            {
                "contractVersion": "1.0.0",
                "operation": "favorite-remove",
                "operationId": "remove-native",
                "actor": "creator",
                "reason": "Remove shared recommendation",
                "provider": "sample",
                "expectedProviderDocument": result["documentSha256"],
                "favoriteId": result["favorite"]["favoriteId"],
            }
        ),
        encoding="utf-8",
    )
    removed = run_bridged(
        definition("favorite-remove").cli_prefix, {**args, "request": str(path)}
    )
    assert removed.exit_code == 0, removed.stderr
    assert removed.parsed_json["favorites"] == []
    assert service.show() == generation


@pytest.mark.parametrize("include", [False, True])
def test_native_scan_selects_provider_defaults_explicitly(
    context, monkeypatch, include
):
    _, _, _, _, path, args = selected(context, monkeypatch)
    promoted = run_cli(
        [
            "sfx",
            "favorite-promote",
            "--project",
            args["project"],
            "--request",
            str(path),
            "--json",
        ]
    )
    assert promoted.exit_code == 0, promoted.stderr
    library = context.raw.parent / "future-library"
    library.mkdir()
    original = b"same sound"
    (library / "future.wav").write_bytes(original)
    project_dir = context.raw.parent / "future-project"
    project_dir.mkdir()
    project = project_dir / "avo.project.json"
    project.write_text(
        json.dumps({"provider": "sample", "rawDir": str(project_dir)}), encoding="utf-8"
    )
    monkeypatch.setattr(
        "avo.sfx_cli.resolve_sfx_roots", lambda workspace: {"test": library}
    )

    def catalogue(workspace, *, roots, analyze=False, semantic=False, favorites=None):
        assert analyze is True and semantic is False
        return SfxCatalogService(
            workspace, roots=roots, analyzer=Facts(), favorites=favorites
        )

    monkeypatch.setattr("avo.adapters.registry.build_sfx_catalog", catalogue)
    if not include:

        def forbidden(*a, **k):
            pytest.fail("An unselected scan read provider favorites")

        monkeypatch.setattr("avo.sfx_preferences.inspect_sfx_favorites", forbidden)
    path.write_text(
        json.dumps(
            {
                "contractVersion": "1.0.0",
                "operation": "scan",
                "operationId": "future-scan",
                "actor": "creator",
                "reason": "Scan selected library",
                "expectedGeneration": None,
                "useProviderFavorites": include,
            }
        ),
        encoding="utf-8",
    )
    result = run_cli(
        ["sfx", "scan", "--project", str(project), "--request", str(path), "--json"]
    )
    assert result.exit_code == 0, result.stderr
    entry = result.parsed_json["entries"][0]
    assert entry["curation"]["favorite"] is include
    assert ("curationOrigin" in entry) is include
    assert entry["rights"]["status"] == "unknown" and entry["marker"] is None
    assert (library / "future.wav").read_bytes() == original
    assert not (project_dir / "edit/timeline").exists()
