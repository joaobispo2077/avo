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
EMBLEM_COMMANDS = (
    LOWER_THIRD_COMMANDS - {"draw.rect", "text.create", "text.fonts"}
) | {"file.import"}

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


def _lower_third_labels(parameters, scale, offset):
    labels = [_speaker_label(parameters, scale, offset)]
    if "secondaryText" not in parameters:
        return labels
    text = parameters["secondaryText"]
    if (
        not isinstance(text, str)
        or not text.strip()
        or len(text) > 48
        or any(char in text for char in "\r\n\0—")
    ):
        raise ArtCraftError("Choose one nonempty secondary label within 48 characters")
    labels.append(
        _step(
            "text.create",
            text=text,
            x=42 * scale,
            y=306 * scale + offset,
            font=parameters["font"],
            size=14 * scale,
            color="#e0ebf6",
        )
    )
    return labels


def lower_third_steps(
    output, parameters, source, white_directory, *, identity_svg=None
):
    """Build the selected native commands, with frame numbers in the document clock."""
    _profile_clock(output)
    scale, offset = _lower_third_layout(output)
    hold = "motion" in parameters
    if hold and parameters["motion"] != "hold":
        raise ArtCraftError("AniCraft lower-third motion must select a fixed hold")
    distance = 24 * scale
    labels = _lower_third_labels(parameters, scale, offset)
    artwork = [
        _step(
            "draw.rect",
            x=24 * scale,
            y=268 * scale + offset,
            w=270 * scale,
            h=56 * scale,
            radius=8 * scale,
            fill="#102c48",
        ),
        *labels,
    ]
    if identity_svg is not None:
        for label in labels:
            label["params"]["x"] += 32 * scale
        artwork.extend(_identity_artwork(identity_svg, scale, offset))
    if hold:
        for step in artwork:
            step["params"]["x"] += distance
    return _slide_steps(
        output,
        artwork,
        source,
        white_directory,
        "Speaker label",
        "Speaker plate",
        distance,
        hold=hold,
    )


def _identity_artwork(svg, scale, offset):
    x, y = 35 * scale, 283 * scale + offset
    factor = 0.18 * scale
    return [
        _step(
            "draw.rect",
            x=31 * scale,
            y=279 * scale + offset,
            w=31 * scale,
            h=31 * scale,
            radius=5 * scale,
            fill="#f5f8fb",
        ),
        _step("file.import", path=str(svg), x=x, y=y, layer="active"),
        _step("element.set_transform", x=x, y=y, sx=factor, sy=factor),
    ]


