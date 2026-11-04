"""Audited evidence decisions use the shared CLI and structured MCP boundary."""

import json

from avo.cli import main
from avo.costs import summarize
from avo.mcp.bridge import run_bridged
from avo.mcp.tools.cli_tools import all_bridge_defs
from test_cost_continuity import evidence, packet, reconciliation, registered_ledger
from test_costs import fact


def _revision(tmp_path):
    store = registered_ledger(tmp_path)
    row = fact()
    old = evidence(row)
    new = evidence(row, nature="manual")
    store.ingest_packet(packet(store, [row], evidence_rows=[old]), allow_synthetic=True)
    store.ingest_packet(
        packet(store, [row], evidence_rows=[new], operation_id="metadata-2"),
        allow_synthetic=True,
    )
    record = reconciliation(store, old, new)
    request = {
        key: value
        for key, value in record.items()
        if key not in {"reconciliationId", "createdAt"}
    }
    return store, store.raw_dir / "avo.project.json", request


def test_reconcile_cli_is_audited_idempotent_and_preserves_history(tmp_path, capsys):
    store, project, request = _revision(tmp_path)
    snapshot = store.snapshot(summarize(store), "draft")
    original = store.path(f"snapshots/{snapshot['snapshotId']}.json").read_bytes()
    path = tmp_path / "decision.json"
    path.write_text(json.dumps(request), encoding="utf-8")
    args = [
        "costs",
        "reconcile",
        "--project",
        str(project),
        "--file",
        str(path),
        "--json",
    ]
    assert main(args) == 0
    first = json.loads(capsys.readouterr().out)
    assert summarize(store)["tokens"]["total"] == 120
    assert main(args) == 0
    second = json.loads(capsys.readouterr().out)
    assert second["replayed"] is True
    assert second["reconciliationId"] == first["reconciliationId"]
    assert len(store.documents("reconciliations")) == 1
    assert (
        store.path(f"snapshots/{snapshot['snapshotId']}.json").read_bytes() == original
    )


def test_reconcile_mcp_is_structured_and_uses_existing_review(tmp_path):
    store, project, request = _revision(tmp_path)
    definition = next(
        d for d in all_bridge_defs() if d.spec.name == "avo_costs_reconcile"
    )
    assert definition.spec.destructive is True
    assert (
        next(p for p in definition.params if p.name == "reconciliation").required
        is True
    )
    result = run_bridged(
        ("costs", "reconcile"),
        {"project": str(project), "reconciliation": request, "as_json": True},
    )
    assert result.ok
    assert (
        result.parsed_json["accountingVideoId"] == store.identity()["accountingVideoId"]
    )


def test_reconcile_rejection_does_not_publish_decision(tmp_path, capsys):
    store, project, request = _revision(tmp_path)
    request["newEvidenceId"] = "0" * 64
    path = tmp_path / "invalid-decision.json"
    path.write_text(json.dumps(request), encoding="utf-8")
    before = store.capture()
    assert (
        main(
            [
                "costs",
                "reconcile",
                "--project",
                str(project),
                "--file",
                str(path),
                "--json",
            ]
        )
        != 0
    )
    assert store.capture() == before
    capsys.readouterr()
