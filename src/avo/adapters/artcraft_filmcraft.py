"""Run the selected FilmCraft native timeline exchange recipe."""

import json
import subprocess
import sys
from pathlib import Path
from time import monotonic

from avo.artcraft import ArtCraftError
from avo.timeline.contracts import content_hash, file_fingerprint
from avo.timeline.store import write_immutable_json

_COMMANDS = {
    "file.newProject",
    "file.import",
    "file.saveAs",
    "file.newSequence",
    "file.exportInterchange",
}


def filmcraft_application_release(path):
    """Read the Windows version resource without starting the desktop application."""
    if sys.platform != "win32":
        raise ArtCraftError(
            "FilmCraft release inspection requires Windows", code="ARTCRAFT_NOT_READY"
        )
    import ctypes
    from ctypes import wintypes

    version = ctypes.WinDLL("version", winmode=0x800)
    size_of = version.GetFileVersionInfoSizeW
    size_of.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(wintypes.DWORD)]
    size_of.restype = wintypes.DWORD
    read = version.GetFileVersionInfoW
    read.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID]
    read.restype = wintypes.BOOL
    query = version.VerQueryValueW
    query.argtypes = [
        wintypes.LPCVOID,
        wintypes.LPCWSTR,
        ctypes.POINTER(wintypes.LPVOID),
        ctypes.POINTER(wintypes.UINT),
    ]
    query.restype = wintypes.BOOL
    size = size_of(str(path), None)
    if not 0 < size <= 1024 * 1024:
        raise ArtCraftError(
            "FilmCraft has no bounded Windows version record", code="ARTCRAFT_NOT_READY"
        )
    buffer = ctypes.create_string_buffer(size)
    pointer = wintypes.LPVOID()
    length = wintypes.UINT()
    if not read(str(path), 0, size, buffer) or not query(
        buffer, "\\", ctypes.byref(pointer), ctypes.byref(length)
    ):
        raise ArtCraftError(
            "FilmCraft Windows version record could not be read",
            code="ARTCRAFT_NOT_READY",
        )
    if length.value < 6 * ctypes.sizeof(wintypes.DWORD):
        raise ArtCraftError(
            "FilmCraft Windows version record is incomplete", code="ARTCRAFT_NOT_READY"
        )
    words = ctypes.cast(pointer, ctypes.POINTER(wintypes.DWORD))
    if words[0] != 0xFEEF04BD:
        raise ArtCraftError(
            "FilmCraft Windows version record is invalid", code="ARTCRAFT_NOT_READY"
        )
    major, minor = divmod(words[4], 65536)
    release, build = divmod(words[5], 65536)
    fields = (major, minor, release, build) if build else (major, minor, release)
    return ".".join(map(str, fields))


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
    commands = {
        row["id"]: row["params"]
        for row in json.loads(result.stdout)
        if row["id"] in _COMMANDS
    }
    if commands.keys() != _COMMANDS or file_fingerprint(path) != executable:
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
    call = _job_runner(directory, budget, invoke)
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


def _job_runner(directory, budget, invoke):
    deadline = monotonic() + budget["seconds"]

    def call(*arguments):
        remaining = deadline - monotonic()
        if remaining <= 0:
            raise ArtCraftError("FilmCraft exchange exceeded its time budget")
        response = invoke(directory, *arguments, timeout=remaining)
        files = list(directory.iterdir())
        if any(
            path.resolve() != path or not path.is_file() or path.stat().st_nlink != 1
            for path in files
        ):
            raise ArtCraftError("FilmCraft created an unowned or nonregular artifact")
        if (
            len(files) > budget["files"]
            or sum(path.stat().st_size for path in files) > budget["bytes"]
        ):
            raise ArtCraftError("FilmCraft exchange exceeded its file or byte budget")
        if len(response) > 1024 * 1024:
            raise ArtCraftError("FilmCraft exchange receipts exceed their byte limit")
        return response

    return call


def _batch(call, script, steps, *options):
    script.write_text(
        "".join(json.dumps(step, ensure_ascii=False) + "\n" for step in steps),
        encoding="utf-8",
    )
    rows = [json.loads(line) for line in call(*options, "run", script).splitlines()]
    if len(rows) != len(steps) or any(
        (row.get("id"), row.get("line")) != (step["id"], index)
        or row.get("ok") is not True
        for index, (row, step) in enumerate(zip(rows, steps, strict=True), start=1)
    ):
        raise ArtCraftError("FilmCraft returned incomplete or failed command receipts")
    return [row["result"] for row in rows]


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
