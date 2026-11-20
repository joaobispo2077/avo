"""A fixed editable VectorCraft card with an independently verified PNG still."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from time import monotonic

from avo.artcraft import ArtCraftError
from avo.timeline.contracts import content_hash, file_fingerprint
from avo.timeline.store import write_immutable_json

_SAVE = "file.save"
_INSPECT = "document.inspect"
_COMMANDS = {
    "file.new",
    "shape.rectangle",
    "paint.setFill",
    "text.create",
    _SAVE,
    _INSPECT,
}
_BLOBS = b"\x00VCBLOBS\x00"


def observe_vectorcraft(executable, env):
    selected = Path(executable["locator"])
    try:
        result = subprocess.run(
            [str(selected), "--safe-mode", "commands"],
            cwd=selected.parent,
            env=env,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=7,
            check=True,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ArtCraftError(
            "Could not inspect the selected VectorCraft commands",
            code="ARTCRAFT_NOT_READY",
        ) from exc
    if len(result.stdout) > 4 * 1024 * 1024:
        raise ArtCraftError("VectorCraft command registry exceeds its byte limit")
    commands = {
        row["id"]: row["params"]
        for row in json.loads(result.stdout)
        if row["id"] in _COMMANDS
    }
    if commands.keys() != _COMMANDS or file_fingerprint(selected) != executable:
        raise ArtCraftError(
            "VectorCraft card command scope or selected executable changed",
            code="ARTCRAFT_NOT_READY",
        )
    return content_hash(commands)


def _card_steps(output, parameters, native):
    width, height = output["width"], output["height"]
    text = parameters["primaryText"]
    if not text.strip() or any(ord(character) < 32 for character in text):
        raise ArtCraftError("VectorCraft card label must be one nonempty line")
    literal = "$" + text if text.startswith("$") else text
    return [
        _step(
            "file.new",
            name="AVO editable card",
            width=width,
            height=height,
            units="Pixels",
            backgroundContents="transparent",
            colorMode="rgb",
            created=0,
        ),
        _step(
            "shape.rectangle",
            x=round(width * 0.075),
            y=round(height * 0.32),
            width=round(width * 0.85),
            height=round(height * 0.35),
            radius=round(min(width, height) * 0.055),
        ),
        _step("paint.setFill", id="$last.id", color="#102c48"),
        _step(
            "text.create",
            x=round(width * 0.14),
            y=round(height * 0.54),
            size=round(min(width * 0.075, height * 0.135)),
            font=parameters["font"],
            color="#ffffff",
            text=literal,
        ),
        _step(_SAVE, path=str(native)),
    ]


def _step(identifier, **options):
    return {"command": identifier, "params": options}


def author_vector_card(output, parameters, *, directory, budget, invoke):
    if directory.resolve() != directory or directory.exists():
        raise ArtCraftError("VectorCraft requires a fresh owned output folder")
    if budget["files"] < 4:
        raise ArtCraftError("VectorCraft card needs enough files for reopen evidence")
    directory.mkdir(parents=True)
    native, image, fresh = (
        directory / name
        for name in ("component.vectorcraft", "card.png", "reopened.png")
    )
    commands = _card_steps(output, parameters, native)
    recipe = write_immutable_json(directory / "recipe.json", commands)
    call = _card_invocation(directory, budget, invoke)
    authored = call("run", "--commands", recipe, "--scale", "1", "--export", image)
    _require_command_receipts(authored, commands, native, image)
    source = inspect_vector_card_native(native, max_bytes=budget["bytes"])
    reopened = call(
        "run", "--in", native, "--cmd", _INSPECT, "--scale", "1", "--export", fresh
    )
    _require_reopened_card(reopened, output, parameters, fresh)
    first = observe_vector_card_png(image, output)
    second = observe_vector_card_png(fresh, output)
    if first != second or file_fingerprint(native) != source:
        raise ArtCraftError("VectorCraft saved card did not reproduce exact pixels")
    return {
        "nativeSource": source,
        "recipe": file_fingerprint(recipe),
        "media": file_fingerprint(image),
        "stillEvidence": first,
    }


def _card_invocation(directory, budget, invoke):
    deadline = monotonic() + budget["seconds"]

    def call(*arguments):
        remaining = deadline - monotonic()
        if remaining <= 0:
            raise ArtCraftError("VectorCraft card exhausted its time budget")
        rows = invoke(directory, "--safe-mode", *arguments, timeout=remaining)
        if len(rows) > 1024 * 1024:
            raise ArtCraftError("VectorCraft card receipts exceed their byte limit")
        files = list(directory.iterdir())
        size = sum(item.stat().st_size for item in files)
        if len(files) > budget["files"] or size > budget["bytes"]:
            raise ArtCraftError("VectorCraft card exceeded its file or byte budget")
        if any(
            item.resolve() != item or not item.is_file() or item.stat().st_nlink != 1
            for item in files
        ):
            raise ArtCraftError("VectorCraft card created a linked or external file")
        return [json.loads(line) for line in rows.splitlines()]

    return call


def _require_command_receipts(rows, commands, native, image):
    if len(rows) != len(commands) + 1 or rows[-1]["step"] != "export":
        raise ArtCraftError("VectorCraft did not report every planned card operation")
    for row, step in zip(rows[:-1], commands, strict=True):
        if row["step"] != "cmd" or row["command"] != step["command"]:
            raise ArtCraftError("VectorCraft returned a different card command")
    text = next(row["result"] for row in rows if row.get("command") == "text.create")
    if text.get("warning") or text.get("overflow"):
        raise ArtCraftError("VectorCraft label font or bounds were not verified")
    _require_saved_path(rows[-2]["result"], native, "vectorcraft")
    _require_saved_path(rows[-1]["result"], image, "png")


def _require_saved_path(receipt, expected, format_name):
    if (
        receipt["format"] != format_name
        or Path(receipt["path"]) != expected
        or receipt.get("warnings")
        or not expected.is_file()
    ):
        raise ArtCraftError("VectorCraft save or export differs from its owned path")


def _require_reopened_card(rows, output, parameters, image):
    if [row.get("step") for row in rows] != ["open", "cmd", "export"]:
        raise ArtCraftError("VectorCraft reopened card has incomplete receipts")
    opened, inspected = (row["result"] for row in rows[:2])
    if (
        opened.get("missingLinks")
        or opened.get("modifiedLinks")
        or opened.get("warnings")
    ):
        raise ArtCraftError(
            "VectorCraft reopened card contains unverified dependencies"
        )
    _require_card_artboard(inspected, output)
    _require_editable_card(inspected, parameters)
    _require_saved_path(rows[-1]["result"], image, "png")


def _require_card_artboard(inspected, output):
    artboards = inspected["artboards"]
    if inspected["colorMode"] != "Rgb" or len(artboards) != 1:
        raise ArtCraftError("VectorCraft card must retain one RGB artboard")
    if tuple(artboards[0][key] for key in ("width", "height")) != (
        output["width"],
        output["height"],
    ):
        raise ArtCraftError("VectorCraft reopened artboard dimensions changed")


def _require_editable_card(inspected, parameters):
    (layer,) = inspected["layers"]
    text, background = layer["children"]
    if (text["kind"], background["kind"]) != ("Type", "Rounded Rectangle"):
        raise ArtCraftError(
            "VectorCraft reopened card lacks editable text and vector paths"
        )
    if text["text"] != parameters["primaryText"] or text["locked"]:
        raise ArtCraftError("VectorCraft reopened card text is no longer editable")
    _require_card_bounds(text["bounds"], background["bounds"])


def _require_card_bounds(text, background):
    if any(
        text[axis] < background[axis]
        or text[axis] + text[span] > background[axis] + background[span]
        for axis, span in (("x", "width"), ("y", "height"))
    ):
        raise ArtCraftError("VectorCraft editable label exceeds its card bounds")


def inspect_vector_card_native(path, *, max_bytes):
    """Read the locally observed v4 envelope and reject non-inline image inputs."""
    path = Path(path)
    if path.resolve() != path or path.stat().st_nlink != 1:
        raise ArtCraftError("VectorCraft source must be one unaliased native file")
    limit = min(max_bytes, 2 * 1024 * 1024)
    with path.open("rb") as stream:
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise ArtCraftError("VectorCraft native source exceeds its byte limit")
    header, separator, pdf = raw.partition(_BLOBS)
    document = json.loads(header)
    if not separator or (document["format"], document["version"]) != ("vectorcraft", 4):
        raise ArtCraftError(
            "VectorCraft native source format differs from its checked profile"
        )
    if document["images"] or document["document"]["images"]:
        raise ArtCraftError("VectorCraft card cannot depend on unverified images")
    if document["pdf"] != {"mime": "application/pdf", "blob": [0, len(pdf)]}:
        raise ArtCraftError("VectorCraft source contains unexpected payloads")
    return file_fingerprint(path)


def observe_vector_card_png(path, output):
    from PIL import Image

    with Image.open(path) as image:
        if (
            image.format != "PNG"
            or image.mode != "RGBA"
            or image.size != (output["width"], output["height"])
            or "srgb" not in image.info
            or image.n_frames != 1
        ):
            raise ArtCraftError(
                "VectorCraft card differs from its sRGB RGBA still contract"
            )
        alpha = image.getchannel("A")
        if alpha.getextrema() != (0, 255) or alpha.getbbox() is None:
            raise ArtCraftError(
                "VectorCraft image lacks both its solid card and transparency"
            )
        return {
            "format": "png",
            "color": "srgb",
            "alpha": "straight",
            "width": image.width,
            "height": image.height,
            "rgbaSha256": hashlib.sha256(image.tobytes()).hexdigest(),
        }
