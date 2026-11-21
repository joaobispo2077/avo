"""Discovery of explicitly selected, separately installed ArtCraft tooling."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

from avo.artcraft import (
    _ANIMATED_EMBLEM_SCOPE,
    _FILM_RETURN_SCOPE,
    _SOUND_CUE_SCOPE,
    _STILL_CARD_SCOPE,
    _VECTOR_EMBLEM_SCOPE,
    ArtCraftError,
)
from avo.timeline.contracts import content_hash, file_fingerprint

_VERSION = re.compile(
    r"(?:(?:ani|sound|vector|film)craft(?:-cli)?\s+)?v?(\d+\.\d+\.\d+(?:[-+][a-z0-9.-]+)?)(?: \((?:early alpha|windows x86_64)\))?",
    re.IGNORECASE,
)
_PRODUCTS = {
    "anicraft": "AniCraft",
    "soundcraft": "SoundCraft",
    "vectorcraft": "VectorCraft",
    "filmcraft": "FilmCraft",
}


def _not_ready(message, remediation):
    return ArtCraftError(message, code="ARTCRAFT_NOT_READY", remediation=remediation)


def _installation_help(app="anicraft"):
    product = _PRODUCTS[app]
    return f"Install the selected {product} app and matching CLI separately from https://getartcraft.com/apps/{app} or pass their installed absolute paths."


def _binary_name(name):
    return f"{name}.exe" if os.name == "nt" else name


def _path_candidates(name):
    for directory in _documented_installations(_binary_app(name)):
        yield directory / name
    for entry in os.environ.get("PATH", "").split(os.pathsep):
        directory = Path(entry.strip('"'))
        if directory.is_absolute():
            yield directory / name


def _binary_app(name):
    return name.casefold().removesuffix(".exe").removesuffix("-cli")


def _documented_installations(app):
    product = _PRODUCTS[app]
    if os.name == "nt":
        for variable, relative in (
            ("LOCALAPPDATA", f"Programs/ArtCraft/{product}"),
            ("ProgramFiles", f"ArtCraft/{product}"),
            ("ProgramFiles(x86)", f"ArtCraft/{product}"),
        ):
            base = Path(os.environ.get(variable) or ".")
            if base.is_absolute():
                yield base / relative
    elif sys.platform == "darwin":
        yield Path(f"/Applications/{product}.app/Contents/MacOS")


def _installed_binary(name, explicit=None, *, adjacent=None):
    app = _binary_app(name)
    name = _binary_name(name)
    if explicit is not None:
        provided = Path(explicit)
        if not provided.is_absolute() or provided.name.casefold() != name.casefold():
            raise _not_ready(
                f"Choose an absolute installed {name} path", _installation_help(app)
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
        _installation_help(app),
    )


def _release(executable):
    app = _binary_app(executable.name)
    try:
        process = subprocess.run(
            [str(executable), "--version"],
            cwd=executable.parent,
            stdin=subprocess.DEVNULL,
            env=_runtime_environment(app),
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
            _installation_help(app),
        ) from exc
    match = _VERSION.fullmatch(version)
    if match is None:
        raise _not_ready(
            f"The selected {executable.name} did not report a recognized release",
            _installation_help(app),
        )
    return match[1]


def _runtime_environment(app="anicraft"):
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.upper().startswith(app.upper() + "_")
    }
    if app == "vectorcraft":
        environment["VECTORCRAFT_NO_PREFS"] = "1"
    return environment


def _command_schema_hash(executable, *, emblem=False):
    from .artcraft_anicraft import (
        EMBLEM_COMMANDS,
        LOWER_THIRD_COMMANDS,
        observe_command_schema,
    )

    path = Path(executable["locator"])
    try:
        process = subprocess.run(
            [str(path), "commands"],
            cwd=path.parent,
            env=_runtime_environment(),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=7,
            check=True,
            shell=False,
        )
        if len(process.stdout) > 2 * 1024 * 1024:
            raise ValueError("registry response exceeded its budget")
        records = json.loads(process.stdout)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        raise _not_ready(
            "Could not inspect the selected AniCraft command registry",
            _installation_help(),
        ) from exc
    if not isinstance(records, list) or any(
        not isinstance(record, dict) for record in records
    ):
        raise _not_ready(
            "The selected AniCraft command registry format is unsupported",
            _installation_help(),
        )
    if file_fingerprint(path) != executable:
        raise _not_ready(
            "AniCraft CLI changed during command inspection", _installation_help()
        )
    required = EMBLEM_COMMANDS if emblem else LOWER_THIRD_COMMANDS
    return content_hash(observe_command_schema(records, required=required))


def _require_headless_transport(executable, mode):
    usage, label = {
        "host-mcp": (b"mcp", "headless stdio MCP"),
        "json-lines": (b"serve", "headless JSON-lines"),
    }[mode]
    path = Path(executable["locator"])
    try:
        process = subprocess.run(
            [str(path), "--help"],
            cwd=path.parent,
            env=_runtime_environment(),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=7,
            check=True,
            shell=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise _not_ready(
            f"Could not inspect the selected AniCraft {label} transport",
            _installation_help(),
        ) from exc
    if len(process.stdout) > 65536 or not any(
        line.strip().startswith(b"anicraft-cli " + usage + b" [file|--sample]")
        and b"stdin/stdout" in line
        for line in process.stdout.splitlines()
    ):
        raise _not_ready(
            f"Selected AniCraft CLI does not advertise the {label} profile",
            _installation_help(),
        )
    if file_fingerprint(path) != executable:
        raise _not_ready(
            "AniCraft CLI changed during transport inspection", _installation_help()
        )


def _installed_anicraft(cli_path, app_path):
    return _installed_tools("anicraft", cli_path, app_path)


def _installed_tools(product, cli_path, app_path):
    cli = _installed_binary(f"{product}-cli", cli_path)
    app = _installed_binary(product, app_path, adjacent=cli.parent)
    platform = {"win32": "windows", "darwin": "macos", "linux": "linux"}.get(
        sys.platform
    )
    if platform is None:
        raise _not_ready(
            "Selected ArtCraft profile is unavailable on this platform",
            _installation_help(product),
        )
    lock, app_lock = file_fingerprint(cli), file_fingerprint(app)
    release = _release(cli)
    if release != _application_release(product, app):
        raise _not_ready(
            "The selected ArtCraft app and CLI report different releases",
            _installation_help(product),
        )
    if file_fingerprint(cli) != lock or file_fingerprint(app) != app_lock:
        raise _not_ready(
            "The selected ArtCraft installation changed during inspection",
            _installation_help(product),
        )
    return {
        "executable": lock,
        "application": app_lock,
        "release": release,
        "platform": platform,
    }


def _application_release(product, app):
    if product == "filmcraft":
        from .artcraft_windows import windows_application_release

        return windows_application_release(app, _PRODUCTS[product])
    return _release(app)


class SelectedArtCraftAdapter:
    """Observe the selected installation and require independently verified confinement."""

    def __init__(self, observe_confinement=None, run_confined=None, open_confined=None):
        self._observe_confinement = observe_confinement
        self._run_confined = run_confined
        self._open_confined = open_confined
        self._registry_observation = None

    def _selected_registry(self, installed, scope, mode):
        key = content_hash({"installation": installed, "scope": scope, "mode": mode})
        previous = self._registry_observation
        if previous is not None and previous[0] == key:
            return previous[1]
        observe = _command_schema_hash
        if scope == _ANIMATED_EMBLEM_SCOPE:
            observed = observe(installed["executable"], emblem=True)
        else:
            observed = observe(installed["executable"])
        self._registry_observation = key, observed
        return observed

    def observe(self, *, scope, mode, roots, cli_path, app_path):
        if scope in (
            _SOUND_CUE_SCOPE,
            _STILL_CARD_SCOPE,
            _FILM_RETURN_SCOPE,
            _VECTOR_EMBLEM_SCOPE,
        ):
            return self._observe_specialist(scope, mode, roots, cli_path, app_path)
        if not _supports_anicraft(scope, mode):
            raise _not_ready(
                "The selected ArtCraft operation or mode has no qualified profile",
                "Use the catalog for documented operations and mode limits.",
            )
        installed = _installed_anicraft(cli_path, app_path)
        if mode in {"guided", "host-mcp"}:
            return self._operator_observation(installed, scope, mode)
        if mode == "json-lines":
            self._require_confined_stream(installed)
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
            "commandSchemaHash": self._selected_registry(installed, scope, mode),
            **installed,
        }

    def _operator_observation(self, installed, scope, mode):
        transport = {}
        if mode == "host-mcp":
            if installed["release"] != "0.2.1" or installed["platform"] != "windows":
                raise _not_ready(
                    "AniCraft host MCP requires the qualified Windows 0.2.1 profile",
                    _installation_help(),
                )
            _require_headless_transport(installed["executable"], mode)
            transport["hostTransport"] = "stdio"
        return {
            "app": scope["app"],
            "operations": scope["operations"],
            "mode": mode,
            "authority": "operator",
            "commandSchemaHash": self._selected_registry(installed, scope, mode),
            **installed,
            **transport,
        }

    def _require_confined_stream(self, installed):
        if not all(
            (self._observe_confinement, self._run_confined, self._open_confined)
        ):
            raise _not_ready(
                "AniCraft JSON-lines requires an independently confined stdio runner",
                "Select a runtime that enforces roots and time limits for this job.",
            )
        if installed["release"] != "0.2.1" or installed["platform"] != "windows":
            raise _not_ready(
                "AniCraft JSON-lines requires the qualified Windows 0.2.1 profile",
                _installation_help(),
            )
        _require_headless_transport(installed["executable"], "json-lines")

    def _observe_specialist(self, scope, mode, roots, cli_path, app_path):
        product = scope["app"]
        label, release, observer = _specialist_profile(scope)
        if mode != "cli" or not all((self._observe_confinement, self._run_confined)):
            raise _not_ready(
                f"{label} requires a confined CLI runner",
                "Select a runtime that independently enforces the job's effective roots.",
            )
        installed = _installed_tools(product, cli_path, app_path)
        if (installed["release"], installed["platform"]) != (release, "windows"):
            raise _not_ready(
                f"{label} requires the qualified Windows {release} profile",
                _installation_help(product),
            )
        effective = self._observe_confinement(installed, roots)
        return {
            **scope,
            **installed,
            "mode": mode,
            "effectiveRoots": effective,
            "commandSchemaHash": observer(
                installed["executable"], _runtime_environment(product)
            ),
        }

    def validate_run(self, job):
        if self._run_confined is None:
            raise _not_ready(
                "The selected AniCraft job requires a confined command runner",
                "Repeat with a runtime that independently enforces the job's effective roots.",
            )
        previous = job["observation"]
        current = self.observe(
            scope=job["decision"]["scope"],
            mode=previous["mode"],
            roots=job["roots"],
            cli_path=previous["executable"]["locator"],
            app_path=previous["application"]["locator"],
        )
        if previous["app"] != "anicraft":
            if current != previous:
                raise _not_ready(
                    "Selected ArtCraft profile requires its exact current tool files and scope",
                    _installation_help(previous["app"]),
                )
            return
        if (
            current != previous
            or current["release"] != "0.2.1"
            or current["platform"] != "windows"
        ):
            raise _not_ready(
                "AniCraft needs the exact qualified Windows 0.2.1 profile and current tool files",
                _installation_help(),
            )

    def author_lower_third(self, job, directory):
        from .artcraft_anicraft import revise_lower_third, run_lower_third

        def invoke(workdir, *arguments, timeout):
            return self._invoke_confined(job, workdir, arguments, timeout)

        def stream(document, *, timeout):
            return self._open_confined(
                job["observation"]["executable"],
                job["roots"],
                directory,
                ("serve", document),
                env=_runtime_environment(),
                timeout=timeout,
            )

        open_stream = stream if job["observation"]["mode"] == "json-lines" else None
        if job["documentState"] == "saved":
            return revise_lower_third(
                job["output"],
                None,
                job["authoringParameters"],
                source=Path(job["workspace"]) / job["document"],
                directory=directory,
                budget=job["budget"],
                invoke=invoke,
                open_stream=open_stream,
            )
        return run_lower_third(
            job["output"],
            job["authoringParameters"],
            directory=directory,
            budget=job["budget"],
            invoke=invoke,
            open_stream=open_stream,
        )

    def _invoke_confined(self, job, directory, arguments, timeout):
        installation = job["observation"]
        return self._run_confined(
            installation["executable"],
            job["roots"],
            directory,
            arguments,
            env=_runtime_environment(installation["app"]),
            timeout=timeout,
        )

    def author_isolated_cue(self, job, directory):
        from .artcraft_soundcraft import run_isolated_cue

        def invoke(workdir, *arguments, timeout):
            return self._invoke_confined(job, workdir, arguments, timeout)

        return run_isolated_cue(
            job["output"],
            job["inputs"][0],
            directory=directory,
            budget=job["budget"],
            invoke=invoke,
        )

    def author_film_interchange(self, job, directory):
        from .artcraft_filmcraft import author_interchange

        def invoke(workdir, *arguments, timeout):
            return self._invoke_confined(job, workdir, arguments, timeout)

        return author_interchange(job, directory=directory, invoke=invoke)

    def author_vector_card(self, job, directory):
        from .artcraft_vectorcraft import author_vector_card

        def invoke(workdir, *arguments, timeout):
            return self._invoke_confined(job, workdir, arguments, timeout)

        return author_vector_card(
            job["output"],
            job["authoringParameters"],
            directory=directory,
            budget=job["budget"],
            invoke=invoke,
        )

    def author_vector_emblem(self, job, directory):
        from .artcraft_vectorcraft import author_vector_emblem

        def invoke(workdir, *arguments, timeout):
            return self._invoke_confined(job, workdir, arguments, timeout)

        return author_vector_emblem(
            job["output"], directory=directory, budget=job["budget"], invoke=invoke
        )

    def author_animated_emblem(self, job, directory):
        from .artcraft_anicraft import run_animated_emblem

        def invoke(workdir, *arguments, timeout):
            return self._invoke_confined(job, workdir, arguments, timeout)

        return run_animated_emblem(
            job["output"],
            job["inputs"][0],
            directory=directory,
            budget=job["budget"],
            invoke=invoke,
        )

    def plan_lower_third(self, job, directory):
        from .artcraft_anicraft import lower_third_steps

        previous = job["observation"]
        _require_guided_installation(previous)
        document = directory / "component.anicraft"
        empty = directory / "empty.anicraft"
        recipe = directory / "recipe.json"
        output = job["output"]
        steps = lower_third_steps(
            output, job["authoringParameters"], document, directory / "white"
        )
        cli = previous["executable"]["locator"]
        rate = output["frameRate"]
        fps = rate["numerator"] // rate["denominator"]
        initialize = [
            cli,
            "new",
            "--out",
            str(empty),
            "--width",
            str(output["width"]),
            "--height",
            str(output["height"]),
            "--fps",
            str(fps),
        ]
        if previous["mode"] == "host-mcp":
            return {
                "steps": [
                    {"command": step["cmd"], "params": step["params"]} for step in steps
                ],
                "commands": [initialize],
                "host": {
                    "transport": previous["hostTransport"],
                    "argv": [cli, "mcp", str(empty)],
                    "cwd": str(directory),
                    "unsetEnvironmentPrefixes": ["ANICRAFT_"],
                    "enforceOperatorRoots": True,
                    "scriptTool": "anicraft_run_script",
                    "allowedCommandIds": list(
                        dict.fromkeys(step["cmd"] for step in steps)
                    ),
                },
            }
        return {
            "steps": steps,
            "commands": [
                initialize,
                [cli, "run", str(empty), str(recipe)],
                [cli, "info", str(document)],
            ],
        }

    @staticmethod
    def inspect_returned_source(job, native):
        from .artcraft_anicraft import inspect_lower_third_source

        if job["decision"]["scope"] != {
            "app": "anicraft",
            "operations": ["lower-third"],
        }:
            raise _not_ready(
                "The returned document has no checked ArtCraft source profile",
                "Inspect the selected task against its app-specific native contract.",
            )
        return inspect_lower_third_source(
            native,
            job["output"],
            job["authoringParameters"],
            max_bytes=job["budget"]["bytes"],
        )


def _supports_anicraft(scope, mode):
    if scope == _ANIMATED_EMBLEM_SCOPE:
        return mode == "cli"
    return scope == {"app": "anicraft", "operations": ["lower-third"]} and mode in {
        "cli",
        "guided",
        "host-mcp",
        "json-lines",
    }


def _specialist_profile(scope):
    product = scope["app"]
    if product == "filmcraft":
        from .artcraft_filmcraft import observe_filmcraft

        return "FilmCraft exchange", "0.20.1", observe_filmcraft
    if product == "soundcraft":
        from .artcraft_soundcraft import observe_soundcraft_profile

        return "SoundCraft cue", "0.20.1", observe_soundcraft_profile
    if scope == _VECTOR_EMBLEM_SCOPE:
        from .artcraft_vectorcraft import observe_vector_emblem

        return "VectorCraft emblem", "0.24.1", observe_vector_emblem
    from .artcraft_vectorcraft import observe_vectorcraft

    return "VectorCraft card", "0.24.1", observe_vectorcraft


def _require_guided_installation(previous):
    if previous["release"] != "0.2.1" or previous["platform"] != "windows":
        raise _not_ready(
            "AniCraft needs the qualified Windows 0.2.1 profile", _installation_help()
        )
    if "commandSchemaHash" not in previous:
        raise _not_ready(
            "The guided job predates selected command verification",
            "Prepare a new guided job from the installed AniCraft profile.",
        )
    for kind in ("executable", "application"):
        observed = previous[kind]
        if file_fingerprint(Path(observed["locator"])) != observed:
            raise _not_ready(
                "AniCraft installation changed after the guided job was prepared",
                _installation_help(),
            )
