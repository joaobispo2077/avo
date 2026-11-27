"""Run the selected FilmCraft native timeline exchange recipe."""

import json
import subprocess
from pathlib import Path

from avo.artcraft import ArtCraftError
from avo.timeline.contracts import content_hash, file_fingerprint
from avo.timeline.store import write_immutable_json

from .artcraft_native_cli import (
    bounded_native_invocation,
    selected_native_command_signatures,
)

_REQUIRED_RESULT_FIELDS = {
    "file.newProject": {"name": str},
    "file.import": {"errors": list, "items": list},
    "file.saveAs": {"bytes": int, "path": str},
    "file.newSequence": {"sequence": int},
    "file.exportInterchange": {"bytes": int, "path": str, "report": list},
}


def observe_filmcraft(executable, environment):
    path = Path(executable["locator"])
    try:
        result = subprocess.run(
            [str(path), "commands", "--json"],
            cwd=path.parent,
            env=environment,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=7,
            check=True,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ArtCraftError(
            "Could not inspect FilmCraft commands", code="ARTCRAFT_NOT_READY"
        ) from exc
    if len(result.stdout) > 4 * 1024 * 1024:
        raise ArtCraftError("FilmCraft command registry exceeds its byte limit")
    required = _REQUIRED_RESULT_FIELDS.keys()
    commands = selected_native_command_signatures(
        result.stdout, required, label="FilmCraft"
    )
    if commands.keys() != required or file_fingerprint(path) != executable:
        raise ArtCraftError(
            "FilmCraft exchange command scope or executable changed",
            code="ARTCRAFT_NOT_READY",
        )
    return content_hash(commands)


def author_interchange(job, *, directory, invoke):
    if directory.resolve() != directory or directory.exists():
        raise ArtCraftError("FilmCraft requires a fresh owned job directory")
    budget = job["budget"]
    if budget["files"] < 6:
        raise ArtCraftError("FilmCraft exchange requires six job files")
    directory.mkdir(parents=True)
    call = bounded_native_invocation(
        directory, budget, invoke, label="FilmCraft exchange"
    )
    source = job["inputs"][0]
    original = Path(source["locator"])
    stage = directory / "imported.fcproj"
    native = directory / "component.fcproj"
    exchange = directory / "component.otio"
    first = [
        _step("file.newProject", name="AVO source timeline"),
        _step("file.import", paths=[str(original)]),
        _step("file.saveAs", path=str(stage)),
    ]
    receipts = _batch(call, directory / "import.jsonl", first)
    imported = receipts[1]
    _require_saved(receipts[-1], stage)
    if imported["errors"] or len(imported["items"]) != 1:
        raise ArtCraftError("FilmCraft did not import exactly the selected original")
    selection = job["interchangeSource"]
    rate = job["output"]["frameRate"]
    second = [
        _step(
            "file.newSequence",
            name="AVO source timeline",
            width=selection["width"],
            height=selection["height"],
            fps=rate["numerator"] / rate["denominator"],
            sampleRate=48000,
            fromItems=imported["items"],
            video=1,
            audio=1,
        ),
        _step("file.saveAs", path=str(native)),
        _step("file.exportInterchange", format="otio", path=str(exchange)),
    ]
    recipe = write_immutable_json(directory / "recipe.json", [first, second])
    receipts = _batch(call, directory / "exchange.jsonl", second, "--project", stage)
    _require_saved(receipts[-2], native)
    _require_saved(receipts[-1], exchange)
    _require_sequence(
        json.loads(call("--project", native, "inspect", "sequence")),
        job,
        imported["items"][0],
    )
    if file_fingerprint(original) != source:
        raise ArtCraftError("FilmCraft changed the selected original")
    losses = [
        value
        if isinstance(value, str)
        else json.dumps(value, sort_keys=True, ensure_ascii=False)
        for value in receipts[-1]["report"]
    ]
    return {
        "nativeSource": file_fingerprint(native),
        "recipe": file_fingerprint(recipe),
        "media": file_fingerprint(exchange),
        "interchangeEvidence": {"losses": losses},
    }


def _step(identifier, **options):
    return {"id": identifier, "params": options}


def _batch(call, script, steps, *options):
    script.write_text(
        "".join(json.dumps(step, ensure_ascii=False) + "\n" for step in steps),
        encoding="utf-8",
    )
    response = call(*options, "run", script)
    try:
        rows = [
            json.loads(line.decode("utf-8"), object_pairs_hook=_distinct_receipt_fields)
            for line in response.splitlines()
        ]
    except (ValueError, RecursionError) as exc:
        raise ArtCraftError("FilmCraft returned malformed command receipts") from exc
    if len(rows) != len(steps) or any(
        not _valid_batch_receipt(row, step, index)
        for index, (row, step) in enumerate(zip(rows, steps, strict=True), start=1)
    ):
        raise ArtCraftError("FilmCraft returned incomplete or failed command receipts")
    return [row["result"] for row in rows]


def _distinct_receipt_fields(pairs):
    fields = dict(pairs)
    if len(fields) != len(pairs):
        raise ValueError("duplicate FilmCraft receipt field")
    return fields


def _valid_batch_receipt(row, step, index):
    if (
        not isinstance(row, dict)
        or row.get("id") != step["id"]
        or type(row.get("line")) is not int
        or row["line"] != index
        or row.get("ok") is not True
        or "error" in row
        or not isinstance(row.get("result"), dict)
    ):
        return False
    return _valid_batch_result(row["result"], step)


def _valid_batch_result(result, step):
    command = step["id"]
    fields = _REQUIRED_RESULT_FIELDS.get(command)
    if (
        fields is None
        or "error" in result
        or any(
            type(result.get(field)) is not expected
            for field, expected in fields.items()
        )
    ):
        return False
    if command == "file.newProject":
        return result["name"] == step["params"]["name"]
    if command == "file.import":
        return all(item is not None for item in result["items"])
    if command in {"file.saveAs", "file.exportInterchange"}:
        return bool(result["path"]) and result["bytes"] >= 0
    return True


def _require_saved(receipt, target):
    if (
        Path(receipt["path"]) != target
        or not target.is_file()
        or receipt["bytes"] != target.stat().st_size
    ):
        raise ArtCraftError("FilmCraft did not write its exact owned artifact")


def _require_sequence(sequence, job, source_id):
    settings = sequence["settings"]
    source, output = job["interchangeSource"], job["output"]
    expected = (
        source["width"],
        source["height"],
        48000,
        output["frameCount"],
        {
            "num": output["frameRate"]["numerator"],
            "den": output["frameRate"]["denominator"],
        },
    )
    if (
        settings["width"],
        settings["height"],
        settings["sample_rate"],
        sequence["durationFrames"],
        settings["frame_rate"],
    ) != expected:
        raise ArtCraftError(
            "FilmCraft reopened timeline differs from the selected canvas or clock"
        )
    for name in ("video", "audio"):
        (track,) = sequence[name]
        (clip,) = track["items"]
        if (clip["item"], clip["startFrame"], clip["endFrame"]) != (
            source_id,
            0,
            output["frameCount"],
        ):
            raise ArtCraftError(
                "FilmCraft reopened timeline differs from the selected original placement"
            )