def _slide_steps(
    output, artwork, source, white_directory, layer, symbol, distance, *, hold=False
):
    count = output["frameCount"]
    enter, visible = count // 8, count // 3
    leave, exit_end = 3 * count // 4, 7 * count // 8
    motion_steps = []
    if not hold:
        motion_steps = [
            *_move_key(visible, distance),
            _step("timeline.create_tween", frame=enter),
            _step("timeline.insert_keyframe", frame=leave),
            *_move_key(exit_end, -distance),
            _step("timeline.create_tween", frame=leave),
        ]
    return [
        _step("layer.new", name=layer),
        _step("timeline.insert_blank_keyframe", frame=enter),
        _step("timeline.goto", frame=enter),
        *artwork,
        _step("edit.select_all"),
        _step("modify.convert_to_symbol", name=symbol, kind="graphic"),
        *motion_steps,
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


def inspect_lower_third_source(native, output, parameters, *, max_bytes, artwork=None):
    """Inspect the selected native JSON without asking AniCraft to load it."""
    return _inspect_source_file(
        native,
        output,
        parameters,
        max_bytes=max_bytes,
        identity_outline=None
        if artwork is None
        else _selected_identity_outline(artwork),
    )


def inspect_animated_emblem_source(native, output, artwork, *, max_bytes):
    from .artcraft_vectorcraft import verify_emblem_svg

    digest, outline = verify_emblem_svg(Path(artwork["locator"]))
    if digest != artwork["sha256"]:
        raise ArtCraftError("AniCraft source no longer matches its selected artwork")
    return _inspect_source_file(
        native, output, None, max_bytes=max_bytes, emblem_path=outline
    )


def _inspect_source_file(
    native, output, parameters, *, max_bytes, emblem_path=None, identity_outline=None
):
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
        details = _native_source_profile(
            source,
            output,
            parameters,
            emblem_path=emblem_path,
            identity_outline=identity_outline,
        )
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


def _native_source_profile(
    source, output, parameters, *, emblem_path=None, identity_outline=None
):
    extra = 0 if identity_outline is None else 2
    paths, body = _native_document(
        source, output, path_counts=(1,) if emblem_path else (2 + extra, 3 + extra)
    )
    if emblem_path is not None:
        return _inspect_emblem_source(paths, body, output, emblem_path)
    return _inspect_label_source(paths, body, output, parameters, identity_outline)


def _inspect_label_source(paths, body, output, parameters, identity_outline):
    identity = identity_outline is not None
    symbol = _native_symbol(body)
    hold = _require_symbol_references(
        body["scenes"], symbol["id"], output["frameCount"], allow_hold=True
    )
    label_count = len(paths) - (3 if identity else 1)
    if identity and paths[-1] != identity_outline:
        raise ArtCraftError("AniCraft identity outline differs from the selected SVG")
    labels = _inspect_symbol_artwork(symbol, labels=label_count, identity=identity)
    facts = _observed_lower_third(labels, output, identity=identity)
    if hold:
        facts["motion"] = "hold"
    if parameters is not None and facts != parameters:
        raise ArtCraftError(
            "AniCraft saved editable text, font or motion differs from the selected parameters"
        )
    return {
        "editableText": facts["primaryText"],
        "fontFamily": facts["font"],
        **({"identityVectorHash": content_hash(identity_outline)} if identity else {}),
        **({"motion": "hold"} if hold else {}),
        **(
            {"editableSecondaryText": facts["secondaryText"]}
            if "secondaryText" in facts
            else {}
        ),
        "inlineVectorHash": content_hash(paths),
    }


def _observed_lower_third(labels, output, *, identity=False):
    primary, *optional = labels
    facts = {"primaryText": primary["text"], "font": primary["font"]}
    if identity:
        scale, _ = _lower_third_layout(output)
        if not all(0 < label["box_width"] <= 214 * scale for label in labels):
            raise ArtCraftError(
                "AniCraft text exceeds the identity layout's readable width"
            )
    if optional:
        (secondary,) = optional
        if secondary["font"] != primary["font"]:
            raise ArtCraftError(
                "AniCraft secondary text uses a different installed font"
            )
        scale, _ = _lower_third_layout(output)
        width = secondary["box_width"]
        _native_numbers((width,), 1)
        if not 0 < width <= 244 * scale:
            raise ArtCraftError("AniCraft secondary text exceeds its approved bounds")
        facts["secondaryText"] = secondary["text"]
    _lower_third_labels(facts, 1, 0)
    return facts


def _native_document(source, output, *, path_counts):
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
        or len(paths) not in path_counts
        or any(
            not isinstance(path, str) or not _VECTOR_PATH.fullmatch(path)
            for path in paths
        )
    ):
        raise ArtCraftError("AniCraft source must contain only inline vector paths")
    body = source["document"]
    _native_shape(body, "stage scenes library next_id")
    _require_native_canvas(body["stage"], output)
    return paths, body


def _inspect_emblem_source(paths, body, output, emblem_path):
    symbol = _native_symbol(body, name="Emblem")
    _require_symbol_references(
        body["scenes"], symbol["id"], output["frameCount"], layer="Emblem"
    )
    (element,) = _native_elements(symbol["timeline"])
    _native_shape(element, "Shape")
    if paths != [emblem_path] or _inspect_svg_shape(element) != 0:
        raise ArtCraftError(
            "AniCraft editable emblem does not match the selected polygon"
        )
    return {"inlineVectorHash": content_hash(paths)}


