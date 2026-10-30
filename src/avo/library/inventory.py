"""Incremental metadata inventory, with no source hashing or inference."""

from __future__ import annotations

import os
import subprocess
from copy import deepcopy
from uuid import uuid4

from avo.library.rules import finite_seconds, is_link, observation, safe_path

MEDIA = {
    ".mp4",
    ".mov",
    ".mkv",
    ".avi",
    ".webm",
    ".m4v",
    ".mts",
    ".mxf",
    ".wav",
    ".mp3",
    ".m4a",
    ".flac",
}
EXCLUDED = {
    "edit",
    "cache",
    "proxies",
    "proxy",
    "masters",
    "preview",
    "reviews",
    ".git",
}


def discover(root, recursive):
    pending = [root]
    while pending:
        directory = pending.pop()
        with os.scandir(directory) as entries:
            for entry in sorted(entries, key=lambda item: item.name.casefold()):
                if entry.name.startswith(".") or entry.name.casefold() in EXCLUDED:
                    continue
                path = directory / entry.name
                if is_link(path):
                    continue
                if entry.is_dir(follow_symlinks=False) and recursive:
                    pending.append(path)
                elif (
                    entry.is_file(follow_symlinks=False)
                    and path.suffix.lower() in MEDIA
                ):
                    yield path


def summarize(records, *, reused=0):
    available = [item for item in records if item["availability"] != "missing"]
    durations = [item["metadata"].get("durationSeconds") for item in available]
    return {
        "total": len(records),
        "bytes": sum(item["observation"]["sizeBytes"] for item in available),
        "knownDurationSeconds": sum(value for value in durations if value is not None),
        "unknownDuration": sum(value is None for value in durations),
        "reused": reused,
        "failed": sum(bool(item["metadata"].get("error")) for item in available),
    }


def _probe_metadata(path, probe):
    metadata = {"durationSeconds": None, "audio": None}
    try:
        if probe:
            metadata.update(probe(path))
        if not finite_seconds(metadata.get("durationSeconds")):
            metadata["durationSeconds"] = None
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        metadata["error"] = str(exc)
    return metadata


def _changed_recording(path, relative, current, prior, probe):
    metadata = _probe_metadata(path, probe)
    return {
        "id": prior["id"] if prior else uuid4().hex,
        "version": uuid4().hex,
        "path": relative,
        "originalPath": prior["originalPath"] if prior else relative,
        "observation": current,
        "metadata": metadata,
        "availability": "available",
        "transcript": None,
        "restrictions": prior["restrictions"] if prior else [],
    }


def _missing_recordings(old, seen, recursive):
    return [
        {**deepcopy(item), "availability": "missing"}
        for relative, item in old.items()
        if relative not in seen and (recursive or "/" not in relative)
    ]


def scan_inventory(root, previous, *, recursive=False, probe=None, activity=None):
    old = {item["path"]: item for item in (previous or {}).get("recordings", [])}
    records = []
    seen = set()
    reused = 0
    for path in discover(root, recursive):
        relative = path.relative_to(root).as_posix()
        safe_path(root, relative)
        seen.add(relative)
        if activity:
            activity(len(records), None, relative)
        current = observation(path)
        prior = old.get(relative)
        if (
            prior
            and prior["observation"] == current
            and prior["availability"] == "available"
        ):
            records.append(deepcopy(prior))
            reused += 1
            continue
        records.append(_changed_recording(path, relative, current, prior, probe))
        if activity:
            activity(len(records), None, relative)
    records.extend(_missing_recordings(old, seen, recursive))
    return {
        "recordings": records,
        "scope": {"recursive": recursive, "exclusions": sorted(EXCLUDED)},
        "summary": summarize(records, reused=reused),
    }
