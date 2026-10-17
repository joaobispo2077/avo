"""Describe metric semantics and frozen policy without reading test baselines."""

from __future__ import annotations

import hashlib
import json
import math
import re

REFERENCE = "tests/fixtures/quality_metrics/definitions.json"
FIELDS = (
    "classification",
    "unit",
    "scope",
    "grain",
    "calculation",
    "validity",
    "interpretation",
    "sources",
)
REVISIONS = {
    "architecture": 1,
    "branches": 1,
    "complexity": 1,
    "coupling": 1,
    "coupling_files": 2,
    "coverage": 1,
    "crap": 1,
    "deadcode": 1,
    "dependencies": 1,
    "duplication": 1,
    "execution_events": 1,
    "mutation": 1,
    "tree": 1,
}

# The independent reviewed projection lives in the tracked test fixtures. Runtime
# never reads that expected catalog or uses it to calculate measurements.
DEFINITIONS = {
    "architecture": (
        "execution observation",
        "contracts",
        "avo import-linter contracts",
        "executed contract",
        "Observed kept and broken contract counts from the captured import-linter execution.",
        "Missing or invalid execution evidence is unavailable; configured contract count is not an executed result.",
        "Broken contracts follow the existing architecture gate; contract counts are not a quality percentage.",
        ("scripts/ci/quality_measurements.py", ".importlinter"),
    ),
    "branches": (
        "measurement",
        "percent",
        "selected safety modules; separate scheduled run",
        "instrumented branch",
        "No branch percentage is inferred from the PR line-coverage profile.",
        "Unavailable in the PR report unless separately captured evidence has its own matching identity.",
        "Scheduled branch evidence cannot replace the current PR line measurement or create a new gate.",
        ("scripts/ci/quality_measurements.py", "scripts/ci/report_branch_coverage.py"),
    ),
    "complexity": (
        "measurement",
        "independent paths",
        "src/avo Python functions and methods",
        "function definition",
        "Radon cyclomatic complexity for each observed callable definition.",
        "Positive integer complexity with a unique source location; source errors make total population unknown.",
        "Rank descending value then path, definition line and qualified name; top 10 is an excerpt. Xenon/Ruff and exception policies remain separate.",
        ("scripts/ci/measure_code_risk.py", "scripts/ci/quality_hotspots.py"),
    ),
    "coupling": (
        "measurement",
        "distinct directed import edges",
        "static internal imports aggregated at avo.<package>",
        "package",
        "CA counts distinct incoming packages; CE counts distinct outgoing packages. Same-package and self edges are omitted; instability is CE/(CA+CE).",
        "Missing or invalid graph is unavailable; instability is undefined when CA+CE is zero.",
        "Informational static connectivity; external/dynamic imports and runtime calls are not measured. Package values cannot be relabeled as files.",
        ("scripts/ci/avo_dep_graph.py", "scripts/ci/measure_code_risk.py"),
    ),
    "coupling_files": (
        "measurement",
        "distinct directed import edges",
        "src/avo/**/*.py; static internal module imports",
        "actual Python source file",
        "CA counts distinct incoming modules; CE counts distinct outgoing modules. Include same-package imports, deduplicate edges and exclude self edges; instability is CE/(CA+CE).",
        "Every actual file has its source hash; namespace-only containers have null paths and hashes. Invalid graph is unavailable; zero-degree instability is undefined.",
        "CE horizontal, CA vertical. Raw medians include all actual files and isolates; equality is lower. F IDs sort by path; coincident numbered G groups sort by (CE, CA) and map to a below-plot file index plus full text/JSON membership. Disclosed piecewise log2(1+count) spacing centers each raw median to form four equal-area quadrants; tick labels remain raw counts. Colored regions and median references describe informational connectivity, never gate outcomes or architectural verdicts.",
        (
            "scripts/ci/avo_dep_graph.py",
            "scripts/ci/measure_code_risk.py",
            "scripts/ci/coupling_dashboard.py",
        ),
    ),
    "coverage": (
        "measurement",
        "percent",
        "unit-suite executable lines; src/avo",
        "executable source line",
        "100 * covered_lines / num_statements.",
        "Nonnegative integer counts, positive denominator and covered <= total; missing or inconsistent evidence is unavailable, not zero.",
        "Minimum gate uses frozen coverage precision; raw value controls the band. Below limit is red; from limit to limit+0.25*(100-limit) is yellow; at or above that margin is green. A 100% floor requires exactly 100%.",
        (
            "scripts/ci/quality_measurements.py",
            "scripts/ci/quality_dashboard.py",
            "pyproject.toml",
        ),
    ),
    "crap": (
        "measurement",
        "CRAP score",
        "src/avo; same-function complexity and line coverage",
        "function definition",
        "CC^2 * (1 - covered_statements/total_statements)^3 + CC.",
        "Requires valid same-function statement counts and successful same-source coverage proof. Missing inputs remain unmeasured; valid partial populations stay partial.",
        "Reference 30 is informational. Rank observed scores descending then path, definition line and qualified name; show top 10 with measured/unmeasured and unknown population context.",
        ("scripts/ci/measure_code_risk.py", "scripts/ci/quality_hotspots.py"),
    ),
    "deadcode": (
        "finding",
        "analyzer findings",
        "Vulture confidence >=60; src/avo",
        "reported source finding",
        "Observed findings and unwaived findings from the captured analyzer output; configured entries and observed matches are separate counts.",
        "Incomplete or invalid analyzer evidence is unavailable or explicitly partial; missing reasons are not invented.",
        "Unwaived/stale exceptions follow existing gate policy; allowlist size is not removed defects or test efficacy.",
        (
            "scripts/ci/check_deadcode.py",
            "scripts/ci/quality_measurements.py",
            "scripts/ci/deadcode-allowlist.json",
        ),
    ),
    "dependencies": (
        "finding",
        "tool-specific advisory or vulnerable-package counts",
        "frozen Python dev + MCP dependencies and npm lock",
        "captured tool finding",
        "Keep Python advisory findings, npm severity counts and blocking findings separate; never sum unlike counting units into a defect total.",
        "Incomplete raw audits remain partial and cannot imply zero findings; recorded waiver context is distinct from observed findings.",
        "Existing unwaived Python advisory and npm-critical policy blocks; other npm severities are reported. Configuration is not a measurement.",
        (
            "scripts/ci/check_npm_audit.py",
            "scripts/ci/quality_measurements.py",
            "scripts/ci/deps-audit-allowlist.json",
        ),
    ),
    "duplication": (
        "measurement",
        "percent",
        "duplicated source lines; src/avo",
        "source line",
        "100 * duplicatedLines / lines; reported percentage must agree within 0.01 percentage points.",
        "Nonnegative integer counts, positive denominator, duplicated <= total and clone-pair list required; missing/inconsistent evidence is unavailable.",
        "Direct percent with maximum gate. Above ceiling is red; above 0.75*ceiling through ceiling is yellow; at or below 0.75*ceiling is green. No goodness conversion.",
        (
            "scripts/ci/quality_measurements.py",
            "scripts/ci/quality_dashboard.py",
            ".jscpd.json",
        ),
    ),
    "execution_events": (
        "execution observation",
        "JUnit testcase events",
        "captured unit and CLI/MCP/media integration suites",
        "testcase execution event within its suite",
        "Count observed passed, failed, errored and skipped testcase events; total equals their sum.",
        "Conflicting outcomes or invalid receipt/XML are unavailable; partial execution retains explicitly observed counts and recorded reasons.",
        "Repeated executions are not additional unique tests. Success is execution evidence, not a quality percentage; missing reasons remain unavailable.",
        ("scripts/ci/test_execution_evidence.py",),
    ),
    "mutation": (
        "measurement",
        "percent",
        "frozen mutation profile; selected Python modules",
        "mutant test verdict",
        "100 * killed / (killed + survived), only when every mutant has a killed or survived verdict and total is positive.",
        "Nonnegative integer outcomes must reconcile with total. Every supported unresolved category and unaccounted remainder withhold efficacy; profile/floor and commit/run must match.",
        "Minimum frozen profile floor; raw band uses the minimum margin rule. Unresolved outcomes are not kills or equivalent mutants; scopes and runs are not pooled.",
        (
            "scripts/ci/check_mutation.py",
            "scripts/ci/quality_dashboard.py",
            "scripts/ci/mutation-config.json",
        ),
    ),
    "tree": (
        "configuration diagnostic",
        "proposed package changes",
        "npm lock; find-dupes dry run",
        "proposed add/remove/change operation",
        "Report proposed added, removed and changed package counts with their separate units/context.",
        "Missing/invalid output is unavailable; command outcome and proposal completeness remain distinct.",
        "Report-only hoist proposal; no package change is claimed applied and no quality percentage is inferred.",
        ("scripts/ci/quality-tree.sh", "scripts/ci/quality_measurements.py"),
    ),
}


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def _mapping(value: object) -> dict:
    return value if isinstance(value, dict) else {}


