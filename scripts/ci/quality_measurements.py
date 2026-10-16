"""Freeze measurements from verified gate outputs, separately from decisions."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import re
import sys
from pathlib import Path

KEYS = (
    "coverage",
    "duplication",
    "mutation",
    "complexity",
    "crap",
    "coupling",
    "dependencies",
    "deadcode",
    "architecture",
    "tree",
    "branches",
)


def module(name: str, filename: str):
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(
            name, Path(__file__).with_name(filename)
        )
        if spec is None or spec.loader is None:
            raise RuntimeError(f"cannot load {filename}")
        value = importlib.util.module_from_spec(spec)
        sys.modules[name] = value
        spec.loader.exec_module(value)
    return sys.modules[name]


def read_json(path: Path) -> dict | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else None
    except (OSError, ValueError):
        return None


def count(value: object) -> int | None:
    return value if type(value) is int and value >= 0 else None


def mapping(value: object) -> dict:
    return value if isinstance(value, dict) else {}


def reference(path: Path, directory: Path, artifact: str = "quality-evidence") -> dict:
    return {
        "artifact": artifact,
        "path": path.relative_to(directory).as_posix(),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def row(key: str, title: str, scope: str) -> dict:
    return {
        "key": key,
        "title": title,
        "scope": scope,
        "state": "UNAVAILABLE",
        "value": "Unavailable",
        "number": None,
        "unit": None,
        "basis": "No verified measurement for this commit and run.",
        "sources": [],
    }


def gate_evidence(doc: dict, directory: Path) -> dict:
    validator = module("avo_ci_gate_execution", "run_quality_gate.py")
    proofs = {}
    for gate in doc.get("gates", []):
        key = gate["key"]
        path = directory / "gates" / key / "gate.json"
        result = validator.validate_receipt(
            path,
            sha=doc["sha"],
            run_id=str(doc["run_id"]),
            gate=key,
            artifact_root=directory,
        )
        receipt = result.get("receipt")
        receipt = receipt if isinstance(receipt, dict) else {}
        outcome = receipt.get("status")
        agrees = outcome == gate["status"] or (
            gate["status"] == "FAIL" and outcome in {"ERROR", "CANCELLED"}
        )
        verified = bool(result["valid"] and agrees)
        proofs[key] = {
            "verified": verified,
            "reason": result["reason"]
            if not result["valid"]
            else "Execution receipt disagrees with the gate outcome."
            if not agrees
            else "Verified execution and hashes.",
            "receipt": receipt,
            "sources": [reference(path, directory)] if path.is_file() else [],
        }
        log = receipt.get("log", {})
        if verified and isinstance(log, dict):
            proofs[key]["sources"].append(
                {
                    "artifact": "quality-evidence",
                    "path": f"gates/{key}/gate.log",
                    "sha256": log.get("sha256"),
                }
            )
    return proofs


def risk_evidence(doc: dict, directory: Path) -> dict:
    validator = module("avo_ci_gate_execution", "run_quality_gate.py")
    result = validator.validate_receipt(
        directory / "gates/code-risk/gate.json",
        sha=doc["sha"],
        run_id=str(doc["run_id"]),
        gate="code-risk",
        artifact_root=directory,
    )
    receipt = result.get("receipt")
    receipt = receipt if isinstance(receipt, dict) else {}
    return {
        "verified": bool(result["valid"] and receipt.get("status") == "PASS"),
        "receipt": receipt,
    }


def output(
    proofs: dict, gate: str, name: str, directory: Path
) -> tuple[dict | None, list[dict]]:
    proof = proofs.get(gate, {})
    if not proof.get("verified"):
        return None, []
    receipt = proof["receipt"]
    logical = f"reports/quality/{name}"
    item = next(
        (
            x
            for x in receipt.get("artifacts", [])
            if x.get("path", "").replace("\\", "/") == logical
        ),
        None,
    )
    path = directory / name
    if not item or item.get("reason") or not path.is_file():
        return None, []
    value = read_json(path)
    if value is None:
        return None, []
    if hashlib.sha256(path.read_bytes()).hexdigest() != item.get("sha256"):
        return None, []
    return value, [reference(path, directory)]


def measured(
    metric: dict,
    value: str,
    basis: str,
    sources: list[dict],
    *,
    number=None,
    unit=None,
    partial=False,
):
    metric.update(
        state="PARTIAL" if partial else "MEASURED",
        value=value,
        basis=basis,
        sources=sources,
        number=number,
        unit=unit,
    )


def producer_matches(payload: dict, doc: dict) -> bool:
    return payload.get("sha") == doc["sha"] and str(payload.get("run_id") or "") == str(
        doc["run_id"]
    )


def collect(doc: dict, directory: Path) -> dict:
    proofs = gate_evidence(doc, directory)
    metrics = {
        item[0]: row(*item)
        for item in (
            ("coverage", "Line coverage", "unit suite; src/avo"),
            ("duplication", "Duplication", "source lines; src/avo"),
            ("mutation", "Mutation efficacy", "light profile; selected Python modules"),
            (
                "complexity",
                "Cyclomatic complexity",
                "Python functions and methods; src/avo",
            ),
            ("crap", "CRAP", "same-run function line coverage and complexity; src/avo"),
            (
                "coupling",
                "Coupling (CA / CE)",
                "static internal imports; avo.<package>",
            ),
            (
                "dependencies",
                "Dependency findings",
                "frozen Python dev + MCP; npm lock",
            ),
            ("deadcode", "Dead-code findings", "Vulture confidence >=60; src/avo"),
            ("architecture", "Import boundaries", "import-linter contracts; avo"),
            ("tree", "Dependency hoist plan", "npm lock; dry run"),
            (
                "branches",
                "Safety branch coverage",
                "selected safety modules; separate scheduled run",
            ),
        )
    }
    diagnostics = {}
    coverage, sources = output(proofs, "coverage", "coverage.json", directory)
    if coverage:
        totals = mapping(coverage.get("totals"))
        covered, total = (
            count(totals.get("covered_lines")),
            count(totals.get("num_statements")),
        )
        if covered is not None and total and covered <= total:
            value = covered / total * 100
            measured(
                metrics["coverage"],
                f"{value:.2f}%",
                f"{covered:,}/{total:,} executable lines",
                sources,
                number=value,
                unit="percent",
                partial=proofs["coverage"]["receipt"]["status"] != "PASS",
            )
    clones, sources = output(
        proofs, "duplication", "jscpd/jscpd-report.json", directory
    )
    if clones:
        totals = mapping(mapping(clones.get("statistics")).get("total"))
        duplicated, total = (
            count(totals.get("duplicatedLines")),
            count(totals.get("lines")),
        )
        percent = totals.get("percentage")
        if (
            type(percent) in (int, float)
            and 0 <= percent <= 100
            and duplicated is not None
            and total
            and duplicated <= total
            and abs(percent - duplicated / total * 100) <= 0.01
            and isinstance(clones.get("duplicates"), list)
        ):
            measured(
                metrics["duplication"],
                f"{duplicated / total * 100:.2f}%",
                f"{duplicated:,}/{total:,} duplicated lines; {len(clones.get('duplicates', []))} clone pairs",
                sources,
                number=duplicated / total * 100,
                unit="percent",
                partial=proofs["duplication"]["receipt"]["status"] != "PASS",
            )
    for key in ("complexity", "deadcode"):
        payload, sources = output(proofs, key, f"{key}.json", directory)
        if payload and producer_matches(payload, doc) and payload.get("complete"):
            diagnostics[key] = payload
            if key == "deadcode":
                counts = mapping(payload.get("counts"))
                found, unwaived = (
                    count(counts.get("findings")),
                    count(counts.get("unwaived")),
                )
                if found is not None and unwaived is not None:
                    measured(
                        metrics[key],
                        f"{found} reported; {unwaived} unwaived",
                        "Actual analyzer findings; documented exceptions listed separately.",
                        sources,
                        partial=proofs[key]["receipt"]["status"] != "PASS",
                    )
    npm, npm_sources = output(proofs, "deps", "npm-audit-summary.json", directory)
    dependencies, dep_sources = output(proofs, "deps", "deps-findings.json", directory)
    raw_sources = []
    raw_states = {}
    for tool in ("pip", "npm"):
        raw, sources = output(proofs, "deps", f"{tool}-audit-raw.json", directory)
        if raw and producer_matches(raw, doc):
            raw_states[tool] = raw.get("status")
            raw_sources.extend(sources)
    if npm and dependencies and not dependencies.get("error"):
        counts = npm
        values = [
            count(counts.get(key)) for key in ("critical", "high", "moderate", "low")
        ]
        findings = dependencies.get("findings")
        if isinstance(findings, list) and all(value is not None for value in values):
            blocking = len(findings)
            incomplete_tools = [
                f"{tool}: {raw_states.get(tool, 'capture unavailable')}"
                for tool in ("pip", "npm")
                if raw_states.get(tool) != "COMPLETE"
            ]
            measured(
                metrics["dependencies"],
                f"{blocking} blocking; npm {values[0]} critical / {values[1]} high / {values[2]} moderate / {values[3]} low",
                "Captured finding summaries; unwaived Python advisories and npm criticals block."
                + (
                    f" Raw audit incomplete ({'; '.join(incomplete_tools)})."
                    if incomplete_tools
                    else " Both raw audits completed; other npm severities are reported."
                ),
                npm_sources + dep_sources + raw_sources,
                partial=bool(incomplete_tools),
            )
            diagnostics["dependencies"] = dependencies
    for key in ("architecture",):
        proof = proofs.get(key, {})
        if proof.get("verified"):
            text = (directory / "gates" / key / "gate.log").read_text(
                encoding="utf-8", errors="replace"
            )
            text = re.sub(r"\x1b\[[0-9;]*m", "", text)
            match = re.search(r"Contracts:\s*(\d+)\s+kept,\s*(\d+)\s+broken", text)
            if match:
                kept, broken = (int(item) for item in match.groups())
                measured(
                    metrics[key],
                    f"{kept} kept; {broken} broken",
                    "Actual executed contract results, not configured contract count.",
                    proof["sources"],
                    partial=proof["receipt"]["status"] != "PASS",
                )
    tree, sources = output(proofs, "tree", "dependency-tree.json", directory)
    if tree:
        counts = [count(tree.get(key)) for key in ("added", "removed", "changed")]
        if all(value is not None for value in counts):
            measured(
                metrics["tree"],
                f"{sum(counts)} proposed package changes",
                f"{counts[0]} additions / {counts[1]} removals / {counts[2]} changes; not applied",
                sources,
                partial=proofs["tree"]["receipt"]["status"] != "PASS",
            )
    risk_proof = risk_evidence(doc, directory)
    risk, risk_sources = output(
        {"code-risk": risk_proof}, "code-risk", "code-risk.json", directory
    )
    if risk and producer_matches(risk, doc):
        diagnostics["code_risk"] = risk
        summary = risk.get("summary", {})
        functions = risk.get("functions", [])
        complexities = [
            item.get("complexity") for item in functions if isinstance(item, dict)
        ]
        maximum = summary.get("max_complexity")
        if (
            complexities
            and all(count(value) is not None and value > 0 for value in complexities)
            and maximum == max(complexities)
        ):
            measured(
                metrics["complexity"],
                f"Maximum {maximum}; {len(functions)} functions",
                "Actual cyclomatic complexity; function locations and existing debt reasons below.",
                risk_sources,
                number=maximum,
                unit="paths",
                partial=summary.get("complexity_status") != "MEASURED",
            )
        provenance = risk.get("provenance", {})
        binding = provenance.get("coverage", {})
        crap = summary.get("max_crap")
        available = count(summary.get("measured_functions"))
        missing = count(summary.get("unmeasured_functions"))
        coverage_proof = proofs.get("coverage", {})
        coverage_receipt = coverage_proof.get("receipt", {})
        coverage_source = coverage_receipt.get("source", {})
        verified_source = provenance.get("sources", {}).get("sha256")
        coverage_binding = (
            coverage is not None
            and coverage_proof.get("verified")
            and coverage_receipt.get("status") == "PASS"
            and coverage_source.get("unchanged") is True
            and verified_source
            and coverage_source.get("start", {}).get("sha256") == verified_source
            and coverage_source.get("end", {}).get("sha256") == verified_source
            and binding.get("sha256")
            == hashlib.sha256((directory / "coverage.json").read_bytes()).hexdigest()
            and binding.get("receipt", {}).get("sha256")
            == hashlib.sha256(
                (directory / "gates/coverage/gate.json").read_bytes()
            ).hexdigest()
        )
        if (
            type(crap) in (int, float)
            and math.isfinite(crap)
            and crap >= 0
            and available
            and missing is not None
            and binding.get("binding") == "validated receipt"
            and coverage_binding
        ):
            measured(
                metrics["crap"],
                f"Max observed {crap:.2f}; {summary.get('above_reference', 0)} above reference 30",
                f"{available}/{available + missing} observed functions joined; {len(risk.get('source_errors', []))} source-analysis errors. CC² × (1 − function line coverage)³ + CC. Reference 30 is informational.",
                risk_sources,
                number=crap,
                unit="score",
                partial=missing > 0 or summary.get("crap_status") != "MEASURED",
            )
        coupling = risk.get("coupling", {})
        packages = coupling.get("packages", [])
        if coupling.get("status") == "MEASURED" and packages:
            ca = [count(item.get("ca")) for item in packages]
            ce = [count(item.get("ce")) for item in packages]
            if all(value is not None for value in ca + ce):
                measured(
                    metrics["coupling"],
                    f"Maximum CA {max(ca)} / CE {max(ce)}; {len(packages)} packages",
                    f"{coupling.get('edge_count')} distinct internal edges; dynamic and intra-package imports not measured.",
                    risk_sources,
                )
    metrics["branches"]["basis"] = (
        "The PR line profile does not instrument branches. The scheduled safety report has its own commit/run identity."
    )
    return {
        "schema": 1,
        "metrics": [metrics[key] for key in KEYS],
        "gates": proofs,
        "diagnostics": diagnostics,
    }


def add_mutation(evidence: dict, doc: dict, path: Path | None) -> None:
    metric = next(row for row in evidence["metrics"] if row["key"] == "mutation")
    dashboard = module("avo_ci_quality_dashboard", "quality_dashboard.py")
    result = dashboard.mutation_metric(doc)
    if result["measured"] is None or path is None or not path.is_file():
        metric["basis"] = result["detail"]
        return
    payload = read_json(path)
    if payload is None or payload != doc.get("mutation"):
        metric["basis"] = "Mutation artifact does not match the frozen counters."
        return
    counts = dashboard.mutation_checker().mutation_evaluation(
        payload.get("counts", payload), min_killed_percent=result["threshold"]
    )["counts"]
    measured(
        metric,
        f"{result['measured']:.2f}%",
        f"{counts['killed']} killed / {counts['survived']} survived / {counts['total']} total; 0 unresolved",
        [reference(path, path.parent, "mutation-reports-light")],
        number=result["measured"],
        unit="percent",
    )
