"""Render categorical gate decisions without turning checks into quality scores."""

from __future__ import annotations

import copy
import importlib.util
import re
import sys
import textwrap
from collections import Counter
from pathlib import Path

GATES = (
    ("lint", "Lint"),
    ("format", "Format"),
    ("coverage", "Coverage"),
    ("complexity", "Complexity"),
    ("deps", "Dependency audit"),
    ("deadcode", "Dead code"),
    ("duplication", "Duplication"),
    ("architecture", "Architecture"),
    ("tree", "Dependency tree"),
)
# gate_decisions revision 1 retains this population when live CI policy changes.
GATE_KEYS_V1 = frozenset(
    {
        "lint",
        "format",
        "coverage",
        "complexity",
        "deps",
        "deadcode",
        "duplication",
        "architecture",
        "tree",
        "mutation",
    }
)
REQUIRED_JOBS_V1 = (
    "prerequisites-gate",
    "repo-unit-tests",
    "repo-integration-tests",
    "software-quality",
    "usability-gate",
    "mutation-light",
    "ci-readiness",
)


def _view():
    key = "avo_ci_quality_mutation_dashboard"
    if key not in sys.modules:
        spec = importlib.util.spec_from_file_location(
            key, Path(__file__).with_name("quality_mutation_dashboard.py")
        )
        if spec is None or spec.loader is None:
            raise RuntimeError("Gate view helpers are unavailable")
        module = importlib.util.module_from_spec(spec)
        sys.modules[key] = module
        spec.loader.exec_module(module)
    return sys.modules[key]


def _status(value: str) -> str:
    value = str(value or "MISSING").upper()
    value = {
        "SUCCESS": "PASS",
        "FAILURE": "FAIL",
        "CANCELLED": "CANCELED",
        "TIMED_OUT": "TIMEOUT",
    }.get(value, value)
    return (
        value
        if value
        in {
            "PASS",
            "FAIL",
            "ERROR",
            "INVALID",
            "MISSING",
            "UNAVAILABLE",
            "UNKNOWN",
            "INCOMPLETE",
            "CANCELED",
            "TIMEOUT",
            "SKIPPED",
        }
        else "UNKNOWN"
    )


def _decision(reported: str, proof: dict) -> str:
    receipt = proof.get("receipt", {})
    recorded = _status(receipt.get("status"))
    error = str(receipt.get("error") or "").lower()
    if proof.get("verified") is True:
        if "timed out" in error or "timeout" in error:
            return "TIMEOUT"
        if recorded in {"CANCELED", "TIMEOUT", "SKIPPED", "INCOMPLETE", "ERROR"}:
            return recorded
        code = receipt.get("exit_code")
        if recorded in {"FAIL", "INVALID"}:
            return recorded
        if type(code) is int and code != 0:
            return "FAIL"
        if reported == "PASS" and (recorded != "PASS" or type(code) is not int):
            return "INCOMPLETE"
    elif reported == "PASS":
        return "INCOMPLETE"
    return reported


def _policy(document: dict, gate: dict) -> str:
    key = gate["key"]
    text = gate.get("checks") or "Policy unavailable."
    if key in {"coverage", "duplication"}:
        values = document.get("series", {}).get(key, {})
        floor = document.get("floor") if key == "coverage" else None
        limit = values.get("floor" if key == "coverage" else "ceiling", floor)
        limit = _view().load("quality_dashboard").percentage(limit)
        if limit is not None:
            text += f"; {'Minimum' if key == 'coverage' else 'Maximum'} {limit:g}%"
        precision = document.get("coverage_precision")
        if key == "coverage" and type(precision) is int and 0 <= precision <= 9:
            text += f"; comparison at {precision} decimal places"
    return text


