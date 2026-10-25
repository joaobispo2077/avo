"""Wrap cost snapshots after existing media closure verification."""

from pathlib import Path

from avo.cost_sources import collect
from avo.cost_store import CostError, CostStore, read_json
from avo.costs import summarize


def cleanup_evidence(raw_dir):
    path = Path(raw_dir) / "edit/cleanup/cleanup-result.json"
    if not path.is_file():
        raise CostError("final cost snapshot requires completed cleanup evidence")
    receipt = read_json(path)
    if receipt.get("status") != "completed":
        raise CostError("final cost snapshot requires completed cleanup evidence")
    return {
        "receiptPath": "edit/cleanup/cleanup-result.json",
        "receiptHash": CostStore.digest(receipt),
    }


def close_costs(raw_dir, stage, *, preservation=False):
    store = CostStore(raw_dir)
    if not store.identity():
        return summarize(store)
    refreshed = collect(store)
    report = summarize(store)
    report["diagnostics"].extend(refreshed["diagnostics"])
    closure = None
    if stage == "final":
        if preservation:
            receipt = read_json(Path(raw_dir) / "edit/cleanup/preservation-result.json")
            closure = {"mode": "preservation", "receiptHash": CostStore.digest(receipt)}
        else:
            closure = cleanup_evidence(raw_dir)
    return store.snapshot(report, stage, closure=closure)
