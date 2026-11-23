"""Validate selected ArtCraft profiles and their native job boundaries."""

import json
from contextlib import contextmanager
from os import scandir
from zipfile import ZipFile

import pytest

from avo import artcraft, init_project
from avo.adapters import artcraft_native_cli
from avo.adapters.artcraft import SelectedArtCraftAdapter
from avo.adapters.artcraft_photocraft import _read_rgba, _require_package
from tests.artcraft_fixtures import request
from tests.test_artcraft_jobs import _prepare, job_spec

PHOTO_OPERATION = "layered-image-card"
FIG_OPERATION = "editable-design-variant"
DECK_OPERATION = "editable-explanation-slide"
LIGHT_OPERATION = "reusable-photo-treatment"
EFFECT_OPERATION = "editable-masked-lower-third"


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


def static_review_spec(workspace, **overrides):
    return job_spec(
        workspace,
        **{
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


def prepare_fig(spec, adapter):
    return _prepare_static_profile(spec, adapter, "figcraft", FIG_OPERATION)


def prepare_deck(spec, adapter):
    return _prepare_static_profile(spec, adapter, "deckcraft", DECK_OPERATION)


def prepare_light(spec, adapter):
    return _prepare_static_profile(spec, adapter, "lightcraft", LIGHT_OPERATION)


def effect_spec(workspace, **overrides):
    return job_spec(
        workspace,
        **{
            "authoringParameters": {"primaryText": "AVO", "font": "Arial"},
            "output": {
                "role": "overlay-video",
                "format": "png-sequence",
                "width": 320,
                "height": 180,
                "alpha": "straight",
                "color": "srgb",
                "frameRate": {"numerator": 24, "denominator": 1},
                "frameCount": 6,
            },
            **overrides,
        },
    )


def prepare_effect(spec, adapter):
    brief = request(
        provider=spec["provider"],
        required={
            "behavior": EFFECT_OPERATION,
            "outputRole": "overlay-video",
            "editable": True,
        },
    )
    return _prepare(
        artcraft,
        brief,
        spec,
        adapter,
        intent=artcraft.ArtCraftIntent("explicit", "effectcraft", (EFFECT_OPERATION,)),
    )


def _prepare_static_profile(spec, adapter, app, operation):
    brief = request(
        provider=spec["provider"],
        required={
            "behavior": operation,
            "outputRole": "generated-still",
            "editable": True,
        },
    )
    return _prepare(
        artcraft,
        brief,
        spec,
        adapter,
        intent=artcraft.ArtCraftIntent("explicit", app, (operation,)),
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


def test_figcraft_rejects_unqualified_attached_mode(tmp_path, monkeypatch):
    monkeypatch.setattr(init_project, "load_provider", lambda slug: {"slug": slug})
    with pytest.raises(artcraft.ArtCraftError, match="FigCraft.*confined CLI"):
        prepare_fig(static_review_spec(tmp_path, mode="live"), None)


def test_figcraft_observation_requires_an_independently_confined_runner(tmp_path):
    with pytest.raises(artcraft.ArtCraftError, match="FigCraft.*confined CLI"):
        SelectedArtCraftAdapter().observe(
            scope={"app": "figcraft", "operations": [FIG_OPERATION]},
            mode="cli",
            roots={"read": [], "write": [str(tmp_path / "outputs")]},
            cli_path=None,
            app_path=None,
        )


def test_deckcraft_rejects_live_control_for_cli_recipe(tmp_path, monkeypatch):
    monkeypatch.setattr(init_project, "load_provider", lambda slug: {"slug": slug})
    with pytest.raises(artcraft.ArtCraftError, match="DeckCraft.*confined CLI"):
        prepare_deck(static_review_spec(tmp_path, mode="live"), None)


def test_lightcraft_rejects_unqualified_raw_input(tmp_path, monkeypatch):
    monkeypatch.setattr(init_project, "load_provider", lambda slug: {"slug": slug})
    source = tmp_path / "camera.dng"
    source.write_bytes(b"unqualified fixture RAW")
    with pytest.raises(artcraft.ArtCraftError, match="LightCraft.*original JPEG"):
        prepare_light(photo_spec(tmp_path, source), None)


def test_effectcraft_requires_a_selected_font_source(tmp_path, monkeypatch):
    monkeypatch.setattr(init_project, "load_provider", lambda slug: {"slug": slug})
    with pytest.raises(artcraft.ArtCraftError, match="EffectCraft.*Arial font source"):
        prepare_effect(effect_spec(tmp_path), None)


@pytest.mark.parametrize(
    ("late", "message"),
    [
        (False, "exceeded its receipt, file or byte budget"),
        (True, "exhausted its time budget"),
    ],
    ids=["oversized-receipt", "late-reply"],
)
def test_native_cli_invalid_reply_skips_scratch_audit(
    tmp_path, monkeypatch, late, message
):
    elapsed = 0
    monkeypatch.setattr(artcraft_native_cli, "monotonic", lambda: elapsed)

    def invoke(*_args, timeout):
        nonlocal elapsed
        assert timeout == 5
        if late:
            elapsed = 5
            return b"receipt"
        return b"x" * (1024 * 1024 + 1)

    def unexpected_scratch(*_args):
        pytest.fail("Rejected replies must not inspect scratch")

    monkeypatch.setattr(artcraft_native_cli, "_owned_files", unexpected_scratch)
    call = artcraft_native_cli.bounded_native_invocation(
        tmp_path, {"seconds": 5, "files": 1, "bytes": 8}, invoke, label="Native job"
    )

    with pytest.raises(artcraft.ArtCraftError, match=message):
        call("mock-command")


@pytest.mark.parametrize("limit", ["files", "bytes"])
def test_native_cli_scratch_audit_stops_at_first_excess(tmp_path, monkeypatch, limit):
    for name in ("first.bin", "second.bin"):
        (tmp_path / name).write_bytes(b"x")

    def owned_files(directory, _allowed, _label):
        yield directory / "first.bin"
        yield directory / "second.bin"
        pytest.fail("Scratch audit must stop at the first over-budget file")

    monkeypatch.setattr(artcraft_native_cli, "_owned_files", owned_files)
    budget = {"seconds": 5, "files": 5, "bytes": 5}
    budget[limit] = 1
    call = artcraft_native_cli.bounded_native_invocation(
        tmp_path.resolve(),
        budget,
        lambda *_args, **_kwargs: b"receipt",
        label="Native job",
    )

    with pytest.raises(
        artcraft.ArtCraftError, match="exceeded its receipt, file or byte budget"
    ):
        call("mock-command")


def test_native_cli_closes_directory_scans_at_scratch_limit(tmp_path, monkeypatch):
    workspace = tmp_path.resolve()
    scratch = workspace / "scratch"
    scratch.mkdir()
    for index in range(3):
        (scratch / f"{index}.bin").write_bytes(b"x")
    visited, closed = [], []

    @contextmanager
    def watch_scan(directory):
        with scandir(directory) as entries:

            def observed_entries():
                for entry in entries:
                    visited.append(directory)
                    yield entry

            try:
                yield observed_entries()
            finally:
                closed.append(directory)

    monkeypatch.setattr(artcraft_native_cli, "scandir", watch_scan, raising=False)
    call = artcraft_native_cli.bounded_native_invocation(
        workspace,
        {"seconds": 5, "files": 1, "bytes": 5},
        lambda *_args, **_kwargs: b"receipt",
        label="Native job",
        owned_directories=("scratch",),
    )

    with pytest.raises(
        artcraft.ArtCraftError, match="exceeded its receipt, file or byte budget"
    ):
        call("mock-command")
    assert visited == [workspace, scratch, scratch]
    assert closed == [scratch, workspace]
