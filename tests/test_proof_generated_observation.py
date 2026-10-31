"""Repeated ranges of one verified lossless asset share pixel inspection only."""

from copy import deepcopy
from fractions import Fraction
from pathlib import Path

import pytest

from avo.adapters.media import proof_generated


def fixture():
    return {
        "path": Path("source-base.mkv"),
        "record": {"output": {"sha256": "a" * 64}},
        "operation": {
            "kind": "generated-clip",
            "outputRange": {"startFrame": 0, "endFrameExclusive": 30},
            "parameters": {"sourceRange": {"startFrame": 30, "endFrameExclusive": 60}},
        },
    }


def test_observation_reused_but_each_range_and_fingerprint_still_checked(monkeypatch):
    calls = []

    def probe(path):
        calls.append(path)
        return {
            "codec_name": "ffv1",
            "pix_fmt": "bgra",
            "r_frame_rate": "60/1",
            "nb_read_frames": "120",
            "width": 1280,
            "height": 720,
        }

    monkeypatch.setattr(proof_generated, "_probe", probe)
    monkeypatch.setattr(
        proof_generated, "_alpha_observation", lambda *args: (120, True)
    )
    spec, cache = {"width": 1280, "height": 720}, {}
    asset = fixture()
    proof_generated.inspect(asset, spec, Fraction(60), observations=cache)
    proof_generated.inspect(deepcopy(asset), spec, Fraction(60), observations=cache)
    assert len(calls) == 1
    wrong = deepcopy(asset)
    wrong["operation"]["parameters"]["sourceRange"]["endFrameExclusive"] = 121
    with pytest.raises(RuntimeError, match="frame range"):
        proof_generated.inspect(wrong, spec, Fraction(60), observations=cache)
    changed = deepcopy(asset)
    changed["record"]["output"]["sha256"] = "b" * 64
    proof_generated.inspect(changed, spec, Fraction(60), observations=cache)
    proof_generated.inspect(asset, spec, Fraction(60), observations={})
    assert len(calls) == 3


def verification_fixture(tmp_path, monkeypatch, *, adapter="native-source-composite"):
    from unittest.mock import Mock

    record_path = tmp_path / "record.json"
    record_path.write_bytes(b"record-1")
    operation = {
        "operationId": "overlay-1",
        "kind": "overlay-video",
        "outputRange": {"startFrame": 0, "endFrameExclusive": 30},
        "parameters": {
            "generatedAssetRef": {
                "assetId": "source-base",
                "locator": str(record_path),
                "recordHash": "a" * 64,
            },
            "inputLockRef": {"path": "lock.json", "sha256": "b" * 64},
            "sourceFingerprint": {"locator": "base.mkv", "sha256": "c" * 64},
            "sourceRange": {"startFrame": 0, "endFrameExclusive": 30},
            "placement": {"x": 0, "y": 0, "width": 1280, "height": 720},
        },
    }

    def verified(op, *_args):
        return {
            "operation": deepcopy(op),
            "record": {
                "generator": {"adapterId": adapter},
                "output": deepcopy(op["parameters"]["sourceFingerprint"]),
            },
            "path": Path("base.mkv"),
        }

    verifier = Mock(side_effect=verified)
    monkeypatch.setattr(proof_generated, "verify", verifier)
    return operation, verifier, record_path


