"""Bound each selected native recipe by its owned output and execution budget."""

import json
import subprocess
from pathlib import Path
from time import monotonic

from avo.artcraft import ArtCraftError
from avo.timeline.contracts import content_hash, file_fingerprint


def bounded_native_invocation(directory, budget, invoke, *, label):
    deadline = monotonic() + budget["seconds"]

    def call(*arguments):
        remaining = deadline - monotonic()
        if remaining <= 0:
            raise ArtCraftError(f"{label} exhausted its time budget")
        result = invoke(directory, *arguments, timeout=remaining)
        files = tuple(directory.iterdir())
        _require_owned_outputs(files, label)
        if (
            len(result) > 1024 * 1024
            or len(files) > budget["files"]
            or sum(item.stat().st_size for item in files) > budget["bytes"]
        ):
            raise ArtCraftError(f"{label} exceeded its receipt, file or byte budget")
        return result

    return call


def _require_owned_outputs(files, label):
    if any(
        item.resolve() != item or not item.is_file() or item.stat().st_nlink != 1
        for item in files
    ):
        raise ArtCraftError(f"{label} created a linked or external file")


def observe_native_command_schema(executable, environment, *, needed, label):
    path = Path(executable["locator"])
    try:
        result = subprocess.run(
            [str(path), "commands", "--json"],
            cwd=path.parent,
            env=environment,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            check=True,
            timeout=7,
        )
        if len(result.stdout) > 4 * 1024 * 1024:
            raise ValueError("command registry exceeds its byte limit")
        commands = {
            item["id"]: item["params"]
            for item in json.loads(result.stdout)
            if item["id"] in needed
        }
    except (
        OSError,
        subprocess.SubprocessError,
        ValueError,
        KeyError,
        TypeError,
    ) as exc:
        raise ArtCraftError(
            f"Could not inspect the selected {label} commands",
            code="ARTCRAFT_NOT_READY",
        ) from exc
    if commands.keys() != needed or file_fingerprint(path) != executable:
        raise ArtCraftError(
            f"The selected {label} command scope or executable changed",
            code="ARTCRAFT_NOT_READY",
        )
    return content_hash(commands)
