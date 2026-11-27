"""Author and verify a bounded EffectCraft masked lower-third review."""

import json
from hashlib import sha256
from pathlib import Path

from PIL import Image, ImageFont

from avo.artcraft import _EFFECT_SOURCE_WINDOW, ArtCraftError
from avo.timeline.contracts import file_fingerprint
from avo.timeline.store import write_immutable_json

from .artcraft_native_cli import (
    bounded_native_invocation,
    observe_native_command_schema,
)

_COMP = "Lower third"
_TEXT = "Editable label"
_BACKING = "Masked backing"
_MASK = [[24, 108], [296, 108], [296, 160], [24, 160]]
_RATE = 24
_FONT_SIZE = 25
_COMMAND_RESULTS = {
    "comp.new": "comp",
    "layer.newSolid": "layer",
    "mask.new": "mask",
    "layer.newText": "layer",
}


def observe_effectcraft(executable, environment):
    return observe_native_command_schema(
        executable, environment, needed=set(_COMMAND_RESULTS), label="EffectCraft"
    )


def author_effect_mask(job, *, directory, invoke):
    budget = job["budget"]
    label = job["authoringParameters"]["primaryText"]
    font = job["inputs"][0]
    face = ImageFont.truetype(font["locator"], size=_FONT_SIZE)
    if face.getlength(label) > 248:
        raise ArtCraftError("EffectCraft label does not fit the selected lower third")
    if directory.resolve() != directory or directory.exists() or budget["files"] < 10:
        raise ArtCraftError(
            "EffectCraft needs a fresh owned folder and ten available files"
        )
    directory.mkdir(parents=True)
    (directory / "alpha").mkdir()
    invoke = bounded_native_invocation(
        directory,
        budget,
        invoke,
        label="EffectCraft mask review",
        owned_directories=("alpha",),
    )
    native, recipe = _save_project(invoke, directory, label)
    fingerprint = file_fingerprint(native)
    _inspect_reopened_project(invoke, native, label)
    frames = _render_review_frames(invoke, directory, native)
    if (
        file_fingerprint(native) != fingerprint
        or file_fingerprint(Path(font["locator"])) != font
    ):
        raise ArtCraftError("EffectCraft modified the pinned font or native project")
    return {
        "nativeSource": fingerprint,
        "recipe": file_fingerprint(recipe),
        "frames": frames,
    }


def _save_project(call, directory, label):
    native = directory / "component.ecproj"
    steps = [
        _step(
            "comp.new", name=_COMP, width=320, height=180, frameRate=_RATE, duration=1
        ),
        _step("layer.newSolid", name=_BACKING, color="#164E63", width=320, height=180),
        _step("mask.new", vertices=_MASK, closed=True, mode="add"),
        _step(
            "layer.newText",
            name=_TEXT,
            text=label,
            position=[36, 141],
            font="Arial",
            size=_FONT_SIZE,
            fill="#FFFFFF",
        ),
    ]
    recipe = write_immutable_json(directory / "recipe.json", steps)
    response = call(
        "--empty", "run", "--commands", recipe, "--save-as", native, "--json"
    )
    try:
        result = json.loads(response)
    except ValueError as exc:
        raise ArtCraftError("EffectCraft returned malformed command output") from exc
    if (
        not isinstance(result, dict)
        or "error" in result
        or result.get("saved") != str(native)
        or not isinstance(rows := result.get("result"), list)
        or len(rows) != len(steps)
        or any(
            not _valid_command_result(row, step["command"])
            for row, step in zip(rows, steps, strict=True)
        )
    ):
        raise ArtCraftError(
            "EffectCraft did not save every selected lower-third command"
        )
    return native, recipe


def _valid_command_result(row, command):
    return (
        isinstance(row, dict)
        and row.keys() == {"command", "result"}
        and row["command"] == command
        and isinstance(result := row["result"], dict)
        and "error" not in result
        and type(result.get(_COMMAND_RESULTS[command])) is int
    )


def _step(command, **params):
    return {"command": command, "params": params}


