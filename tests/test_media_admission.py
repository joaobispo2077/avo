from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from avo.delivery_fidelity import resolve_delivery_fidelity_policy
from avo.timeline.contracts import file_fingerprint
from avo.timeline.materialize import materialize_assembly
from avo.timeline.media_admission import MediaAdmissionError, require_media_admission
from avo.timeline.migration import (
    inventory_historical_output_fingerprints,
    legacy_edl_snapshots,
)


def _node(path: Path, **values) -> dict:
    return {
        "nodeId": values.pop("nodeId", path.stem),
        "kind": values.pop("kind", "source"),
        "role": values.pop("role", "base"),
        "mediaClass": values.pop("mediaClass", "camera-original"),
        **file_fingerprint(path),
        "pictureCarrying": values.pop("pictureCarrying", True),
        "audioCarrying": values.pop("audioCarrying", False),
        **values,
    }


def _original(path: Path, source_id: str = "camera") -> dict:
    return {"sourceId": source_id, "fingerprint": file_fingerprint(path)}


def _asset(asset_id: str, output: Path, inputs: list[dict], **values) -> dict:
    return {
        "assetId": asset_id,
        "output": file_fingerprint(output),
        "inputs": inputs,
        "sourceFree": not inputs,
        "reproducibility": values.pop("reproducibility", "verified"),
        "approvalReference": values.pop("approvalReference", None),
        **values,
    }


def _ref(artifact_id: str, path: Path, role: str) -> dict:
    return {
        "artifactId": artifact_id,
        "fingerprint": file_fingerprint(path),
        "ancestryRole": role,
    }


def test_registered_original_and_current_generated_asset_are_admitted(tmp_path: Path):
    raw = tmp_path / "camera.mov"
    graphic = tmp_path / "graphic.png"
    raw.write_bytes(b"original")
    graphic.write_bytes(b"generated")
    assets = {
        "graphic-current": _asset(
            "graphic-current", graphic, [_ref("camera", raw, "source")]
        )
    }
    report = require_media_admission(
        [
            _node(raw),
            _node(
                graphic,
                nodeId="graphic",
                kind="generated",
                mediaClass="generated",
                assetId="graphic-current",
            ),
        ],
        registered_originals=[_original(raw)],
        generated_assets=assets,
    )
    assert report["status"] == "pass"
    assert {item["admission"] for item in report["admitted"]} == {
        "registered-original",
        "canonical-generated-asset",
    }


@pytest.mark.parametrize("role", ["proof", "preview", "proxy", "master", "delivery"])
def test_output_roles_are_quarantined_with_exact_evidence(tmp_path: Path, role: str):
    output = tmp_path / f"old-{role}.mp4"
    output.write_bytes(role.encode())
    node = _node(output, nodeId=f"node-{role}", role=role, mediaClass=role)
    with pytest.raises(MediaAdmissionError) as raised:
        require_media_admission([node])
    assert raised.value.code == "PROOF_FORBIDDEN_ANCESTOR"
    assert raised.value.finding["nodeId"] == f"node-{role}"
    assert raised.value.finding["locator"] == str(output)
    assert raised.value.finding["sha256"] == file_fingerprint(output)["sha256"]


def test_copied_or_renamed_known_output_is_blocked_by_fingerprint(tmp_path: Path):
    proof = tmp_path / "proof.mp4"
    renamed = tmp_path / "innocent-name.mov"
    proof.write_bytes(b"old-proof")
    renamed.write_bytes(proof.read_bytes())
    known = [{**file_fingerprint(proof), "role": "proof"}]
    with pytest.raises(MediaAdmissionError, match="PROOF_FORBIDDEN_ANCESTOR"):
        require_media_admission([_node(renamed)], known_outputs=known)


def test_unregistered_transformed_or_legacy_input_remains_ambiguous(tmp_path: Path):
    transformed = tmp_path / "crop.mp4"
    transformed.write_bytes(b"re-encoded-old-proof")
    with pytest.raises(MediaAdmissionError) as raised:
        require_media_admission([_node(transformed, provenanceStatus="unverifiable")])
    assert raised.value.code == "PROOF_MEDIA_QUARANTINED"
    assert raised.value.finding["reason"] == "unregistered-or-ambiguous"


def test_generated_asset_ancestry_is_recursive_and_rejects_known_output(tmp_path: Path):
    proof = tmp_path / "proof.mp4"
    nested = tmp_path / "nested.png"
    proof.write_bytes(b"proof")
    nested.write_bytes(b"nested")
    assets = {
        "nested": _asset("nested", nested, [_ref("old-proof", proof, "dependency")])
    }
    with pytest.raises(MediaAdmissionError) as raised:
        require_media_admission(
            [_node(nested, kind="generated", assetId="nested")],
            generated_assets=assets,
            known_outputs=[{**file_fingerprint(proof), "role": "proof"}],
        )
    assert raised.value.code == "PROOF_FORBIDDEN_ANCESTOR"
    assert raised.value.finding["artifactId"] == "old-proof"