def _observed(document: dict, key: str, proof: dict) -> str:
    if key in {"lint", "format"}:
        code = proof.get("receipt", {}).get("exit_code")
        return f"Captured exit {code if code is not None else 'unavailable'}. Numeric finding count not exported."
    evidence = document.get("measurement_evidence", {})
    metric_key = "dependencies" if key == "deps" else key
    observation = next(
        (row for row in evidence.get("metrics", []) if row.get("key") == metric_key), {}
    )
    if key == "complexity":
        counts = evidence.get("diagnostics", {}).get("complexity", {}).get("counts", {})
        if "unwaived" in counts and "allowlisted" in counts:
            return f"{counts['unwaived']} unwaived · {counts['allowlisted']} observed accepted findings"
    if observation.get("state") not in {"MEASURED", "PARTIAL"}:
        return (
            observation.get("basis")
            or "Measurements unavailable; inspect execution evidence."
        )
    value = observation.get("value") or "Measured value unavailable"
    basis = observation.get("basis", "")
    return str(value) + (
        f" · {basis}" if key in {"coverage", "duplication", "tree"} and basis else ""
    )


def build_gate_series(document: dict, *, primary_series: dict | None = None) -> dict:
    view = _view()
    shared = view.load("coupling_dashboard")
    series = shared.context(document, "gate_decisions")
    gates = {row["key"]: row for row in document.get("gates", [])}
    proofs = document.get("measurement_evidence", {}).get("gates", {})
    primary = (
        primary_series
        if primary_series is not None
        else view.load("quality_dashboard").build_series(document)
    )
    measured = {metric["title"].lower(): metric for metric in primary["metrics"]}
    rows = []
    for key, title in GATES:
        gate = gates.get(key, {"key": key, "title": title, "status": "MISSING"})
        proof = proofs.get(key, {}) if key in gates else {}
        reported = _status(gate.get("status"))
        decision = _decision(reported, proof)
        policy_status = measured.get(key, {}).get("status")
        if (
            key in {"coverage", "duplication"}
            and policy_status in {"FAIL", "INVALID"}
            and decision in {"PASS", "INCOMPLETE", "UNKNOWN", "MISSING", "UNAVAILABLE"}
        ):
            decision = policy_status
        rows.append(
            {
                "key": key,
                "title": gate.get("title") or title,
                "reported_decision": reported,
                "decision": decision,
                "policy": _policy(document, gate),
                "observed": _observed(document, key, proof),
                "proof": "VERIFIED"
                if proof.get("verified") is True
                else "UNVERIFIED"
                if proof
                else "MISSING",
                "proof_reason": proof.get("reason")
                or "Current execution proof unavailable.",
                "receipt_status": proof.get("receipt", {}).get("status"),
                "exit_code": proof.get("receipt", {}).get("exit_code"),
                "sources": copy.deepcopy(proof.get("sources", [])),
            }
        )
    metric, evaluation, mutation_refs = view.aggregate(document, primary_series=primary)
    verified = bool(evaluation.get("counts") and mutation_refs)
    floor = metric["threshold"]
    rows.append(
        {
            "key": "mutation",
            "title": "Mutation",
            "reported_decision": metric["status"],
            "decision": metric["status"],
            "policy": f"Complete accounting; aggregate minimum {floor:g}%; {document.get('mutation_policy', {}).get('profile')} profile"
            if floor is not None
            else "Aggregate policy unavailable.",
            "observed": f"{view.load('quality_dashboard').value_text(metric['measured'])} · {evaluation['counts']['killed']} killed / {evaluation['counts']['total']} total · {evaluation['unresolved']} unresolved"
            if evaluation.get("counts")
            else metric["detail"],
            "proof": "VERIFIED" if verified else "UNVERIFIED",
            "proof_reason": metric["detail"],
            "receipt_status": evaluation.get("status"),
            "exit_code": None,
            "sources": mutation_refs,
        }
    )
    refs = view.sources(*(row["sources"] for row in rows if row["proof"] == "VERIFIED"))
    verified_count = sum(row["proof"] == "VERIFIED" for row in rows)
    known_statuses = all(
        row["decision"] not in {"UNKNOWN", "MISSING", "UNAVAILABLE"} for row in rows
    )
    required = (*view.load("check_ci_readiness").MANDATORY_JOBS, "ci-readiness")
    series.update(
        rows=rows,
        required_jobs={
            key: document.get("jobs", {}).get(key, "unknown") for key in required
        },
        counts=dict(Counter(row["decision"] for row in rows)),
        verified_proofs=verified_count,
        total=len(rows),
        state="MEASURED"
        if verified_count == len(rows) and known_statuses
        else "PARTIAL"
        if verified_count
        else "UNAVAILABLE",
        reason="Categorical enforcement outcomes; execution proof completeness is separate from pass counts.",
        sources=refs,
        source_fingerprint=view.fingerprint(refs),
        decision_grain="categorical; no percent score",
    )
    return series


