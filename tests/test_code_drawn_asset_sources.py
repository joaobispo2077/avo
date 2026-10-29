"""Canonical drawing image ancestry, using real stores and no browser."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from avo import motion
from avo.timeline.animation import AnimationService
from avo.timeline.contracts import file_fingerprint
from avo.timeline.generated_assets import GeneratedAssetError, GeneratedAssetService
from avo.timeline.tracks import TracksService
from tests.code_drawn_asset_fixture import canonical_asset
from tests.test_generated_assets import _record


def _add_asset(asset, *, reference=None, data=b"licensed local image", kind="image"):
    target = asset.composition.parent / "assets" / "picture.png"
    target.write_bytes(data)
    fingerprint = file_fingerprint(target)
    declaration = {
        "id": "authored-picture",
        "kind": kind,
        "path": target.relative_to(asset.composition.parent).as_posix(),
        "sha256": fingerprint["sha256"],
        "sizeBytes": fingerprint["sizeBytes"],
        "rightsRef": "ANIMATION-SOURCE-LOG.md",
    }
    if reference is not None:
        declaration["sourceRef"] = deepcopy(reference)
    manifest = motion.load_composition(asset.composition)
    manifest["assets"].append(declaration)
    asset.composition.write_text(
        json.dumps(motion.seal_composition(manifest)), encoding="utf-8"
    )
    return target


def _rebind(asset):
    reference = deepcopy(asset.reference)
    reference["manifestRef"]["sha256"] = file_fingerprint(asset.composition)["sha256"]
    index = asset.workspace.require_active("tracks")
    tracks = asset.workspace.store("tracks").revision(index["headRevisionId"])[
        "snapshot"
    ]
    layer = next(
        row for row in tracks["videoTracks"]["layers"] if row.get("generatedSourceRef")
    )
    layer["generatedSourceRef"] = reference
    TracksService(asset.workspace).author(
        tracks, actor="unit-test", reason="image source"
    )
    strategy = deepcopy(asset.strategy)
    strategy["components"][0]["extensions"]["codeDrawn"]["manifestRef"] = deepcopy(
        reference["manifestRef"]
    )
    AnimationService(asset.workspace).author(
        strategy, actor="unit-test", reason="image source"
    )


def _image_input(asset):
    manifest = motion.load_composition(asset.composition)
    inputs = motion._frozen_drawing_inputs(asset.composition, manifest)
    return next(
        row for row in inputs if row["fingerprint"]["locator"].endswith("picture.png")
    )


def _parent(asset):
    path = asset.composition.parent / "source-still.png"
    path.write_bytes(b"registered extracted still")
    service = GeneratedAssetService(asset.workspace)
    value = _record(path)
    value.update(
        assetId="registered-still",
        sourceFree=False,
        inputs=[
            {
                "artifactId": "camera",
                "fingerprint": file_fingerprint(asset.workspace.raw_dir / "raw.bin"),
                "ancestryRole": "source",
            }
        ],
    )
    value["generator"]["adapterId"] = "fixture.still"
    record = service.register(value)
    assert service.admit(record["assetId"]) == record
    return service, record, path


@pytest.mark.parametrize("kind", ["image", "svg"])
def test_local_licensed_imagery_is_a_fingerprinted_dependency(tmp_path, kind):
    asset = canonical_asset(tmp_path)
    target = _add_asset(asset, kind=kind)
    _rebind(asset)
    binding = motion.canonical_code_drawn_binding(
        asset.workspace, asset.reference["instanceId"]
    )
    frozen = _image_input(asset)
    assert frozen["ancestryRole"] == "dependency"
    assert frozen["fingerprint"] == file_fingerprint(target)
    assert not any(item.get("sourceRef") for item in binding["manifest"]["assets"])
    GeneratedAssetService(asset.workspace).validate_code_drawn_inputs(
        motion._frozen_drawing_inputs(asset.composition, binding["manifest"])
    )


def test_registered_generated_still_keeps_exact_parent_identity(tmp_path):
    asset = canonical_asset(tmp_path)
    service, parent, path = _parent(asset)
    _add_asset(
        asset,
        reference={"assetId": parent["assetId"], "recordHash": parent["recordHash"]},
        data=path.read_bytes(),
    )
    _rebind(asset)
    binding = motion.canonical_code_drawn_binding(
        asset.workspace, asset.reference["instanceId"]
    )
    frozen = _image_input(asset)
    assert frozen["artifactId"] == parent["assetId"]
    assert frozen["ancestryRole"] == "generated"
    service.validate_code_drawn_inputs(
        motion._frozen_drawing_inputs(asset.composition, binding["manifest"])
    )


def test_original_image_ref_requires_exact_registered_original(tmp_path):
    asset = canonical_asset(tmp_path)
    index = asset.workspace.require_active("cmap")
    source = asset.workspace.store("cmap").revision(index["headRevisionId"])[
        "snapshot"
    ]["sources"][0]
    original = Path(source.get("locator") or source["fingerprint"]["locator"])
    _add_asset(
        asset, reference={"sourceId": source["sourceId"]}, data=original.read_bytes()
    )
    _rebind(asset)
    motion.canonical_code_drawn_binding(asset.workspace, asset.reference["instanceId"])
    frozen = _image_input(asset)
    assert frozen["artifactId"] == source["sourceId"]
    assert frozen["ancestryRole"] == "source"


@pytest.mark.parametrize("fault", ["parent-hash", "parent-output", "missing-parent"])
def test_stale_generated_parent_blocks_before_browser(tmp_path, fault):
    asset = canonical_asset(tmp_path)
    _service, parent, path = _parent(asset)
    reference = {"assetId": parent["assetId"], "recordHash": parent["recordHash"]}
    data = path.read_bytes()
    if fault == "parent-hash":
        reference["recordHash"] = "0" * 64
    elif fault == "parent-output":
        data += b"changed local extraction"
    else:
        reference["assetId"] = "missing-still"
    _add_asset(asset, reference=reference, data=data)
    _rebind(asset)
    with pytest.raises(
        (motion.MotionError, GeneratedAssetError),
        match="(?i)parent|source|still|generated|fingerprint|record",
    ):
        motion.canonical_code_drawn_binding(
            asset.workspace, asset.reference["instanceId"]
        )


@pytest.mark.parametrize("fault", ["source-id", "source-bytes"])
def test_wrong_original_source_identity_blocks_before_browser(tmp_path, fault):
    asset = canonical_asset(tmp_path)
    index = asset.workspace.require_active("cmap")
    source = asset.workspace.store("cmap").revision(index["headRevisionId"])[
        "snapshot"
    ]["sources"][0]
    path = Path(source.get("locator") or source["fingerprint"]["locator"])
    reference = {
        "sourceId": "missing-original" if fault == "source-id" else source["sourceId"]
    }
    _add_asset(
        asset,
        reference=reference,
        data=path.read_bytes() + (b"changed" if fault == "source-bytes" else b""),
    )
    _rebind(asset)
    with pytest.raises(motion.MotionError, match="(?i)original|source|fingerprint"):
        motion.canonical_code_drawn_binding(
            asset.workspace, asset.reference["instanceId"]
        )


@pytest.mark.parametrize(
    "reference",
    [
        {},
        {"assetId": "registered-still"},
        {"assetId": "registered-still", "recordHash": "not-a-sha"},
        {"assetId": "registered-still", "recordHash": "a" * 64, "extra": True},
        {"sourceId": ""},
        {"sourceId": "camera", "assetId": "registered-still", "recordHash": "a" * 64},
    ],
)
def test_unknown_source_reference_shapes_fail_closed(tmp_path, reference):
    destination = tmp_path / "standalone"
    motion.scaffold_code_drawn(
        destination,
        route="canvas",
        width=128,
        height=96,
        fps="30/1",
        frames=9,
        background="transparent",
    )
    asset = SimpleNamespace(composition=destination / "composition.json")
    _add_asset(asset, reference=reference)
    with pytest.raises(
        motion.MotionError, match="(?i)sourceRef|invalid|contract|schema"
    ):
        motion.load_composition(asset.composition)


def test_known_proof_bytes_cannot_hide_as_local_brand_image(tmp_path):
    asset = canonical_asset(tmp_path)
    _add_asset(asset, data=(asset.workspace.raw_dir / "edit/proof.mp4").read_bytes())
    _rebind(asset)

    class BrowserMustNotStart:
        def check(self, *_args, **_kwargs):
            pytest.fail("Forbidden media reached the browser.")

    with pytest.raises(GeneratedAssetError, match="(?i)forbidden|ancestor|quarantin"):
        motion.materialize_code_drawn(
            asset.workspace,
            asset.reference["instanceId"],
            output=asset.composition.parent / "must-not-render.mkv",
            adapter=BrowserMustNotStart(),
        )
