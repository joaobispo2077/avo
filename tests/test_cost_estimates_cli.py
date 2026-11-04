"""Estimate entry points preserve review, replay and transient-input privacy."""

import json

from avo.cli import main
from avo.cost_participation import register_context
from avo.mcp.bridge import run_bridged
from avo.mcp.tools.cli_tools import all_bridge_defs
from test_cost_continuity import host_descriptor, production


def _estimate(tmp_path):
    store, project = production(tmp_path)
    descriptor = host_descriptor("estimate")
    context = register_context(store, descriptor)
    request = {
        "schemaVersion": "2.0.0",
        "operationId": "range-1",
        "participationId": context["participationId"],
        "scope": descriptor["scope"],
        "method": "manual-range",
        "inputs": {
            "ranges": {"input": {"minimum": 100, "maximum": 200}},
            "basis": "bounded synthetic visible input",
        },
        "assumptions": ["Only the supplied test scope"],
        "limitations": ["Hidden context and billing are unknown"],
        "provenance": {"producer": "synthetic-test", "reference": "fixture"},
    }
    return store, project, request


def test_estimate_cli_replays_without_duplicate_records(tmp_path, capsys):
    store, project, request = _estimate(tmp_path)
    path = tmp_path / "estimate.json"
    path.write_text(json.dumps(request), encoding="utf-8")
    args = [
        "costs",
        "estimate",
        "--project",
        str(project),
        "--request",
        str(path),
        "--json",
    ]
    assert main(args) == 0
    first = json.loads(capsys.readouterr().out)
    before = store.capture()
    assert main(args) == 0
    second = json.loads(capsys.readouterr().out)
    assert second["replayed"] is True
    assert second["estimateId"] == first["estimateId"]
    assert store.capture() == before


def test_estimate_mcp_is_structured_and_keeps_mutation_review(tmp_path):
    store, project, request = _estimate(tmp_path)
    definition = next(
        d for d in all_bridge_defs() if d.spec.name == "avo_costs_estimate"
    )
    assert definition.spec.destructive is True
    assert next(p for p in definition.params if p.name == "request").required is True
    result = run_bridged(
        ("costs", "estimate"),
        {"project": str(project), "request": request, "as_json": True},
    )
    assert result.ok
    assert (
        result.parsed_json["accountingVideoId"] == store.identity()["accountingVideoId"]
    )


def test_estimate_mcp_does_not_admit_client_filesystem_paths(tmp_path):
    store, project, request = _estimate(tmp_path)
    request.update(
        method="visible-content-tokenizer",
        inputs={
            "inputPath": "C:/private/CLIENT-SENTINEL.txt",
            "model": "model-a",
            "encoding": "cl100k_base",
            "tokenizer": "tiktoken",
            "tokenizerVersion": "unknown",
            "assetsDigest": "0" * 64,
        },
    )
    before = store.capture()
    result = run_bridged(
        ("costs", "estimate"),
        {"project": str(project), "request": request, "as_json": True},
    )
    assert not result.ok and result.exit_code == 2
    assert "CLIENT-SENTINEL" not in json.dumps(result.__dict__, default=str)
    assert store.capture() == before


def test_estimate_semantic_rejection_precedes_publication(tmp_path, capsys):
    store, project, request = _estimate(tmp_path)
    request["inputs"]["ranges"]["input"] = {"minimum": 200, "maximum": 100}
    path = tmp_path / "invalid-estimate.json"
    path.write_text(json.dumps(request), encoding="utf-8")
    before = store.capture()
    assert (
        main(
            [
                "costs",
                "estimate",
                "--project",
                str(project),
                "--request",
                str(path),
                "--json",
            ]
        )
        != 0
    )
    assert store.capture() == before
    assert "200" not in capsys.readouterr().err
