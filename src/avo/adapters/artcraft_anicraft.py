"""The bounded AniCraft lower-third recipe and its measured alpha conversion."""

from __future__ import annotations

import json
from contextlib import ExitStack
from fractions import Fraction
from pathlib import Path
from time import monotonic

from avo.artcraft import ArtCraftError
from avo.timeline.contracts import file_fingerprint
from avo.timeline.store import write_immutable_json

MATTE_CHECK_RGB = (55, 113, 174)

__all__ = ["MATTE_CHECK_RGB", "lower_third_steps", "recover_matte", "run_lower_third"]


def _profile_clock(output):
    numerator, denominator = (
        output["frameRate"][key] for key in ("numerator", "denominator")
    )
    rate = Fraction(numerator, denominator)
    width, height = output["width"], output["height"]
    if (
        rate.denominator != 1
        or not 1 <= rate <= 120
        or output["frameCount"] < max(24, rate)
        or 9 * width != 16 * height
        or output["role"] != "overlay-video"
        or output["format"] != "png-sequence"
        or output["alpha"] != "straight"
        or output["color"] != "srgb"
    ):
        raise ArtCraftError(
            "AniCraft lower-third contract requires a 16:9 sRGB straight-alpha PNG sequence, an integral 1–120 fps clock and at least one second",
            code="ARTCRAFT_NOT_READY",
        )
    return int(rate)


def _step(command, **parameters):
    return {"cmd": command, "params": parameters}


def _move_key(frame, distance):
    return [
        _step("timeline.insert_keyframe", frame=frame),
        _step("timeline.goto", frame=frame),
        _step("edit.select_all"),
        _step("element.translate", dx=distance, dy=0),
    ]


def _speaker_label(parameters, scale):
    text = parameters.get("primaryText")
    font = parameters.get("font")
    if (
        not isinstance(text, str)
        or not text.strip()
        or len(text) > 64
        or any(char in text for char in "\r\n\0—")
    ):
        raise ArtCraftError(
            "Choose one nonempty lower-third label within 64 characters"
        )
    if not isinstance(font, str) or not font.strip() or len(font) > 128:
        raise ArtCraftError("Choose an exact installed font for the lower third")
    return _step(
        "text.create",
        text=text,
        x=42 * scale,
        y=280 * scale,
        font=font,
        size=24 * scale,
        color="#ffffff",
    )


def lower_third_steps(output, parameters, source, white_directory):
    """Build the selected native commands, with frame numbers in the document clock."""
    _profile_clock(output)
    scale = output["width"] / 640
    count = output["frameCount"]
    enter, hold = count // 8, count // 3
    leave, exit_end = 3 * count // 4, 7 * count // 8
    return [
        _step("layer.new", name="Speaker label"),
        _step("timeline.insert_blank_keyframe", frame=enter),
        _step("timeline.goto", frame=enter),
        _step(
            "draw.rect",
            x=24 * scale,
            y=268 * scale,
            w=270 * scale,
            h=56 * scale,
            radius=8 * scale,
            fill="#102c48",
        ),
        _speaker_label(parameters, scale),
        _step("edit.select_all"),
        _step("modify.convert_to_symbol", name="Speaker plate", kind="graphic"),
        *_move_key(hold, 24 * scale),
        _step("timeline.create_tween", frame=enter),
        _step("timeline.insert_keyframe", frame=leave),
        *_move_key(exit_end, -24 * scale),
        _step("timeline.create_tween", frame=leave),
        _step("timeline.insert_blank_keyframe", frame=count - 1),
        _step("file.save_as", path=str(source)),
        _step(
            "file.export_png_sequence",
            dir=str(white_directory),
            **{"from": 0, "to": count - 1},
        ),
    ]