def _inspect_svg_shape(element):
    _native_shape(element, "Shape")
    shape = element["Shape"]
    _native_shape(shape, "fill fill_rule path stroke")
    _native_shape(shape["fill"], "Solid")
    _native_rgba(shape["fill"]["Solid"])
    _native_shape(shape["stroke"], "color width style")
    _native_rgba(shape["stroke"]["color"])
    _native_shape(shape["stroke"]["style"], "cap join miter_limit")
    return shape["path"]


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


def _native_symbol(body, *, name="Speaker plate"):
    if len(body["library"]) != 1:
        raise ArtCraftError("AniCraft source has unexpected library dependencies")
    symbol = body["library"][0]
    _native_shape(symbol, "id kind name timeline")
    if (symbol["name"], symbol["kind"]) != (name, "Graphic"):
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


def _require_symbol_references(
    scenes, expected_id, count, *, layer="Speaker label", allow_hold=False
):
    if len(scenes) != 1:
        raise ArtCraftError("AniCraft source must contain one selected scene")
    _native_shape(scenes[0], "name timeline")
    hold = _require_native_keyframes(
        scenes[0]["timeline"], count, layer, allow_hold=allow_hold
    )
    for reference in _native_elements(scenes[0]["timeline"]):
        _native_shape(reference, "Symbol")
        _native_shape(reference["Symbol"], "first_frame loop_mode symbol")
        if reference["Symbol"]["symbol"] != expected_id:
            raise ArtCraftError(
                "AniCraft source contains an unselected symbol reference"
            )
    return hold


