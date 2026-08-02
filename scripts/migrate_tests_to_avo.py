#!/usr/bin/env python3
"""Rewrite tests to import avo.* instead of helpers.* (Phase 2.5)."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TESTS = ROOT / "tests"

REMOVALS = [
    r"^sys\.path\.insert\(0, str\(ROOT / \"helpers\"\)\)\n",
    r"^sys\.path\.insert\(0, str\(HELPERS\)\)\n",
    r"^HELPERS = .+\n",
    r"^sys\.path\.insert\(0, str\(ROOT\)\)\n",
    r"^sys\.path\.insert\(0, str\(Path\(__file__\)\.resolve\(\)\.parents\[1\] / \"helpers\"\)\)\n",
    r"^HELPERS = Path\(__file__\)\.resolve\(\)\.parents\[1\] / \"helpers\"\n",
]


BARE_IMPORTS = [
    "validate_edl",
    "render",
    "transcribe",
    "transcribe_batch",
    "init_project",
    "session",
    "project_inventory",
    "build_captions",
    "stats",
    "wrap",
]


def migrate(path: Path) -> bool:
    text = path.read_text(encoding="utf-8")
    orig = text
    for pat in REMOVALS:
        text = re.sub(pat, "", text, flags=re.M)
    text = re.sub(r"\bfrom helpers\.", "from avo.", text)
    text = re.sub(r"\bimport helpers\.", "import avo.", text)
    text = re.sub(r'"helpers\.', '"avo.', text)
    text = re.sub(r"'helpers\.", "'avo.", text)
    text = re.sub(r'ROOT / "helpers/', 'ROOT / "src/avo/', text)
    text = re.sub(r'"helpers/', '"src/avo/', text)
    text = re.sub(r'"helpers":', '"src/avo":', text)
    for mod in BARE_IMPORTS:
        text = re.sub(
            rf"^import {mod}\b",
            f"from avo import {mod}",
            text,
            flags=re.M,
        )
    if text != orig:
        path.write_text(text, encoding="utf-8")
        return True
    return False


def main() -> None:
    changed = [p for p in TESTS.rglob("*.py") if migrate(p)]
    for p in changed:
        print(p.relative_to(ROOT))


if __name__ == "__main__":
    main()
