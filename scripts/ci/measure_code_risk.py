#!/usr/bin/env python3
"""Informational callable complexity, function CRAP, and package coupling."""

from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.metadata
import importlib.util
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from radon.visitors import ComplexityVisitor

ROOT = Path(__file__).resolve().parents[2]
CRAP_REFERENCE = 30


def _graph():
    name = "avo_ci_code_risk_dep_graph"
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(
            name, Path(__file__).with_name("avo_dep_graph.py")
        )
        if spec is None or spec.loader is None:
            raise RuntimeError("dependency collector unavailable")
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return sys.modules[name]


def source_manifest(root: Path) -> list[dict[str, str]]:
    root = root.resolve()
    source = root / "src" / "avo"
    records = []
    for _module, path in _graph().iter_modules(source):
        if not path.resolve().is_relative_to(source.resolve()):
            raise ValueError(f"source escapes declared scope: {path}")
        records.append(
            {
                "path": path.relative_to(root).as_posix(),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        )
    return sorted(records, key=lambda row: row["path"])


def source_fingerprint(records: object) -> str:
    frozen = json.dumps(records, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(frozen).hexdigest()


def crap_score(complexity: int, function_coverage_percent: float) -> float:
    return complexity**2 * (1 - function_coverage_percent / 100) ** 3 + complexity


def _callables(
    tree: ast.AST,
) -> list[tuple[str, ast.FunctionDef | ast.AsyncFunctionDef]]:
    found = []

    class Definitions(ast.NodeVisitor):
        def __init__(self):
            self.names = []

        def visit_ClassDef(self, node):
            self.names.append(node.name)
            self.generic_visit(node)
            self.names.pop()

        def visit_FunctionDef(self, node):
            self.names.append(node.name)
            found.append((".".join(self.names), node))
            self.generic_visit(node)
            self.names.pop()

        visit_AsyncFunctionDef = visit_FunctionDef

    Definitions().visit(tree)
    return found


def _owned_lines(node: ast.FunctionDef | ast.AsyncFunctionDef) -> set[int]:
    lines = set(range(node.body[0].lineno, node.body[-1].end_lineno + 1))
    for child in ast.walk(node):
        if child is not node and isinstance(
            child, (ast.FunctionDef, ast.AsyncFunctionDef)
        ):
            lines.difference_update(
                range(child.body[0].lineno, child.body[-1].end_lineno + 1)
            )
    return lines


def _path_in_scope(name: str, root: Path) -> str:
    normalized = name.replace("\\", "/")
    path = Path(normalized)
    if ".." in path.parts:
        raise ValueError(f"coverage source path escapes scope: {name}")
    path = path if path.is_absolute() else root / path
    if not path.resolve().is_relative_to((root / "src" / "avo").resolve()):
        raise ValueError(f"coverage source outside declared scope: {name}")
    return path.resolve().relative_to(root.resolve()).as_posix()


def _read_json(path: Path) -> tuple[dict, str]:
    raw = path.read_bytes()
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError(f"JSON must be an object: {path}")
    return payload, hashlib.sha256(raw).hexdigest()


def _validate_receipt(
    receipt: dict,
    coverage_path: Path,
    digest: str,
    sha: str,
    run_id: str,
    fingerprint: str,
) -> None:
    if receipt.get("sha") != sha or receipt.get("run_id") != run_id:
        raise ValueError("coverage receipt identity mismatch")
    if receipt.get("gate") != "coverage" or receipt.get("status") != "PASS":
        raise ValueError("coverage receipt is not a successful coverage execution")
    if type(receipt.get("exit_code")) is not int or receipt["exit_code"] != 0:
        raise ValueError("coverage receipt exit code is not successful")
    artifacts = receipt.get("artifacts")
    if not isinstance(artifacts, list):
        raise ValueError("coverage receipt artifacts missing")
    matching = [
        item
        for item in artifacts
        if isinstance(item, dict)
        and Path(str(item.get("path", "")).replace("\\", "/")).name
        == coverage_path.name
    ]
    if (
        len(matching) != 1
        or matching[0].get("sha256") != digest
        or matching[0].get("reason")
    ):
        raise ValueError(
            "coverage receipt artifact is missing, stale, or hash-mismatched"
        )
    source = receipt.get("source")
    if not isinstance(source, dict) or source.get("unchanged") is not True:
        raise ValueError("coverage receipt sources were not unchanged")
    for point in ("start", "end"):
        state = source.get(point)
        if (
            not isinstance(state, dict)
            or state.get("sha256") != fingerprint
            or state.get("error")
        ):
            raise ValueError("coverage receipt source fingerprint mismatch")


def _coverage_evidence(
    coverage_path: Path,
    receipt_path: Path | None,
    *,
    root: Path,
    sha: str,
    run_id: str,
    fingerprint: str,
    test_outcome: str,
    require_receipt: bool,
) -> tuple[dict, dict]:
    evidence = {
        "path": str(coverage_path),
        "sha256": None,
        "tool_version": None,
        "test_outcome": test_outcome,
        "status": "UNAVAILABLE",
        "binding": "local declaration",
        "reason": "",
        "receipt": {
            "path": str(receipt_path) if receipt_path else None,
            "sha256": None,
        },
    }
    try:
        raw = coverage_path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        evidence["sha256"] = digest
        profile = json.loads(raw)
        if not isinstance(profile, dict):
            raise ValueError("coverage JSON must be an object")
        if test_outcome != "success":
            raise ValueError(f"suite did not complete successfully: {test_outcome}")
        meta = profile.get("meta")
        if (
            not isinstance(meta, dict)
            or type(meta.get("format")) is not int
            or meta["format"] != 3
        ):
            raise ValueError("coverage JSON requires format 3 per-function regions")
        evidence["tool_version"] = meta.get("version")
        if not isinstance(profile.get("files"), dict):
            raise ValueError("coverage JSON files missing")
        for binding in (profile, meta, profile.get("provenance", {})):
            if not isinstance(binding, dict):
                continue
            for key, expected in (
                ("sha", sha),
                ("run_id", run_id),
                ("source_fingerprint", fingerprint),
            ):
                if key in binding and binding[key] != expected:
                    raise ValueError(f"coverage {key} does not match current input")
        if require_receipt and receipt_path is None:
            raise ValueError("CI coverage requires a current-run execution receipt")
        if receipt_path is not None:
            receipt, receipt_hash = _read_json(receipt_path)
            evidence["receipt"]["sha256"] = receipt_hash
            _validate_receipt(receipt, coverage_path, digest, sha, run_id, fingerprint)
            evidence["binding"] = "validated receipt"
        files = {}
        for name, payload in profile["files"].items():
            path = _path_in_scope(name, root)
            if path in files:
                raise ValueError(f"duplicate coverage source: {path}")
            files[path] = payload
        evidence.update(
            status="AVAILABLE", reason="Validated function regions are required."
        )
        return files, evidence
    except (OSError, ValueError, TypeError) as exc:
        evidence["reason"] = str(exc)
        return {}, evidence


def _function_coverage(
    region: object, node: ast.FunctionDef | ast.AsyncFunctionDef
) -> dict:
    if (
        not isinstance(region, dict)
        or type(region.get("start_line")) is not int
        or region["start_line"] != node.lineno
    ):
        raise ValueError("function region missing or definition line does not match")
    summary = region.get("summary")
    if not isinstance(summary, dict):
        raise ValueError("function coverage counts missing")
    covered, total, missing = (
        summary.get(key) for key in ("covered_lines", "num_statements", "missing_lines")
    )
    if any(type(value) is not int or value < 0 for value in (covered, total, missing)):
        raise ValueError("function coverage counts must be nonnegative integers")
    if not total or covered + missing != total:
        raise ValueError("function coverage is empty or counts are inconsistent")
    sets = []
    owned = _owned_lines(node)
    for key in ("executed_lines", "missing_lines", "excluded_lines"):
        lines = region.get(key)
        if (
            not isinstance(lines, list)
            or any(type(line) is not int or line < 1 for line in lines)
            or len(set(lines)) != len(lines)
            or not set(lines).issubset(owned)
        ):
            raise ValueError(f"function {key} does not match callable ownership")
        sets.append(set(lines))
    executed, absent, excluded = sets
    if executed & absent or absent & excluded:
        raise ValueError("function line outcomes overlap")
    if len(executed - excluded) != covered or len(absent) != missing:
        raise ValueError("function line evidence does not match coverage counts")
    return {
        "status": "MEASURED",
        "covered_lines": covered,
        "num_statements": total,
        "percent": 100.0 * covered / total,
        "reason": "Per-function statement counts.",
    }


def _function_rows(
    root: Path, files: dict, coverage_reason: str
) -> tuple[list[dict], list[str]]:
    rows, errors = [], []
    for module, path in _graph().iter_modules(root / "src" / "avo"):
        rel = path.relative_to(root).as_posix()
        try:
            tree = ast.parse(path.read_bytes(), filename=rel)
        except (OSError, SyntaxError) as exc:
            errors.append(f"{rel}: {exc}")
            continue
        payload = files.get(rel)
        regions = payload.get("functions", {}) if isinstance(payload, dict) else {}
        for qualname, node in _callables(tree):
            complexity = ComplexityVisitor.from_ast(node).functions[0].complexity
            coverage = {
                "status": "UNAVAILABLE",
                "covered_lines": None,
                "num_statements": None,
                "percent": None,
                "reason": coverage_reason or "Function not measured.",
            }
            try:
                region = regions.get(qualname) if isinstance(regions, dict) else None
                coverage = _function_coverage(region, node)
            except ValueError as exc:
                if not coverage_reason:
                    coverage["reason"] = str(exc)
            measured = coverage["percent"] is not None
            rows.append(
                {
                    "id": f"{module}.{qualname}@{rel}:{node.lineno}",
                    "module": module,
                    "qualname": qualname,
                    "path": rel,
                    "line": node.lineno,
                    "end_line": node.end_lineno,
                    "complexity": complexity,
                    "function_coverage": coverage,
                    "crap": {
                        "status": "MEASURED" if measured else "UNAVAILABLE",
                        "value": crap_score(complexity, coverage["percent"])
                        if measured
                        else None,
                        "reference": CRAP_REFERENCE,
                        "informational": True,
                        "reason": "Function complexity and line coverage."
                        if measured
                        else coverage["reason"],
                    },
                }
            )
    return rows, errors


def _coupling(source: Path) -> dict:
    result = {
        "status": "UNAVAILABLE",
        "scope": "avo.<package>",
        "packages": [],
        "node_count": None,
        "edge_count": None,
        "topology_sha256": None,
        "reason": "",
    }
    try:
        nodes, edges = _graph().collect_edges(source)
    except (OSError, SyntaxError, ValueError) as exc:
        result["reason"] = str(exc)
        return result
    packages = []
    for node in sorted(nodes):
        ca = sum(target == node for _source, target in edges)
        ce = sum(origin == node for origin, _target in edges)
        packages.append(
            {
                "package": node,
                "ca": ca,
                "ce": ce,
                "instability": ce / (ca + ce) if ca + ce else None,
            }
        )
    topology = {"nodes": sorted(nodes), "edges": sorted(edges)}
    result.update(
        status="MEASURED",
        packages=packages,
        node_count=len(nodes),
        edge_count=len(edges),
        topology_sha256=source_fingerprint(topology),
        reason="Distinct internal AST import edges; same-package edges omitted.",
    )
    return result


def build_report(
    *,
    root: Path,
    coverage_path: Path,
    sha: str,
    run_id: str,
    recorded_at: str,
    test_outcome: str = "unknown",
    coverage_receipt: Path | None = None,
    require_receipt: bool = False,
) -> dict:
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise ValueError("a full commit SHA is required")
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", run_id):
        raise ValueError("a run_id is required")
    datetime.strptime(recorded_at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    root = root.resolve()
    manifest = source_manifest(root)
    fingerprint = source_fingerprint(manifest)
    files, evidence = _coverage_evidence(
        coverage_path,
        coverage_receipt,
        root=root,
        sha=sha,
        run_id=run_id,
        fingerprint=fingerprint,
        test_outcome=test_outcome,
        require_receipt=require_receipt,
    )
    reason = evidence["reason"] if evidence["status"] != "AVAILABLE" else ""
    functions, errors = _function_rows(root, files, reason)
    coupling = _coupling(root / "src" / "avo")
    if source_manifest(root) != manifest:
        raise ValueError("source changed during code risk measurement")
    measured = [
        row["crap"]["value"] for row in functions if row["crap"]["value"] is not None
    ]
    summary = {
        "function_count": len(functions),
        "max_complexity": max((row["complexity"] for row in functions), default=None),
        "max_crap": max(measured, default=None),
        "above_reference": sum(value > CRAP_REFERENCE for value in measured)
        if measured
        else None,
        "measured_functions": len(measured),
        "unmeasured_functions": len(functions) - len(measured),
        "complexity_status": "INCOMPLETE" if errors else "MEASURED",
        "crap_status": "MEASURED"
        if functions and len(measured) == len(functions) and not errors
        else "INCOMPLETE",
    }
    return {
        "schema": 1,
        "sha": sha,
        "run_id": run_id,
        "recorded_at": recorded_at,
        "scope": "src/avo/**/*.py",
        "informational": True,
        "provenance": {
            "coverage": evidence,
            "sources": {"sha256": fingerprint, "files": manifest},
            "tools": {
                "radon": importlib.metadata.version("radon"),
                "coverage": importlib.metadata.version("coverage"),
                "python": sys.version.split()[0],
            },
        },
        "functions": functions,
        "summary": summary,
        "coupling": coupling,
        "source_errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument(
        "--coverage", type=Path, default=Path("reports/quality/coverage.json")
    )
    parser.add_argument("--coverage-receipt", type=Path)
    parser.add_argument(
        "--out", type=Path, default=Path("reports/quality/code-risk.json")
    )
    parser.add_argument("--sha", default=os.environ.get("GITHUB_SHA", ""))
    parser.add_argument("--run-id", default=os.environ.get("GITHUB_RUN_ID", ""))
    parser.add_argument("--test-outcome", default="unknown")
    args = parser.parse_args()
    try:
        document = build_report(
            root=args.root,
            coverage_path=args.coverage,
            coverage_receipt=args.coverage_receipt,
            sha=args.sha,
            run_id=args.run_id,
            recorded_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            test_outcome=args.test_outcome,
            require_receipt=os.environ.get("GITHUB_ACTIONS") == "true",
        )
    except (OSError, ValueError) as exc:
        print(f"code risk measurement failed: {exc}", file=sys.stderr)
        return 1
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
