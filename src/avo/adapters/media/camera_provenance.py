"""Observed native camera tools and recipes; no media or model discovery."""

from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
from copy import deepcopy
from pathlib import Path

from avo.capabilities import _implementation_digest
from avo.timeline.contracts import content_hash, file_fingerprint, fingerprint_stage


def _shim_target(executable):
    """Resolve only the installed Chocolatey launcher, using its read-only help."""
    if executable.suffix.lower() != ".exe":
        return None
    with executable.open("rb") as stream:
        header = stream.read(2 * 1024 * 1024)
    marker = "shimgen-help"
    if not any(marker.encode(encoding) in header for encoding in ("ascii", "utf-16le")):
        return None
    result = subprocess.run(
        [str(executable), "--shimgen-help"],
        check=False,  # ShimGen help normally exits with a nonzero status.
        capture_output=True,
        text=True,
        timeout=10,
    )
    help_text = result.stdout + result.stderr
    targets = re.findall(r"^\s*Target:\s*'([^'\r\n]+)'\s*$", help_text, re.MULTILINE)
    if (
        len(help_text) > 65536
        or "ShimGenerator (shimgen)" not in help_text
        or len(targets) != 1
        or not Path(targets[0]).is_absolute()
    ):
        raise RuntimeError("Selected camera runtime has an unverifiable shim target")
    return Path(targets[0]).resolve()


def _runtime_binary(executable):
    launchers, seen = [], set()
    for _ in range(8):
        if executable in seen:
            raise RuntimeError("Selected camera runtime has a cyclic shim target")
        seen.add(executable)
        fingerprint = file_fingerprint(executable)
        observed = {key: fingerprint[key] for key in ("sha256", "sizeBytes")}
        target = _shim_target(executable)
        if target is None:
            return {**observed, **({"launcherChain": launchers} if launchers else {})}
        launchers.append({"kind": "chocolatey-shimgen", **observed})
        executable = target
    raise RuntimeError("Selected camera runtime exceeds the shim target depth limit")


def _runtime_tool(name):
    executable = shutil.which(name)
    if executable is None:
        raise RuntimeError(f"Selected camera runtime is unavailable: {name}")
    # Always observe installed bytes anew, even inside a media-fingerprint batch.
    with fingerprint_stage(verify_on_exit=True):
        observed = _runtime_binary(Path(executable).resolve())
        version = subprocess.run(
            [executable, "-version"],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout
    if not version.strip() or len(version) > 65536:
        raise RuntimeError(f"Selected camera runtime has invalid version data: {name}")
    release = re.match(rf"^{name} version n?(\d+)\.(\d+)(?:[.\s-]|$)", version)
    if release is None or release.groups() not in {("6", "1"), ("7", "1")}:
        raise RuntimeError(
            f"Selected camera runtime is not qualified: {name}; tested releases are 6.1 and 7.1"
        )
    return {
        **observed,
        "version": version.splitlines()[0][:512],
        "versionSha256": hashlib.sha256(version.encode("utf-8")).hexdigest(),
    }


def camera_runtime_identity():
    """Inspect selected installed tools without inventing a timed camera graph."""
    observed = {
        "implementationSha256": _implementation_digest(
            "camera-transform-v1", "ffmpeg.camera-transform"
        ),
        "runtime": {name: _runtime_tool(name) for name in ("ffmpeg", "ffprobe")},
    }
    return {**observed, "environmentHash": content_hash(observed)}


def camera_render_provenance(execution):
    """Bind complete graph/options/source/profile identities to actual tools.

    Tool locators are deliberately excluded: executables remain separately
    installed prerequisites, not media to bundle into a reconstruction pack.
    """
    if not any(
        operation.get("kind") == "camera-transform"
        for operation in execution.get("videoGraph", {}).get("operations", [])
    ):
        return None
    recipe = {
        key: execution[key]
        for key in (
            "videoGraph",
            "audioGraph",
            "events",
            "implementationRefs",
            "canonicalInputLock",
            "output",
        )
    }
    observed = {
        "contractVersion": "1.0.0",
        "recipeHash": content_hash(recipe),
        "window": deepcopy(execution.get("window")),
        **camera_runtime_identity(),
    }
    return {**observed, "provenanceHash": content_hash(observed)}