def _percentage(value: object) -> float | None:
    return (
        float(value)
        if type(value) in (int, float) and 0 <= value <= 100 and math.isfinite(value)
        else None
    )


def _semantic(entry: dict) -> dict:
    return {key: value for key, value in entry.items() if key != "sha256"}


def build_definitions(doc: dict) -> dict:
    """Freeze descriptions and this document's policy, never current configuration."""
    entries = []
    for identifier, values in sorted(DEFINITIONS.items()):
        entry = {
            "id": identifier,
            "revision": REVISIONS[identifier],
            **dict(zip(FIELDS, values, strict=True)),
        }
        entry["sources"] = list(entry["sources"])
        entries.append({**entry, "sha256": _digest(entry)})
    mutation = _mapping(doc.get("mutation_policy"))
    precision = doc.get("coverage_precision")
    policy = {
        "coverage_floor": _percentage(doc.get("floor")),
        "coverage_precision": precision
        if type(precision) is int and 0 <= precision <= 9
        else None,
        "duplication_ceiling": _percentage(
            _mapping(_mapping(doc.get("series")).get("duplication")).get("ceiling")
        ),
        "mutation": {
            "profile": mutation.get("profile")
            if isinstance(mutation.get("profile"), str)
            and mutation["profile"] in {"light", "full"}
            else None,
            "floor": _percentage(mutation.get("floor")),
        },
    }
    return {
        "schema": 1,
        "entries": entries,
        "catalog_sha256": _digest(
            {"schema": 1, "entries": [_semantic(entry) for entry in entries]}
        ),
        "policy": policy,
        "policy_sha256": _digest(policy),
        "reference": {"path": REFERENCE, "sha": doc.get("sha", "")},
    }


