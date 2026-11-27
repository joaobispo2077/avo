"""Author and verify the selected PhotoCraft layered image recipe."""

import io
import json
import re
import stat
from hashlib import sha256
from pathlib import Path
from zipfile import BadZipFile, ZipFile

from PIL import Image, ImageCms

from avo.artcraft import ArtCraftError
from avo.timeline.contracts import file_fingerprint
from avo.timeline.store import write_immutable_json

from .artcraft_native_cli import (
    bounded_native_invocation,
    observe_native_command_schema,
)

_ADD_CURVES = "layer.newAdjustmentLayer.curves"
_HIDE_LAYERS = "layer.hideLayers"
_POINTS = [[0, 0], [64, 48], [192, 212], [255, 255]]
_IDENTITY = [[0, 0], [255, 255]]
_DIGEST = re.compile("[a-f0-9]{64}")


def observe_photocraft(executable, environment):
    return observe_native_command_schema(
        executable, environment, needed={_ADD_CURVES, _HIDE_LAYERS}, label="PhotoCraft"
    )


def author_photo_card(job, *, directory, invoke):
    source = Path(job["inputs"][0]["locator"])
    output, budget = job["output"], job["budget"]
    original = _read_rgba(source, output)
    if directory.resolve() != directory or directory.exists() or budget["files"] < 5:
        raise ArtCraftError(
            "PhotoCraft requires a fresh owned folder with five available files"
        )
    directory.mkdir(parents=True)
    native, image, fresh, base = (
        directory / name
        for name in ("component.pcraft", "photo.png", "reopened.png", "base-only.png")
    )
    recipe = write_immutable_json(
        directory / "recipe.json",
        {"original": job["inputs"][0], "adjustment": _ADD_CURVES, "points": _POINTS},
    )
    call = bounded_native_invocation(directory, budget, invoke, label="PhotoCraft card")
    adjustment = _create_editable_photo(call, source, native)
    _require_package(native, budget["bytes"])
    native_fingerprint = file_fingerprint(native)
    _require_reopened_layers(json.loads(call("info", native)), output, adjustment)
    _export_photo(call, native, image)
    _export_photo(call, native, fresh)
    _verify_original_layer(call, native, base, adjustment)
    rgba_hash = _verify_photo_outputs(original, output, image, fresh, base)
    if (
        file_fingerprint(native) != native_fingerprint
        or file_fingerprint(source) != job["inputs"][0]
    ):
        raise ArtCraftError(
            "PhotoCraft modified a retained native document or original input"
        )
    return {
        "nativeSource": native_fingerprint,
        "recipe": file_fingerprint(recipe),
        "media": file_fingerprint(image),
        "stillEvidence": {
            **{
                key: output[key]
                for key in ("width", "height", "format", "color", "alpha")
            },
            "rgbaSha256": rgba_hash,
        },
    }


def _create_editable_photo(call, source, native):
    receipt = json.loads(
        call(
            "run",
            source,
            "--no-gpu",
            "--cmd",
            _ADD_CURVES,
            "--params",
            json.dumps({"points": _POINTS}),
            "--out",
            native,
        )
    )
    if not _created_curves(receipt):
        raise ArtCraftError("PhotoCraft did not report an editable Curves layer")
    return receipt["result"]["layer"]


def _created_curves(receipt):
    return (
        isinstance(receipt, dict)
        and receipt.get("command") == _ADD_CURVES
        and "error" not in receipt
        and isinstance(receipt.get("result"), dict)
        and "error" not in receipt["result"]
        and type(receipt["result"].get("layer")) is int
    )


def _verify_original_layer(call, native, base, adjustment):
    hidden = _export_photo(
        call,
        native,
        base,
        "--cmd",
        _HIDE_LAYERS,
        "--params",
        json.dumps({"layer": adjustment}),
    )
    if json.loads(hidden) != {"command": _HIDE_LAYERS, "result": None}:
        raise ArtCraftError(
            "PhotoCraft did not verify the retained original pixel layer"
        )


def _export_photo(call, native, output, *operation):
    return call(
        "run", native, "--no-gpu", *operation, "--metadata", "none", "--out", output
    )


