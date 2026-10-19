"""Freeze measurements from verified gate outputs, separately from decisions."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import os
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


def require(condition: bool) -> None:
    if not condition:
        raise ValueError("Evidence contract mismatch")


def canonical_digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def freeze_definitions(doc: dict) -> None:
    doc["metric_definitions"] = module(
        "avo_ci_quality_metric_definitions", "quality_metric_definitions.py"
    ).build_definitions(doc)


def definition_error(doc: dict) -> str | None:
    block = doc.get("metric_definitions")
    if block is None:
        return "Legacy or missing metric-definition identity."
    helper = module(
        "avo_ci_quality_metric_definitions", "quality_metric_definitions.py"
    )
    error = helper.validate_definitions(block)
    if error:
        return error
    if block["reference"]["sha"] != doc.get("sha"):
        return "Metric definition reference belongs to another measured revision."
    if block["policy"] != helper.build_definitions(doc)["policy"]:
        return "Metric definition policy disagrees with this report's frozen policy."
    return None


def reporting_context(*, sha: str, run_id: str, repository: str) -> dict:
    context = {
        "schema": 1,
        "mode": "ci" if os.environ.get("GITHUB_ACTIONS") == "true" else "local-preview",
    }
    attempt = os.environ.get("GITHUB_RUN_ATTEMPT", "")
    if attempt.isdigit() and int(attempt) > 0:
        context["run_attempt"] = int(attempt)
    if os.environ.get("GITHUB_EVENT_NAME") == "pull_request":
        event = read_json(Path(os.environ.get("GITHUB_EVENT_PATH", ""))) or {}
        pr = mapping(event.get("pull_request"))
        number = event.get("number")
        head, base = (
            mapping(pr.get("head")).get("sha"),
            mapping(pr.get("base")).get("sha"),
        )
        if (
            type(number) is int
            and number > 0
            and all(
                isinstance(v, str) and re.fullmatch(r"[0-9a-f]{40}", v)
                for v in (head, base)
            )
        ):
            context.update(pr_number=number, head_sha=head, base_sha=base)
    return context


def validate_reporting_context(doc: dict) -> str | None:
    if "reporting" not in doc:
        return None
    context = doc["reporting"]
    allowed = {"schema", "mode", "pr_number", "head_sha", "base_sha", "run_attempt"}
    if (
        not isinstance(context, dict)
        or set(context) - allowed
        or type(context.get("schema")) is not int
        or context["schema"] != 1
    ):
        return "Invalid reporting context schema or duplicated identity."
    if context.get("mode") not in {"ci", "local-preview", "fixture"}:
        return "Invalid reporting mode."
    if "run_attempt" in context and (
        type(context["run_attempt"]) is not int or context["run_attempt"] < 1
    ):
        return "Invalid reporting attempt."
    if any(key in context for key in ("pr_number", "head_sha", "base_sha")) and (
        type(context.get("pr_number")) is not int
        or context["pr_number"] < 1
        or not all(
            isinstance(context.get(key), str)
            and re.fullmatch(r"[0-9a-f]{40}", context[key])
            for key in ("head_sha", "base_sha")
        )
    ):
        return "Incomplete PR identity."
    if context["mode"] == "ci" and (
        not re.fullmatch(r"[0-9a-f]{40}", str(doc.get("sha", "")))
        or not re.fullmatch(r"[0-9]{1,20}", str(doc.get("run_id", "")))
        or not re.fullmatch(
            r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", str(doc.get("repository", ""))
        )
    ):
        return "CI reporting requires canonical commit, run and repository identity."
    return None


def source_path(value: object) -> bool:
    return (
        isinstance(value, str)
        and value.startswith("src/avo/")
        and value.endswith(".py")
        and not any(c in value for c in "\\\r\n\x00")
        and all(part not in {"", ".", ".."} for part in value.split("/"))
    )


def exception_summary(tool: str, payload: dict) -> dict:
    matches, stale, violations = (
        payload.get(key) for key in ("allowlisted", "stale", "violations")
    )
    valid_matches = isinstance(matches, list) and all(
        isinstance(row, dict)
        and isinstance(row.get("path"), str)
        and isinstance(row.get("name"), str)
        for row in matches
    )
    return {
        "tool": tool,
        "configured_entries": count(
            mapping(payload.get("policy")).get("configured_allowlist_entries")
        ),
        "matched_findings": len(matches) if valid_matches else None,
        "unique_affected": len({(row["path"], row["name"]) for row in matches})
        if valid_matches
        else None,
        "stale_entries": len(stale) if isinstance(stale, list) else None,
        "unwaived_findings": len(violations) if isinstance(violations, list) else None,
        "non_additive": True,
        "counting_unit": "analyzer finding; affected identity is canonical path plus name",
        "members": matches if valid_matches else [],
    }


def source_module(path: str) -> str:
    parts = path.removeprefix("src/").removesuffix(".py").split("/")
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def validated_graph(graph: object, manifest: dict[str, str]) -> dict:
    unavailable = {
        "state": "UNAVAILABLE",
        "reason": "Verified file/module coupling unavailable.",
        "modules": [],
        "edges": [],
    }
    if (
        not isinstance(graph, dict)
        or type(graph.get("schema")) is not int
        or graph["schema"] != 1
        or graph.get("status") != "MEASURED"
    ):
        return unavailable
    try:
        nodes, pairs = graph["modules"], graph["edges"]
        require(isinstance(nodes, list) and isinstance(pairs, list))
        names = [node["module"] for node in nodes]
        require(
            all(
                isinstance(name, str) and re.fullmatch(r"avo(?:\.[\w]+)*", name)
                for name in names
            )
        )
        require(len(set(names)) == len(names))
        expected_names = set()
        for path in manifest:
            parts = source_module(path).split(".")
            expected_names.update(
                ".".join(parts[:index]) for index in range(1, len(parts) + 1)
            )
        require(set(names) == expected_names)
        actual = {}
        files = set()
        for node in nodes:
            name, kind = node["module"], node["kind"]
            if kind == "file":
                path = node["path"]
                require(
                    source_path(path)
                    and path not in files
                    and manifest.get(path) == node["sha256"]
                    and source_module(path) == name
                )
                files.add(path)
            else:
                require(
                    kind == "namespace"
                    and node.get("path") is None
                    and node.get("sha256") is None
                )
                require(any(other.startswith(name + ".") for other in names))
            actual[name] = node
        require(files == set(manifest))
        require(
            all(
                isinstance(edge, list)
                and len(edge) == 2
                and all(isinstance(name, str) for name in edge)
                for edge in pairs
            )
        )
        edges = [tuple(edge) for edge in pairs]
        require(
            all(
                len(edge) == 2
                and edge[0] in actual
                and edge[1] in actual
                and edge[0] != edge[1]
                and actual[edge[0]]["kind"] == "file"
                for edge in edges
            )
        )
        require(len(set(edges)) == len(edges))
        require(type(graph["node_count"]) is int and graph["node_count"] == len(nodes))
        require(type(graph["edge_count"]) is int and graph["edge_count"] == len(edges))
        for name, node in actual.items():
            ca = sum(target == name for _, target in edges)
            ce = sum(origin == name for origin, _ in edges)
            require(count(node["ca"]) == ca and count(node["ce"]) == ce)
            require(
                node.get("instability") is None
                if ca + ce == 0
                else type(node.get("instability")) in (int, float)
                and math.isfinite(node["instability"])
            )
            require(node.get("instability") == (ce / (ca + ce) if ca + ce else None))
        require(
            graph["topology_sha256"]
            == canonical_digest({"nodes": sorted(names), "edges": sorted(edges)})
        )
    except (AssertionError, KeyError, TypeError, ValueError):
        return {
            **unavailable,
            "reason": "File graph disagrees with source, topology or degree evidence.",
        }
    return {**graph, "state": "MEASURED"}


def supporting_evidence(
    risk: dict | None, proof: dict, sources: list[dict], *, coverage_bound: bool
) -> dict:
    functions = {
        "state": "UNAVAILABLE",
        "reason": "Verified source/function evidence unavailable.",
        "records": [],
        "observed_functions": 0,
        "measured_crap_functions": 0,
        "unmeasured_observed_functions": 0,
        "source_errors": [],
        "total_population_known": False,
    }
    result = {
        "schema": 1,
        "source_fingerprint": None,
        "sources": sources,
        "functions": functions,
        "coupling": validated_graph(None, {}),
    }
    if not risk or not proof.get("verified"):
        return result
    try:
        provenance = mapping(risk.get("provenance"))
        source = mapping(provenance.get("sources"))
        receipt_source = mapping(proof["receipt"].get("source"))
        manifest_rows = source["files"]
        require(isinstance(manifest_rows, list) and manifest_rows)
        manifest = {row["path"]: row["sha256"] for row in manifest_rows}
        require(len(manifest) == len(manifest_rows))
        require(
            all(
                source_path(path)
                and isinstance(digest, str)
                and re.fullmatch(r"[0-9a-f]{64}", digest)
                for path, digest in manifest.items()
            )
        )
        fingerprint = canonical_digest(manifest_rows)
        require(
            source["sha256"] == fingerprint and receipt_source.get("unchanged") is True
        )
        require(
            all(
                mapping(receipt_source.get(key)).get("sha256") == fingerprint
                and mapping(receipt_source.get(key)).get("files") == manifest_rows
                for key in ("start", "end")
            )
        )
        rows, errors = risk["functions"], risk.get("source_errors", [])
        require(
            isinstance(rows, list)
            and isinstance(errors, list)
            and all(isinstance(error, str) for error in errors)
        )
        records, seen = [], set()
        for row in rows:
            path, line, name, cc = (
                row["path"],
                row["line"],
                row["qualname"],
                row["complexity"],
            )
            require(
                path in manifest
                and source_path(path)
                and type(line) is int
                and line > 0
                and isinstance(name, str)
                and name
                and not any(c in name for c in "\r\n\x00")
            )
            require(count(cc) is not None and cc > 0 and (path, line, name) not in seen)
            seen.add((path, line, name))
            end = row.get("end_line", line)
            require(type(end) is int and end >= line)
            module_name = source_module(path)
            require(row.get("module", module_name) == module_name)
            coverage = mapping(row.get("function_coverage"))
            covered, total = (
                count(coverage.get("covered_lines")),
                count(coverage.get("num_statements")),
            )
            value = mapping(row.get("crap")).get("value")
            valid = bool(
                coverage_bound
                and coverage.get("status") == "MEASURED"
                and covered is not None
                and total
                and covered <= total
            )
            calculated = cc**2 * (1 - covered / total) ** 3 + cc if valid else None
            valid = (
                valid
                and type(value) in (int, float)
                and math.isfinite(value)
                and math.isclose(value, calculated, rel_tol=1e-10, abs_tol=1e-10)
            )
            coverage = {
                **coverage,
                "status": "MEASURED" if valid else "UNAVAILABLE",
                "percent": covered / total * 100 if valid else None,
                "reason": coverage.get("reason", "")
                if valid
                else "Same-function coverage/score binding unavailable or inconsistent.",
            }
            records.append(
                {
                    **row,
                    "id": f"{module_name}.{name}@{path}:{line}",
                    "module": module_name,
                    "end_line": end,
                    "source_sha256": manifest[path],
                    "function_coverage": coverage,
                    "crap": {
                        "status": "MEASURED" if valid else "UNAVAILABLE",
                        "value": calculated if valid else None,
                        "reference": 30,
                        "informational": True,
                        "reason": coverage["reason"],
                    },
                }
            )
        require(mapping(risk.get("summary")).get("function_count") == len(records))
    except (AssertionError, KeyError, TypeError, ValueError, OverflowError):
        return result
    measured_count = sum(row["crap"]["value"] is not None for row in records)
    result.update(
        source_fingerprint=fingerprint,
        coupling=validated_graph(risk.get("coupling_modules"), manifest),
    )
    functions.update(
        state="PARTIAL" if errors or measured_count < len(records) else "MEASURED",
        reason="Verified observed functions; unknown total population after source errors."
        if errors
        else "Verified observed function records.",
        records=records,
        observed_functions=len(records),
        measured_crap_functions=measured_count,
        unmeasured_observed_functions=len(records) - measured_count,
        source_errors=errors,
        total_population_known=not errors,
    )
    return result


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
            report = module(
                "avo_ci_write_quality_pr_report", "write_quality_pr_report.py"
            )
            text = report.format_npm_summary(npm)
            if text and isinstance(findings, list):
                extras: list[str] = []
                if npm.get("ok") is False:
                    extras.extend(
                        report.format_deps_finding(item)
                        for item in findings
                        if isinstance(item, dict) and item.get("package")
                    )
                else:
                    for item in findings:
                        if not isinstance(item, dict) or item.get("package"):
                            continue
                        advisory = str(item.get("advisory") or "").strip()
                        if not advisory:
                            continue
                        tool = str(item.get("tool") or "").strip()
                        extras.append(f"{tool} {advisory}".strip())
                if extras:
                    text = f"{text}; {'; '.join(extras)}"
            incomplete_tools = [
                f"{tool}: {raw_states.get(tool, 'capture unavailable')}"
                for tool in ("pip", "npm")
                if raw_states.get(tool) != "COMPLETE"
            ]
            measured(
                metrics["dependencies"],
                text
                or f"{len(findings)} blocking; npm {values[0]} critical / {values[1]} high / {values[2]} moderate / {values[3]} low",
                "Captured finding summaries; unwaived Python advisories and npm criticals block."
                + (
                    f" Raw audit incomplete ({'; '.join(incomplete_tools)})."
                    if incomplete_tools
                    else " Both raw audits completed; high or moderate stays a yellow pass and low stays green."
                ),
                npm_sources + dep_sources + raw_sources,
                partial=bool(incomplete_tools),
            )
            metrics["dependencies"]["band"] = report.audit_band(npm)
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
    coverage_proof = proofs.get("coverage", {})
    coverage_receipt = mapping(coverage_proof.get("receipt"))
    coverage_source = mapping(coverage_receipt.get("source"))
    provenance = mapping(mapping(risk).get("provenance"))
    binding = mapping(provenance.get("coverage"))
    verified_source = mapping(provenance.get("sources")).get("sha256")
    coverage_binding = bool(
        coverage is not None
        and coverage_proof.get("verified")
        and coverage_receipt.get("status") == "PASS"
        and coverage_source.get("unchanged") is True
        and verified_source
        and mapping(coverage_source.get("start")).get("sha256") == verified_source
        and mapping(coverage_source.get("end")).get("sha256") == verified_source
        and binding.get("binding") == "validated receipt"
        and binding.get("sha256")
        == hashlib.sha256((directory / "coverage.json").read_bytes()).hexdigest()
        and mapping(binding.get("receipt")).get("sha256")
        == hashlib.sha256(
            (directory / "gates/coverage/gate.json").read_bytes()
        ).hexdigest()
    )
    support = supporting_evidence(
        risk if risk and producer_matches(risk, doc) else None,
        risk_proof,
        risk_sources,
        coverage_bound=coverage_binding,
    )
    functions = support["functions"]
    if functions["state"] != "UNAVAILABLE":
        diagnostics["code_risk"] = risk
        records = functions["records"]
        if records:
            maximum = max(item["complexity"] for item in records)
            measured(
                metrics["complexity"],
                f"Maximum {maximum}; {len(records)} functions",
                "Actual cyclomatic complexity; verified function locations and existing debt reasons below.",
                risk_sources,
                number=maximum,
                unit="paths",
                partial=not functions["total_population_known"],
            )
        crap_values = [
            item["crap"]["value"]
            for item in records
            if item["crap"]["value"] is not None
        ]
        if crap_values:
            maximum = max(crap_values)
            available, total = len(crap_values), len(records)
            measured(
                metrics["crap"],
                f"Max observed {maximum:.2f}; {sum(value > 30 for value in crap_values)} above reference 30",
                f"{available}/{total} observed functions joined; {len(functions['source_errors'])} source-analysis errors. CC² × (1 − function line coverage)³ + CC. Reference 30 is informational.",
                risk_sources,
                number=maximum,
                unit="score",
                partial=available < total or not functions["total_population_known"],
            )
        coupling = mapping(risk.get("coupling"))
        packages = coupling.get("packages", [])
        if (
            coupling.get("status") == "MEASURED"
            and isinstance(packages, list)
            and packages
        ):
            ca = [count(mapping(item).get("ca")) for item in packages]
            ce = [count(mapping(item).get("ce")) for item in packages]
            if all(value is not None for value in ca + ce):
                measured(
                    metrics["coupling"],
                    f"Maximum CA {max(ca)} / CE {max(ce)}; {len(packages)} packages",
                    f"{coupling.get('edge_count')} distinct internal edges; dynamic and intra-package imports not measured.",
                    risk_sources,
                )
    diagnostics["exception_summaries"] = [
        exception_summary(key, diagnostics[key])
        for key in ("complexity", "deadcode")
        if key in diagnostics
    ]
    metrics["branches"]["basis"] = (
        "The PR line profile does not instrument branches. The scheduled safety report has its own commit/run identity."
    )
    return {
        "schema": 1,
        "metrics": [metrics[key] for key in KEYS],
        "gates": proofs,
        "diagnostics": diagnostics,
        "supporting": support,
    }


def add_mutation(evidence: dict, doc: dict, path: Path | None) -> None:
    metric = next(row for row in evidence["metrics"] if row["key"] == "mutation")
    dashboard = module("avo_ci_quality_dashboard", "quality_dashboard.py")
    result = dashboard.mutation_metric(doc)
    if result["status"] == "UNAVAILABLE" or path is None or not path.is_file():
        metric["basis"] = result["detail"]
        return
    payload = read_json(path)
    if payload is None or payload != doc.get("mutation"):
        metric["basis"] = "Mutation artifact does not match the frozen counters."
        return
    evaluation = dashboard.mutation_checker().mutation_evaluation(
        payload.get("counts", payload), min_killed_percent=result["threshold"]
    )
    counts = evaluation["counts"]
    sources = [reference(path, path.parent, f"mutation-reports-{payload['profile']}")]
    if not evaluation["complete"]:
        metric.update(
            state="UNAVAILABLE",
            number=None,
            value="Unavailable",
            basis=evaluation["reason"],
            sources=sources,
        )
        return
    measured(
        metric,
        f"{result['measured']:.2f}%",
        f"{counts['killed']} killed / {counts['survived']} survived / {counts['total']} total; 0 unresolved",
        sources,
        number=result["measured"],
        unit="percent",
    )


def add_mutation_scopes(evidence: dict, doc: dict, path: Path | None) -> None:
    """Normalize optional scope proof once, without changing aggregate gates."""
    profile = mapping(doc.get("mutation_policy")).get("profile")
    result = {
        "schema": 1,
        "state": "UNAVAILABLE",
        "reason": "Per-source mutation results were not retained for this run.",
        "profile": profile,
        "threshold_scope": "aggregate",
        "sources": [],
        "source_fingerprint": None,
        "scopes": [],
    }
    evidence["mutation_scopes"] = result
    if path is None or not path.is_file():
        return
    helper = module("avo_ci_mutation_scopes", "mutation_scopes.py")
    artifact = f"mutation-reports-{profile}"
    try:
        payload, digest = helper._read(path)
        checked = helper.validate_scopes(
            payload,
            sha=doc.get("sha", ""),
            run_id=str(doc.get("run_id") or ""),
            profile=profile,
            aggregate=doc.get("mutation"),
        )
        sources = [reference(path, path.parent, artifact)]
        require(sources[0]["sha256"] == digest)
        if checked["state"] == "UNAVAILABLE" and not checked["scopes"]:
            result.update(reason=checked["reason"], sources=sources)
            result["source_fingerprint"] = canonical_digest(sources)
            return
        raw_stats_path = path.parent / (
            "mutmut-cicd-stats-light.json"
            if profile == "light"
            else "mutmut-cicd-stats.json"
        )
        raw_stats, stats_digest = helper._read(raw_stats_path)
        require(stats_digest == checked["aggregate"]["sha256"])
        require(
            all(
                raw_stats.get(key) == doc["mutation"].get(key)
                for key in ("sha", "run_id", "profile")
            )
            and helper._aggregate_counts(raw_stats) == checked["aggregate"]["counts"]
        )
        sources.append(reference(raw_stats_path, path.parent, artifact))
        graph = mapping(mapping(evidence.get("supporting")).get("coupling"))
        manifest = (
            {
                row["path"]: row.get("sha256")
                for row in graph.get("modules", [])
                if row.get("path") is not None
            }
            if graph.get("state") == "MEASURED"
            else {}
        )
        for row in checked["scopes"]:
            if manifest:
                require(manifest.get(row["path"]) == row["source_sha256"])
            metadata = row.get("metadata")
            if metadata is None:
                continue
            relative = metadata.get("artifact_path", "")
            require(
                relative == "scope-evidence/" + row["path"] + ".meta"
                and not Path(relative).is_absolute()
                and (path.parent / relative)
                .resolve()
                .is_relative_to(path.parent.resolve())
            )
            raw, raw_digest = helper._read(path.parent / relative)
            outcomes = raw.get("exit_code_by_key")
            require(
                raw_digest == metadata["sha256"]
                and isinstance(outcomes, dict)
                and all(code is None or type(code) is int for code in outcomes.values())
                and outcomes
                == {mutant["id"]: mutant["exit_code"] for mutant in row["mutants"]}
            )
            sources.append(reference(path.parent / relative, path.parent, artifact))
        result.update(
            state=checked["state"],
            reason=checked["reason"],
            scopes=checked["scopes"],
            sources=sources,
            source_fingerprint=canonical_digest(sources),
        )
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        result["reason"] = f"Per-source mutation evidence unavailable: {exc}"