def _safe_path(value: object) -> bool:
    return (
        isinstance(value, str)
        and re.fullmatch(r"[A-Za-z0-9_.\-/]+", value) is not None
        and all(part not in {"", ".", ".."} for part in value.split("/"))
    )


def validate_definitions(block: object) -> str | None:
    """Validate a retained catalog offline without consulting today's definitions."""
    try:
        if not isinstance(block, dict) or set(block) != {
            "schema",
            "entries",
            "catalog_sha256",
            "policy",
            "policy_sha256",
            "reference",
        }:
            raise ValueError("metric definition block fields are invalid")
        if type(block["schema"]) is not int or block["schema"] != 1:
            raise ValueError("metric definition schema is unsupported")
        entries = block["entries"]
        if not isinstance(entries, list) or not entries:
            raise ValueError("metric definition entries are missing")
        identifiers = []
        for entry in entries:
            if not isinstance(entry, dict) or set(entry) != {
                "id",
                "revision",
                "sha256",
                *FIELDS,
            }:
                raise ValueError("metric definition entry fields are invalid")
            identifier = entry["id"]
            if not isinstance(identifier, str) or not re.fullmatch(
                r"[a-z][a-z0-9_]*", identifier
            ):
                raise ValueError("metric definition ID is invalid")
            identifiers.append(identifier)
            if type(entry["revision"]) is not int or entry["revision"] < 1:
                raise ValueError(f"{identifier}: definition revision is invalid")
            if any(
                not isinstance(entry[field], str) or not entry[field].strip()
                for field in FIELDS[:-1]
            ):
                raise ValueError(f"{identifier}: semantic text is invalid")
            if entry["classification"] not in {
                "measurement",
                "execution observation",
                "finding",
                "configuration diagnostic",
            }:
                raise ValueError(f"{identifier}: classification is invalid")
            sources = entry["sources"]
            if (
                not isinstance(sources, list)
                or not sources
                or not all(_safe_path(source) for source in sources)
                or len(sources) != len(set(sources))
            ):
                raise ValueError(f"{identifier}: source references are invalid")
            if entry["sha256"] != _digest(_semantic(entry)):
                raise ValueError(f"{identifier}: semantic hash mismatch")
        if identifiers != sorted(set(identifiers)):
            raise ValueError("metric IDs must be unique and sorted")
        if block["catalog_sha256"] != _digest(
            {"schema": 1, "entries": [_semantic(entry) for entry in entries]}
        ):
            raise ValueError("metric catalog hash mismatch")
        policy = block["policy"]
        if not isinstance(policy, dict) or set(policy) != {
            "coverage_floor",
            "coverage_precision",
            "duplication_ceiling",
            "mutation",
        }:
            raise ValueError("frozen policy fields are invalid")
        for key in ("coverage_floor", "duplication_ceiling"):
            if policy[key] is not None and _percentage(policy[key]) is None:
                raise ValueError(f"frozen {key} is invalid")
        precision = policy["coverage_precision"]
        if precision is not None and (
            type(precision) is not int or not 0 <= precision <= 9
        ):
            raise ValueError("frozen coverage precision is invalid")
        mutation = policy["mutation"]
        if (
            not isinstance(mutation, dict)
            or set(mutation) != {"profile", "floor"}
            or mutation["profile"] not in {None, "light", "full"}
        ):
            raise ValueError("frozen mutation policy is invalid")
        if mutation["floor"] is not None and _percentage(mutation["floor"]) is None:
            raise ValueError("frozen mutation floor is invalid")
        if block["policy_sha256"] != _digest(policy):
            raise ValueError("frozen policy hash mismatch")
        reference = block["reference"]
        if (
            not isinstance(reference, dict)
            or set(reference) != {"path", "sha"}
            or reference["path"] != REFERENCE
            or not isinstance(reference["sha"], str)
            or not re.fullmatch(r"[0-9a-f]{40}", reference["sha"])
        ):
            raise ValueError("measured-revision definition reference is invalid")
    except (ValueError, TypeError, KeyError) as exc:
        return str(exc)
    return None
