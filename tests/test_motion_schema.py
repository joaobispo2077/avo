"""Motion data contracts: strict choices, immutable identities and local inputs."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from avo.motion import (
    MotionError,
    load_composition,
    seal_composition,
    seal_input_lock,
    validate_composition,
    validate_engine,
    validate_input_lock,
    validate_motion_config,
)
from avo.timeline.contracts import (
    ContractError,
    content_hash,
    document_hash_excluding,
    file_fingerprint,
    validate_document,
)

SHA = "a" * 64
MOTION_CONFIG = "avo.motion.schema.json#/$defs/config"
MOTION_SELECTION = "avo.motion.schema.json#/$defs/selection"
RESOLVED_SELECTION = "avo.motion.schema.json#/$defs/resolvedSelection"
COMPOSITION = "avo.code-drawn.schema.json"
INPUT_LOCK = "avo.code-drawn.schema.json#/$defs/inputLock"


@pytest.fixture
def composition(tmp_path: Path) -> dict:
    entry = tmp_path / "index.html"
    entry.write_text(
        '<!doctype html><canvas id="avo-stage"></canvas>'
        "<script>window.avoReady=Promise.resolve();window.seek=()=>true;</script>",
        encoding="utf-8",
    )
    fingerprint = file_fingerprint(entry)
    return seal_composition(
        {
            "schemaVersion": "1.0.0",
            "compositionId": "motion-example",
            "engine": "code-drawn",
            "drawingRoute": "canvas",
            "entry": "index.html",
            "sourceRevision": "source-r0001",
            "files": [
                {
                    "path": "index.html",
                    "sha256": fingerprint["sha256"],
                    "sizeBytes": fingerprint["sizeBytes"],
                    "role": "source",
                }
            ],
            "assets": [],
            "dependencies": [],
            "seed": 7,
            "renderContract": {
                "width": 1280,
                "height": 720,
                "frameRate": {"num": 30000, "den": 1001},
                "frameCount": 90,
                "background": {"mode": "opaque", "color": "#121212"},
                "alphaMode": "opaque",
                "captureColorSpace": "srgb",
                "compositeColorSpace": "sdr-bt709",
                "quality": {"spatialSamples": 1, "temporalSamples": 1},
            },
        }
    )


@pytest.fixture
def input_lock() -> dict:
    return seal_input_lock(
        {
            "schemaVersion": "1.0.0",
            "bindingMode": "standalone",
            "instanceId": "motion-instance",
            "manifestRef": {
                "path": "edit/derived/components/motion-instance/composition.json",
                "sha256": SHA,
            },
            "renderContractHash": SHA,
            "inputsHash": content_hash([]),
            "inputs": [],
            "generator": {
                "adapterId": "code-drawn",
                "version": "1.0.0",
                "executableSha256": SHA,
                "sourceSha256": SHA,
            },
            "environment": {"platform": "test", "dependencies": {}},
        }
    )


@pytest.fixture
def selection() -> dict:
    return {
        "engine": "code-drawn",
        "source": "invocation",
        "advanced": True,
        "resolutionHash": SHA,
        "maskedChoices": [],
    }


@pytest.mark.parametrize("engine", ["hyperframes", "remotion", "code-drawn"])
def test_engine_ids_and_config_preserve_explicit_choice(engine: str) -> None:
    assert validate_engine(engine) == engine
    config = {"engine": engine}
    assert validate_motion_config(config) == config
    assert validate_document(config, MOTION_CONFIG) == config


@pytest.mark.parametrize(
    "value", [None, "", "none", "canvas", "HyperFrames", " code-drawn ", 1, False]
)
def test_engine_rejects_missing_alias_and_noncanonical_values(value) -> None:
    with pytest.raises(MotionError) as caught:
        validate_engine(value)
    assert caught.value.code == "MOTION_ENGINE_INVALID"


def test_empty_config_means_inherit_without_inserting_default() -> None:
    assert validate_motion_config({}) == {}
    assert validate_document({}, MOTION_CONFIG) == {}


@pytest.mark.parametrize(
    "value",
    [
        None,
        [],
        {"engine": None},
        {"engine": ""},
        {"engine": "none"},
        {"engine": "code-drawn", "command": "external-program"},
    ],
)
def test_config_rejects_invalid_explicit_values_and_extra_fields(value) -> None:
    with pytest.raises(MotionError):
        validate_motion_config(value)
    with pytest.raises(ContractError):
        validate_document(value, MOTION_CONFIG)


def test_nested_selection_and_unready_inspection_validate(selection: dict) -> None:
    assert validate_document(selection, MOTION_SELECTION) == selection
    document = {
        "selection": selection,
        "savedPreferences": {
            scope: {"engine": None, "target": None}
            for scope in ("global", "provider", "project")
        },
        "readiness": {
            "ready": False,
            "state": "unavailable",
            "checks": [],
            "blockers": [],
            "nextActions": [],
        },
        "runSelection": None,
        "recordedAnimation": None,
    }
    assert validate_document(document, RESOLVED_SELECTION) == document


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("engine", "canvas"),
        ("source", "machine"),
        ("resolutionHash", "not-a-hash"),
        ("command", "execute-something"),
    ],
)
def test_selection_rejects_unknown_choices_scopes_hashes_and_commands(
    selection: dict, field: str, value
) -> None:
    selection[field] = value
    with pytest.raises(ContractError):
        validate_document(selection, MOTION_SELECTION)


def test_composition_has_a_stable_nonmutating_content_seal(
    composition: dict, tmp_path: Path
) -> None:
    original = deepcopy(composition)
    resealed = seal_composition(dict(reversed(list(composition.items()))))
    assert resealed == original
    assert resealed["manifestHash"] == document_hash_excluding(original, "manifestHash")
    resealed["renderContract"]["width"] = 640
    assert composition == original
    assert validate_document(composition, COMPOSITION) == original
    assert validate_composition(composition, root=tmp_path) == original


def test_composition_seal_ignores_old_seal_but_detects_content_change(
    composition: dict, tmp_path: Path
) -> None:
    original_hash = composition["manifestHash"]
    composition["manifestHash"] = "f" * 64
    assert seal_composition(composition)["manifestHash"] == original_hash
    with pytest.raises(MotionError):
        validate_composition(composition, root=tmp_path)
    composition["seed"] = 8
    assert seal_composition(composition)["manifestHash"] != original_hash


@pytest.mark.parametrize("field", ["command", "argv", "startFrame"])
def test_composition_rejects_commands_and_private_placement_fields(
    composition: dict, tmp_path: Path, field: str
) -> None:
    composition[field] = "unexpected"
    composition = seal_composition(composition)
    with pytest.raises(ContractError):
        validate_document(composition, COMPOSITION)
    with pytest.raises(MotionError):
        validate_composition(composition, root=tmp_path)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("width", 0),
        ("height", -1),
        ("frameCount", 0),
        ("frameCount", 1.5),
        ("frameRate", {"num": 30, "den": 0}),
        ("frameRate", {"num": 0, "den": 1}),
        ("frameRate", {"num": 30.0, "den": 1}),
        ("frameRate", {"num": 60, "den": 2}),
        ("quality", {"spatialSamples": 2, "temporalSamples": 1}),
        ("quality", {"spatialSamples": 1, "temporalSamples": 4}),
        ("captureColorSpace", "display-p3"),
    ],
)
def test_composition_rejects_invalid_or_unsupported_frame_targets(
    composition: dict, tmp_path: Path, field: str, value
) -> None:
    composition["renderContract"][field] = value
    with pytest.raises(MotionError):
        validate_composition(seal_composition(composition), root=tmp_path)


def test_transparent_contract_requires_matching_alpha_and_no_opaque_color(
    composition: dict, tmp_path: Path
) -> None:
    contract = composition["renderContract"]
    contract["background"] = {"mode": "transparent"}
    contract["alphaMode"] = "straight"
    assert (
        validate_composition(seal_composition(composition), root=tmp_path)[
            "renderContract"
        ]["alphaMode"]
        == "straight"
    )
    contract["alphaMode"] = "opaque"
    with pytest.raises(MotionError):
        validate_composition(seal_composition(composition), root=tmp_path)
    contract["alphaMode"] = "straight"
    contract["background"]["color"] = "#ffffff"
    with pytest.raises(MotionError):
        validate_composition(seal_composition(composition), root=tmp_path)


@pytest.mark.parametrize(
    "path",
    [
        "../outside.html",
        "/private.html",
        "C:/private.html",
        "https://example.invalid/source.html",
        "nested/../../outside.html",
    ],
)
def test_composition_rejects_escaping_or_remote_source_paths(
    composition: dict, tmp_path: Path, path: str
) -> None:
    composition["entry"] = path
    composition["files"][0]["path"] = path
    with pytest.raises(MotionError):
        validate_composition(
            seal_composition(composition), root=tmp_path, verify_files=False
        )


def test_composition_rejects_duplicate_paths_and_undeclared_entry(
    composition: dict, tmp_path: Path
) -> None:
    duplicate = deepcopy(composition)
    duplicate["files"].append(deepcopy(duplicate["files"][0]))
    with pytest.raises(MotionError):
        validate_composition(seal_composition(duplicate), root=tmp_path)
    composition["entry"] = "unlisted.html"
    with pytest.raises(MotionError):
        validate_composition(seal_composition(composition), root=tmp_path)


def test_file_bytes_and_sizes_are_verified_separately(
    composition: dict, tmp_path: Path
) -> None:
    entry = tmp_path / "index.html"
    original = entry.read_bytes()
    entry.write_bytes(b"X" + original[1:])
    with pytest.raises(MotionError):
        validate_composition(composition, root=tmp_path)
    entry.write_bytes(original)
    composition["files"][0]["sizeBytes"] += 1
    with pytest.raises(MotionError):
        validate_composition(seal_composition(composition), root=tmp_path)


def test_missing_files_fail_verification_but_shape_only_validation_is_explicit(
    composition: dict, tmp_path: Path
) -> None:
    (tmp_path / "index.html").unlink()
    with pytest.raises(MotionError):
        validate_composition(composition, root=tmp_path)
    assert (
        validate_composition(composition, root=tmp_path, verify_files=False)
        == composition
    )


def test_resolved_symlink_cannot_escape_composition_root(
    composition: dict, tmp_path: Path
) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-outside.html"
    outside.write_bytes((tmp_path / "index.html").read_bytes())
    alias = tmp_path / "escaped.html"
    try:
        alias.symlink_to(outside)
    except (OSError, NotImplementedError) as error:
        pytest.skip(f"Symlink creation unavailable on this test environment: {error}")
    composition["entry"] = alias.name
    composition["files"][0]["path"] = alias.name
    with pytest.raises(MotionError):
        validate_composition(seal_composition(composition), root=tmp_path)


def test_load_composition_uses_its_own_directory_and_rejects_bad_json(
    composition: dict, tmp_path: Path
) -> None:
    path = tmp_path / "composition.json"
    path.write_text(json.dumps(composition, indent=2), encoding="utf-8")
    assert load_composition(path) == composition
    assert file_fingerprint(path)["sha256"] != composition["manifestHash"]
    path.write_text("{invalid", encoding="utf-8")
    with pytest.raises(MotionError):
        load_composition(path)


def test_input_lock_seals_are_stable_nonmutating_and_validate(input_lock: dict) -> None:
    original = deepcopy(input_lock)
    resealed = seal_input_lock(dict(reversed(list(input_lock.items()))))
    assert resealed == original
    assert resealed["inputLockHash"] == document_hash_excluding(
        original, "inputLockHash"
    )
    resealed["environment"]["platform"] = "changed"
    assert input_lock == original
    assert validate_document(input_lock, INPUT_LOCK) == original
    assert validate_input_lock(input_lock) == original


def test_input_lock_checks_seal_and_input_set_independently(input_lock: dict) -> None:
    input_lock["inputLockHash"] = "f" * 64
    with pytest.raises(MotionError):
        validate_input_lock(input_lock)
    input_lock["inputsHash"] = "b" * 64
    input_lock["inputLockHash"] = document_hash_excluding(input_lock, "inputLockHash")
    with pytest.raises(MotionError):
        validate_input_lock(input_lock)


def test_standalone_lock_rejects_fabricated_canonical_authority(
    input_lock: dict,
) -> None:
    input_lock["canonicalInputLock"] = {"cmap": SHA}
    with pytest.raises(MotionError):
        validate_input_lock(seal_input_lock(input_lock))


def test_canonical_lock_requires_canonical_inputs_and_resolved_placement(
    input_lock: dict,
) -> None:
    input_lock["bindingMode"] = "canonical"
    with pytest.raises(MotionError):
        validate_input_lock(seal_input_lock(input_lock))
    input_lock.update(
        {
            "canonicalInputLock": {
                key: SHA for key in ("cmap", "bmap", "tracks", "animation", "sync-map")
            },
            "range": {"startFrame": 0, "endFrameExclusive": 90},
            "placement": {
                "x": 0,
                "y": 0,
                "width": 1280,
                "height": 720,
                "zOrder": 1,
                "layerRole": "overlay",
            },
        }
    )
    sealed = seal_input_lock(input_lock)
    assert validate_input_lock(sealed) == sealed
    sealed["range"]["endFrameExclusive"] = 0
    with pytest.raises(MotionError):
        validate_input_lock(seal_input_lock(sealed))
