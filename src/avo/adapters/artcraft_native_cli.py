"""Bound each selected native recipe by its owned output and execution budget."""

import json
import subprocess
from contextlib import closing
from os import scandir
from pathlib import Path
from stat import S_ISREG
from time import monotonic

from avo.artcraft import ArtCraftError
from avo.timeline.contracts import content_hash, file_fingerprint


def bounded_native_invocation(
    directory, budget, invoke, *, label, owned_directories=()
):
    deadline = monotonic() + budget["seconds"]

    def remaining_time():
        remaining = deadline - monotonic()
        if remaining <= 0:
            raise ArtCraftError(f"{label} exhausted its time budget")
        return remaining

    def call(*arguments):
        result = invoke(directory, *arguments, timeout=remaining_time())
        remaining_time()
        if len(result) <= 1024 * 1024:
            with closing(_owned_files(directory, owned_directories, label)) as files:
                if _owned_outputs_fit(files, budget, label, remaining_time):
                    remaining_time()
                    return result
        raise ArtCraftError(f"{label} exceeded its receipt, file or byte budget")

    return call


def _owned_files(directory, allowed, label):
    with scandir(directory) as entries:
        for entry in entries:
            item = Path(entry.path)
            if entry.name not in allowed:
                yield item
                continue
            if item.resolve() != item or not item.is_dir():
                raise ArtCraftError(f"{label} created an invalid owned directory")
            with scandir(item) as children:
                yield from (Path(child.path) for child in children)


def _owned_outputs_fit(files, budget, label, check_time):
    remaining_bytes = budget["bytes"]
    for count, item in enumerate(files, 1):
        check_time()
        if count > budget["files"]:
            return False
        metadata = item.lstat()
        if (
            item.resolve() != item
            or not S_ISREG(metadata.st_mode)
            or metadata.st_nlink != 1
        ):
            raise ArtCraftError(f"{label} created a linked or external file")
        remaining_bytes -= metadata.st_size
        if remaining_bytes < 0:
            return False
    return True


def observe_native_command_schema(
    executable, environment, *, needed, label, json_registry=True
):
    path = Path(executable["locator"])
    arguments = ["commands", "--json"] if json_registry else ["commands"]
    try:
        result = subprocess.run(
            [str(path), *arguments],
            cwd=path.parent,
            env=environment,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            check=True,
            timeout=7,
        )
        if len(result.stdout) > 4 * 1024 * 1024:
            raise ValueError("command registry exceeds its byte limit")
        commands = _selected_registry_rows(result.stdout, needed, json_registry)
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


def _selected_registry_rows(stdout, needed, json_registry):
    if json_registry:
        return {
            item["id"]: item["params"]
            for item in json.loads(stdout)
            if item["id"] in needed
        }
    rows = (line.partition(" — ") for line in stdout.decode("utf-8").splitlines())
    return {
        command: spec
        for command, delimiter, spec in rows
        if delimiter and command in needed
    }
