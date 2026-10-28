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


def test_code_drawn_registration_cannot_use_legacy_output_only_path(tmp_path):
    output = tmp_path / "drawing.mkv"
    output.write_bytes(b"synthetic drawing output")
    record = _record(output)
    record["generator"]["adapterId"] = "code-drawn"
    record["parameters"] = {"codeDrawn": {}}
    with pytest.raises(
        GeneratedAssetError, match="(?i)code.drawn|environment|fresh|binding"
    ):
        GeneratedAssetService(_workspace(tmp_path)).register(record)


def test_code_drawn_old_admit_signature_blocks_even_a_saved_verified_record(tmp_path):
    import json

    output = tmp_path / "drawing.mkv"
    output.write_bytes(b"synthetic drawing output")
    record = _record(output)
    record["generator"]["adapterId"] = "code-drawn"
    record["parameters"] = {"codeDrawn": {}}
    service = GeneratedAssetService(_workspace(tmp_path))
    saved = service._seal(record)
    service.directory.mkdir(parents=True)
    service.path(saved["assetId"]).write_text(json.dumps(saved), encoding="utf-8")
    with pytest.raises(
        GeneratedAssetError, match="(?i)code.drawn|environment|fresh|binding"
    ):
        service.admit(saved["assetId"])


def test_code_drawn_admission_uses_actual_canonical_stores_and_supplied_observations(
    tmp_path, monkeypatch
):
    import builtins
    import subprocess

    from tests.code_drawn_asset_fixture import canonical_asset

    asset = canonical_asset(tmp_path)
    original_import = builtins.__import__

    def domain_import(name, *args, **kwargs):
        assert not name.startswith(("playwright", "avo.adapters.motion")), (
            "Domain imported browser runtime"
        )
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", domain_import)
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: pytest.fail("Domain launched a runtime"),
    )
    service = GeneratedAssetService(asset.workspace)
    registered = service.register(
        asset.record, code_drawn_environment=asset.environment
    )
    admitted = service.admit(
        registered["assetId"], code_drawn_environment=asset.environment
    )
    assert admitted["recordHash"] == registered["recordHash"]
    assert (
        admitted["parameters"]["codeDrawn"]["inputLockRef"]
        == asset.record["parameters"]["codeDrawn"]["inputLockRef"]
    )
    assert (
        admitted["parameters"]["codeDrawn"]["canonicalInputLock"]
        == asset.lock["canonicalInputLock"]
    )


@pytest.mark.parametrize(
    "change",
    [
        "source",
        "font",
        "brush",
        "manifest",
        "seed",
        "contract",
        "runtime",
        "generator",
        "canonical",
    ],
)
def test_code_drawn_admission_rechecks_complete_current_inputs(
    tmp_path, monkeypatch, change
):
    from copy import deepcopy

    from avo import motion
    from avo.timeline.animation import AnimationService
    from tests.code_drawn_asset_fixture import canonical_asset, write_manifest

    asset = canonical_asset(tmp_path)
    service = GeneratedAssetService(asset.workspace)
    registered = service.register(
        asset.record, code_drawn_environment=asset.environment
    )
    observed = deepcopy(asset.environment)
    if change in {"source", "font", "brush"}:
        path = getattr(asset, change)
        path.write_bytes(path.read_bytes() + b"changed")
    elif change in {"manifest", "seed", "contract"}:
        value = deepcopy(asset.manifest)
        if change == "manifest":
            value["sourceRevision"] = "source-r0002"
        elif change == "seed":
            value["seed"] += 1
        else:
            value["renderContract"]["frameCount"] += 1
        write_manifest(asset.composition, value)
    elif change == "runtime":
        observed["graphics"] = "different-observed-graphics"
    elif change == "generator":
        changed = {**asset.lock["generator"], "sourceSha256": "0" * 64}
        monkeypatch.setattr(motion, "_drawing_generator_identity", lambda: changed)
    else:
        strategy = deepcopy(asset.strategy)
        strategy["density"] = 3
        AnimationService(asset.workspace).author(
            strategy, actor="unit-test", reason="new canonical strategy"
        )
    with pytest.raises(
        GeneratedAssetError,
        match="(?i)stale|changed|mismatch|current|canonical|fingerprint|binding|input|environment",
    ):
        service.admit(registered["assetId"], code_drawn_environment=observed)


def test_code_drawn_resealed_canonical_lie_is_not_workspace_authority(tmp_path):
    from tests.code_drawn_asset_fixture import (
        canonical_asset,
        forge_current_looking_binding,
    )

    asset = canonical_asset(tmp_path)
    forged = forge_current_looking_binding(asset)
    with pytest.raises(
        GeneratedAssetError, match="(?i)canonical|binding|current|mismatch|stale"
    ):
        GeneratedAssetService(asset.workspace).register(
            forged, code_drawn_environment=asset.environment
        )


def test_code_drawn_cached_admission_still_requires_fresh_observations(tmp_path):
    from tests.code_drawn_asset_fixture import canonical_asset

    asset = canonical_asset(tmp_path)
    service = GeneratedAssetService(asset.workspace)
    registered = service.register(
        asset.record, code_drawn_environment=asset.environment
    )
    with pytest.raises(GeneratedAssetError, match="(?i)environment|fresh|observation"):
        service.admit(registered["assetId"])


def test_code_drawn_known_proof_bytes_cannot_enter_as_redeclared_font_dependency(
    tmp_path,
):
    from avo.motion import MotionError
    from tests.code_drawn_asset_fixture import canonical_asset

    with pytest.raises(
        (MotionError, GeneratedAssetError), match="(?i)forbidden|ancestor|quarantin"
    ):
        asset = canonical_asset(tmp_path, forbidden_dependency=True)
        GeneratedAssetService(asset.workspace).register(
            asset.record, code_drawn_environment=asset.environment
        )


def test_generated_proof_input_resolution_keeps_receipt_identity_without_claiming_admission(
    tmp_path, monkeypatch
):
    from avo.timeline.materialize import canonical_proof_media_inputs
    from tests.code_drawn_asset_fixture import canonical_asset

    asset = canonical_asset(tmp_path)
    service = GeneratedAssetService(asset.workspace)
    record = service.register(asset.record, code_drawn_environment=asset.environment)
    plan = {
        "checkpoint": "motion-proof",
        "canonicalInputLock": {
            "source:camera": file_fingerprint(asset.workspace.raw_dir / "raw.bin")[
                "sha256"
            ],
            "generated:" + record["assetId"]: record["recordHash"],
            "input-lock:" + asset.lock["instanceId"]: asset.lock["inputLockHash"],
        },
    }
    monkeypatch.setattr(
        GeneratedAssetService,
        "admit",
        lambda *args, **kwargs: pytest.fail("Resolution is not admission"),
    )
    resolved = canonical_proof_media_inputs(asset.workspace, plan)
    value = resolved["generated:" + record["assetId"]]
    assert value["path"] == asset.output
    assert value["kind"] == value["mediaClass"] == "generated"
    assert value["generatedAssetRef"]["recordHash"] == record["recordHash"]
    assert value["inputLockRef"] == record["parameters"]["codeDrawn"]["inputLockRef"]
    assert "admitted" not in value
    assert resolved["camera"]["path"] == asset.workspace.raw_dir / "raw.bin"
    plan["canonicalInputLock"]["generated:" + record["assetId"]] = "0" * 64
    with pytest.raises(ValueError, match="receipt.*proof lock"):
        canonical_proof_media_inputs(asset.workspace, plan)
