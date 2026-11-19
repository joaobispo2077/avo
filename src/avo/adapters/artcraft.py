"""Discovery of explicitly selected, separately installed ArtCraft tooling."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

from avo.artcraft import ArtCraftError
from avo.timeline.contracts import file_fingerprint

_ANICRAFT_INSTALL = "https://getartcraft.com/apps/anicraft"
_VERSION = re.compile(
    r"(?:anicraft(?:-cli)?\s+)?v?(\d+\.\d+\.\d+(?:[-+][a-z0-9.-]+)?)", re.IGNORECASE
)


def _not_ready(message, remediation):
    return ArtCraftError(message, code="ARTCRAFT_NOT_READY", remediation=remediation)


def _installation_help():
    return f"Install the selected AniCraft app and matching CLI separately from {_ANICRAFT_INSTALL} or pass their installed absolute paths."


def _binary_name(name):
    return f"{name}.exe" if os.name == "nt" else name


def _path_candidates(name):
    for entry in os.environ.get("PATH", "").split(os.pathsep):
        directory = Path(entry.strip('"'))
        if directory.is_absolute():
            yield directory / name


def _installed_binary(name, explicit=None, *, adjacent=None):
    name = _binary_name(name)
    if explicit is not None:
        provided = Path(explicit)
        if not provided.is_absolute() or provided.name.casefold() != name.casefold():
            raise _not_ready(
                f"Choose an absolute installed {name} path", _installation_help()
            )
        candidates = (provided,)
    else:
        candidates = _path_candidates(name)
        if adjacent is not None:
            candidates = iter((adjacent / name, *candidates))
    for candidate in candidates:
        if candidate.is_file() and os.access(candidate, os.X_OK):
            resolved = candidate.resolve(strict=True)
            if resolved.name.casefold() == name.casefold():
                return resolved
    raise _not_ready(
        f"The selected {name} is unavailable at the requested installation",
        _installation_help(),
    )


def _release(executable):
    try:
        process = subprocess.run(
            [str(executable), "--version"],
            cwd=executable.parent,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=5,
            check=True,
            shell=False,
        )
        version = process.stdout.decode("ascii").strip()
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        raise _not_ready(
            f"Could not verify the installed release of {executable.name}",
            _installation_help(),
        ) from exc
    match = _VERSION.fullmatch(version)
    if match is None:
        raise _not_ready(
            f"The selected {executable.name} did not report a recognized release",
            _installation_help(),
        )
    return match[1]


def _installed_anicraft(cli_path, app_path):
    cli = _installed_binary("anicraft-cli", cli_path)
    app = _installed_binary("anicraft", app_path, adjacent=cli.parent)
    platform = {"win32": "windows", "darwin": "macos", "linux": "linux"}.get(
        sys.platform
    )
    if platform is None:
        raise _not_ready(
            "AniCraft profile is unavailable on this platform", _installation_help()
        )
    lock, app_lock = file_fingerprint(cli), file_fingerprint(app)
    release = _release(cli)
    if release != _release(app):
        raise _not_ready(
            "The selected AniCraft app and CLI report different releases",
            _installation_help(),
        )
    if file_fingerprint(cli) != lock or file_fingerprint(app) != app_lock:
        raise _not_ready(
            "The selected AniCraft installation changed during inspection",
            _installation_help(),
        )
    return {
        "executable": lock,
        "application": app_lock,
        "release": release,
        "platform": platform,
    }


class SelectedArtCraftAdapter:
    """Observe the selected installation and require independently verified confinement."""

    def __init__(self, observe_confinement=None):
        self._observe_confinement = observe_confinement

    def observe(self, *, scope, mode, roots, cli_path, app_path):
        if (
            scope["app"] != "anicraft"
            or scope["operations"] != ["lower-third"]
            or mode != "cli"
        ):
            raise _not_ready(
                "The selected ArtCraft operation or mode has no qualified profile",
                "Use the catalog for documented operations and mode limits.",
            )
        installed = _installed_anicraft(cli_path, app_path)
        if self._observe_confinement is None:
            raise _not_ready(
                "AniCraft CLI file confinement is unverified in this environment",
                "Use an independently confined authoring runtime for the selected read and write roots.",
            )
        effective = self._observe_confinement(installed, roots)
        return {
            "app": scope["app"],
            "operations": scope["operations"],
            "mode": mode,
            "effectiveRoots": effective,
            **installed,
        }
