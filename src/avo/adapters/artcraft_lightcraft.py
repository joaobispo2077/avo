"""Develop one JPEG in an isolated LightCraft library and verify its recovery."""

import io
import json
from hashlib import sha256
from pathlib import Path

from PIL import Image, ImageCms

from avo.artcraft import ArtCraftError
from avo.timeline.contracts import file_fingerprint
from avo.timeline.store import write_immutable_json

from .artcraft_native_cli import (
    bounded_native_invocation,
    observe_native_command_schema,
)

_CONTROL = "light.exposure"
_EXPOSURE = 0.65
_GET = "develop.get"
_SET = "develop.set"
_EXPORT = "app.export"
_SNAPSHOT = "catalog.snap"
_LIBRARIES = ("authoring.lightcraft", "reopen.lightcraft")
_EXPORT_SETTINGS = {
    "format": "png",
    "longEdge": 0,
    "colorSpace": "srgb",
    "bitDepth": 8,
    "metadata": "none",
    "sharpen": "none",
}


def observe_lightcraft(executable, environment):
    return observe_native_command_schema(
        executable, environment, needed={_GET, _SET, _EXPORT}, label="LightCraft"
    )


def author_light_treatment(job, *, directory, invoke):
    original = job["inputs"][0]
    source = Path(original["locator"])
    output, budget = job["output"], job["budget"]
    _require_source(source, output)
    if directory.resolve() != directory or directory.exists() or budget["files"] < 13:
        raise ArtCraftError(
            "LightCraft requires a fresh owned folder with thirteen available files"
        )
    directory.mkdir(parents=True)
    call = bounded_native_invocation(
        directory,
        budget,
        invoke,
        label="LightCraft treatment",
        owned_directories=_LIBRARIES,
    )
    native, recipe = _capture_treatment(call, directory, source, original, output)
    fingerprint = file_fingerprint(native)
    first, second = _reopen_exports(call, directory, native, output)
    if first != second:
        raise ArtCraftError(
            "LightCraft did not reproduce exact pixels from its retained catalog"
        )
    if file_fingerprint(native) != fingerprint or file_fingerprint(source) != original:
        raise ArtCraftError(
            "LightCraft modified the retained catalog or selected original"
        )
    return {
        "nativeSource": fingerprint,
        "recipe": file_fingerprint(recipe),
        "media": file_fingerprint(directory / "photo.png"),
        "stillEvidence": {
            **{
                key: output[key]
                for key in ("width", "height", "format", "color", "alpha")
            },
            "rgbaSha256": first[0],
        },
    }


def _require_source(source, output):
    with Image.open(source, formats=["JPEG"]) as image:
        if (image.mode, image.size) != (
            "RGB",
            (output["width"], output["height"]),
        ) or image.getexif().get(274, 1) != 1:
            raise ArtCraftError(
                "LightCraft original JPEG differs from the selected RGB canvas or orientation"
            )
        if (profile := image.info.get("icc_profile")) is not None:
            _require_srgb(profile)


def _capture_treatment(call, directory, source, original, output):
    adjustment = {"control": _CONTROL, "value": _EXPOSURE}
    recipe = write_immutable_json(
        directory / "recipe.json",
        {"original": original, "adjustment": adjustment, "export": _EXPORT_SETTINGS},
    )
    library = directory / _LIBRARIES[0]
    image = directory / "authored.png"
    default, _, exported = _receipts(
        call(
            "run",
            "--library",
            library,
            "--import",
            source,
            _GET,
            _SET,
            json.dumps(adjustment),
            *_export_command(image),
        ),
        (_GET, _SET, _EXPORT),
    )
    if default["light"]["exposure"] != 0:
        raise ArtCraftError(
            "LightCraft starting library did not have the default exposure"
        )
    _require_export_receipt(exported, image, output)
    data = (library / _SNAPSHOT).read_bytes()
    _require_native_catalog(json.loads(data), original, output)
    native = directory / "component.snap"
    with native.open("xb") as retained:
        retained.write(data)
    return native, recipe


def _reopen_exports(call, directory, native, output):
    first = _inspect_image(
        directory / "authored.png", output, normalized=directory / "photo.png"
    )
    restored = directory / _LIBRARIES[1]
    restored.mkdir()
    with (restored / _SNAPSHOT).open("xb") as catalog:
        catalog.write(native.read_bytes())
    image = directory / "reopened.png"
    developed, exported = _receipts(
        call("run", "--library", restored, _GET, *_export_command(image)),
        (_GET, _EXPORT),
    )
    if developed["light"]["exposure"] != _EXPOSURE:
        raise ArtCraftError(
            "LightCraft restored catalog did not retain the exposure adjustment"
        )
    _require_export_receipt(exported, image, output)
    return first, _inspect_image(image, output)


def _receipts(result, commands):
    rows = [json.loads(line) for line in result.splitlines()]
    if tuple(row["command"] for row in rows) != commands or any(
        row["ok"] is not True for row in rows
    ):
        raise ArtCraftError("LightCraft did not report every selected command")
    return [row["result"] for row in rows]


def _export_command(path):
    return _EXPORT, json.dumps({"path": str(path), **_EXPORT_SETTINGS})


def _require_export_receipt(result, image, output):
    (reported,) = result["files"]
    if (
        reported["path"],
        reported["width"],
        reported["height"],
        reported["sidecars"],
    ) != (str(image), output["width"], output["height"], []):
        raise ArtCraftError(
            "LightCraft reported an unexpected output path, shape or sidecar"
        )


def _require_native_catalog(snapshot, original, output):
    if (snapshot["format"], snapshot["version"]) != ("lightcraft-catalog", 13):
        raise ArtCraftError(
            "LightCraft produced an unsupported native catalog snapshot"
        )
    (photo,) = snapshot["catalog"]["photos"].values()
    if (
        photo["source"],
        photo["format"],
        photo["width"],
        photo["height"],
        photo["file_size"],
    ) != (
        {"type": "file", "path": original["locator"]},
        "JPEG",
        output["width"],
        output["height"],
        original["sizeBytes"],
    ):
        raise ArtCraftError(
            "LightCraft catalog changed the exact original photo reference"
        )
    if photo["develop"]["light"]["exposure"] != _EXPOSURE:
        raise ArtCraftError("LightCraft catalog did not retain the selected exposure")


def _require_srgb(profile):
    if not profile or len(profile) > 128 * 1024:
        raise ArtCraftError("LightCraft requires a bounded sRGB profile")
    parsed = ImageCms.ImageCmsProfile(io.BytesIO(profile))
    if (
        parsed.profile.xcolor_space.strip() != "RGB"
        or "srgb" not in ImageCms.getProfileDescription(parsed).casefold()
    ):
        raise ArtCraftError("LightCraft requires an sRGB color profile")


def _inspect_image(path, output, *, normalized=None):
    with path.open("rb") as stream:
        header = stream.read(26)
    if header[:8] != b"\x89PNG\r\n\x1a\n" or header[24:] != b"\x08\x02":
        raise ArtCraftError("LightCraft did not produce an 8-bit RGB PNG")
    with Image.open(path, formats=["PNG"]) as image:
        if image.size != (output["width"], output["height"]) or image.n_frames != 1:
            raise ArtCraftError(
                "LightCraft export differs from the selected single-image canvas"
            )
        profile = image.info.get("icc_profile")
        _require_srgb(profile)
        rgba = image.convert("RGBA")
        if normalized is not None:
            with normalized.open("xb") as review:
                rgba.save(review, format="PNG", icc_profile=profile)
        return sha256(rgba.tobytes()).hexdigest(), sha256(profile).hexdigest()