def _require_package(path, max_bytes):
    try:
        with ZipFile(path) as package:
            entries = package.infolist()
            names = {entry.filename for entry in entries}
            if (
                len(names) != len(entries)
                or sum(entry.file_size for entry in entries) > max_bytes
                or any(stat.S_ISLNK(entry.external_attr >> 16) for entry in entries)
            ):
                raise ArtCraftError(
                    "PhotoCraft native package has unsafe or oversized members"
                )
            manifest = package.getinfo("manifest.json")
            if manifest.file_size > 1024 * 1024:
                raise ArtCraftError(
                    "PhotoCraft native manifest exceeded its byte limit"
                )
            expected = _embedded_native_files(json.loads(package.read(manifest)))
    except (OSError, BadZipFile, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ArtCraftError(
            "Could not verify PhotoCraft native embedded content"
        ) from exc
    if names != expected:
        raise ArtCraftError(
            "PhotoCraft native package includes unverified dependencies"
        )


def _embedded_native_files(manifest):
    document = manifest["document"]
    layers = document["layers"]
    if len(layers) != 2:
        raise ArtCraftError("PhotoCraft native package must contain exactly two layers")
    raster, adjustment = (item["content"] for item in layers)
    if (manifest["format_version"], raster["kind"], adjustment["kind"]) != (
        1,
        "raster",
        "adjustment",
    ):
        raise ArtCraftError(
            "PhotoCraft native package must contain raster and adjustment layers"
        )
    tiles = [tile["hash"] for tile in raster["surface"]["tiles"]]
    profile = document["icc_profile"]
    if not all(_DIGEST.fullmatch(value) for value in [profile, *tiles]):
        raise ArtCraftError(
            "PhotoCraft embedded dependency is missing its content address"
        )
    return {
        "manifest.json",
        "thumb.png",
        "composite/preview.png",
        f"blobs/{profile}.zst",
        *(f"tiles/{digest}.zst" for digest in tiles),
    }


def _require_reopened_layers(observed, output, adjustment):
    width, height = output["width"], output["height"]
    layers = observed["layers"]
    if (observed["width"], observed["height"], observed["mode"], observed["depth"]) != (
        width,
        height,
        "Rgb",
        8,
    ) or len(layers) != 2:
        raise ArtCraftError(
            "PhotoCraft reopened with changed dimensions, depth or layer count"
        )
    curves, pixels = layers
    if (
        (curves["id"], curves["kind"], curves["visible"])
        != (adjustment, "Adjustment", True)
        or curves["adjustment"]
        != {
            "kind": "curves",
            "params": {
                "points": _POINTS,
                "red": _IDENTITY,
                "green": _IDENTITY,
                "blue": _IDENTITY,
            },
        }
        or (pixels["kind"], pixels["visible"], pixels["bounds"])
        != ("Pixel", True, [0, 0, width, height])
    ):
        raise ArtCraftError(
            "PhotoCraft reopened with changed editable layers or Curves points"
        )


def _read_rgba(path, output):
    with path.open("rb") as source:
        header = source.read(26)
    if header[:8] != b"\x89PNG\r\n\x1a\n" or header[24:] != b"\x08\x06":
        raise ArtCraftError("PhotoCraft requires an 8-bit RGBA PNG")
    with Image.open(path, formats=["PNG"]) as image:
        if image.size != (output["width"], output["height"]) or image.n_frames != 1:
            raise ArtCraftError(
                "PhotoCraft PNG differs from the selected single-image canvas"
            )
        icc = image.info.get("icc_profile")
        if not icc or len(icc) > 128 * 1024:
            raise ArtCraftError("PhotoCraft requires an embedded sRGB profile")
        profile = ImageCms.ImageCmsProfile(io.BytesIO(icc))
        if (
            profile.profile.xcolor_space.strip() != "RGB"
            or "srgb" not in ImageCms.getProfileDescription(profile).casefold()
        ):
            raise ArtCraftError("PhotoCraft requires an embedded sRGB profile")
        return image.tobytes(), image.getchannel("A").tobytes(), icc


def _verify_photo_outputs(original, output, image, fresh, base):
    pixels, alpha, profile = _read_rgba(image, output)
    if (alpha, profile) != original[1:] or (pixels, alpha, profile) != _read_rgba(
        fresh, output
    ):
        raise ArtCraftError(
            "PhotoCraft PNG did not preserve alpha and profile or reproduce exact pixels"
        )
    if _read_rgba(base, output) != original:
        raise ArtCraftError(
            "PhotoCraft retained original pixels changed after reopening"
        )
    return sha256(pixels).hexdigest()
