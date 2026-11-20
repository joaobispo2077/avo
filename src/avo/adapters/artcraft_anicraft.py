"""The bounded AniCraft lower-third recipe and its measured alpha conversion."""

from __future__ import annotations

import hashlib
import json
import re
from contextlib import ExitStack
from fractions import Fraction
from itertools import pairwise
from pathlib import Path
from time import monotonic

from avo.artcraft import ArtCraftError
from avo.timeline.contracts import content_hash, file_fingerprint
from avo.timeline.store import write_immutable_json

MATTE_CHECK_RGB = (55, 113, 174)
_VECTOR_PATH = re.compile(r"[MmZzLlHhVvCcSsQqTtAaEe0-9+.,\s-]+\Z", re.ASCII)

LOWER_THIRD_COMMANDS = frozenset(
    {
        "doc.set_stage",
        "draw.rect",
        "edit.select_all",
        "element.translate",
        "file.export_png_sequence",
        "file.save_as",
        "layer.new",
        "modify.convert_to_symbol",
        "text.create",
        "text.fonts",
        "timeline.create_tween",
        "timeline.goto",
        "timeline.insert_blank_keyframe",
        "timeline.insert_keyframe",
    }
)
TEXT_REVISION_COMMANDS = frozenset(
    {"symbol.edit", "symbol.exit", "element.select", "text.edit"}
)

__all__ = [
    "LOWER_THIRD_COMMANDS",
    "MATTE_CHECK_RGB",
    "lower_third_steps",
    "observe_command_schema",
    "recover_matte",
    "revise_lower_third",
    "run_lower_third",
]


def observe_command_schema(commands, *, required=LOWER_THIRD_COMMANDS):
    """Retain only the native command signatures needed for this profile."""
    observed = {}
    for row in commands:
        name = row.get("id")
        if name not in required:
            continue
        signature = row.get("params")
        if name in observed or not isinstance(signature, str) or not signature.strip():
            raise ArtCraftError(
                "AniCraft command registry has an invalid selected signature"
            )
        observed[name] = signature
    if missing := sorted(required - observed.keys()):
        raise ArtCraftError(
            f"AniCraft is missing required lower-third commands: {', '.join(missing)}",
            code="ARTCRAFT_NOT_READY",
        )
    return observed


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
        or Fraction(width, height) not in (Fraction(16, 9), Fraction(9, 16))
        or output["role"] != "overlay-video"
        or output["format"] != "png-sequence"
        or output["alpha"] != "straight"
        or output["color"] != "srgb"
    ):
        raise ArtCraftError(
            "AniCraft lower-third contract requires 16:9 or 9:16 sRGB straight-alpha PNGs, an integral 1–120 fps clock and at least one second",
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


def _speaker_label(parameters, scale, offset):
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
        y=280 * scale + offset,
        font=font,
        size=24 * scale,
        color="#ffffff",
    )


def _lower_third_layout(output):
    scale = output["width"] / 640
    offset = (output["height"] - 360 * scale) * (268 / 360)
    return scale, offset


def lower_third_steps(output, parameters, source, white_directory):
    """Build the selected native commands, with frame numbers in the document clock."""
    _profile_clock(output)
    scale, offset = _lower_third_layout(output)
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
            y=268 * scale + offset,
            w=270 * scale,
            h=56 * scale,
            radius=8 * scale,
            fill="#102c48",
        ),
        _speaker_label(parameters, scale, offset),
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


