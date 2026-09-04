from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from avo.delivery_fidelity import resolve_delivery_fidelity_policy
from avo.timeline.contracts import content_hash, file_fingerprint, validate_document
from avo.timeline.materialize import materialize_assembly


class FakeRender:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def render(self, projection, output, **request):
        self.calls.append({"projection": projection, "output": output, **request})
        Path(output).parent.mkdir(parents=True, exist_ok=True)
        Path(output).write_bytes(b"assembly-master")
        return {
            "output": file_fingerprint(Path(output)),
            "producer": {"name": "fake-render", "version": "1"},
        }


def _lock() -> dict:
    return {
        "cmapRevisionId": "cmap-r0001",
        "cmapRevisionHash": "a" * 64,
        "syncRevisionId": "sync-r0001",
        "syncRevisionHash": "b" * 64,
        "bmapRevisionId": "bmap-r0001",
        "bmapRevisionHash": "c" * 64,
        "tracksRevisionId": "tracks-r0001",
        "tracksRevisionHash": "d" * 64,
        "rawFingerprints": {"raw": "e" * 64},
    }


def _contract() -> dict:
    return {
        "width": 1920,
        "height": 1080,
        "frameRate": {"num": 30, "den": 1, "tolerance": 0.001},
        "allowedTransformations": ["trim", "concat", "encode"],
    }


def _lineage(lock: dict, output: dict) -> dict:
    body = {
        "schemaVersion": "1.0.0",
        "canonicalInputLock": lock,
        "projectionHash": "f" * 64,
        "nodes": [
            {
                "nodeId": "base",
                "kind": "source",
                "role": "base",
                "mediaClass": "camera-original",
                "locator": "raw.mov",
                "sha256": "e" * 64,
                "pictureCarrying": True,
                "media": {},
            },
            {
                "nodeId": "output",
                "kind": "output",
                "role": "output",
                "mediaClass": "rendered-output",
                "locator": output["locator"],
                "sha256": output["sha256"],
                "pictureCarrying": True,
                "media": {},
            },
        ],
        "edges": [
            {
                "edgeId": "edge-0001",
                "from": "base",
                "to": "output",
                "operation": "encode",
                "order": 0,
                "parameters": {},
            }
        ],
        "rootIds": ["output"],
    }
    return {**body, "pictureLineageHash": content_hash(body)}


def test_assembly_materialization_binds_locks_policy_lineage_and_output(
    tmp_path, monkeypatch
):
    workspace = SimpleNamespace(timeline_dir=tmp_path / "edit" / "timeline")
    workspace.timeline_dir.mkdir(parents=True)
    projection = workspace.timeline_dir / "edl.json"
    projection.write_text("{}", encoding="utf-8")
    revisions = {"cmap": {}, "tracks": {}}
    monkeypatch.setattr(
        "avo.timeline.picture_lineage.current_assembly_lock",
        lambda _workspace: (_lock(), revisions),
    )
    monkeypatch.setattr(
        "avo.timeline.projection.write_assembly_projection",
        lambda _workspace: (projection, {"projectionHash": "f" * 64}),
    )
    monkeypatch.setattr(
        "avo.timeline.picture_lineage.build_picture_lineage",
        lambda **kwargs: _lineage(kwargs["canonical_input_lock"], kwargs["output"]),
    )
    contract = _contract()
    policy = resolve_delivery_fidelity_policy(
        profile_id="fixture-1080p", render_contract=contract
    )
    renderer = FakeRender()
    output = tmp_path / "edit" / "master.mp4"
    first = materialize_assembly(
        workspace=workspace,
        output_path=output,
        render_contract=policy["renderContract"],
        delivery_fidelity_policy=policy,
        render_port=renderer,
    )
    second = materialize_assembly(
        workspace=workspace,
        output_path=output,
        render_contract=policy["renderContract"],
        delivery_fidelity_policy=policy,
        render_port=renderer,
    )
    assert first == second
    assert len(renderer.calls) == 1
    assert first["canonicalInputLock"] == _lock()
    assert first["output"] == file_fingerprint(output)
    assert first["deliveryFidelityPolicyHash"] == policy["policyHash"]
    assert first["pictureLineageHash"] == first["pictureLineage"]["pictureLineageHash"]
    validate_document(first, "avo.materialization.schema.json")


def test_assembly_rejects_stale_immutable_record(tmp_path, monkeypatch):
    workspace = SimpleNamespace(timeline_dir=tmp_path / "edit" / "timeline")
    workspace.timeline_dir.mkdir(parents=True)
    projection = workspace.timeline_dir / "edl.json"
    projection.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        "avo.timeline.picture_lineage.current_assembly_lock",
        lambda _workspace: (_lock(), {"cmap": {}, "tracks": {}}),
    )
    monkeypatch.setattr(
        "avo.timeline.projection.write_assembly_projection",
        lambda _workspace: (projection, {"projectionHash": "f" * 64}),
    )
    monkeypatch.setattr(
        "avo.timeline.picture_lineage.build_picture_lineage",
        lambda **kwargs: _lineage(kwargs["canonical_input_lock"], kwargs["output"]),
    )
    contract = _contract()
    policy = resolve_delivery_fidelity_policy(
        profile_id="fixture-1080p", render_contract=contract
    )
    output = tmp_path / "master.mp4"
    record = materialize_assembly(
        workspace=workspace,
        output_path=output,
        render_contract=policy["renderContract"],
        delivery_fidelity_policy=policy,
        render_port=FakeRender(),
    )
    record_path = (
        workspace.timeline_dir
        / "materializations"
        / "assembly"
        / f"{record['materializationId']}.json"
    )
    stored = json.loads(record_path.read_text(encoding="utf-8"))
    stored["materializationHash"] = "0" * 64
    record_path.write_text(json.dumps(stored), encoding="utf-8")
    with pytest.raises(ValueError, match="hash mismatch"):
        materialize_assembly(
            workspace=workspace,
            output_path=output,
            render_contract=policy["renderContract"],
            delivery_fidelity_policy=policy,
            render_port=FakeRender(),
        )
