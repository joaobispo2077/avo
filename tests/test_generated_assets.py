from __future__ import annotations

from types import SimpleNamespace

import pytest

from avo.timeline.contracts import file_fingerprint
from avo.timeline.generated_assets import GeneratedAssetError, GeneratedAssetService

HASH_A = "a" * 64


def _workspace(tmp_path):
    return SimpleNamespace(timeline_dir=tmp_path / "edit" / "timeline")


def _record(path, reproducibility="verified"):
    output = file_fingerprint(path)
    return {
        "assetId": "asset-title-card",
        "role": "authored-graphic",
        "generator": {
            "adapterId": "hyperframes",
            "version": "1.0.0",
            "executableSha256": HASH_A,
        },
        "parameters": {"title": "Friday Night"},
        "inputs": [],
        "sourceFree": True,
        "environment": {"platform": "test", "dependencies": {}},
        "output": output,
        "reproducibility": reproducibility,
        "approvalReference": None,
    }


def test_generated_asset_is_fingerprinted_immutable_and_admitted(tmp_path):
    output = tmp_path / "title.png"
    output.write_bytes(b"generated-title")
    service = GeneratedAssetService(_workspace(tmp_path))
    first = service.register(_record(output))
    assert service.admit(first["assetId"])["recordHash"] == first["recordHash"]
    assert service.register(_record(output)) == first
    output.write_bytes(b"changed")
    with pytest.raises(GeneratedAssetError, match="changed"):
        service.admit(first["assetId"])


def test_unverified_generated_output_is_reference_only(tmp_path):
    output = tmp_path / "draft.png"
    output.write_bytes(b"draft")
    service = GeneratedAssetService(_workspace(tmp_path))
    service.register(_record(output, reproducibility="unverified"))
    with pytest.raises(GeneratedAssetError, match="reference-only"):
        service.admit("asset-title-card")
