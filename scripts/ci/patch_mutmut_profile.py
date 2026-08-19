#!/usr/bin/env python3
"""Apply or restore [tool.mutmut] profile arrays from mutation-config.json."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PYPROJECT = ROOT / "pyproject.toml"
BACKUP = ROOT / ".pyproject.toml.mutmut.bak"
CONFIG_PATH = ROOT / "scripts/ci/mutation-config.json"

SOURCE_START = "# mutmut-profile-source-paths:start"
SOURCE_END = "# mutmut-profile-source-paths:end"
TESTS_START = "# mutmut-profile-test-selection:start"
TESTS_END = "# mutmut-profile-test-selection:end"


def format_toml_array(key: str, values: list[str]) -> str:
    lines = [f"{key} = ["]
    for value in values:
        lines.append(f'    "{value}",')
    lines.append("]")
    return "\n".join(lines)


def replace_marked_block(text: str, start: str, end: str, body: str) -> str:
    start_idx = text.find(start)
    end_idx = text.find(end)
    if start_idx < 0 or end_idx < 0 or end_idx <= start_idx:
        raise SystemExit(f"missing mutmut profile markers {start!r} / {end!r}")
    before = text[: start_idx + len(start)]
    after = text[end_idx:]
    return f"{before}\n{body}\n{after}"


def apply_profile(profile: str) -> None:
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    if profile not in config:
        raise SystemExit(f"unknown mutation profile: {profile}")
    spec = config[profile]
    paths = spec.get("source_paths") or []
    tests = spec.get("pytest_add_cli_args_test_selection") or []
    if not paths or not tests:
        raise SystemExit(f"profile {profile} missing source_paths or tests")
    if not BACKUP.is_file():
        shutil.copy2(PYPROJECT, BACKUP)
    text = BACKUP.read_text(encoding="utf-8")
    text = replace_marked_block(
        text, SOURCE_START, SOURCE_END, format_toml_array("source_paths", paths)
    )
    text = replace_marked_block(
        text,
        TESTS_START,
        TESTS_END,
        format_toml_array("pytest_add_cli_args_test_selection", tests),
    )
    PYPROJECT.write_text(text, encoding="utf-8", newline="\n")
    print(
        f"applied mutmut profile {profile} ({len(paths)} sources, {len(tests)} tests)"
    )


def restore() -> None:
    if not BACKUP.is_file():
        print("no mutmut profile backup; nothing to restore")
        return
    shutil.move(str(BACKUP), str(PYPROJECT))
    print("restored pyproject.toml mutmut profile")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    apply_p = sub.add_parser("apply")
    apply_p.add_argument("profile")
    sub.add_parser("restore")
    args = parser.parse_args(argv)
    if args.cmd == "apply":
        apply_profile(args.profile)
        return 0
    restore()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
