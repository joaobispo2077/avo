"""Drawing source/lock boundaries; actual browser rendering is tested separately."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from avo.adapters.motion.code_drawn import CodeDrawnAdapter
from avo.motion import (
    MotionError,
    freeze_code_drawn_lock,
    load_composition,
    scaffold_code_drawn,
    seal_composition,
    seal_input_lock,
    verify_code_drawn_lock,
)
from avo.timeline.contracts import content_hash, file_fingerprint, validate_document


@pytest.fixture
def observed_environment() -> dict:
    return {
        "platform": "test-os-x64",
        "dependencies": {"playwright": "1.64.1", "ffmpeg": "test-encoder"},
        "browserVersion": "test-browser-1",
        "browserRevision": "test-browser-revision-1",
        "graphics": "test-software-renderer",
        "driverSha256": "a" * 64,
        "encoderSha256": "b" * 64,
        "locale": "en-US",
        "timezone": "UTC",
        "colorSpace": "srgb",
    }


@pytest.fixture
def drawing(tmp_path: Path) -> Path:
    destination = tmp_path / "drawing"
    scaffold_code_drawn(
        destination=destination,
        route="canvas",
        width=640,
        height=360,
        fps="30000/1001",
        frames=90,
        background="opaque",
        background_color="#121212",
    )
    return destination / "composition.json"


def rewrite_manifest(path: Path, value: dict) -> None:
    path.write_text(json.dumps(seal_composition(value), indent=2), encoding="utf-8")


def attach_local_asset(path: Path) -> Path:
    manifest = load_composition(path)
    asset = path.parent / "assets" / "local-data.txt"
    asset.parent.mkdir(exist_ok=True)
    asset.write_text("local drawing data", encoding="utf-8")
    fingerprint = file_fingerprint(asset)
    manifest["assets"].append(
        {
            "id": "local-data",
            "kind": "data",
            "path": asset.relative_to(path.parent).as_posix(),
            "sha256": fingerprint["sha256"],
            "sizeBytes": fingerprint["sizeBytes"],
            "rightsRef": "ANIMATION-SOURCE-LOG.md",
        }
    )
    rewrite_manifest(path, manifest)
    return asset


@pytest.mark.parametrize("route", ["canvas", "svg"])
def test_plain_scaffolds_are_editable_local_and_expose_the_bridge(
    tmp_path: Path, route: str
) -> None:
    destination = tmp_path / route
    scaffold_code_drawn(
        destination=destination,
        route=route,
        width=320,
        height=180,
        fps="30/1",
        frames=30,
        background="transparent",
    )
    manifest = load_composition(destination / "composition.json")
    assert manifest["engine"] == "code-drawn"
    assert manifest["drawingRoute"] == route
    assert manifest["dependencies"] == []
    assert manifest["renderContract"]["background"] == {"mode": "transparent"}
    assert manifest["renderContract"]["alphaMode"] == "straight"
    source = "\n".join(
        (destination / item["path"]).read_text(encoding="utf-8")
        for item in manifest["files"]
        if Path(item["path"]).suffix in {".html", ".js"}
    )
    assert "avo-stage" in source
    assert "window.avoReady" in source
    assert "window.seek" in source
    for name in (
        "DESIGN.md",
        "STORYBOARD.md",
        "ANIMATION-EDITLOG.md",
        "ANIMATION-SOURCE-LOG.md",
    ):
        assert (destination / name).is_file()


def test_lock_requires_observed_runtime_instead_of_fabricating_it(
    drawing: Path,
) -> None:
    with pytest.raises(MotionError) as caught:
        freeze_code_drawn_lock(drawing)
    assert caught.value.code == "CODE_DRAWN_RUNTIME_MISSING"


def test_freeze_preserves_source_and_binds_original_manifest_environment_and_inputs(
    drawing: Path, observed_environment: dict
) -> None:
    asset = attach_local_asset(drawing)
    original_bytes = drawing.read_bytes()
    environment_before = deepcopy(observed_environment)
    lock = freeze_code_drawn_lock(drawing, environment=observed_environment)
    validate_document(lock, "avo.code-drawn.schema.json#/$defs/inputLock")
    assert drawing.read_bytes() == original_bytes
    assert observed_environment == environment_before
    assert lock["bindingMode"] == "standalone"
    assert "canonicalInputLock" not in lock
    assert "placement" not in lock
    assert "range" not in lock
    assert lock["manifestRef"]["sha256"] == file_fingerprint(drawing)["sha256"]
    assert lock["renderContractHash"] == content_hash(
        load_composition(drawing)["renderContract"]
    )
    assert lock["inputsHash"] == content_hash(lock["inputs"])
    assert lock["environment"] == observed_environment
    inputs = {Path(item["fingerprint"]["locator"]).resolve() for item in lock["inputs"]}
    manifest = load_composition(drawing)
    assert {drawing.resolve(), asset.resolve()} <= inputs
    assert {
        (drawing.parent / item["path"]).resolve() for item in manifest["files"]
    } <= inputs
    assert lock["generator"]["adapterId"] == "code-drawn"
    verify_code_drawn_lock(drawing, lock, environment=observed_environment)


def test_repeated_freeze_and_verification_do_not_rewrite_the_lock(
    drawing: Path, observed_environment: dict
) -> None:
    lock = freeze_code_drawn_lock(drawing, environment=observed_environment)
    before = deepcopy(lock)
    again = freeze_code_drawn_lock(drawing, environment=observed_environment)
    assert again == lock
    verify_code_drawn_lock(drawing, lock, environment=observed_environment)
    assert lock == before


@pytest.mark.parametrize("input_kind", ["source", "asset"])
def test_lock_rejects_changed_input_even_when_new_manifest_is_self_consistent(
    drawing: Path, observed_environment: dict, input_kind: str
) -> None:
    asset = attach_local_asset(drawing)
    lock = freeze_code_drawn_lock(drawing, environment=observed_environment)
    original_lock = deepcopy(lock)
    manifest = load_composition(drawing)
    owner = manifest["files"][0] if input_kind == "source" else manifest["assets"][0]
    target = drawing.parent / owner["path"] if input_kind == "source" else asset
    target.write_bytes(target.read_bytes() + b"\nchanged")
    fingerprint = file_fingerprint(target)
    owner.update(sha256=fingerprint["sha256"], sizeBytes=fingerprint["sizeBytes"])
    manifest["sourceRevision"] = "source-r0002"
    rewrite_manifest(drawing, manifest)
    with pytest.raises(MotionError) as caught:
        verify_code_drawn_lock(drawing, lock, environment=observed_environment)
    assert caught.value.code == "CODE_DRAWN_LOCK_STALE"
    assert lock == original_lock


def test_missing_asset_is_named_and_cannot_be_a_successful_lock(
    drawing: Path, observed_environment: dict
) -> None:
    asset = attach_local_asset(drawing)
    lock = freeze_code_drawn_lock(drawing, environment=observed_environment)
    asset.unlink()
    with pytest.raises(MotionError) as caught:
        verify_code_drawn_lock(drawing, lock, environment=observed_environment)
    assert asset.name in str(caught.value)
    assert caught.value.code in {"CODE_DRAWN_ASSET_NOT_READY", "CODE_DRAWN_LOCK_STALE"}


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("browserRevision", "another-browser-revision"),
        ("graphics", "another-graphics-renderer"),
        ("driverSha256", "c" * 64),
        ("encoderSha256", "d" * 64),
    ],
)
def test_observed_environment_change_invalidates_original_lock(
    drawing: Path, observed_environment: dict, field: str, value: str
) -> None:
    lock = freeze_code_drawn_lock(drawing, environment=observed_environment)
    changed = {**observed_environment, field: value}
    with pytest.raises(MotionError) as caught:
        verify_code_drawn_lock(drawing, lock, environment=changed)
    assert caught.value.code == "CODE_DRAWN_LOCK_STALE"


def test_source_only_verification_does_not_claim_runtime_verification(
    drawing: Path, observed_environment: dict
) -> None:
    lock = freeze_code_drawn_lock(drawing, environment=observed_environment)
    verify_code_drawn_lock(drawing, lock)
    assert lock["environment"] == observed_environment


def test_partial_canonical_binding_cannot_create_fabricated_authority(
    drawing: Path, observed_environment: dict
) -> None:
    with pytest.raises(MotionError):
        freeze_code_drawn_lock(
            drawing,
            environment=observed_environment,
            canonical_binding={"canonicalInputLock": {"cmap": "a" * 64}},
        )


def test_resealed_lock_with_false_input_identity_is_rejected(
    drawing: Path, observed_environment: dict
) -> None:
    lock = freeze_code_drawn_lock(drawing, environment=observed_environment)
    assert lock["inputs"]
    lock["inputs"][0]["fingerprint"]["sha256"] = "f" * 64
    lock["inputsHash"] = content_hash(lock["inputs"])
    forged = seal_input_lock(lock)
    with pytest.raises(MotionError) as caught:
        verify_code_drawn_lock(drawing, forged, environment=observed_environment)
    assert caught.value.code == "CODE_DRAWN_LOCK_STALE"


@pytest.mark.parametrize("frame", [-1, 90])
def test_snapshot_rejects_out_of_range_frames_without_producing_an_image(
    drawing: Path, tmp_path: Path, frame: int
) -> None:
    output = tmp_path / "invalid-frame.png"
    with pytest.raises(MotionError) as caught:
        CodeDrawnAdapter().snapshot(drawing, frame=frame, output=output)
    assert caught.value.code == "CODE_DRAWN_INPUT_INVALID"
    assert not output.exists()


def test_snapshot_cannot_replace_editable_source(drawing: Path) -> None:
    manifest = load_composition(drawing)
    source = drawing.parent / manifest["entry"]
    original = source.read_bytes()
    with pytest.raises(MotionError):
        CodeDrawnAdapter().snapshot(drawing, frame=0, output=source)
    assert source.read_bytes() == original


def test_check_rejects_invalid_source_before_browser_work(drawing: Path) -> None:
    manifest = load_composition(drawing)
    manifest["entry"] = "../outside.html"
    rewrite_manifest(drawing, manifest)
    with pytest.raises(MotionError) as caught:
        CodeDrawnAdapter().check(drawing)
    assert caught.value.code == "CODE_DRAWN_INPUT_INVALID"


def test_existing_lock_is_never_overwritten_by_check(drawing: Path) -> None:
    output = drawing.parent / "input-lock.json"
    output.write_bytes(b"existing immutable evidence")
    original = output.read_bytes()
    with pytest.raises(MotionError):
        CodeDrawnAdapter().check(drawing, output_lock=output)
    assert output.read_bytes() == original


def test_existing_generated_output_is_preserved_on_failed_render(
    drawing: Path, observed_environment: dict
) -> None:
    lock = freeze_code_drawn_lock(drawing, environment=observed_environment)
    lock_path = drawing.parent / "input-lock.json"
    lock_path.write_text(json.dumps(lock), encoding="utf-8")
    output = drawing.parent / "asset.mkv"
    output.write_bytes(b"previous completed output")
    with pytest.raises(MotionError):
        CodeDrawnAdapter().render(drawing, input_lock=lock_path, output=output)
    assert output.read_bytes() == b"previous completed output"
    assert not (drawing.parent / "asset.generated-asset.json").exists()


def test_staging_rejects_an_input_changed_after_manifest_validation(drawing: Path):
    manifest = load_composition(drawing)
    target = drawing.parent / manifest["entry"]
    target.write_bytes(target.read_bytes() + b"\n<!-- changed after validation -->")
    with pytest.raises(MotionError) as caught:
        CodeDrawnAdapter._closure(drawing, manifest)
    assert caught.value.code == "CODE_DRAWN_LOCK_STALE"
