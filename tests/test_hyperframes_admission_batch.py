"""Reuse physical HyperFrames observations only inside a fresh native proof batch."""

import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from avo import proof_composition
from avo.adapters.motion import hyperframes_materialize
from avo.timeline.contracts import ContractError
from avo.timeline.generated_assets import GeneratedAssetError, GeneratedAssetService
from avo.timeline.proof_validation_stage import proof_validation_batch
from tests import test_hyperframes_binding

receipt_asset = test_hyperframes_binding.receipt_asset


@pytest.fixture
def admission(receipt_asset, monkeypatch):
    workspace, record, environment = receipt_asset
    service = GeneratedAssetService(workspace)
    if not service.path(record["assetId"]).exists():
        service.register(record, hyperframes_environment=environment)
    observed, admitted = [], []
    original_admit = GeneratedAssetService.admit

    def observe(*args, **kwargs):
        observed.append(deepcopy(args[2]))
        return deepcopy(environment)

    def admit(self, *args, **kwargs):
        result = original_admit(self, *args, **kwargs)
        admitted.append(kwargs["hyperframes_environment"])
        return result

    monkeypatch.setattr(hyperframes_materialize, "observe", observe)
    monkeypatch.setattr(GeneratedAssetService, "admit", admit)
    extension = record["parameters"]["hyperframes"]
    return SimpleNamespace(
        workspace=workspace,
        record=record,
        service=service,
        environment=environment,
        observed=observed,
        admitted=admitted,
        reference={"assetId": record["assetId"], "recordHash": record["recordHash"]},
        lock=extension["inputLockRef"],
        canonical=extension["canonicalInputLock"],
        validate=proof_composition.create_generated_asset_validator(workspace),
    )


def validate(asset):
    return asset.validate(asset.reference, asset.lock, asset.canonical)


def test_one_observation_per_batch_but_every_call_is_admitted(admission):
    with proof_validation_batch():
        assert validate(admission) == admission.record
        assert validate(admission) == admission.record
        # A separate configured port shares the same current immutable batch.
        other = proof_composition.create_generated_asset_validator(admission.workspace)
        assert other(admission.reference, admission.lock, admission.canonical)
    assert len(admission.observed) == 1
    assert len(admission.admitted) == 3
    with proof_validation_batch():
        validate(admission)
    assert len(admission.observed) == 2


def test_observations_are_not_cached_outside_a_batch(admission):
    validate(admission)
    validate(admission)
    assert len(admission.observed) == len(admission.admitted) == 2


@pytest.mark.parametrize("operation", ["rename", "delete"])
def test_unrelated_preview_is_not_a_closing_guard_dependency(admission, operation):
    directory = admission.workspace.raw_dir / "edit/preview/proof-placed-unrelated"
    directory.mkdir(parents=True, exist_ok=True)
    candidate = directory / "candidate.mp4"
    published = directory / "published.mp4"
    candidate.write_bytes(b"unrelated temporary preview; not a proof input")
    try:
        with proof_validation_batch():
            assert validate(admission) == admission.record
            if operation == "rename":
                candidate.rename(published)
            else:
                candidate.unlink()
    finally:
        candidate.unlink(missing_ok=True)
        published.unlink(missing_ok=True)


@pytest.mark.parametrize("renamed", [False, True])
def test_preview_copy_quarantine_survives_inventory_isolation(admission, renamed):
    directory = admission.workspace.raw_dir / "edit/preview/proof-placed-quarantine"
    directory.mkdir(parents=True, exist_ok=True)
    preview = directory / "candidate.mp4"
    preview.write_bytes((admission.workspace.raw_dir / "original.gif").read_bytes())
    if renamed:
        preview = preview.rename(directory / "renamed-original.gif")
    try:
        with proof_validation_batch():
            with pytest.raises(ValueError, match="PROOF_FORBIDDEN_ANCESTOR"):
                validate(admission)
    finally:
        preview.unlink(missing_ok=True)


def test_cached_environment_is_not_shared_with_admission_callers(admission):
    with proof_validation_batch():
        validate(admission)
        admission.admitted[0]["captureEvidence"]["frames"].append(99)
        validate(admission)
    assert len(admission.observed) == 1
    assert admission.admitted[1]["captureEvidence"]["frames"] == [0, 4, 8]


def test_failed_admission_does_not_publish_observation_cache(admission, monkeypatch):
    original = GeneratedAssetService.admit
    calls = 0

    def fail_first(self, *args, **kwargs):
        nonlocal calls
        calls += 1
        result = original(self, *args, **kwargs)
        if calls == 1:
            raise GeneratedAssetError("admission interrupted")
        return result

    monkeypatch.setattr(GeneratedAssetService, "admit", fail_first)
    with proof_validation_batch():
        with pytest.raises(GeneratedAssetError, match="interrupted"):
            validate(admission)
        validate(admission)
    assert len(admission.observed) == 2


@pytest.mark.parametrize("changed", ["record", "source", "output", "tool"])
def test_cached_observation_never_admits_changed_dependencies(admission, changed):
    paths = {
        "record": admission.service.path(admission.record["assetId"]),
        "source": admission.workspace.raw_dir / "original.gif",
        "output": Path(admission.record["output"]["locator"]),
        "tool": admission.workspace.raw_dir / "synthetic-node.exe",
    }
    path = paths[changed]
    original = path.read_bytes()
    try:
        with pytest.raises(
            (ValueError, GeneratedAssetError),
            match="changed|mismatch|identity|fingerprint",
        ):
            with proof_validation_batch():
                validate(admission)
                if changed == "record":
                    record = deepcopy(admission.record)
                    record["parameters"]["hyperframes"]["instanceHash"] = "f" * 64
                    path.write_text(
                        json.dumps(GeneratedAssetService._seal(record)),
                        encoding="utf-8",
                    )
                else:
                    path.write_bytes(original + b"changed")
                validate(admission)
    finally:
        path.write_bytes(original)
    assert len(admission.admitted) == 1


def test_changed_binding_is_freshly_observed_and_rejected(admission, monkeypatch):
    from avo.timeline import hyperframes_binding

    original = hyperframes_binding.resolve_binding

    def changed_binding(*args, **kwargs):
        value = original(*args, **kwargs)
        value["placement"]["x"] += 1
        return value

    with pytest.raises(
        (ValueError, GeneratedAssetError), match="binding|changed|mismatch"
    ):
        with proof_validation_batch():
            validate(admission)
            monkeypatch.setattr(hyperframes_binding, "resolve_binding", changed_binding)
            validate(admission)
    assert len(admission.observed) == 2
    assert len(admission.admitted) == 1


@pytest.mark.parametrize("changed", ["source", "output", "tool"])
@pytest.mark.parametrize("operation", ["mutate", "delete"])
def test_closing_guard_checks_bytes_after_last_cached_admission(
    admission, changed, operation
):
    paths = {
        "source": admission.workspace.raw_dir / "original.gif",
        "output": Path(admission.record["output"]["locator"]),
        "tool": admission.workspace.raw_dir / "synthetic-node.exe",
    }
    path, original = paths[changed], paths[changed].read_bytes()
    try:
        with pytest.raises(ContractError, match="changed during fingerprint stage"):
            with proof_validation_batch():
                validate(admission)
                validate(admission)
                if operation == "delete":
                    path.unlink()
                else:
                    path.write_bytes(original + b"changed")
    finally:
        path.write_bytes(original)