def _inspect_reopened_project(call, native, label):
    summary = json.loads(call("--project", native, "info", "--json"))
    comp = summary["activeComp"]
    layers = [(layer["name"], layer["type"]) for layer in comp["layers"]]
    if (
        comp["name"],
        comp["width"],
        comp["height"],
        comp["frameRate"],
        comp["duration"],
    ) != (_COMP, 320, 180, _RATE, 1) or layers != [
        (_TEXT, "Text"),
        (_BACKING, "Solid"),
    ]:
        raise ArtCraftError(
            "EffectCraft reopened with a different timebase, canvas or layer order"
        )
    if {record["type"] for record in summary["project"]["items"]} != {
        "Composition",
        "Folder",
        "Solid",
    } or summary["project"]["bitDepth"] != "8 bpc":
        raise ArtCraftError("EffectCraft project contains unverified external footage")
    _require_editable_properties(call, native, comp["id"], label)


def _require_editable_properties(call, native, comp, label):
    project = json.loads(native.read_bytes())
    if (project["savedBy"], project["schema"], project["activeComp"]) != (
        "0.24.1",
        2,
        comp,
    ):
        raise ArtCraftError("EffectCraft saved an unsupported project format")
    text = project["items"][str(comp)]["kind"]["layers"][0]["props"]["children"][0][
        "children"
    ][0]
    if text["value"]["v"]["font"] != "Arial":
        raise ArtCraftError("EffectCraft did not retain the selected text font")
    label_props = _properties(call, native, _TEXT)
    mask = _properties(call, native, _BACKING)["masks/mask/path"]["v"]
    if (
        label_props["text/sourceText"] != label
        or not mask["closed"]
        or mask["vertices"] != _MASK
    ):
        raise ArtCraftError(
            "EffectCraft reopened without the selected editable text and mask"
        )


def _properties(call, native, name):
    response = json.loads(
        call("--project", native, "props", _COMP, name, "--flat", "--json")
    )
    return {item["path"]: item["value"] for item in response["properties"]}


def _render_review_frames(call, directory, native):
    first = _EFFECT_SOURCE_WINDOW["startFrame"]
    end = _EFFECT_SOURCE_WINDOW["endFrameExclusive"]
    alpha = directory / "alpha"
    raw = [alpha / f"partial_{frame:05d}.png" for frame in range(first, end)]
    result = json.loads(
        call(
            "--project",
            native,
            "render",
            "--comp",
            _COMP,
            "--out",
            alpha / "partial.png",
            "--format",
            "png",
            "--start",
            str(first / _RATE),
            "--end",
            str(end / _RATE),
            "--fps",
            str(_RATE),
            "--channels",
            "rgba",
            "--audio",
            "off",
            "--json",
        )
    )
    (rendered,) = result["rendered"]
    if rendered["output"] != str(raw[0]) or set(alpha.iterdir()) != set(raw):
        raise ArtCraftError(
            "EffectCraft did not render the exact selected half-open source span"
        )
    clock_hashes = _reopen_selected_frame(call, directory, native, first)
    fingerprints = []
    for index, frame in enumerate(raw, 1):
        if _inspect_frame(frame) != clock_hashes:
            raise ArtCraftError(
                "EffectCraft partial frame differs from the verified still hold"
            )
        retained = frame.rename(alpha / f"frame_{index:05d}.png")
        fingerprints.append(file_fingerprint(retained))
    return fingerprints


def _reopen_selected_frame(call, directory, native, frame):
    seconds = frame / _RATE
    paths = []
    for unit, value in (("frame", str(frame)), ("time", str(seconds))):
        target = directory / f"clock-{unit}.png"
        response = json.loads(
            call(
                "--project",
                native,
                "render-frame",
                "--comp",
                _COMP,
                f"--{unit}",
                value,
                "--transparent",
                "--out",
                target,
                "--json",
            )
        )
        if response["time"] != seconds or response["path"] != str(target):
            raise ArtCraftError(
                "EffectCraft frame and seconds clock did not resolve to the same time"
            )
        paths.append(target)
    by_frame, by_time = map(_inspect_frame, paths)
    if by_frame != by_time:
        raise ArtCraftError(
            "EffectCraft time and frame selections rendered different pixels"
        )
    return by_frame


def _inspect_frame(path):
    with Image.open(path, formats=["PNG"]) as image:
        if (
            (image.mode, image.size) != ("RGBA", (320, 180))
            or image.getpixel((10, 10)) != (0, 0, 0, 0)
            or image.getpixel((270, 154)) != (22, 78, 99, 255)
            or image.getpixel((315, 132)) != (0, 0, 0, 0)
        ):
            raise ArtCraftError(
                "EffectCraft PNG differs from the selected transparent mask"
            )
        return sha256(image.tobytes()).hexdigest()