def inspect_lower_third_source(native, output, parameters, *, max_bytes):
    """Inspect the selected native JSON without asking AniCraft to load it."""
    native = Path(native)
    if not native.is_absolute() or native.resolve() != native or not native.is_file():
        raise ArtCraftError("AniCraft source must be one exact regular native file")
    max_bytes = min(max_bytes, 2 * 1024 * 1024)
    metadata = native.stat()
    if metadata.st_nlink != 1 or metadata.st_size > max_bytes:
        raise ArtCraftError(
            "AniCraft source exceeds the byte budget or has a file alias"
        )
    with native.open("rb") as stream:
        raw = stream.read(max_bytes + 1)
    if len(raw) > max_bytes:
        raise ArtCraftError("AniCraft source exceeds the byte budget")
    try:
        source = json.loads(raw, object_pairs_hook=_distinct_native_fields)
        details = _native_source_profile(source, output, parameters)
    except (
        KeyError,
        TypeError,
        AttributeError,
        IndexError,
        RecursionError,
        json.JSONDecodeError,
        UnicodeError,
    ) as exc:
        raise ArtCraftError(
            "AniCraft source does not match the selected native document structure"
        ) from exc
    return {
        **details,
        "fingerprint": {
            "locator": str(native),
            "sizeBytes": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(),
        },
    }


def _distinct_native_fields(pairs):
    result = dict(pairs)
    if len(result) != len(pairs):
        raise ArtCraftError("AniCraft source contains duplicate native fields")
    return result


def _native_source_profile(source, output, parameters):
    _native_shape(source, "format version generator paths document")
    if (source["format"], source["version"], source["generator"]) != (
        "anicraft",
        3,
        "AniCraft 0.2.1",
    ):
        raise ArtCraftError(
            "AniCraft saved format or source release differs from the checked profile"
        )
    paths = source["paths"]
    if (
        not isinstance(paths, list)
        or len(paths) != 2
        or any(
            not isinstance(path, str) or not _VECTOR_PATH.fullmatch(path)
            for path in paths
        )
    ):
        raise ArtCraftError("AniCraft source must contain only inline vector paths")
    body = source["document"]
    _native_shape(body, "stage scenes library next_id")
    _require_native_canvas(body["stage"], output)
    symbol = _native_symbol(body)
    _require_symbol_references(body["scenes"], symbol["id"], output["frameCount"])
    text = _inspect_symbol_artwork(symbol)
    _speaker_label({"primaryText": text["text"], "font": text["font"]}, 1, 0)
    if parameters is not None and (
        text["text"] != parameters["primaryText"] or text["font"] != parameters["font"]
    ):
        raise ArtCraftError(
            "AniCraft saved editable text or font differs from the selected parameters"
        )
    return {
        "editableText": text["text"],
        "fontFamily": text["font"],
        "inlineVectorHash": content_hash(paths),
    }


def _native_shape(value, names):
    if not isinstance(value, dict) or set(value) != set(names.split()):
        raise ArtCraftError(
            "AniCraft source contains unexpected native document fields"
        )


def _require_native_canvas(stage, output):
    expected = {
        "width": output["width"],
        "height": output["height"],
        "fps": _profile_clock(output),
        "background": dict.fromkeys("rgba", 1.0),
    }
    if stage != expected:
        raise ArtCraftError(
            "AniCraft native source canvas differs from the selected contract"
        )


def _native_symbol(body):
    if len(body["library"]) != 1:
        raise ArtCraftError("AniCraft source has unexpected library dependencies")
    symbol = body["library"][0]
    _native_shape(symbol, "id kind name timeline")
    if symbol["name"] != "Speaker plate" or symbol["kind"] != "Graphic":
        raise ArtCraftError(
            "AniCraft source library lacks the selected editable graphic symbol"
        )
    return symbol


def _native_elements(timeline):
    _native_shape(timeline, "layers")
    for layer in timeline["layers"]:
        _native_shape(layer, "color id keyframes kind locked name outline visible")
        if layer["kind"] != "Normal":
            raise ArtCraftError("AniCraft source contains an unsupported layer kind")
        for frame in layer["keyframes"]:
            _native_shape(frame, "start duration elements tween label")
            if frame["tween"] not in (None, {"easing": "Linear"}):
                raise ArtCraftError(
                    "AniCraft source contains unsupported animation behavior"
                )
            for element in frame["elements"]:
                _native_shape(element, "color id kind name transform")
                _native_shape(element["transform"], "m")
                _native_numbers(element["transform"]["m"], 6)
                _native_shape(element["color"], "alpha tint tint_amount")
                _native_rgba(element["color"]["tint"])
                yield element["kind"]


