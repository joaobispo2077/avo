#!/usr/bin/env python3
"""Bulk-update docs/commands from helpers/*.py paths to python -m avo.* (Phase 4)."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

REPLACEMENTS = [
    (r"python helpers/init_project\.py", "python -m avo.init_project"),
    (r"python helpers/project_inventory\.py", "python -m avo.project_inventory"),
    (r"python helpers/wrap\.py", "python -m avo.wrap"),
    (r"python helpers/stats\.py", "python -m avo.stats"),
    (r"python helpers/session\.py", "python -m avo.session"),
    (r"python helpers/prepare_transcription\.py", "python -m avo.prepare_transcription"),
    (r"python helpers/transcribe\.py", "python -m avo.transcribe"),
    (r"python helpers/validate_dependencies\.py", "python -m avo.validate_dependencies"),
    (r"python helpers/validate_usability\.py", "python -m avo.validate_usability"),
    (r"python helpers/models_cli\.py", "python -m avo.models_cli"),
    (r"python helpers/adapters/run_job\.py", "python -m avo.adapters.run_job"),
    (r"`helpers/validate_dependencies\.py`", "`src/avo/validate_dependencies.py`"),
    (r"`helpers/validate_usability\.py`", "`src/avo/validate_usability.py`"),
    (r"`helpers/telemetry\.py`", "`src/avo/telemetry.py`"),
    (r"`helpers/hardware\.py`", "`src/avo/hardware.py`"),
    (r"`helpers/stats\.py`", "`src/avo/stats.py`"),
    (r"`helpers/session\.py`", "`src/avo/session.py`"),
    (r"`helpers/project_inventory\.py`", "`src/avo/project_inventory.py`"),
    (r"`helpers/wrap\.py`", "`src/avo/wrap.py`"),
    (r"`helpers/init_project\.py`", "`src/avo/init_project.py`"),
    (r"`helpers/transcribe\.py`", "`src/avo/transcribe.py`"),
    (r"`helpers/render\.py`", "`src/avo/render.py`"),
    (r"`helpers/adapters/`", "`src/avo/adapters/`"),
    (r"helpers/adapters/registry\.py", "src/avo/adapters/registry.py"),
    (r"\[`helpers/hardware\.py`\]\(\.\./helpers/hardware\.py\)", "[`src/avo/hardware.py`](../src/avo/hardware.py)"),
    (r"helpers/prepare_transcription\.py", "avo.prepare_transcription"),
    (r"\*\*`helpers/` \+ `pyproject\.toml`\*\*", "**`src/avo/` + `pyproject.toml`**"),
    (r"`pyproject\.toml` \+ `helpers/`", "`pyproject.toml` + `src/avo/`"),
    (r"engine\*\* \(`helpers/`, `pyproject\.toml`\)", "engine** (`src/avo/`, `pyproject.toml`)"),
    (r"\| `helpers/` \|", "| `src/avo/` |"),
]

GLOBS = [
    "commands/**/*.md",
    "agent-skills/**/*.md",
    "docs/**/*.md",
    "AGENTS.md",
    "SKILL.md",
    "SECURITY.md",
    ".github/instructions/*.md",
]

SKIP = {"docs/repo-layout.md"}  # already updated; keep helpers/ shim row


def migrate_file(path: Path) -> bool:
    rel = path.relative_to(ROOT).as_posix()
    if rel in SKIP:
        return False
    text = path.read_text(encoding="utf-8")
    orig = text
    for pat, rep in REPLACEMENTS:
        text = re.sub(pat, rep, text)
    if text != orig:
        path.write_text(text, encoding="utf-8")
        return True
    return False


def main() -> None:
    changed: list[Path] = []
    for pattern in GLOBS:
        for path in ROOT.glob(pattern):
            if path.is_file() and migrate_file(path):
                changed.append(path)
    for path in sorted(changed):
        print(path.relative_to(ROOT))


if __name__ == "__main__":
    main()