def validate_frozen_series(series: dict, document: dict) -> bool:
    """Bind frozen decisions to the saved document without reloading live policy."""
    try:
        return _validate_frozen_series(series, document)
    except (KeyError, TypeError, AttributeError) as exc:
        raise ValueError("Frozen gate decisions have an invalid shape") from exc


def _validate_frozen_series(series: dict, document: dict) -> bool:
    view = _view()
    view._check_context(series, document, "gate_decisions")
    rows = series["rows"]
    keys = [row["key"] for row in rows]
    gates = {row["key"]: row for row in document.get("gates", [])}
    if (
        not isinstance(rows, list)
        or not rows
        or len(keys) != len(set(keys))
        or set(keys) != GATE_KEYS_V1
    ):
        raise ValueError("Frozen gate population does not cover captured decisions")
    for row in rows:
        _validate_decision_row(row, document, gates)
    verified = sum(row["proof"] == "VERIFIED" for row in rows)
    known = all(
        row["decision"] not in {"UNKNOWN", "MISSING", "UNAVAILABLE"} for row in rows
    )
    state = (
        "MEASURED"
        if verified == len(rows) and known
        else "PARTIAL"
        if verified
        else "UNAVAILABLE"
    )
    if (
        series.get("counts") != dict(Counter(row["decision"] for row in rows))
        or any(type(count) is not int for count in series["counts"].values())
        or type(series.get("total")) is not int
        or series["total"] != len(rows)
        or type(series.get("verified_proofs")) is not int
        or series["verified_proofs"] != verified
        or series.get("state") != state
        or series.get("sources")
        != view.sources(*(row["sources"] for row in rows if row["proof"] == "VERIFIED"))
        or series.get("decision_grain") != "categorical; no percent score"
    ):
        raise ValueError("Frozen gate summary disagrees with its captured decisions")
    jobs = series["required_jobs"]
    if (
        not isinstance(jobs, dict)
        or set(jobs) != set(REQUIRED_JOBS_V1)
        or any(
            value != document.get("jobs", {}).get(key, "unknown")
            for key, value in jobs.items()
        )
    ):
        raise ValueError(
            "Frozen gate required-job evidence disagrees with its document"
        )
    return True


def _validate_decision_row(row: dict, document: dict, gates: dict) -> None:
    if any(
        not isinstance(row.get(key), str)
        for key in ("title", "policy", "observed", "proof_reason")
    ):
        raise ValueError("Frozen gate labels have an invalid shape")
    key = row["key"]
    if key == "mutation":
        _validate_mutation_decision(row, document)
        return
    gate = gates.get(key, {"status": "MISSING"})
    proof = (
        document.get("measurement_evidence", {}).get("gates", {}).get(key, {})
        if key in gates
        else {}
    )
    receipt = proof.get("receipt", {})
    reported = _status(gate.get("status"))
    decision = _decision(reported, proof)
    if (
        key in {"coverage", "duplication"}
        and _captured_limit_failed(document, key)
        and decision in {"PASS", "INCOMPLETE", "UNKNOWN", "MISSING", "UNAVAILABLE"}
    ):
        decision = "FAIL"
    if (
        row.get("reported_decision") != reported
        or row.get("decision") != decision
        or row.get("proof")
        != (
            "VERIFIED"
            if proof.get("verified") is True
            else "UNVERIFIED"
            if proof
            else "MISSING"
        )
        or row.get("receipt_status") != receipt.get("status")
        or row.get("exit_code") != receipt.get("exit_code")
        or type(row.get("exit_code")) is not type(receipt.get("exit_code"))
        or row.get("sources") != proof.get("sources", [])
    ):
        raise ValueError(
            "Frozen gate decision or proof disagrees with its captured receipt"
        )


