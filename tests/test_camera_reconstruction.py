"""Retain observed camera gate metadata, never decoder executables or proofs."""

import json

import pytest

from avo.timeline.contracts import content_hash
from avo.timeline.reconstruction import (
    ReconstructionError,
    build_reconstruction_bundle,
    verify_reconstruction_bundle,
)
from tests.test_reconstruction_bundle import canonical_project


def test_reconstruction_retains_camera_gate_identity_and_detects_tampering(tmp_path):
    workspace, basename = canonical_project(tmp_path)
    root = workspace.timeline_dir / "microproofs" / "camera-plan"
    root.mkdir(parents=True)
    # Metadata retention fixture; decoder execution is covered by native tests.
    gate = {
        "proofPlanHash": "a" * 64,
        "cameraEnvironmentHash": "b" * 64,
        "results": [
            {
                "cameraProvenance": {
                    "environmentHash": "b" * 64,
                    "recipeHash": "c" * 64,
                    "runtime": {"ffmpeg": {"sha256": "d" * 64}},
                }
            }
        ],
    }
    gate["gateHash"] = content_hash(gate)
    path = root / "gate.json"
    path.write_text(json.dumps(gate), encoding="utf-8")
    (root / "window.mkv").write_bytes(b"Disposable proof, never a source")
    bundle = build_reconstruction_bundle(
        workspace, master_basename=basename, actor="creator"
    )
    relative = path.relative_to(workspace.raw_dir).as_posix()
    entries = [entry for entry in bundle["files"] if entry["path"] == relative]
    assert len(entries) == 1
    assert entries[0]["role"] == "ancestry-evidence"
    assert all(not entry["path"].endswith("window.mkv") for entry in bundle["files"])
    verify_reconstruction_bundle(tmp_path)
    path.write_text("{}", encoding="utf-8")
    with pytest.raises(ReconstructionError, match="changed"):
        verify_reconstruction_bundle(tmp_path)
