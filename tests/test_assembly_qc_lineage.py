import json
from copy import deepcopy
from types import SimpleNamespace

import pytest

from avo.adapters.qc import cut_proof
from avo.timeline.contracts import content_hash, file_fingerprint
from avo.timeline.store import atomic_write_json
from test_materialization_schema import _assembly


@pytest.fixture
def assembly(tmp_path):
    candidate = tmp_path / "master.mp4"
    candidate.write_bytes(b"fixture master bytes")
    record = _assembly()
    record["output"] = {**file_fingerprint(candidate), "locator": str(candidate)}
    record["pictureLineage"]["nodes"][-1].update(
        locator=str(candidate), sha256=record["output"]["sha256"]
    )
    lineage = record["pictureLineage"]
    lineage["pictureLineageHash"] = content_hash(
        {key: value for key, value in lineage.items() if key != "pictureLineageHash"}
    )
    record["pictureLineageHash"] = lineage["pictureLineageHash"]
    record["materializationHash"] = content_hash(
        {key: value for key, value in record.items() if key != "materializationHash"}
    )
    path = tmp_path / "assembly.json"
    atomic_write_json(path, record)
    lock = record["canonicalInputLock"]
    dependencies = {
        "cmap": lock["cmapRevisionHash"],
        "sync-map": lock["syncRevisionHash"],
        "bmap": lock["bmapRevisionHash"],
        "tracks": lock["tracksRevisionHash"],
        "raw": content_hash(lock["rawFingerprints"]),
        "materialization": record["materializationHash"],
        "assembly-output": record["output"]["sha256"],
        "delivery-fidelity-policy": record["deliveryFidelityPolicyHash"],
        "picture-lineage": record["pictureLineageHash"],
    }

    class Store:
        def __init__(self, name):
            self.name = "sync" if name == "sync-map" else name

        def load_index(self):
            return {
                "headRevisionId": lock[f"{self.name}RevisionId"],
                "revisionRefs": [
                    {
                        "revisionId": lock[f"{self.name}RevisionId"],
                        "contentSha256": lock[f"{self.name}RevisionHash"],
                    }
                ],
            }

        def effective_approval(self):
            return {"subject": {"contentSha256": lock["syncRevisionHash"]}}

    workspace = SimpleNamespace(
        store=lambda name: Store(name),
        require_active=lambda name: Store(name).load_index(),
    )
    probe = {
        "streams": [
            {
                "codec_type": "video",
                "width": 1920,
                "height": 1080,
                "avg_frame_rate": "30000/1001",
                "codec_name": "h264",
            }
        ],
        "format": {"duration": "10", "size": str(candidate.stat().st_size)},
    }
    return workspace, record, candidate, dependencies, path, probe


def _check(assembly):
    workspace, record, candidate, dependencies, path, probe = assembly
    cut_proof._require_cut_lineage(
        workspace,
        record,
        candidate,
        dependencies,
        materialization_path=path,
        probe=probe,
    )


def test_assembly_qc_uses_persisted_lineage_without_legacy_projection(
    assembly, monkeypatch
):
    monkeypatch.setattr(
        cut_proof, "verify_projection", lambda _: pytest.fail("legacy projection used")
    )
    _check(assembly)


@pytest.mark.parametrize("field", ["materialization", "raw", "bmap", "tracks"])
def test_assembly_qc_rejects_conflicting_dependencies(assembly, field):
    assembly[3][field] = "0" * 64
    with pytest.raises(ValueError, match="dependenc"):
        _check(assembly)


def test_assembly_qc_requires_persisted_identical_record(assembly):
    changed = deepcopy(assembly[1])
    changed["renderProfile"] = "other"
    atomic_write_json(assembly[4], changed)
    with pytest.raises(ValueError, match="persisted"):
        _check(assembly)


def test_assembly_qc_rejects_changed_master_bytes(assembly):
    assembly[2].write_bytes(b"different master bytes")
    with pytest.raises(ValueError, match="candidate"):
        _check(assembly)


def test_assembly_qc_rejects_rehashed_forbidden_ancestry(assembly):
    record = assembly[1]
    lineage = record["pictureLineage"]
    lineage["nodes"][0]["mediaClass"] = "proof"
    lineage["pictureLineageHash"] = content_hash(
        {key: value for key, value in lineage.items() if key != "pictureLineageHash"}
    )
    record["pictureLineageHash"] = lineage["pictureLineageHash"]
    record["materializationHash"] = content_hash(
        {key: value for key, value in record.items() if key != "materializationHash"}
    )
    atomic_write_json(assembly[4], record)
    assembly[3].update(
        {
            "picture-lineage": record["pictureLineageHash"],
            "materialization": record["materializationHash"],
        }
    )
    with pytest.raises(ValueError, match="(?i)lineage|fidelity|ancestor"):
        _check(assembly)


def test_assembly_qc_rejects_stale_head_even_with_matching_review_lock(assembly):
    workspace = assembly[0]
    original = workspace.require_active

    def changed(name):
        index = original(name)
        if name == "tracks":
            index["headRevisionId"] = "tracks-r0002"
            index["revisionRefs"].append(
                {"revisionId": "tracks-r0002", "contentSha256": "0" * 64}
            )
        return index

    workspace.require_active = changed
    with pytest.raises(ValueError, match="tracks dependency is not current"):
        _check(assembly)


def test_assembly_qc_rejects_modified_materialization_hash(assembly):
    record = assembly[1]
    record["renderHash"] = "0" * 64
    atomic_write_json(assembly[4], record)
    with pytest.raises(ValueError, match="fidelity"):
        _check(assembly)


def test_qc_adapter_passes_assembly_contract_and_probe(assembly, monkeypatch):
    workspace, record, candidate, dependencies, path, probe = assembly
    monkeypatch.setattr(
        cut_proof.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(stdout=json.dumps(probe)),
    )
    monkeypatch.setattr(cut_proof, "_join_windows", lambda _: [])
    result = cut_proof.CutProofQcAdapter().check(
        candidate,
        workspace=workspace,
        materialization=record,
        materialization_path=path,
        dependencies=dependencies,
    )
    assert result["status"] == "pass"
    assert result["findings"] == []


@pytest.mark.parametrize("field", ["projectionHash", "root"])
def test_assembly_qc_rejects_rehashed_disconnected_lineage(assembly, field):
    record = assembly[1]
    graph = record["pictureLineage"]
    if field == "root":
        graph["nodes"][-1]["sha256"] = "0" * 64
    else:
        graph[field] = "0" * 64
    graph["pictureLineageHash"] = content_hash(
        {key: value for key, value in graph.items() if key != "pictureLineageHash"}
    )
    record["pictureLineageHash"] = graph["pictureLineageHash"]
    record["materializationHash"] = content_hash(
        {key: value for key, value in record.items() if key != "materializationHash"}
    )
    atomic_write_json(assembly[4], record)
    assembly[3].update(
        {
            "picture-lineage": record["pictureLineageHash"],
            "materialization": record["materializationHash"],
        }
    )
    with pytest.raises(ValueError, match="lineage"):
        _check(assembly)
