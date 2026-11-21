"""Author and verify the selected FigCraft component variant recipe."""

import json
from hashlib import sha256
from zipfile import BadZipFile, ZipFile

from PIL import Image

from avo.artcraft import ArtCraftError
from avo.timeline.contracts import file_fingerprint
from avo.timeline.store import write_immutable_json

from .artcraft_native_cli import (
    bounded_native_invocation,
    observe_native_command_schema,
)

_CREATE = "node.create"
_GET = "node.get"
_VARIANTS = "component.combineVariants"
_INTERACTION = "proto.interaction.add"


def observe_figcraft(executable, environment):
    return observe_native_command_schema(
        executable,
        environment,
        needed={_CREATE, _GET, _VARIANTS, _INTERACTION},
        label="FigCraft",
    )


def author_fig_variant(job, *, directory, invoke):
    budget, output = job["budget"], job["output"]
    if directory.resolve() != directory or directory.exists() or budget["files"] < 8:
        raise ArtCraftError(
            "FigCraft requires a fresh owned folder with eight available files"
        )
    directory.mkdir(parents=True)
    call = bounded_native_invocation(
        directory, budget, invoke, label="FigCraft variant"
    )
    native, recipe, node = _author_document(call, directory, budget)
    fingerprint = file_fingerprint(native)
    first = _export_card(call, native, node, directory / "design.png", output)
    second = _export_card(call, native, node, directory / "reopened.png", output)
    if first != second or file_fingerprint(native) != fingerprint:
        raise ArtCraftError("FigCraft did not reproduce exact rasterized pixels")
    return {
        "nativeSource": fingerprint,
        "recipe": file_fingerprint(recipe),
        "media": file_fingerprint(directory / "design.png"),
        "stillEvidence": {
            **{
                key: output[key]
                for key in ("width", "height", "format", "color", "alpha")
            },
            "rgbaSha256": first,
        },
    }


def _author_document(call, directory, budget):
    staging, native = directory / "layout.figcraft", directory / "component.figcraft"
    initial = [
        _layout("Compact", 320, 0, "#164e63"),
        _layout("Wide", 640, 480, "#14532d"),
    ]
    created = _run_script(call, directory, "create", initial, "--out", staging)
    compact, wide = (row["id"] for row in created)
    _require_native_members(staging, budget["bytes"])
    edit = [
        _action(compact),
        _action(wide),
        _step(_VARIANTS, ids=[compact, wide]),
        _step(
            _INTERACTION,
            id=compact,
            trigger={"type": "onClick"},
            action={"type": "changeTo", "dest": wide},
            transition={"type": "instant"},
        ),
    ]
    results = _run_script(
        call, directory, "variants", edit, "--in", staging, "--out", native
    )
    group = results[2]["id"]
    _require_native_members(native, budget["bytes"])
    fingerprint = file_fingerprint(native)
    inspect = [_step(_GET, id=node) for node in (compact, wide, group)]
    observed = _run_script(call, directory, "inspect", inspect, "--in", native)
    _require_variants(observed, (compact, wide, group))
    recipe = write_immutable_json(
        directory / "recipe.json",
        {"create": initial, "variants": edit, "inspect": inspect},
    )
    if file_fingerprint(native) != fingerprint:
        raise ArtCraftError("FigCraft inspection modified its retained document")
    return native, recipe, compact


def _step(command, **parameters):
    return {"command": command, "params": parameters}


def _layout(name, width, x, fill):
    return _step(
        _CREATE,
        type="component",
        name=f"Layout={name}",
        x=x,
        y=0,
        width=width,
        height=180,
        props={
            "fill": fill,
            "layout": "horizontal",
            "gap": 16,
            "padding": 16,
            "cornerRadius": 20,
        },
    )


def _action(parent):
    return _step(
        _CREATE,
        type="rectangle",
        parent=parent,
        width=92,
        height=52,
        name="Action",
        props={"fill": "#facc15", "cornerRadius": 12},
    )


def _run_script(call, directory, stem, steps, *options):
    script = write_immutable_json(directory / f"{stem}.json", steps)
    receipt = call(
        "run",
        script,
        "--no-system-fonts",
        "--automation-read-root",
        directory,
        "--automation-write-root",
        directory,
        *options,
    )
    rows = [json.loads(line) for line in receipt.splitlines()]
    if len(rows) != len(steps) or any(
        (row["step"], row["command"], row["ok"]) != (index, step["command"], True)
        for index, (row, step) in enumerate(zip(rows, steps, strict=True))
    ):
        raise ArtCraftError("FigCraft did not report every selected script step")
    return [row["result"] for row in rows]


def _require_native_members(path, byte_limit):
    try:
        with ZipFile(path) as document:
            if (
                sorted(document.namelist()) != ["document.json", "thumbnail.png"]
                or sum(item.file_size for item in document.infolist()) > byte_limit
            ):
                raise ArtCraftError(
                    "FigCraft native document has unverified dependencies"
                )
    except (OSError, BadZipFile) as error:
        raise ArtCraftError(
            "FigCraft did not produce a readable native document"
        ) from error


def _require_variants(observed, nodes):
    compact, wide, group = observed
    first, second, combined = nodes
    if (group["id"], group["type"], [child["id"] for child in group["children"]]) != (
        combined,
        "COMPONENT_SET",
        [first, second],
    ):
        raise ArtCraftError(
            "FigCraft reopened with different component variant membership"
        )
    _require_layout(compact, first, "Layout=Compact", 320)
    _require_layout(wide, second, "Layout=Wide", 640)
    interactions = compact["interactions"]
    if len(interactions) != 1 or (
        interactions[0]["trigger"],
        interactions[0]["actions"],
        interactions[0]["transition"],
    ) != (
        {"type": "onClick"},
        [{"dest": second, "type": "changeTo"}],
        {"type": "instant"},
    ):
        raise ArtCraftError("FigCraft reopened without the selected variant switch")


def _require_layout(node, identifier, name, width):
    if (node["id"], node["name"], node["type"], node["width"], node["height"]) != (
        identifier,
        name,
        "COMPONENT",
        width,
        180,
    ):
        raise ArtCraftError("FigCraft reopened with different editable layout geometry")
    layout = node["layout"]
    if (layout["mode"], layout["padding"], layout["gap"]) != (
        "horizontal",
        [16] * 4,
        16,
    ):
        raise ArtCraftError("FigCraft reopened with different auto layout settings")
    (child,) = node["children"]
    if (child["name"], child["type"], child["width"], child["height"]) != (
        "Action",
        "RECTANGLE",
        92,
        52,
    ):
        raise ArtCraftError(
            "FigCraft reopened without the selected editable action layer"
        )


def _export_card(call, native, node, output_path, output):
    call(
        "export",
        native,
        "--no-system-fonts",
        "--node",
        str(node),
        "--format",
        "png",
        "--out",
        output_path,
    )
    with Image.open(output_path, formats=["PNG"]) as image:
        if (
            (image.mode, image.size, image.info.get("srgb"))
            != ("RGBA", (output["width"], output["height"]), 0)
            or image.getpixel((0, 0)) != (0, 0, 0, 0)
            or image.getpixel((40, 40)) != (250, 204, 21, 255)
            or image.getpixel((200, 60)) != (22, 78, 99, 255)
        ):
            raise ArtCraftError(
                "FigCraft PNG differs from the selected static sRGB variant"
            )
        return sha256(image.tobytes()).hexdigest()