def _native_numbers(values, count):
    if (
        not isinstance(values, (list, tuple))
        or len(values) != count
        or any(
            type(value) not in (int, float) or not -1_000_000 <= value <= 1_000_000
            for value in values
        )
    ):
        raise ArtCraftError("AniCraft source contains invalid numeric geometry")


def _native_rgba(color):
    _native_shape(color, "r g b a")
    _native_numbers(list(color.values()), 4)


def _require_symbol_references(scenes, expected_id, count):
    if len(scenes) != 1:
        raise ArtCraftError("AniCraft source must contain one selected scene")
    _native_shape(scenes[0], "name timeline")
    _require_native_keyframes(scenes[0]["timeline"], count)
    for reference in _native_elements(scenes[0]["timeline"]):
        _native_shape(reference, "Symbol")
        _native_shape(reference["Symbol"], "first_frame loop_mode symbol")
        if reference["Symbol"]["symbol"] != expected_id:
            raise ArtCraftError(
                "AniCraft source contains an unselected symbol reference"
            )


def _require_native_keyframes(timeline, count):
    layers = timeline["layers"]
    if [layer["name"] for layer in layers] != ["Speaker label", "Layer 1"]:
        raise ArtCraftError("AniCraft source has unexpected scene layers")
    starts = [
        0,
        count // 8,
        count // 3,
        3 * count // 4,
        7 * count // 8,
        count - 1,
        count,
    ]
    expected = [(start, end - start) for start, end in pairwise(starts)]
    actual = [(frame["start"], frame["duration"]) for frame in layers[0]["keyframes"]]
    if actual != expected or any(frame["elements"] for frame in layers[1]["keyframes"]):
        raise ArtCraftError(
            "AniCraft source keyframes differ from the selected lower-third profile"
        )


def _inspect_symbol_artwork(symbol):
    elements = list(_native_elements(symbol["timeline"]))
    if len(elements) != 2:
        raise ArtCraftError("AniCraft source contains unexpected symbol artwork")
    shape, text = elements
    _native_shape(shape, "Shape")
    _native_shape(shape["Shape"], "fill fill_rule path stroke")
    _native_shape(shape["Shape"]["fill"], "Solid")
    _native_rgba(shape["Shape"]["fill"]["Solid"])
    _native_shape(shape["Shape"]["stroke"], "color width")
    _native_rgba(shape["Shape"]["stroke"]["color"])
    _native_shape(text, "Text")
    native_text = text["Text"]
    _native_shape(
        native_text,
        "align bold box_height box_width color font italic letter_spacing line_spacing outline size text width",
    )
    _native_rgba(native_text["color"])
    if (shape["Shape"]["path"], native_text["outline"]) != (0, 1):
        raise ArtCraftError(
            "AniCraft source refers outside its retained shape and text outlines"
        )
    return native_text


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
    return _verified_export(call, native, recipe, output, parameters, budget, deadline)


def revise_lower_third(
    output, original_parameters, parameters, *, source, directory, budget, invoke
):
    """Change the selected editable label in a newly saved native revision."""
    from avo.artcraft import _copy_native_source

    source, directory = Path(source), Path(directory)
    original = inspect_lower_third_source(
        source, output, original_parameters, max_bytes=budget["bytes"]
    )
    _speaker_label(parameters, *_lower_third_layout(output))
    if parameters["font"] != original["fontFamily"]:
        raise ArtCraftError(
            "Changing the approved font requires a separately reviewed design"
        )
    _require_new_output_directory(directory, budget, output["frameCount"])
    if source.is_relative_to(directory):
        raise ArtCraftError("AniCraft revision requires a separate retained source")
    native = directory / "component.anicraft"
    directory.mkdir(parents=True)
    deadline = monotonic() + budget["seconds"]
    call = _profile_invocation(directory, budget, invoke, deadline)
    commands = observe_command_schema(
        json.loads(call("commands")), required=TEXT_REVISION_COMMANDS
    )
    working = directory / "original.anicraft"
    _copy_native_source(working, original["fingerprint"])
    prior, target = _native_text_target(working)
    steps = _text_revision_steps(
        target, parameters["primaryText"], native, output["frameCount"]
    )
    recipe = write_immutable_json(directory / "recipe.json", steps)
    _require_profile_budget(directory, budget)
    _require_font(call, working, parameters["font"])
    _run_recipe(call, working, native, recipe, steps)
    result = _verified_export(
        call, native, recipe, output, parameters, budget, deadline
    )
    if file_fingerprint(source) != original["fingerprint"]:
        raise ArtCraftError("AniCraft changed the preserved source during revision")
    revised, _ = _native_text_target(native)
    if revised != prior:
        raise ArtCraftError(
            "AniCraft changed native design outside the selected editable text"
        )
    return {**result, "revisionCommandSchemaHash": content_hash(commands)}


