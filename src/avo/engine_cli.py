"""Unified engine dispatcher (spec FR-3). Lazy-imports wrapped modules."""

from __future__ import annotations

import importlib
import inspect
import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

PUBLIC_VERBS = ("transcribe", "render", "shorts", "cli", "mcp")

# One table: verb → existing ``python -m`` module. Clone entrypoints stay intact.
_MODULES: dict[str, str] = {
    "transcribe": "avo.transcribe",
    "render": "avo.render",
    "shorts": "avo.shorts",
    "cli": "avo.cli",
    "mcp": "avo.mcp.__main__",
    "init_project": "avo.init_project",
    "session": "avo.session",
    "wrap": "avo.wrap",
    "stats": "avo.stats",
    "videos": "avo.videos",
    "grade": "avo.grade",
    "prepare_transcription": "avo.prepare_transcription",
    "models_cli": "avo.models_cli",
    "validate_dependencies": "avo.validate_dependencies",
    "update": "avo.update",
}


def main(argv: list[str] | None = None) -> int | None:
    args = sys.argv[1:] if argv is None else argv
    if not args or args[0] in ("-h", "--help"):
        _print_help()
        return 0
    verb, *rest = args
    if verb == "version":
        print(_semver())
        return 0
    if verb == "runtime":
        return _runtime(rest)
    if verb not in _MODULES:
        _print_unknown()
        return 2
    return _invoke(verb, rest)


def _semver() -> str:
    try:
        return version("avo")
    except PackageNotFoundError:
        return "0.0.0+local"


def _verb_list() -> str:
    return ", ".join((*PUBLIC_VERBS, "version"))


def _print_help() -> None:
    print("usage: avo <verb> ...")
    print(f"commands: {_verb_list()}, runtime")


def _print_unknown() -> None:
    print(f"unknown command. choose one of: {_verb_list()}", file=sys.stderr)


def _is_help(rest: list[str]) -> bool:
    return bool(rest) and rest[0] in ("-h", "--help")


def _runtime(rest: list[str]) -> int:
    from avo.consume_mode import resolve_consume_mode

    if _is_help(rest):
        print("usage: avo runtime")
        print("Print consume mode (checkout | binary | override) and command prefix.")
        return 0
    result = resolve_consume_mode(Path.cwd(), home=Path.home())
    print(f"{result.mode} {result.command_prefix}")
    return 0


def _invoke(verb: str, rest: list[str]) -> int | None:
    if verb == "mcp" and _is_help(rest):
        print("usage: avo mcp")
        print("Start the local stdio MCP server.")
        return 0
    if _is_help(rest):
        print(f"usage: avo {verb}")
    fn = importlib.import_module(_MODULES[verb]).main
    try:
        if inspect.signature(fn).parameters:
            result = fn(rest)
        else:
            result = _call_sysargv(fn, verb, rest)
    except SystemExit as exc:
        return _exit_code(exc.code)
    return result


def _call_sysargv(fn: object, verb: str, rest: list[str]) -> object:
    old = sys.argv
    sys.argv = [f"avo-{verb}", *rest]
    try:
        return fn()  # type: ignore[operator]
    finally:
        sys.argv = old


def _exit_code(code: object) -> int:
    if code is None:
        return 0
    if isinstance(code, int):
        return code
    print(code, file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
