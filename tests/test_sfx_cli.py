"""Native sound discovery keeps source roots and execution choices explicit."""

import json
import wave
from types import SimpleNamespace

import pytest

from avo.mcp.bridge import run_bridged, run_cli


def definition(operation):
    from avo.mcp.tools.cli_tools import all_bridge_defs

    return next(
        item for item in all_bridge_defs() if item.cli_prefix == ("sfx", operation)
    )


def test_sound_root_resolution_inherits_empty_project_without_mutation(
    tmp_path, monkeypatch
):
    from avo import video_context
    from avo.sfx_cli import resolve_sfx_roots

    root = tmp_path / "avo"
    root.mkdir()
    library = tmp_path / "external sounds"
    project = {"provider": "test", "assets": {"sfx": ""}}
    original = json.dumps(project, sort_keys=True)
    monkeypatch.setattr(
        video_context, "load_config", lambda root: {"assets": {"sfx": ""}}
    )
    monkeypatch.setattr(
        video_context,
        "load_provider",
        lambda *a, **k: {"assets": {"sfx": str(library)}},
    )
    workspace = SimpleNamespace(
        project=project, video_id="v1", raw_dir=tmp_path / "project"
    )
    assert resolve_sfx_roots(workspace, root=root) == {"sfx": library}
    assert json.dumps(project, sort_keys=True) == original
    project["assets"]["sfx"] = str(tmp_path / "override")
    assert resolve_sfx_roots(workspace, root=root) == {"sfx": tmp_path / "override"}


@pytest.mark.parametrize(
    "value",
    [
        "https://example.com/sounds",
        "../sounds",
        "//server/sounds",
        "\\\\server\\sounds",
    ],
)
def test_sound_roots_reject_nonlocal_or_ambiguous_relative_paths(
    tmp_path, value, monkeypatch
):
    from avo import video_context
    from avo.sfx_cli import resolve_sfx_roots

    monkeypatch.setattr(video_context, "load_config", lambda root: {})
    monkeypatch.setattr(video_context, "load_provider", lambda *a, **k: {})
    workspace = SimpleNamespace(
        project={"assets": {"sfx": value}}, video_id="v1", raw_dir=tmp_path
    )
    with pytest.raises(ValueError, match="absolute|local"):
        resolve_sfx_roots(workspace)


def test_empty_native_and_mcp_views_are_equivalent_and_do_not_initialize(
    footage_project_factory,
):
    workspace = footage_project_factory()
    before = {p: p.read_bytes() for p in workspace.raw_dir.rglob("*") if p.is_file()}
    args = {"project": str(workspace.project_path), "as_json": True}
    native = run_cli(["sfx", "show", "--project", args["project"], "--json"])
    bridged = run_bridged(definition("show").cli_prefix, args)
    assert native.exit_code == bridged.exit_code == 0
    assert native.parsed_json == bridged.parsed_json
    assert native.parsed_json["effect"] == "metadata-read"
    assert native.parsed_json["coverage"]["total"] == 0
    assert {
        p: p.read_bytes() for p in workspace.raw_dir.rglob("*") if p.is_file()
    } == before


def test_scan_annotation_and_descriptor_search_use_read_only_declared_library(
    footage_project_factory, tmp_path
):
    workspace = footage_project_factory()
    library = tmp_path / "library"
    library.mkdir()
    sound = library / "soft-click.wav"
    with wave.open(str(sound), "wb") as output:
        output.setparams((1, 2, 48000, 0, "NONE", "not compressed"))
        output.writeframes((b"\xff\x1f" * 2400) + (b"\x00\x00" * 2400))
    original = sound.read_bytes()
    project = json.loads(workspace.project_path.read_text(encoding="utf-8"))
    project["assets"] = {"sfx": str(library)}
    workspace.project_path.write_text(json.dumps(project), encoding="utf-8")
    request = tmp_path / "sfx-request.json"

    def invoke(operation, body):
        request.write_text(
            json.dumps(
                {
                    "contractVersion": "1.0.0",
                    "operation": operation,
                    "operationId": operation + "-1",
                    **body,
                }
            ),
            encoding="utf-8",
        )
        result = run_cli(
            [
                "sfx",
                operation,
                "--project",
                str(workspace.project_path),
                "--request",
                str(request),
                "--json",
            ]
        )
        assert result.exit_code == 0, result.stderr
        return result.parsed_json

    scanned = invoke(
        "scan",
        {
            "actor": "creator",
            "reason": "Index selected library",
            "expectedGeneration": None,
        },
    )
    assert scanned["effect"] == "source-analysis"
    entry = scanned["entries"][0]
    annotated = invoke(
        "annotate",
        {
            "actor": "creator",
            "reason": "Record license evidence",
            "expectedGeneration": scanned["generationId"],
            "selection": {"entryId": entry["entryId"]},
            "patch": {
                "rights": {
                    "status": "licensed",
                    "license": "Fixture",
                    "evidenceRef": "fixture-license",
                }
            },
        },
    )
    found = invoke(
        "search", {"query": "soft click", "generation": annotated["generationId"]}
    )
    assert found["effect"] == "metadata-read"
    assert found["results"][0]["entryId"] == entry["entryId"]
    assert found["results"][0]["rightsState"] == "licensed"
    assert sound.read_bytes() == original
    assert sorted(path.name for path in library.iterdir()) == [sound.name]


def test_descriptor_tool_cannot_select_semantic_execution_and_unknown_fields_fail(
    footage_project_factory, tmp_path
):
    descriptor = definition("search")
    semantic = definition("search-semantic")
    assert "mode" not in {param.name for param in descriptor.params}
    assert "model" in semantic.spec.description.lower()
    workspace = footage_project_factory()
    path = tmp_path / "request.json"
    path.write_text(
        json.dumps(
            {
                "contractVersion": "1.0.0",
                "operation": "search",
                "operationId": "s1",
                "query": "click",
                "mode": "semantic",
            }
        ),
        encoding="utf-8",
    )
    result = run_bridged(
        descriptor.cli_prefix,
        {"project": str(workspace.project_path), "request": str(path), "as_json": True},
    )
    assert result.exit_code == 2
    assert "mode" in result.stderr
