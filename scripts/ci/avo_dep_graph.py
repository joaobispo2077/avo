#!/usr/bin/env python3
"""Generate a package-level import graph for src/avo (task-026 / FR-12)."""

from __future__ import annotations

import ast
import html
import importlib.util
import json
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src" / "avo"
OUT_DIR = ROOT / "reports" / "dep-graph"


def _pkg(module: str) -> str:
    parts = module.split(".")
    if len(parts) >= 2:
        return ".".join(parts[:2])
    return module


def iter_modules(source: Path = SRC) -> list[tuple[str, Path]]:
    if not source.is_dir():
        raise FileNotFoundError(f"dependency source missing: {source}")
    found: list[tuple[str, Path]] = []
    for path in sorted(source.rglob("*.py")):
        rel = path.relative_to(source)
        if rel.name == "__init__.py":
            mod = (
                "avo"
                if rel.parent == Path(".")
                else "avo." + ".".join(rel.parent.parts)
            )
        else:
            mod = "avo." + ".".join(rel.with_suffix("").parts)
        found.append((mod, path))
    return found


def _targets(
    node: ast.Import | ast.ImportFrom, package: str, known: set[str], path: Path
) -> list[str]:
    if isinstance(node, ast.Import):
        targets = [alias.name for alias in node.names]
    else:
        base = node.module or ""
        if node.level:
            try:
                base = importlib.util.resolve_name("." * node.level + base, package)
            except ImportError as exc:
                raise ValueError(
                    f"{path}:{node.lineno}: invalid relative import"
                ) from exc
        targets = [
            f"{base}.{alias.name}" if f"{base}.{alias.name}" in known else base
            for alias in node.names
        ]
    internal = [name for name in targets if name == "avo" or name.startswith("avo.")]
    for name in internal:
        if name not in known:
            raise ValueError(f"{path}:{node.lineno}: unresolved internal import {name}")
    return internal


def collect_edges(source: Path = SRC) -> tuple[set[str], set[tuple[str, str]]]:
    modules = iter_modules(source)
    if not modules:
        raise ValueError(f"dependency source has no Python modules: {source}")
    known = {
        ".".join(module.split(".")[:length])
        for module, _path in modules
        for length in range(1, len(module.split(".")) + 1)
    }
    nodes = {_pkg(module) for module, _path in modules}
    edges: set[tuple[str, str]] = set()
    for module, path in modules:
        src_pkg = _pkg(module)
        package = module if path.name == "__init__.py" else module.rsplit(".", 1)[0]
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError(f"{path}: invalid UTF-8 source: {exc}") from exc
        tree = ast.parse(text, filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                for target in _targets(node, package, known, path):
                    dst_pkg = _pkg(target)
                    if dst_pkg != src_pkg:
                        nodes.add(dst_pkg)
                        edges.add((src_pkg, dst_pkg))
    return nodes, edges


def write_dot(nodes: set[str], edges: set[tuple[str, str]], dest: Path) -> None:
    lines = ["digraph avo {", "  rankdir=LR;", '  node [shape=box, fontname="Inter"];']
    for name in sorted(nodes):
        lines.append(f'  "{name}";')
    for src, dst in sorted(edges):
        lines.append(f'  "{src}" -> "{dst}";')
    lines.append("}")
    dest.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_html(
    nodes: set[str],
    edges: set[tuple[str, str]],
    dest: Path,
    *,
    provenance: dict[str, str],
) -> None:
    outgoing: dict[str, set[str]] = defaultdict(set)
    incoming: dict[str, set[str]] = defaultdict(set)
    for src, dst in edges:
        outgoing[src].add(dst)
        incoming[dst].add(src)
    rows = []
    for name in sorted(nodes):
        cells = []
        for neighbors in (outgoing[name], incoming[name]):
            listing = "".join(
                f"<li>{html.escape(item)}</li>" for item in sorted(neighbors)
            )
            cells.append(
                f"<td><strong>{len(neighbors)}</strong>"
                + (f"<ul>{listing}</ul>" if listing else "<p>None</p>")
                + "</td>"
            )
        rows.append(
            f'<tr><th scope="row">{html.escape(name)}</th>{"".join(cells)}</tr>'
        )
    stamp = "".join(
        f"<dt>{label}</dt><dd><code>{html.escape(provenance[key])}</code></dd>"
        for key, label in (
            ("sha", "Checkout commit"),
            ("recorded_at", "Recorded (UTC)"),
            ("scope", "Source scope"),
        )
    )
    dest.write_text(
        '<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        "<title>AVO package dependencies</title><style>"
        "body{font:16px/1.5 system-ui,sans-serif;color:#24292f;background:#f6f8fa;"
        "margin:0;padding:clamp(12px,3vw,32px)}main{max-width:1120px;margin:auto}"
        "h1{font-size:clamp(24px,4vw,32px)}a{color:#0969da}code{overflow-wrap:anywhere}"
        "dl{display:grid;grid-template-columns:auto 1fr;gap:6px 16px}dt{font-weight:600}"
        "dd{margin:0;min-width:0}table{width:100%;table-layout:fixed;border-collapse:collapse;"
        "background:white}th,td{padding:12px;border:1px solid #d0d7de;text-align:left;"
        "vertical-align:top;overflow-wrap:anywhere}thead{background:#eaeef2}"
        "th:first-child{width:26%}ul{padding-left:18px;margin:6px 0}td p{margin:6px 0}"
        "caption{text-align:left;font-weight:600;padding:12px 0}"
        "@media(max-width:600px){body{font-size:14px}th,td{padding:8px}"
        "dl{display:block}dd{margin-bottom:8px}ul{padding-left:14px}}"
        "</style></head><body><main><h1>AVO package dependencies</h1>"
        "<p>Optional architecture diagnostic from Python AST imports. "
        "Packages aggregate at <code>avo.&lt;package&gt;</code>; imports within the same "
        "package are omitted. Dynamic imports are not measured. This does not replace "
        "the import-linter gate.</p>"
        f"<dl>{stamp}</dl><p>{len(nodes)} packages · {len(edges)} dependencies. "
        '<a href="avo-imports.dot">Download the DOT graph</a></p>'
        "<table><caption>Outgoing and incoming internal package imports</caption>"
        '<thead><tr><th scope="col">Package</th><th scope="col">Depends on</th>'
        '<th scope="col">Used by</th></tr></thead>'
        f"<tbody>{''.join(rows)}</tbody></table></main></body></html>\n",
        encoding="utf-8",
    )


def main() -> int:
    try:
        nodes, edges = collect_edges(SRC)
        provenance = {
            "sha": subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
            ).strip(),
            "recorded_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "scope": "src/avo/**/*.py",
        }
    except SyntaxError as exc:
        print(
            f"dependency diagnostic failed: {exc.filename}:{exc.lineno}: {exc.msg}",
            file=sys.stderr,
        )
        return 1
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"dependency diagnostic failed: {exc}", file=sys.stderr)
        return 1
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    write_dot(nodes, edges, OUT_DIR / "avo-imports.dot")
    write_html(nodes, edges, OUT_DIR / "avo-imports.html", provenance=provenance)
    (OUT_DIR / "summary.json").write_text(
        json.dumps(
            {**provenance, "nodes": len(nodes), "edges": len(edges)},
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"wrote {OUT_DIR} ({len(nodes)} nodes, {len(edges)} edges)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