def _require_native_keyframes(timeline, count, layer_name, *, allow_hold=False):
    layers = timeline["layers"]
    if [layer["name"] for layer in layers] != [layer_name, "Layer 1"]:
        raise ArtCraftError("AniCraft source has unexpected scene layers")
    starts = (
        0,
        count // 8,
        count // 3,
        3 * count // 4,
        7 * count // 8,
        count - 1,
        count,
    )
    frames = layers[0]["keyframes"]
    actual = [(frame["start"], frame["duration"]) for frame in frames]
    held_starts = (0, count // 8, count - 1, count)
    if any(frame["elements"] for frame in layers[1]["keyframes"]):
        raise ArtCraftError("AniCraft source has unexpected content in the blank layer")
    if allow_hold and actual == _keyframe_spans(held_starts):
        _require_fixed_keyframe_contents(frames)
        return True
    if actual != _keyframe_spans(starts):
        raise ArtCraftError(
            "AniCraft source keyframes differ from the selected lower-third profile"
        )
    return False


def _keyframe_spans(starts):
    return [(start, end - start) for start, end in pairwise(starts)]


def _require_fixed_keyframe_contents(frames):
    if [len(frame["elements"]) for frame in frames] != [0, 1, 0] or any(
        frame["tween"] is not None for frame in frames
    ):
        raise ArtCraftError("AniCraft fixed hold contains unexpected keyframe content")


def _inspect_symbol_artwork(symbol, *, labels, identity=False):
    elements = list(_native_elements(symbol["timeline"]))
    if len(elements) != labels + 1 + (2 if identity else 0):
        raise ArtCraftError("AniCraft source contains unexpected symbol artwork")
    shape, *texts = elements
    _inspect_plate_shape(shape, path_index=0)
    if identity:
        tile, icon = texts[-2:]
        _inspect_plate_shape(tile, path_index=labels + 1)
        if _inspect_svg_shape(icon) != labels + 2:
            raise ArtCraftError(
                "AniCraft identity artwork does not use its exact inline path"
            )
        texts = texts[:-2]
    return [_inspect_native_label(text, index) for index, text in enumerate(texts, 1)]


def _inspect_plate_shape(shape, *, path_index):
    _native_shape(shape, "Shape")
    _native_shape(shape["Shape"], "fill fill_rule path stroke")
    _native_shape(shape["Shape"]["fill"], "Solid")
    _native_rgba(shape["Shape"]["fill"]["Solid"])
    _native_shape(shape["Shape"]["stroke"], "color width")
    _native_rgba(shape["Shape"]["stroke"]["color"])
    if shape["Shape"]["path"] != path_index:
        raise ArtCraftError("AniCraft source refers outside its retained plate shape")


def _selected_identity_outline(artwork):
    from .artcraft_vectorcraft import verify_emblem_svg

    digest, outline = verify_emblem_svg(Path(artwork["locator"]))
    numbers = re.findall(r"\d+(?:\.\d+)?", outline)
    if digest != artwork["sha256"] or any(float(number) > 128 for number in numbers):
        raise ArtCraftError(
            "AniCraft identity requires the exact artwork inside its 128-unit canvas"
        )
    return outline


def _inspect_native_label(text, index):
    _native_shape(text, "Text")
    native_text = text["Text"]
    _native_shape(
        native_text,
        "align bold box_height box_width color font italic letter_spacing line_spacing outline size text width",
    )
    _native_rgba(native_text["color"])
    if native_text["outline"] != index:
        raise ArtCraftError(
            "AniCraft source refers outside its retained shape and text outlines"
        )
    return native_text


def run_lower_third(
    output, parameters, *, directory, budget, invoke, open_stream=None, artwork=None
):
    """Materialize the selected native recipe through a supplied confined runner."""
    directory = Path(directory)
    native, white = directory / "component.anicraft", directory / "white"
    identity = None if artwork is None else directory / "identity.svg"
    steps = lower_third_steps(output, parameters, native, white, identity_svg=identity)
    count = output["frameCount"]
    _require_new_output_directory(directory, budget, count)
    directory.mkdir(parents=True)
    deadline = monotonic() + budget["seconds"]
    call = _profile_invocation(directory, budget, invoke, deadline)
    outline = None if artwork is None else _prepare_identity(artwork, identity, call)
    recipe = write_immutable_json(directory / "recipe.json", steps)
    _require_profile_budget(directory, budget)
    empty = directory / "empty.anicraft"
    _initialize_document(call, empty, output, parameters["font"])
    replies = _apply_recipe(
        call, empty, native, recipe, steps, open_stream, budget, deadline
    )
    if identity is not None and replies is not None:
        index = next(
            index for index, step in enumerate(steps) if step["cmd"] == "file.import"
        )
        _require_emblem_import(replies[index])
    return _verified_export(
        call,
        native,
        recipe,
        output,
        parameters,
        budget,
        deadline,
        identity_outline=outline,
    )


def _prepare_identity(artwork, identity, call):
    from avo.artcraft import _copy_native_source

    _copy_native_source(identity, artwork)
    outline = _selected_identity_outline({**artwork, "locator": str(identity)})
    observe_command_schema(
        json.loads(call("commands")), required={"file.import", "element.set_transform"}
    )
    return outline


def run_animated_emblem(output, artwork, *, directory, budget, invoke):
    from avo.artcraft import _copy_native_source

    from .artcraft_vectorcraft import verify_emblem_svg

    count = output["frameCount"]
    _require_new_output_directory(directory, budget, count)
    directory.mkdir(parents=True)
    native, white = directory / "component.anicraft", directory / "white"
    retained = directory / "emblem.svg"
    _copy_native_source(retained, artwork)
    digest, emblem_path = verify_emblem_svg(retained)
    if digest != artwork["sha256"]:
        raise ArtCraftError("AniCraft SVG differs from the exact selected artwork")
    deadline = monotonic() + budget["seconds"]
    call = _profile_invocation(directory, budget, invoke, deadline)
    art = [_step("file.import", path=str(retained), x=36, y=26, layer="active")]
    steps = _slide_steps(output, art, native, white, "Emblem", "Emblem", 24)
    recipe = write_immutable_json(directory / "recipe.json", steps)
    empty = directory / "empty.anicraft"
    _initialize_document(call, empty, output, None)
    receipts = _apply_recipe(call, empty, native, recipe, steps, None, budget, deadline)
    _require_emblem_import(receipts[3])
    return _verified_export(
        call, native, recipe, output, None, budget, deadline, emblem_path=emblem_path
    )


def _require_emblem_import(receipt):
    expected = {
        "bitmap": None,
        "elements": 1,
        "height": 128.0,
        "layers": 0,
        "masks": 0,
        "missing_fonts": [],
        "skipped": {},
        "texts": 0,
        "width": 128.0,
    }
    if {key: receipt.get(key) for key in expected} != expected:
        raise ArtCraftError(
            "AniCraft import omitted or changed part of the editable emblem"
        )


def revise_lower_third(
    output,
    original_parameters,
    parameters,
    *,
    source,
    directory,
    budget,
    invoke,
    open_stream=None,
    artwork=None,
):
    """Change the selected editable label in a newly saved native revision."""
    from avo.artcraft import _copy_native_source

    source, directory = Path(source), Path(directory)
    original = inspect_lower_third_source(
        source, output, original_parameters, max_bytes=budget["bytes"], artwork=artwork
    )
    labels = _lower_third_labels(parameters, *_lower_third_layout(output))
    if parameters["font"] != original["fontFamily"]:
        raise ArtCraftError(
            "Changing the approved font requires a separately reviewed design"
        )
    if parameters.get("motion") != original.get("motion"):
        raise ArtCraftError(
            "Changing approved motion requires a separately reviewed design"
        )
    if ("secondaryText" in parameters) != ("editableSecondaryText" in original):
        raise ArtCraftError(
            "Changing available text slots requires a separately reviewed design"
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
        target,
        [step["params"]["text"] for step in labels],
        native,
        output["frameCount"],
    )
    recipe = write_immutable_json(directory / "recipe.json", steps)
    _require_profile_budget(directory, budget)
    _require_font(call, working, parameters["font"])
    _apply_recipe(call, working, native, recipe, steps, open_stream, budget, deadline)
    result = _verified_export(
        call,
        native,
        recipe,
        output,
        parameters,
        budget,
        deadline,
        identity_outline=None
        if artwork is None
        else _selected_identity_outline(artwork),
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
    elements = [
        element
        for layer in symbol["timeline"]["layers"]
        for frame in layer["keyframes"]
        for element in frame["elements"]
        if "Text" in element["kind"]
    ]
    for element in elements:
        text = element["kind"]["Text"]
        source["paths"][text["outline"]] = ""
        for key in ("text", "box_width"):
            text.pop(key)
    return source, (symbol["id"], [element["id"] for element in elements])


def _text_revision_steps(target, labels, native, count):
    symbol, elements = target
    steps = [
        _step("symbol.edit", symbol=symbol),
        _step("timeline.goto", frame=0),
    ]
    for element, label in zip(elements, labels, strict=True):
        steps.extend(
            (_step("element.select", ids=[element]), _step("text.edit", text=label))
        )
    return [
        *steps,
        _step("symbol.exit", all=True),
        _step("file.save_as", path=str(native)),
        _step(
            "file.export_png_sequence",
            dir=str(native.parent / "white"),
            **{"from": 0, "to": count - 1},
        ),
    ]


def _verified_export(
    call,
    native,
    recipe,
    output,
    parameters,
    budget,
    deadline,
    *,
    emblem_path=None,
    identity_outline=None,
):
    directory = native.parent
    white = directory / "white"
    source = _inspect_source_file(
        native,
        output,
        parameters,
        max_bytes=budget["bytes"],
        emblem_path=emblem_path,
        identity_outline=identity_outline,
    )
    locked_source = source["fingerprint"]
    symbol = "Emblem" if emblem_path is not None else "Speaker plate"
    information = _inspect_document(call, native, output, symbol=symbol)
    reopened, black, check = _render_backings(
        call, directory, native, output["frameCount"]
    )
    safe_bounds = (51, 38, 173, 132) if emblem_path is not None else None
    matte, maximum = _render_matte(
        (white, reopened, black, check),
        directory,
        output,
        budget,
        deadline,
        safe_bounds=safe_bounds,
        hold=source.get("motion") == "hold",
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


def _initialize_document(call, empty, output, font):
    width, height, fps = output["width"], output["height"], _profile_clock(output)
    call("new", "--out", empty, "--width", width, "--height", height, "--fps", fps)
    if font is not None:
        _require_font(call, empty, font)


def _require_font(call, document, font):
    installed = json.loads(call("exec", document, "text.fonts"))
    if font not in installed.get("families", []):
        raise ArtCraftError("AniCraft cannot resolve the exact requested font family")


def _apply_recipe(call, document, native, recipe, steps, open_stream, budget, deadline):
    if open_stream is not None:
        _run_json_lines(
            open_stream, document, native, steps, budget=budget, deadline=deadline
        )
        return
    responses = json.loads(call("run", document, recipe))
    if (
        not isinstance(responses, list)
        or len(responses) != len(steps)
        or not native.is_file()
    ):
        raise ArtCraftError(
            "AniCraft did not report every authoring operation or save its native document"
        )
    return responses


def _run_json_lines(open_stream, document, native, steps, *, budget, deadline):
    with open_stream(document, timeout=_remaining(deadline)) as session:
        ready = _json_lines_record(session, deadline)
        if (
            ready != {"app": "AniCraft", "ready": True, "version": "0.2.1"}
            or ready["ready"] is not True
        ):
            raise ArtCraftError(
                "AniCraft JSON-lines handshake differs from the selected release"
            )
        for index, step in enumerate(steps, 1):
            message = json.dumps({"id": index, **step}, ensure_ascii=False).encode(
                "utf-8"
            )
            session.send_line(message + b"\n", timeout=_remaining(deadline))
            reply = _json_lines_record(session, deadline)
            _require_json_lines_reply(reply, index)
            _require_profile_budget(native.parent, budget)
    if not native.is_file():
        raise ArtCraftError(
            "AniCraft JSON-lines recipe did not save its native document"
        )


def _json_lines_record(session, deadline):
    limit = 2 * 1024 * 1024
    raw = session.read_line(max_bytes=limit + 1, timeout=_remaining(deadline))
    if len(raw) > limit or not raw.endswith(b"\n"):
        raise ArtCraftError(
            "AniCraft JSON-lines reply exceeded its frame budget or was incomplete"
        )
    try:
        return json.loads(raw, object_pairs_hook=_distinct_native_fields)
    except ValueError as exc:
        raise ArtCraftError("AniCraft JSON-lines returned invalid JSON") from exc


def _require_json_lines_reply(reply, index):
    if (
        not isinstance(reply, dict)
        or type(reply.get("id")) is not int
        or reply["id"] != index
        or reply.get("ok") is not True
        or "result" not in reply
    ):
        raise ArtCraftError(
            f"AniCraft JSON-lines command {index} failed or had an invalid receipt"
        )


def _inspect_document(call, native, output, *, symbol="Speaker plate"):
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
    _require_native_library(document, symbol)
    return document


def _require_native_library(document, symbol):
    library = [
        (item["name"], item["kind"], item["frames"]) for item in document["library"]
    ]
    if library != [(symbol, "Graphic", 1)]:
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


def _render_matte(
    backings, directory, output, budget, deadline, *, safe_bounds=None, hold=False
):
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
    if hold:
        _require_fixed_hold(boxes, rendered, output)
    else:
        _require_motion_observation(boxes, output, safe_bounds=safe_bounds)
    return rendered, maximum


def _require_fixed_hold(boxes, rendered, output):
    enter = len(boxes) // 8
    if (
        any(boxes[:enter])
        or boxes[-1]
        or not all(boxes[enter:-1])
        or len({frame["sha256"] for frame in rendered[enter:-1]}) != 1
    ):
        raise ArtCraftError(
            "AniCraft fixed hold differs from its clear and static phases"
        )
    _require_safe_area(boxes, output, None)


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


def _require_motion_observation(boxes, output, *, safe_bounds=None):
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
    _require_safe_area(boxes, output, safe_bounds)


def _lower_third_bounds(output):
    scale, offset = _lower_third_layout(output)
    return (
        round(23 * scale),
        round(267 * scale + offset),
        round(319 * scale),
        round(325 * scale + offset),
    )


def _require_safe_area(boxes, output, bounds):
    expected = bounds or _lower_third_bounds(output)
    for box in filter(None, boxes):
        if (
            box[0] < expected[0] - 2
            or box[1] < expected[1] - 2
            or box[2] > expected[2] + 2
            or box[3] > expected[3] + 2
        ):
            raise ArtCraftError("AniCraft label exceeds its inspected safe area")