def test_generic_verification_reused_with_current_range_and_geometry(
    tmp_path, monkeypatch
):
    operation, verifier, _ = verification_fixture(tmp_path, monkeypatch)
    observations = {}
    first = proof_generated.verify_cached(operation, {}, None, None, observations)
    current = deepcopy(operation)
    current["operationId"] = "overlay-2"
    current["outputRange"] = {"startFrame": 60, "endFrameExclusive": 90}
    current["parameters"]["sourceRange"] = {
        "startFrame": 30,
        "endFrameExclusive": 60,
    }
    current["parameters"]["placement"]["x"] = 400
    second = proof_generated.verify_cached(current, {}, None, None, observations)
    assert verifier.call_count == 1
    assert second["operation"] == current
    assert second["operation"] is not current
    assert first["operation"]["parameters"]["placement"]["x"] == 0

    monkeypatch.setattr(
        proof_generated,
        "_probe",
        lambda _: {
            "codec_name": "ffv1",
            "pix_fmt": "bgra",
            "r_frame_rate": "60/1",
            "width": 1280,
            "height": 720,
        },
    )
    monkeypatch.setattr(
        proof_generated, "_alpha_observation", lambda *args: (120, False)
    )
    proof_generated.inspect(second, {"width": 1920, "height": 1080}, Fraction(60))
    current["parameters"]["placement"]["x"] = 1920
    invalid = proof_generated.verify_cached(current, {}, None, None, observations)
    with pytest.raises(RuntimeError, match="canvas"):
        proof_generated.inspect(invalid, {"width": 1920, "height": 1080}, Fraction(60))
    assert verifier.call_count == 1


@pytest.mark.parametrize(
    "field", ["generatedAssetRef", "sourceFingerprint", "inputLockRef"]
)
def test_changed_reference_forces_fresh_verification(tmp_path, monkeypatch, field):
    operation, verifier, _ = verification_fixture(tmp_path, monkeypatch)
    observations = {}
    proof_generated.verify_cached(operation, {}, None, None, observations)
    changed = deepcopy(operation)
    key = "recordHash" if field == "generatedAssetRef" else "sha256"
    changed["parameters"][field][key] = "d" * 64
    proof_generated.verify_cached(changed, {}, None, None, observations)
    assert verifier.call_count == 2


def test_code_drawn_admission_is_never_reused(tmp_path, monkeypatch):
    operation, verifier, _ = verification_fixture(
        tmp_path, monkeypatch, adapter="code-drawn"
    )
    observations = {}
    proof_generated.verify_cached(operation, {}, None, None, observations)
    proof_generated.verify_cached(operation, {}, None, None, observations)
    assert verifier.call_count == 2
    assert observations == {}


def test_cached_asset_is_defensively_copied(tmp_path, monkeypatch):
    operation, verifier, _ = verification_fixture(tmp_path, monkeypatch)
    observations = {}
    first = proof_generated.verify_cached(operation, {}, None, None, observations)
    first["record"]["generator"]["adapterId"] = "tampered"
    second = proof_generated.verify_cached(operation, {}, None, None, observations)
    assert second["record"]["generator"]["adapterId"] == "native-source-composite"
    assert verifier.call_count == 1


def test_explicit_caches_do_not_cross_execution_or_canonical_lock(
    tmp_path, monkeypatch
):
    operation, verifier, _ = verification_fixture(tmp_path, monkeypatch)
    observations = {}
    proof_generated.verify_cached(operation, {"cmap": "old"}, None, None, observations)
    proof_generated.verify_cached(operation, {"cmap": "new"}, None, None, observations)
    proof_generated.verify_cached(operation, {"cmap": "new"}, None, None, {})
    assert verifier.call_count == 3


def test_record_bytes_join_batch_fresh_closing_guard(tmp_path, monkeypatch):
    import os

    from avo.timeline.contracts import ContractError
    from avo.timeline.proof_validation_stage import proof_validation_batch

    operation, verifier, record_path = verification_fixture(tmp_path, monkeypatch)
    finished_body = False
    with pytest.raises(ContractError, match="changed"):
        with proof_validation_batch():
            proof_generated.verify_cached(operation, {}, None, None, {})
            before = record_path.stat()
            record_path.write_bytes(b"record-2")
            os.utime(record_path, ns=(before.st_atime_ns, before.st_mtime_ns))
            finished_body = True
    assert finished_body
    assert verifier.call_count == 1


def test_record_change_outside_batch_cannot_reuse_observation(tmp_path, monkeypatch):
    operation, verifier, record_path = verification_fixture(tmp_path, monkeypatch)
    observations = {}
    proof_generated.verify_cached(operation, {}, None, None, observations)
    record_path.write_bytes(b"record-2")
    with pytest.raises(RuntimeError, match="record.*changed"):
        proof_generated.verify_cached(operation, {}, None, None, observations)
    assert verifier.call_count == 1