def _native_text_target(path):
    source = json.loads(path.read_bytes(), object_pairs_hook=_distinct_native_fields)
    symbol = _native_symbol(source["document"])
    element = next(
        element
        for layer in symbol["timeline"]["layers"]
        for frame in layer["keyframes"]
        for element in frame["elements"]
        if "Text" in element["kind"]
    )
    text = element["kind"]["Text"]
    for key in ("text", "box_width"):
        text.pop(key)
    source["paths"][1] = ""
    return source, (symbol["id"], element["id"])


def _text_revision_steps(target, label, native, count):
    symbol, element = target
    return [
        _step("symbol.edit", symbol=symbol),
        _step("timeline.goto", frame=0),
        _step("element.select", ids=[element]),
        _step("text.edit", text=label),
        _step("symbol.exit", all=True),
        _step("file.save_as", path=str(native)),
        _step(
            "file.export_png_sequence",
            dir=str(native.parent / "white"),
            **{"from": 0, "to": count - 1},
        ),
    ]


def _verified_export(call, native, recipe, output, parameters, budget, deadline):
    directory = native.parent
    white = directory / "white"
    source = inspect_lower_third_source(
        native, output, parameters, max_bytes=budget["bytes"]
    )
    locked_source = source["fingerprint"]
    information = _inspect_document(call, native, output)
    reopened, black, check = _render_backings(
        call, directory, native, output["frameCount"]
    )
    matte, maximum = _render_matte(
        (white, reopened, black, check), directory, output, budget, deadline
    )
    _require_profile_budget(directory, budget)
    if file_fingerprint(native) != locked_source:
        raise ArtCraftError("AniCraft saved document changed after reopening")
    return {
        "nativeSource": locked_source,
        "sourceObservations": source,
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
    _require_font(call, empty, font)
    _run_recipe(call, empty, native, recipe, steps)


def _require_font(call, document, font):
    installed = json.loads(call("exec", document, "text.fonts"))
    if font not in installed.get("families", []):
        raise ArtCraftError("AniCraft cannot resolve the exact requested font family")


def _run_recipe(call, document, native, recipe, steps):
    responses = json.loads(call("run", document, recipe))
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
    _require_native_library(document)
    return document


def _require_native_library(document):
    library = [
        (item["name"], item["kind"], item["frames"]) for item in document["library"]
    ]
    if library != [("Speaker plate", "Graphic", 1)]:
        raise ArtCraftError(
            "AniCraft saved document has unexpected library dependencies"
        )


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
    _require_motion_observation(boxes, output)
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


def _require_motion_observation(boxes, output):
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
    _require_safe_area(boxes, output)


def _require_safe_area(boxes, output):
    scale, offset = _lower_third_layout(output)
    expected = (
        round(23 * scale),
        round(267 * scale + offset),
        round(319 * scale),
        round(325 * scale + offset),
    )
    for box in filter(None, boxes):
        if (
            box[0] < expected[0] - 2
            or box[1] < expected[1] - 2
            or box[2] > expected[2] + 2
            or box[3] > expected[3] + 2
        ):
            raise ArtCraftError("AniCraft label exceeds its inspected safe area")
