"""Pin the selected PhotoCraft profile and its original input boundary."""

import json
from zipfile import ZipFile

import pytest

from avo import artcraft, init_project
from avo.adapters.artcraft import SelectedArtCraftAdapter
from avo.adapters.artcraft_photocraft import _read_rgba, _require_package
from tests.artcraft_fixtures import request
from tests.test_artcraft_jobs import _prepare, job_spec

PHOTO_OPERATION = "layered-image-card"


def photo_request(provider="fixture-provider"):
    return request(
        provider=provider,
        required={
            "behavior": PHOTO_OPERATION,
            "outputRole": "generated-still",
            "editable": True,
        },
    )


def photo_spec(workspace, source, **overrides):
    return job_spec(
        workspace,
        **{
            "readRoots": [str(source.parent)],
            "photoSource": {"source": str(source)},
            "output": {
                "role": "generated-still",
                "format": "png",
                "alpha": "straight",
                "color": "srgb",
                "width": 320,
                "height": 180,
            },
            **overrides,
        },
    )


def prepare_photo(spec, adapter):
    return _prepare(
        artcraft,
        photo_request(spec["provider"]),
        spec,
        adapter,
        intent=artcraft.ArtCraftIntent("explicit", "photocraft", (PHOTO_OPERATION,)),
    )


def test_photocraft_cannot_use_a_program_proof(tmp_path, monkeypatch):
    monkeypatch.setattr(init_project, "load_provider", lambda slug: {"slug": slug})
    proof = tmp_path / "proof"
    proof.mkdir()
    source = proof / "export.png"
    source.write_bytes(b"proof image")
    with pytest.raises(artcraft.ArtCraftError, match="program proof"):
        prepare_photo(photo_spec(tmp_path, source), None)


def test_photocraft_observation_requires_an_independently_confined_runner(tmp_path):
    with pytest.raises(artcraft.ArtCraftError, match="PhotoCraft.*confined CLI"):
        SelectedArtCraftAdapter().observe(
            scope={"app": "photocraft", "operations": [PHOTO_OPERATION]},
            mode="cli",
            roots={"read": [str(tmp_path)], "write": [str(tmp_path / "outputs")]},
            cli_path=None,
            app_path=None,
        )


def test_photocraft_rejects_a_native_package_with_an_external_entry(tmp_path):
    profile, tile = "a" * 64, "b" * 64
    native = tmp_path / "component.pcraft"
    manifest = {
        "format_version": 1,
        "document": {
            "icc_profile": profile,
            "layers": [
                {"content": {"kind": "raster", "surface": {"tiles": [{"hash": tile}]}}},
                {"content": {"kind": "adjustment"}},
            ],
        },
    }
    with ZipFile(native, "w") as package:
        package.writestr("manifest.json", json.dumps(manifest))
        for name in (
            "thumb.png",
            "composite/preview.png",
            f"blobs/{profile}.zst",
            f"tiles/{tile}.zst",
            "../linked.png",
        ):
            package.writestr(name, b"synthetic")
    with pytest.raises(artcraft.ArtCraftError, match="unverified dependencies"):
        _require_package(native, 65536)


def test_photocraft_rejects_image_without_srgb_profile(tmp_path):
    from PIL import Image

    source = tmp_path / "unprofiled.png"
    Image.new("RGBA", (320, 180), (64, 128, 196, 200)).save(source)
    with pytest.raises(artcraft.ArtCraftError, match="embedded sRGB profile"):
        _read_rgba(source, {"width": 320, "height": 180})
