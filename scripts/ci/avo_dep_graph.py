#!/usr/bin/env python3
"""Generate a package-level import graph for src/avo (task-026 / FR-12)."""

from __future__ import annotations

import ast
import html
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src" / "avo"
OUT_DIR = ROOT / "reports" / "dep-graph"


def _pkg(module: str) -> str:
    parts = module.split(".")
    if len(parts) >= 2:
        return ".".join(parts[:2])
    return module


def iter_modules() -> list[tuple[str, Path]]:
    found: list[tuple[str, Path]] = []
    for path in SRC.rglob("*.py"):
        rel = path.relative_to(SRC)
        if rel.name == "__init__.py":
            mod = "avo" if rel.parent == Path(".") else "avo." + ".".join(rel.parent.parts)
        else:
            mod = "avo." + ".".join(rel.with_suffix("").parts)
        found.append((mod, path))
    return found


def collect_edges() -> tuple[set[str], set[tuple[str, str]]]:
    nodes: set[str] = set()
    edges: set[tuple[str, str]] = set()
    for module, path in iter_modules():
        src_pkg = _pkg(module)
        nodes.add(src_pkg)
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            target: str | None = None
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith("avo"):
                        target = _pkg(alias.name)
            elif isinstance(node, ast.ImportFrom) and node.module:
                if node.module.startswith("avo"):
                    target = _pkg(node.module)
            if target and target != src_pkg:
                nodes.add(target)
                edges.add((src_pkg, target))
    return nodes, edges


def write_dot(nodes: set[str], edges: set[tuple[str, str]], dest: Path) -> None:
    lines = ["digraph avo {", "  rankdir=LR;", '  node [shape=box, fontname="Inter"];']
    for name in sorted(nodes):
        lines.append(f'  "{name}";')
    for src, dst in sorted(edges):
        lines.append(f'  "{src}" -> "{dst}";')
    lines.append("}")
    dest.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_html(nodes: set[str], edges: set[tuple[str, str]], dest: Path) -> None:
    mermaid = ["flowchart LR"]
    for src, dst in sorted(edges):
        mermaid.append(f"  {src.replace('.', '_')}[{src}] --> {dst.replace('.', '_')}[{dst}]")
    if not edges:
        mermaid.append("  avo[avo]")
    body = html.escape("\n".join(mermaid))
    dest.write_text(
        "<!DOCTYPE html><html lang=\"en\"><head><meta charset=\"utf-8\">"
        "<title>AVO src/avo import graph</title></head><body>"
        "<h1>AVO package import graph</h1>"
        "<p>Generated from <code>src/avo</code> AST imports. Visibility only — "
        "does not replace import-linter.</p>"
        f"<pre>{body}</pre>"
        f"<p>Nodes: {len(nodes)} · Edges: {len(edges)}</p>"
        "</body></html>\n",
        encoding="utf-8",
    )


def main() -> int:
    nodes, edges = collect_edges()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    write_dot(nodes, edges, OUT_DIR / "avo-imports.dot")
    write_html(nodes, edges, OUT_DIR / "avo-imports.html")
    (OUT_DIR / "summary.json").write_text(
        f'{{"nodes": {len(nodes)}, "edges": {len(edges)}}}\n',
        encoding="utf-8",
    )
    print(f"wrote {OUT_DIR} ({len(nodes)} nodes, {len(edges)} edges)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
