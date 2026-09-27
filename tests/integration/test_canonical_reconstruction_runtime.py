from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from avo.timeline.contracts import file_fingerprint
from avo.timeline.iterations import IterationLedgerService
from avo.timeline.reconstruction import (
    build_reconstruction_bundle,
    verify_reconstruction_bundle,
)


def _builder(path: Path):
    spec = importlib.util.spec_from_file_location("iteration_fixture_builder", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_clean_reconstruction_keeps_lineage_not_rejected_proof_bytes(
    tmp_path: Path,
    footage_project_factory,
    iteration_proofing_fixture_dir: Path,
):
    staging = tmp_path / "synthetic"
    _builder(iteration_proofing_fixture_dir / "build_fixtures.py").build_fixture_set(
        staging, only={"proof-ancestry"}
    )
    workspace = footage_project_factory(video_id="canonical-reconstruction")
    raw = workspace.raw_dir / "raw" / "original-source.mp4"
    raw.parent.mkdir(parents=True)
    raw.write_bytes((staging / "original-source.mp4").read_bytes())
    rejected = workspace.raw_dir / "edit" / "proofs" / "rejected-proof.mp4"
    rejected.parent.mkdir(parents=True)
    rejected.write_bytes((staging / "prior-proof.mp4").read_bytes())

    for kind in ("cmap", "bmap", "tracks", "animation", "sync-map"):
        workspace.store(kind).append_revision(
            snapshot={"kind": kind}, actor="agent", reason="synthetic fixture"
        )
    lineage_record = (
        workspace.timeline_dir / "materializations" / "assembly" / "lineage.json"
    )
    lineage_record.parent.mkdir(parents=True)
    lineage_record.write_text(
        json.dumps(
            {
                "audiovisualLineageHash": "a" * 64,
                "rejectedEvidence": {
                    "sha256": file_fingerprint(rejected)["sha256"],
                    "classification": "proof",
                },
            }
        ),
        encoding="utf-8",
    )
    retained_state = {
        "proofPlans": workspace.timeline_dir / "proof-plans" / "proof-plan-0001.json",
        "candidateSnapshots": workspace.timeline_dir
        / "candidate-snapshots"
        / "candidate-0001.json",
        "regressionResults": workspace.timeline_dir
        / "regression-results"
        / "result-0001.json",
    }
    for path in retained_state.values():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}\n", encoding="utf-8")

    ledger = IterationLedgerService(workspace)
    recorded = ledger.record_iteration(
        {
            "intent": {"requestedChanges": ["Keep SFX synchronized"]},
            "canonicalBasis": {"cmap": "b" * 64},
            "proofPlanRef": {"artifactId": "proof-plan-0001", "sha256": "c" * 64},
            "candidate": file_fingerprint(rejected),
            "feedback": [{"actor": "creator", "text": "Approved except SFX"}],
            "decisions": [
                {
                    "kind": "defect",
                    "scope": {"kind": "event", "eventId": "insert-one"},
                    "statement": "Entry SFX must remain synchronized",
                    "rationale": "creator review",
                    "riskWindows": [
                        {
                            "windowId": "insert-sync-risk",
                            "startFrame": 300,
                            "endFrameExclusive": 330,
                            "reason": "historical sync regression",
                        }
                    ],
                }
            ],
        },
        actor="agent",
        reason="synthetic rejected proof review",
    )
    ledger.store.approve(
        recorded["revision"]["revisionId"],
        revision_hash=recorded["revision"]["contentHash"],
        candidate_hash=file_fingerprint(rejected)["sha256"],
    )
    rejected.unlink()
    ledger.mark_iteration_cleaned(
        recorded["iteration"]["iterationId"],
        actor="agent",
        reason="remove bulky rejected proof",
        expected_head_hash=recorded["revision"]["contentHash"],
    )
    contract_before = ledger.compile_regression_contract()
    retained_state["regressionResults"].write_text(
        json.dumps(contract_before), encoding="utf-8"
    )

    basename = "20260927-canonical-master-v001"
    master = workspace.raw_dir / "edit" / "masters" / f"{basename}.mp4"
    master.parent.mkdir(parents=True)
    master.write_bytes(b"canonical-master")
    transcript = workspace.raw_dir / "edit" / "transcripts" / f"{basename}.json"
    transcript.parent.mkdir(parents=True)
    transcript.write_text(
        json.dumps(
            {"source": {"sha256": file_fingerprint(master)["sha256"]}, "words": []}
        ),
        encoding="utf-8",
    )

    bundle = build_reconstruction_bundle(
        workspace, master_basename=basename, actor="creator"
    )
    preserved = {item["path"] for item in bundle["files"]}
    assert lineage_record.relative_to(workspace.raw_dir).as_posix() in preserved
    assert rejected.relative_to(workspace.raw_dir).as_posix() not in preserved
    ledger_paths = {item["path"] for item in bundle["iterationLedgers"]}
    ledger_index = workspace.timeline_dir / "iteration-ledger.json"
    index = json.loads(ledger_index.read_text(encoding="utf-8"))
    expected_ledger_paths = {
        ledger_index.relative_to(workspace.raw_dir).as_posix(),
        *{
            (workspace.timeline_dir / ref["path"])
            .relative_to(workspace.raw_dir)
            .as_posix()
            for ref in [*index["revisionRefs"], *index["eventRefs"]]
        },
    }
    assert ledger_paths == expected_ledger_paths
    assert expected_ledger_paths <= preserved
    assert expected_ledger_paths & {
        item["path"] for item in bundle["canonicalArtifacts"]
    } == {ledger_index.relative_to(workspace.raw_dir).as_posix()}
    for group, path in retained_state.items():
        assert path.relative_to(workspace.raw_dir).as_posix() in {
            item["path"] for item in bundle[group]
        }
    preserved_contract = json.loads(
        retained_state["regressionResults"].read_text(encoding="utf-8")
    )
    assert preserved_contract["contractHash"] == contract_before["contractHash"]
    assert (
        verify_reconstruction_bundle(workspace.raw_dir)["bundleSha256"]
        == bundle["bundleSha256"]
    )
    restored_ledger = IterationLedgerService(workspace).current()
    contract_after = IterationLedgerService(workspace).compile_regression_contract()
    assert contract_after["contractHash"] == contract_before["contractHash"]
    assert sum(len(item["feedback"]) for item in restored_ledger["iterations"]) == 1
    assert len(restored_ledger["decisions"]) == 1
    assert sum(len(item["riskWindows"]) for item in restored_ledger["decisions"]) == 1
