#!/usr/bin/env python3
"""One-shot: regenerate scripts/ci/deadcode-allowlist.json for task-014.

  uv run --frozen --extra dev python scripts/ci/_gen_deadcode_allowlist.py

Prefer deleting real dead code over growing this file. Schema must match
``check_deadcode.py`` (``items`` + ``min_confidence`` = 60).
"""

from __future__ import annotations

import json
from pathlib import Path

from vulture import Vulture

ROOT = Path(__file__).resolve().parents[2]
TARGET = ROOT / "src" / "avo"
OUT = Path(__file__).resolve().parent / "deadcode-allowlist.json"
MIN_CONFIDENCE = 60


def _norm(path: Path) -> str:
    text = path.as_posix().replace("\\", "/")
    if "src/avo/" in text:
        return "src/avo/" + text.split("src/avo/", 1)[1]
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return text


def _reason(rel: str, name: str, typ: str) -> str:
    if "/adapters/stubs/" in rel:
        return "Stub adapter registered dynamically via adapter registry"
    if "/adapters/" in rel:
        return "Adapter class/method loaded dynamically via adapter registry"
    if "/mcp/" in rel:
        return "MCP bridge/registry/CLI surface (dynamic tool registration)"
    if "/timeline/ports.py" in rel:
        return "Timeline port Protocol surface for hexagonal adapters"
    if "/timeline/" in rel:
        return "Timeline domain/API surface (dynamic CLI and future stages)"
    if typ == "attribute" and name.startswith("__"):
        return "Runtime attribute stamped for dynamic MCP tool wrappers"
    if typ == "variable" and name.isupper():
        return "Public constant / enum-like value kept for API and templates"
    if typ in {"function", "method", "class"}:
        return "Public API / CLI surface not referenced inside src/avo scan"
    return "Deferred or dynamic surface; keep until callers land"


def main() -> None:
    v = Vulture(verbose=False)
    v.scavenge([str(TARGET)])
    items = []
    for item in v.get_unused_code(min_confidence=MIN_CONFIDENCE):
        rel = _norm(Path(item.filename))
        items.append(
            {
                "path": rel,
                "name": item.name,
                "kind": item.typ,
                "lineno": int(item.first_lineno),
                "confidence": int(item.confidence),
                "reason": _reason(rel, item.name, item.typ),
            }
        )
    items.sort(key=lambda e: (e["path"], e["lineno"], e["name"]))
    payload = {
        "version": 1,
        "description": (
            "Vulture exemptions for src/avo (task-014 / FR-8). "
            "min_confidence=60 matches vulture unused function/class/method/variable "
            "signal. Prefer deleting dead code over adding entries. Each item needs "
            "path, name, reason."
        ),
        "min_confidence": MIN_CONFIDENCE,
        "items": items,
    }
    OUT.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {len(items)} items -> {OUT.relative_to(ROOT).as_posix()}")


if __name__ == "__main__":
    main()