def _captured_limit_failed(document: dict, key: str) -> bool:
    observation = next(
        (
            row
            for row in document.get("measurement_evidence", {}).get("metrics", [])
            if row.get("key") == key
        ),
        {},
    )
    percentage = _view().load("quality_dashboard").percentage
    value = percentage(observation.get("number"))
    values = document.get("series", {}).get(key, {})
    limit = percentage(values.get("floor" if key == "coverage" else "ceiling"))
    if (
        observation.get("state") not in {"MEASURED", "PARTIAL"}
        or value is None
        or limit is None
    ):
        return False
    precision = document.get("coverage_precision")
    compared = (
        round(value, precision)
        if key == "coverage" and type(precision) is int and 0 <= precision <= 9
        else value
    )
    return (
        (compared < limit or (limit == 100 and value != 100))
        if key == "coverage"
        else value > limit
    )


def _validate_mutation_decision(row: dict, document: dict) -> None:
    view = _view()
    evaluation, refs = view._aggregate_accounting(document)
    if evaluation.get("status") not in {"PASS", "FAIL", "INCOMPLETE"}:
        evaluation = {}
    saved = document.get("series", {}).get("mutation_scopes", {}).get("aggregate", {})
    expected = saved.get("status") or evaluation.get("status")
    decision = row.get("decision")
    if (
        row.get("reported_decision") != decision
        or (expected is not None and decision != expected)
        or (
            expected is None
            and decision not in {"UNAVAILABLE", "INVALID", "INCOMPLETE"}
        )
        or row.get("proof")
        != ("VERIFIED" if evaluation.get("counts") and refs else "UNVERIFIED")
        or row.get("receipt_status") != evaluation.get("status")
        or row.get("exit_code") is not None
        or row.get("sources") != refs
    ):
        raise ValueError(
            "Frozen mutation decision disagrees with its captured outcomes"
        )


def write_gate_indexes(series: dict, directory: Path) -> dict:
    shared = _view().load("coupling_dashboard")
    lines = shared.index_header(series, "AVO gate decisions: complete policy and proof")
    lines += [
        "",
        f"{series['verified_proofs']}/{series['total']} execution proofs verified. Decision counts: {shared.safe_text(str(series['counts']))}.",
        "Equal decision badges are categories, not quality percentages. Accepted debt and report-only findings remain explicit.",
        "",
        "| Gate | Decision | Reported decision | Existing policy | Observed evidence | Proof | Evidence sources |",
        "|---|---|---|---|---|---|---|",
    ]
    for row in series["rows"]:
        refs = "; ".join(
            f"{item.get('artifact')}/{item.get('path')} (SHA-256 {item.get('sha256')})"
            for item in row["sources"]
        )
        cells = [
            row["title"],
            row["decision"],
            row["reported_decision"],
            row["policy"],
            row["observed"],
            row["proof"] + ": " + row["proof_reason"],
            refs or "Unavailable",
        ]
        lines.append("| " + " | ".join(shared.safe_text(cell) for cell in cells) + " |")
    lines += [
        "",
        "## Required CI execution (separate population)",
        "",
        "| Required job | Result |",
        "|---|---|",
    ]
    lines.extend(
        f"| {shared.safe_text(key)} | {shared.safe_text(value)} |"
        for key, value in series["required_jobs"].items()
    )
    return shared.write_indexes(series, directory, "gate-decisions", lines)


def _color(status: str) -> str:
    view = _view()
    return (
        view.GREEN
        if status == "PASS"
        else view.RED
        if status in {"FAIL", "ERROR", "INVALID"}
        else view.AMBER
        if status in {"INCOMPLETE", "TIMEOUT", "CANCELED"}
        else view.MUTED
    )


