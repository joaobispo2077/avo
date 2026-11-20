"""Create a bounded comparison sheet from exact local asset bytes."""

import hashlib
from io import BytesIO

from PIL import Image, ImageDraw, ImageOps

MAX_ASSET_BYTES = 16 * 1024 * 1024
MAX_IMAGE_PIXELS = 16_777_216
TILE = (240, 135)


def _capture(path, source):
    try:
        with path.open("rb") as stream:
            data = stream.read(MAX_ASSET_BYTES + 1)
    except OSError:
        return "source-unavailable", None
    if (
        len(data) != source["sizeBytes"]
        or hashlib.sha256(data).hexdigest() != source["sha256"]
    ):
        return "source-changed", None
    try:
        with Image.open(BytesIO(data)) as image:
            if image.width * image.height > MAX_IMAGE_PIXELS:
                return "capture-failed", None
            preview = ImageOps.exif_transpose(image).convert("RGBA")
            preview.thumbnail(TILE, Image.Resampling.LANCZOS)
            return "ready-for-review", preview
    except (OSError, ValueError, Image.DecompressionBombError):
        return "capture-failed", None


def _tile(sheet, draw, position, row, preview, background):
    width, height = TILE
    x, y = position
    target = background.copy()
    if preview is not None:
        target.alpha_composite(
            preview, ((width - preview.width) // 2, (height - preview.height) // 2)
        )
    else:
        ImageDraw.Draw(target).rectangle(
            (80, 58, width - 80, height - 58), fill="#8b929d"
        )
    sheet.paste(target.convert("RGB"), (x, y))
    draw.text(
        (x, y + height + 4), f"{row['number']}. {row['optionId']}"[:43], fill="#ffffff"
    )
    details = f"{row['state'].replace('-', ' ')} | {row['rights']['state']}"
    draw.text((x, y + height + 18), details, fill="#d9dfe9")


def _background(color, context):
    result = Image.new("RGBA", TILE, color)
    if context is None:
        return result
    state, preview = _capture(*context)
    if state != "ready-for-review":
        raise ValueError(
            "The intended background image could not be verified and decoded"
        )
    result.alpha_composite(ImageOps.fit(preview, TILE, method=Image.Resampling.LANCZOS))
    return result


def render_asset_sheet(prepared, background, *, context=None):
    """Retain each option number and flag capture errors without fabricating imagery."""
    columns = min(3, max(1, len(prepared)))
    rows = max(1, (len(prepared) + columns - 1) // columns)
    width, height = TILE[0] + 16, TILE[1] + 42
    sheet = Image.new("RGB", (columns * width + 8, rows * height + 8), "#20242b")
    draw = ImageDraw.Draw(sheet)
    background = _background(background, context)
    outcomes = []
    seen = set()
    for index, (row, path) in enumerate(prepared):
        state, preview = row["state"], None
        if path is not None:
            digest = row["source"]["sha256"]
            state, preview = _capture(path, row["source"])
            if state == "ready-for-review":
                if digest in seen:
                    state, preview = "duplicate", None
                seen.add(digest)
        selected = {**row, "state": state}
        outcomes.append(selected)
        _tile(
            sheet,
            draw,
            (8 + index % columns * width, 8 + index // columns * height),
            selected,
            preview,
            background,
        )
    if not prepared:
        draw.text((8, 8), "No candidate assets", fill="#ffffff")
    output = BytesIO()
    sheet.save(output, format="PNG")
    return outcomes, output.getvalue()
