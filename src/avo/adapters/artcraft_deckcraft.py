"""Author an editable DeckCraft master layout and inspect one fade frame."""

import json
from hashlib import sha256
from zipfile import BadZipFile, ZipFile

from PIL import Image, PngImagePlugin

from avo.artcraft import ArtCraftError
from avo.timeline.contracts import file_fingerprint
from avo.timeline.store import write_immutable_json

from .artcraft_native_cli import (
    bounded_native_invocation,
    observe_native_command_schema,
)

_LAYOUT = "AVO Explanation"
_SLIDE_POINTS = [960, 540]
_FRAME = [0, 0, *_SLIDE_POINTS]
_PLACEHOLDER = [64, 72, 832, 396]
_SLIDE = 1
_FADE_MS = 600
_START = "#164E63"
_END = "#BE123C"
_COMMAND_RESULT_FIELDS = {
    "view.slideMaster": {"kind": str, "master": int},
    "master.insertLayout": {"id": int},
    "master.insertPlaceholder": {"id": int},
    "slide.layout": {"layout": int},
    "shape.insert": {"id": int},
    "slide.new": {"id": int, "index": int},
    "transition.set": {"kind": str},
    "slide.inspect": {"index": int, "transition": dict},
}


def _steps():
    return [
        ("view.slideMaster", {"master": 0}),
        ("master.insertLayout", {"name": _LAYOUT}),
        ("master.insertPlaceholder", {"kind": "content", "rect": _PLACEHOLDER}),
        ("view.closeMaster", {}),
        ("slide.layout", {"layout": "blank", "index": 0}),
        ("shape.insert", {"preset": "rect", "rect": _FRAME}),
        ("shape.fill", {"color": _START}),
        ("slide.new", {"layout": _LAYOUT}),
        ("slide.rename", {"name": "Explanation", "index": _SLIDE}),
        ("shape.insert", {"preset": "rect", "rect": _FRAME}),
        ("shape.fill", {"color": _END}),
        ("transition.set", {"kind": "fade", "duration": _FADE_MS, "index": _SLIDE}),
    ]


def observe_deckcraft(executable, environment):
    return observe_native_command_schema(
        executable,
        environment,
        needed={command for command, _ in _steps()} | {"slide.inspect"},
        label="DeckCraft",
        json_registry=False,
    )


def author_deck_slide(job, *, directory, invoke):
    output, budget = job["output"], job["budget"]
    if directory.resolve() != directory or directory.exists() or budget["files"] < 8:
        raise ArtCraftError(
            "DeckCraft requires a fresh owned folder with eight available files"
        )
    directory.mkdir(parents=True)
    call = bounded_native_invocation(directory, budget, invoke, label="DeckCraft slide")
    native = directory / "component.deckcraft"
    recipe = _create_deck(call, directory, native, budget)
    fingerprint = file_fingerprint(native)
    _inspect_deck(call, native)
    frame_hash = _render_fade_evidence(call, directory, native, output)
    if file_fingerprint(native) != fingerprint:
        raise ArtCraftError("DeckCraft inspection or rendering changed the saved deck")
    return {
        "nativeSource": fingerprint,
        "recipe": file_fingerprint(recipe),
        "media": file_fingerprint(directory / "slide.png"),
        "stillEvidence": {
            **{
                key: output[key]
                for key in ("width", "height", "format", "color", "alpha")
            },
            "rgbaSha256": frame_hash,
        },
    }


def _create_deck(call, directory, output, budget):
    steps = _steps()
    recipe = write_immutable_json(
        directory / "recipe.json", {"slide": _SLIDE, "steps": steps}
    )
    script = directory / "commands.txt"
    with script.open("x", encoding="utf-8") as stream:
        stream.write(
            "".join(
                f"{command}={json.dumps(parameters)}\n" for command, parameters in steps
            )
        )
    reported = _receipts(call("run", "--cmd-file", script, "--print", "--save", output))
    if [name for name, _ in reported] != [name for name, _ in steps]:
        raise ArtCraftError("DeckCraft did not report every selected command")
    if reported[7][1]["index"] != _SLIDE or reported[-1][1] != {"kind": "fade"}:
        raise ArtCraftError("DeckCraft did not author the selected slide and fade")
    _require_native_members(output, budget["bytes"])
    return recipe