def _wrapped(value: str, width: int = 94, lines: int = 2) -> str:
    plain = re.sub(r"[*`]", "", value).replace("\n", " ")
    wrapped = textwrap.wrap(plain, width=width, break_long_words=True) or [
        "Unavailable"
    ]
    shown = wrapped[:lines]
    if len(wrapped) > lines:
        shown[-1] = shown[-1][:-1] + "…"
    return "\n".join(shown)


def render_gates(series: dict, path: Path) -> None:
    path.unlink(missing_ok=True)
    view = _view()
    height = 11.6
    fig, ax = view.canvas(
        "Gate decisions",
        "Enforcement outcomes with the recorded rule and execution evidence",
        height,
        series,
    )
    passed = series["counts"].get("PASS", 0)
    color = (
        view.GREEN
        if passed == series["total"] and series["verified_proofs"] == series["total"]
        else view.AMBER
    )
    view.box(
        ax,
        0.045,
        height - 2.05,
        0.87,
        0.50,
        "#e8f3ed" if color == view.GREEN else "#fff3cf",
    )
    ax.text(
        0.061, height - 1.86, f"{passed} PASS", fontsize=17, weight="bold", color=color
    )
    summary = (
        " · ".join(
            f"{value} {key}" for key, value in series["counts"].items() if key != "PASS"
        )
        or "0 other decisions"
    )
    ax.text(
        0.23,
        height - 1.86,
        view.short(summary, 85)
        + f" · {series['total'] - series['verified_proofs']} missing/unverified proofs",
        fontsize=10,
        color=view.INK,
    )
    ax.text(
        0.045,
        height - 2.36,
        "9 software-quality checks + aggregate mutation · equal categorical badges",
        fontsize=10.5,
        color=view.MUTED,
    )
    for index, row in enumerate(series["rows"]):
        y = height - 3.07 - index * 0.73
        view.box(ax, 0.045, y - 0.19, 0.87, 0.70, "#ffffff", view.LINE)
        ax.text(
            0.059,
            y + 0.15,
            view.short(row["title"], 24),
            fontsize=11.4,
            weight="bold",
            color=view.INK,
        )
        view.box(ax, 0.216, y + 0.02, 0.096, 0.28, _color(row["decision"]))
        ax.text(
            0.264,
            y + 0.16,
            row["decision"],
            fontsize=8.5,
            weight="bold",
            color="white",
            ha="center",
            va="center",
        )
        ax.text(
            0.327,
            y + 0.33,
            _wrapped(row["policy"], 88, 2),
            fontsize=9.5,
            weight="bold",
            va="top",
            color=view.INK,
            linespacing=1.15,
        )
        ax.text(
            0.327,
            y - 0.035,
            _wrapped(row["observed"], 100, 1),
            fontsize=9.1,
            color=view.MUTED,
            va="top",
        )
        ax.text(
            0.902,
            y + 0.16,
            "PROOF\n" + row["proof"],
            fontsize=7.8,
            color=view.GREEN if row["proof"] == "VERIFIED" else view.AMBER,
            ha="right",
            va="center",
            linespacing=1.35,
        )
    view.box(ax, 0.045, 1.14, 0.87, 0.44, "#fff3cf")
    ax.text(
        0.059,
        1.30,
        "PASS follows existing policy. Accepted debt and report-only findings remain visible.",
        fontsize=10,
        color=view.AMBER,
    )
    successes = sum(value == "success" for value in series["required_jobs"].values())
    ax.text(
        0.045,
        0.81,
        f"Required CI execution: {successes}/{len(series['required_jobs'])} successful jobs · listed separately in the full text companion.",
        fontsize=10.3,
        weight="bold",
        color=view.INK,
    )
    ax.text(
        0.045,
        0.45,
        "Policy/value excerpts above; full rules, states, proof paths and SHA-256: gate-decisions.md / .json",
        fontsize=9.2,
        color=view.MUTED,
    )
    ax.text(
        0.045,
        0.18,
        "Badge meaning: categorical decision, not a quality percentage. Missing proof never becomes verified PASS.",
        fontsize=9.2,
        color=view.MUTED,
    )
    view.save(fig, path, series)