def recover_matte(white, black, check):
    """Reconstruct straight RGBA and verify it on an independently rendered backing."""
    import numpy as np
    from PIL import Image

    images = (white, black, check)
    if any(image.size != white.size or not _opaque(image) for image in images):
        raise ArtCraftError("AniCraft matte requires matching opaque RGB backings")
    light, dark, observed = (
        np.asarray(image.convert("RGB"), dtype=np.int32) for image in images
    )
    transmitted = light - dark
    channel_spread = np.ptp(transmitted, axis=2)
    if int(transmitted.min()) < 0 or int(channel_spread.max()) > 1:
        raise ArtCraftError("AniCraft backings disagree on coverage")
    coverage = 255 - np.median(transmitted, axis=2).astype(np.int32)[..., None]
    straight = np.minimum(255, (dark * 255 + coverage // 2) // np.maximum(1, coverage))
    predicted = (
        straight * coverage + np.asarray(MATTE_CHECK_RGB) * (255 - coverage) + 127
    ) // 255
    max_error = int(np.abs(predicted - observed).max())
    if max_error > 1:
        raise ArtCraftError(
            "AniCraft reconstructed alpha disagrees with the independent backing"
        )
    rgba = np.concatenate((straight, coverage), axis=2).astype(np.uint8)
    return Image.fromarray(rgba), max_error


def _opaque(image):
    return image.convert("RGBA").getchannel("A").getextrema() == (255, 255)


def run_lower_third(output, parameters, *, directory, budget, invoke):
    """Materialize the selected native recipe through a supplied confined runner."""
    directory = Path(directory)
    native, white = directory / "component.anicraft", directory / "white"
    steps = lower_third_steps(output, parameters, native, white)
    count = output["frameCount"]
    _require_new_output_directory(directory, budget, count)
    directory.mkdir(parents=True)
    deadline = monotonic() + budget["seconds"]
    call = _profile_invocation(directory, budget, invoke, deadline)
    recipe = write_immutable_json(directory / "recipe.json", steps)
    _require_profile_budget(directory, budget)
    _author_document(call, directory, native, recipe, steps, output, parameters["font"])
    locked_source = file_fingerprint(native)
    information = _inspect_document(call, native, output)
    reopened, black, check = _render_backings(call, directory, native, count)
    matte, maximum = _render_matte(
        (white, reopened, black, check), directory, output, budget, deadline
    )
    _require_profile_budget(directory, budget)
    if file_fingerprint(native) != locked_source:
        raise ArtCraftError("AniCraft saved document changed after reopening")
    return {
        "nativeSource": locked_source,
        "recipe": file_fingerprint(recipe),
        "frames": matte,
        "layers": [layer["name"] for layer in information["layers"]],
        "freshSessionDecodedRgbaMatched": True,
        "maxMatteError": maximum,
    }


def _require_new_output_directory(directory, budget, count):
    if (
        not directory.is_absolute()
        or directory.resolve() != directory
        or directory.exists()
    ):
        raise ArtCraftError("AniCraft requires a new absolute job output directory")
    if budget["files"] < 5 * count + 5:
        raise ArtCraftError(
            "AniCraft file budget does not cover all required render passes"
        )


def _profile_invocation(directory, budget, invoke, deadline):
    def call(*arguments):
        remaining = _remaining(deadline)
        payload = invoke(directory, *arguments, timeout=remaining)
        if len(payload) > 2 * 1024 * 1024:
            raise ArtCraftError("AniCraft command response exceeded the profile budget")
        _require_profile_budget(directory, budget)
        return payload

    return call


def _remaining(deadline):
    remaining = deadline - monotonic()
    if remaining <= 0:
        raise ArtCraftError("AniCraft job exhausted its time budget")
    return remaining


def _require_profile_budget(directory, budget):
    count = size = 0
    for path in directory.rglob("*"):
        if path.resolve() != path:
            raise ArtCraftError("AniCraft created an external path alias")
        if path.is_dir():
            continue
        metadata = path.stat()
        if not path.is_file() or metadata.st_nlink != 1:
            raise ArtCraftError("AniCraft created a nonregular or shared file")
        count += 1
        size += metadata.st_size
        if count > budget["files"] or size > budget["bytes"]:
            raise ArtCraftError("AniCraft job exceeded its file or byte budget")
    return size


def _author_document(call, directory, native, recipe, steps, output, font):
    empty = directory / "empty.anicraft"
    width, height, fps = output["width"], output["height"], _profile_clock(output)
    call("new", "--out", empty, "--width", width, "--height", height, "--fps", fps)
    installed = json.loads(call("exec", empty, "text.fonts"))
    if font not in installed.get("families", []):
        raise ArtCraftError("AniCraft cannot resolve the exact requested font family")
    responses = json.loads(call("run", empty, recipe))
    if (
        not isinstance(responses, list)
        or len(responses) != len(steps)
        or not native.is_file()
    ):
        raise ArtCraftError(
            "AniCraft did not report every authoring operation or save its native document"
        )


def _inspect_document(call, native, output):
    document = json.loads(call("info", native))
    expected = (output["width"], output["height"], _profile_clock(output), "#ffffff")
    stage = tuple(
        document["stage"][key] for key in ("width", "height", "fps", "background")
    )
    if stage != expected or document["movie_frames"] != output["frameCount"]:
        raise ArtCraftError(
            "AniCraft saved document does not match its exact canvas and clock"
        )
    if document["sounds"] or len(document["scenes"]) != 1:
        raise ArtCraftError(
            "AniCraft saved document contains unsupported audio or scenes"
        )
    if any(
        key.get("script") or key.get("sound")
        for layer in document["layers"]
        for key in layer["keyframes"]
    ):
        raise ArtCraftError(
            "AniCraft saved document contains unsupported scripts or sounds"
        )
    return document


def _render_backings(call, directory, native, count):
    reopened = directory / "reopened"
    _render_sequence(call, native, reopened, count)
    black = _render_backing(call, directory, native, count, "black", "#000000")
    check = _render_backing(call, directory, native, count, "check", "#3771ae")
    return reopened, black, check


def _render_sequence(call, native, folder, count):
    call("render-seq", native, "--out-dir", folder, "--from", 1, "--to", count)


def _render_backing(call, directory, native, count, name, color):
    altered, frames = directory / f"{name}.anicraft", directory / name
    call(
        "exec",
        native,
        "doc.set_stage",
        json.dumps({"background": color}),
        "--save",
        altered,
    )
    _render_sequence(call, altered, frames, count)
    return frames


def _render_matte(backings, directory, output, budget, deadline):
    target = directory / "alpha"
    names = [f"frame_{frame:05d}.png" for frame in range(1, output["frameCount"] + 1)]
    expected_names = set(names)
    if any(
        {path.name for path in folder.iterdir()} != expected_names
        for folder in backings
    ):
        raise ArtCraftError(
            "AniCraft render sequence differs from its exact frame range"
        )
    target.mkdir()
    used_bytes = _require_profile_budget(directory, budget)
    dimensions = output["width"], output["height"]
    rendered, maximum, boxes = [], 0, []
    for name in names:
        _remaining(deadline)
        matte, error = _open_matte_frame(backings, name, dimensions)
        path = target / name
        matte.save(path, format="PNG")
        fingerprint = file_fingerprint(path)
        used_bytes += fingerprint["sizeBytes"]
        if used_bytes > budget["bytes"]:
            raise ArtCraftError("AniCraft alpha output exceeded the byte budget")
        rendered.append(fingerprint)
        maximum = max(maximum, error)
        boxes.append(matte.getchannel("A").getbbox())
    _require_motion_observation(boxes, output["width"] / 640)
    return rendered, maximum


def _open_matte_frame(backings, name, dimensions):
    from PIL import Image

    with ExitStack() as stack:
        frames = [stack.enter_context(Image.open(folder / name)) for folder in backings]
        if any(image.format != "PNG" or image.size != dimensions for image in frames):
            raise ArtCraftError(
                "AniCraft frame format or canvas differs from the render contract"
            )
        white, reopened, dark, check = frames
        if white.convert("RGBA").tobytes() != reopened.convert("RGBA").tobytes():
            raise ArtCraftError(
                "AniCraft saved source did not reproduce its exact original frames"
            )
        return recover_matte(white, dark, check)


def _require_motion_observation(boxes, scale):
    count = len(boxes)
    enter, hold, leave, exit_end = (
        count // 8,
        count // 3,
        3 * count // 4,
        7 * count // 8,
    )
    if (
        boxes[0]
        or boxes[-1]
        or any(boxes[index] is None for index in (enter, hold, leave, exit_end))
    ):
        raise ArtCraftError(
            "AniCraft rendered phases do not contain the required clear and visible frames"
        )
    if not boxes[enter][0] < boxes[hold][0] == boxes[leave][0] > boxes[exit_end][0]:
        raise ArtCraftError(
            "AniCraft rendered phases do not match the selected entrance, hold and exit"
        )
    _require_safe_area(boxes, scale)


def _require_safe_area(boxes, scale):
    expected = [round(value * scale) for value in (23, 267, 319, 325)]
    for box in filter(None, boxes):
        if (
            box[0] < expected[0] - 2
            or box[1] < expected[1] - 2
            or box[2] > expected[2] + 2
            or box[3] > expected[3] + 2
        ):
            raise ArtCraftError("AniCraft label exceeds its inspected safe area")