def test_generated_asset_cycle_blocks_admission(tmp_path: Path):
    a = tmp_path / "a.bin"
    b = tmp_path / "b.bin"
    a.write_bytes(b"a")
    b.write_bytes(b"b")
    assets = {
        "asset-a": _asset("asset-a", a, [_ref("asset-b", b, "generated")]),
        "asset-b": _asset("asset-b", b, [_ref("asset-a", a, "generated")]),
    }
    with pytest.raises(MediaAdmissionError) as raised:
        require_media_admission(
            [_node(a, kind="generated", assetId="asset-a")],
            generated_assets=assets,
        )
    assert raised.value.code == "PROOF_ANCESTRY_CYCLE"


def test_migration_inventories_outputs_and_marks_legacy_assets_unverifiable(
    tmp_path: Path,
):
    proof = tmp_path / "edit" / "proofs" / "old.mp4"
    proof.parent.mkdir(parents=True)
    proof.write_bytes(b"old proof")
    assert inventory_historical_output_fingerprints(tmp_path) == [
        {**file_fingerprint(proof), "role": "proof", "path": str(proof)}
    ]
    overlay = tmp_path / "overlay.png"
    overlay.write_bytes(b"legacy derived bytes")
    edl_path = tmp_path / "edl.json"
    edl_path.write_text("{}", encoding="utf-8")
    snapshots, findings = legacy_edl_snapshots(
        {
            "sources": {"camera": "missing.mov"},
            "ranges": [{"source": "camera", "start": 0, "end": 1}],
            "overlays": [{"file": "overlay.png", "start_in_output": 0, "duration": 1}],
        },
        edl_path=edl_path,
    )
    source = snapshots["tracks"]["videoTracks"]["layers"][0]["source"]
    assert source["provenanceStatus"] == "unverifiable"
    assert any(item["classification"] == "unverifiable-input" for item in findings)


def test_materialization_blocks_known_output_before_renderer_execution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    raw = tmp_path / "camera.mov"
    proof = tmp_path / "old-proof.mp4"
    copied = tmp_path / "asset.mov"
    raw.write_bytes(b"raw")
    proof.write_bytes(b"proof")
    copied.write_bytes(proof.read_bytes())
    revisions = {
        "cmap": {
            "snapshot": {
                "sources": [
                    {
                        "sourceId": "camera",
                        "kind": "raw",
                        "locator": str(raw),
                        "fingerprint": file_fingerprint(raw),
                    }
                ]
            }
        },
        "tracks": {
            "snapshot": {
                "videoTracks": {
                    "layers": [
                        {
                            "layerId": "copied-proof",
                            "role": "overlay",
                            "source": file_fingerprint(copied),
                        }
                    ]
                },
                "audioTracks": {"layers": []},
            }
        },
    }
    lock = {
        "cmapRevisionId": "cmap-r1",
        "cmapRevisionHash": "a" * 64,
        "syncRevisionId": "sync-r1",
        "syncRevisionHash": "b" * 64,
        "bmapRevisionId": "bmap-r1",
        "bmapRevisionHash": "c" * 64,
        "tracksRevisionId": "tracks-r1",
        "tracksRevisionHash": "d" * 64,
        "rawFingerprints": {"camera": file_fingerprint(raw)["sha256"]},
    }
    monkeypatch.setattr(
        "avo.timeline.picture_lineage.current_assembly_lock",
        lambda _workspace: (lock, revisions),
    )
    contract = {
        "width": 160,
        "height": 90,
        "frameRate": {"num": 24, "den": 1, "tolerance": 0.001},
        "allowedTransformations": ["trim", "concat", "encode"],
    }
    policy = resolve_delivery_fidelity_policy(
        profile_id="synthetic", render_contract=contract
    )

    class Renderer:
        calls = 0

        def render(self, *_args, **_kwargs):
            self.calls += 1
            raise AssertionError("renderer must not run")

    renderer = Renderer()
    workspace = SimpleNamespace(
        raw_dir=tmp_path, timeline_dir=tmp_path / "edit" / "timeline"
    )
    workspace.timeline_dir.mkdir(parents=True)
    with pytest.raises(MediaAdmissionError) as raised:
        materialize_assembly(
            workspace=workspace,
            output_path=tmp_path / "candidate.mp4",
            render_contract=contract,
            delivery_fidelity_policy=policy,
            render_port=renderer,
            media_admission={
                "knownOutputs": [{**file_fingerprint(proof), "role": "proof"}]
            },
        )
    assert raised.value.finding["nodeId"] == "track-copied-proof"
    assert raised.value.finding["locator"] == str(copied)
    assert renderer.calls == 0