def _receipts(response):
    rows = []
    try:
        for line in response.decode("utf-8").splitlines():
            name, delimiter, facts = line.partition(" → ")
            if not delimiter:
                raise ArtCraftError("DeckCraft returned unrecognized command output")
            result = json.loads(facts)
            if not _valid_receipt(name, result):
                raise ArtCraftError("DeckCraft returned an invalid command result")
            rows.append((name, result))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ArtCraftError("DeckCraft returned malformed command output") from exc
    return rows


def _valid_receipt(name, result):
    if name in {"view.closeMaster", "slide.rename"}:
        return result is None
    if name == "shape.fill":
        return type(result) is int
    required = _COMMAND_RESULT_FIELDS.get(name)
    return (
        required is not None
        and isinstance(result, dict)
        and "error" not in result
        and all(type(result.get(key)) is kind for key, kind in required.items())
    )


def _require_native_members(path, byte_limit):
    try:
        with ZipFile(path) as deck:
            if (
                sorted(deck.namelist()) != ["mimetype", "presentation.json"]
                or sum(item.file_size for item in deck.infolist()) > byte_limit
            ):
                raise ArtCraftError("DeckCraft native deck contains unverified assets")
    except (OSError, BadZipFile) as error:
        raise ArtCraftError(
            "DeckCraft did not produce a readable native deck"
        ) from error


def _inspect_deck(call, native):
    document = json.loads(call("info", native))
    layouts = [layout["name"] for layout in document["layouts"]]
    slides = [(slide["index"], slide["layout"]) for slide in document["slides"]]
    if (
        document["slideSize"] != _SLIDE_POINTS
        or document["media"] != []
        or layouts.count(_LAYOUT) != 1
        or slides != [(0, "Blank"), (_SLIDE, _LAYOUT)]
    ):
        raise ArtCraftError(
            "DeckCraft reopened with different layouts, slide geometry or media"
        )
    ((command, target),) = _receipts(
        call("run", "--in", native, "--print", "--cmd", 'slide.inspect={"index":1}')
    )
    _require_reopened_slide(command, target)


def _require_reopened_slide(command, target):
    if (
        command,
        target["index"],
        target["transition"]["kind"],
        target["transition"]["durationMs"],
    ) != ("slide.inspect", _SLIDE, "fade", _FADE_MS):
        raise ArtCraftError(
            "DeckCraft reopened without the selected indexed 600 ms fade"
        )
    shapes = [
        (shape["kind"], shape["box"], shape["fill"]) for shape in target["shapes"]
    ]
    if ("placeholder", _PLACEHOLDER, "none") not in shapes or (
        "shape",
        _FRAME,
        _END,
    ) not in shapes:
        raise ArtCraftError(
            "DeckCraft reopened without the editable master placeholder and slide shape"
        )


def _render_fade_evidence(call, directory, native, output):
    _render_frame(call, native, directory / "start.png", "0", output, (22, 78, 99, 255))
    _render_frame(
        call, native, directory / "finish.png", "1", output, (190, 18, 60, 255)
    )
    midpoint = (106, 48, 80, 255)
    frame = _render_frame(
        call, native, directory / "fade-midpoint.png", "0.5", output, midpoint
    )
    pixel_hash = sha256(frame.tobytes()).hexdigest()
    metadata = PngImagePlugin.PngInfo()
    metadata.add(b"sRGB", b"\x00")
    with (directory / "slide.png").open("xb") as review:
        frame.save(review, format="PNG", pnginfo=metadata)
    reopened = _render_frame(
        call, native, directory / "reopened.png", "0.5", output, midpoint
    )
    if sha256(reopened.tobytes()).hexdigest() != pixel_hash:
        raise ArtCraftError("DeckCraft did not reproduce exact transition pixels")
    return pixel_hash


def _render_frame(call, native, path, position, output, expected):
    width, height = output["width"], output["height"]
    call(
        "render-transition",
        native,
        "--slide",
        str(_SLIDE),
        "--t",
        position,
        "--width",
        str(width),
        path,
    )
    with Image.open(path, formats=["PNG"]) as frame:
        if (
            (frame.mode, frame.size) != ("RGBA", (width, height))
            or frame.getpixel((width // 2, height // 2)) != expected
            or "icc_profile" in frame.info
        ):
            raise ArtCraftError(
                "DeckCraft transition frame differs from the selected sRGB sample"
            )
        return frame.copy()
