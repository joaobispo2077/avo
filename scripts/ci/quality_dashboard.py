"""One evidence-bound quality overview shared by CI and release readouts."""

from __future__ import annotations

import importlib.util
import json
import math
import os
import sys
from pathlib import Path

COLORS = {"PASS": "#18794e", "FAIL": "#b42318"}
MUTED = "#667085"
BAND_COLORS = {"red": "#b42318", "yellow": "#f0b400", "green": "#18794e"}


def ci_module(name: str, filename: str):
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(
            name, Path(__file__).with_name(filename)
        )
        if spec is None or spec.loader is None:
            raise RuntimeError(f"CI helper is unavailable: {filename}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return sys.modules[name]


def mutation_checker():
    return ci_module("avo_ci_check_mutation", "check_mutation.py")


def percentage(value: object) -> float | None:
    if type(value) not in (int, float):
        return None
    value = float(value)
    return value if math.isfinite(value) and 0 <= value <= 100 else None


def threshold_band(metric: dict) -> str:
    """Show raw measurement margin without changing the gate's decision policy."""
    measured = percentage(metric.get("measured"))
    threshold = percentage(metric.get("threshold"))
    if measured is None or threshold is None:
        return "unknown"
    if metric.get("direction") == "minimum":
        if measured < threshold:
            return "red"
        return "yellow" if measured < threshold + 0.25 * (100 - threshold) else "green"
    if metric.get("direction") == "maximum":
        if measured > threshold:
            return "red"
        return "yellow" if measured > 0.75 * threshold else "green"
    return "unknown"


def mutation_metric(doc: dict) -> dict:
    payload = doc.get("mutation")
    policy = doc.get("mutation_policy")
    metric = {
        "title": "Mutation",
        "measured": None,
        "threshold": None,
        "direction": "minimum",
        "scope": "light profile; selected Python modules",
        "status": "UNAVAILABLE",
        "detail": "No complete mutation evidence for this commit and run.",
    }
    if isinstance(policy, dict):
        metric["threshold"] = percentage(policy.get("floor"))
        metric["scope"] = (
            f"{policy.get('profile') or 'unspecified'} profile; selected Python modules"
        )
    if not isinstance(payload, dict):
        return metric
    run_id = str(doc.get("run_id") or "")
    if (
        not doc.get("sha")
        or payload.get("sha") != doc["sha"]
        or not run_id
        or str(payload.get("run_id") or "") != run_id
    ):
        metric["detail"] = "Mutation evidence belongs to another commit or run."
        return metric
    if (
        not isinstance(policy, dict)
        or policy.get("profile") not in {"light", "full"}
        or payload.get("profile") != policy["profile"]
        or percentage(policy.get("floor")) is None
        or payload.get("floor") != policy["floor"]
    ):
        metric["detail"] = (
            "Mutation profile or threshold does not match this run's policy."
        )
        return metric
    floor = percentage(payload.get("floor"))
    if floor is None:
        metric["detail"] = "Mutation threshold is invalid."
        return metric
    evaluation = mutation_checker().mutation_evaluation(
        payload.get("counts", payload), min_killed_percent=floor
    )
    metric.update(
        measured=evaluation["score"] if evaluation["complete"] else None,
        threshold=floor,
        status=evaluation["status"],
        scope=f"{payload.get('profile') or 'unspecified'} profile; selected Python modules",
        detail=evaluation["reason"],
    )
    return metric


def measured_metric(doc: dict, key: str, title: str, direction: str, scope: str):
    data = doc.get("series", {}).get(key, {})
    gate = next((row for row in doc.get("gates", []) if row["key"] == key), {})
    status = gate.get("status", "UNKNOWN")
    threshold = percentage(data.get("floor" if direction == "minimum" else "ceiling"))
    measured = percentage(data.get("measured"))
    evidence = doc.get("measurement_evidence")
    if isinstance(evidence, dict):
        observation = next(
            (row for row in evidence.get("metrics", []) if row.get("key") == key), {}
        )
        measured = percentage(observation.get("number"))
        if observation.get("state") not in {"MEASURED", "PARTIAL"}:
            measured = None
    if status not in {"PASS", "FAIL"}:
        measured = None
    elif measured is None or threshold is None:
        status = "UNAVAILABLE"
    else:
        precision = doc.get("coverage_precision")
        compared = (
            round(measured, precision)
            if key == "coverage" and type(precision) is int and 0 <= precision <= 9
            else measured
        )
        violates = (
            compared < threshold if direction == "minimum" else compared > threshold
        )
        if key == "coverage" and threshold == 100 and measured != 100:
            violates = True
        if violates:
            status = "FAIL"
    return {
        "title": title,
        "measured": measured,
        "threshold": threshold,
        "direction": direction,
        "scope": scope,
        "status": status,
        "detail": gate.get("metric", ""),
    }


def build_series(doc: dict) -> dict:
    metrics = [
        measured_metric(
            doc, "coverage", "Coverage", "minimum", "unit-suite line coverage; src/avo"
        ),
        measured_metric(
            doc,
            "duplication",
            "Duplication",
            "maximum",
            "duplicated source lines; src/avo",
        ),
        mutation_metric(doc),
    ]
    evidence = doc.get("measurement_evidence")
    if isinstance(evidence, dict):
        observation = next(
            (
                row
                for row in evidence.get("metrics", [])
                if row.get("key") == "mutation"
            ),
            {},
        )
        actual = metrics[-1]
        number = (
            percentage(observation.get("number"))
            if observation.get("state") in {"MEASURED", "PARTIAL"}
            and observation.get("unit") == "percent"
            else None
        )
        if number is None:
            actual.update(
                measured=None,
                status="UNAVAILABLE",
                detail=observation.get("basis", "Mutation input proof is unavailable."),
            )
        elif number != actual["measured"]:
            actual.update(
                measured=None,
                status="INVALID",
                detail="Mutation display does not match validated outcome counters.",
            )
    for metric in metrics:
        metric["band"] = threshold_band(metric)
    actions = [
        f"{row['title']}: {row['status']}. {row.get('metric') or 'Inspect this gate in the run logs.'}"
        for row in doc.get("gates", [])
        if row["status"] != "PASS"
    ]
    actions.extend(
        f"{row['title']}: {row['status']}. {row['detail'] or 'Inspect measurement evidence and the configured threshold.'}"
        for row in metrics
        if row["status"] != "PASS"
    )
    raw_jobs = doc.get("jobs", {})
    names = ci_module("avo_ci_readiness", "check_ci_readiness.py").MANDATORY_JOBS
    jobs = {name: raw_jobs.get(name, "unknown") for name in (*names, "ci-readiness")}
    actions.extend(
        f"{name}: {result}. Inspect the required job."
        for name, result in jobs.items()
        if result != "success"
    )
    executions = doc.get("test_evidence", {})
    actions.extend(
        f"{name}: partial test evidence. {execution.get('reason', '')}"
        for name, execution in executions.items()
        if execution.get("state") == "PARTIAL"
    )
    evidence = doc.get("measurement_evidence")
    if isinstance(evidence, dict):
        actions.extend(
            f"{gate['title']}: execution proof unavailable. {evidence.get('gates', {}).get(gate['key'], {}).get('reason', 'No current-run capture log.')}"
            for gate in doc.get("gates", [])
            if gate["status"] == "PASS"
            and not evidence.get("gates", {}).get(gate["key"], {}).get("verified")
        )
    statuses = [row["status"] for row in metrics]
    failed = doc.get("overall") == "FAIL" or "FAIL" in statuses or "INVALID" in statuses
    failed = failed or any(row["status"] == "FAIL" for row in doc.get("gates", []))
    failed = failed or any(
        result in {"failure", "cancelled"} for result in jobs.values()
    )
    failed = failed or any(
        execution.get("counts")
        and (execution["counts"]["failed"] or execution["counts"]["errors"])
        for execution in executions.values()
    )
    incomplete = bool(actions) or any(status != "PASS" for status in statuses)
    overall = "FAIL" if failed else "INCOMPLETE" if incomplete else "PASS"
    series = {
        "chart": "dashboard",
        "overall": overall,
        "sha": doc.get("sha", ""),
        "run_id": str(doc.get("run_id") or ""),
        "metrics": metrics,
        "actions": list(dict.fromkeys(actions)),
    }
    if isinstance(evidence, dict):
        for metric in metrics:
            key = metric["title"].lower()
            observation = next(
                (row for row in evidence.get("metrics", []) if row.get("key") == key),
                {},
            )
            metric["measurement_state"] = observation.get("state", "UNAVAILABLE")
        series["presentation"] = "measurements"
        series["measurements"] = evidence.get("metrics", [])
    return series


def value_text(value: object) -> str:
    return "Unavailable" if value is None else f"{float(value):.2f}%"


def safe_text(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def evidence_links(doc: dict, sources: list[dict]) -> str:
    urls = doc.get("artifact_urls", {})
    links = []
    for source in sources:
        name = source.get("path", "Unavailable")
        url = urls.get(source.get("artifact", ""), "")
        label = f"[{safe_text(name)}]({url})" if url else f"`{safe_text(name)}`"
        digest = source.get("sha256")
        if digest:
            label += f" (SHA-256 `{digest[:12]}`)"
        links.append(label)
    return "; ".join(links) or "Not captured"


def source_link(doc: dict, path: str, line: int, name: str = "") -> str:
    repository = doc.get("repository", "")
    label = safe_text(name or f"{path}:{line}")
    if (
        repository
        and len(str(doc.get("sha", ""))) == 40
        and path.startswith("src/avo/")
        and ".." not in path.split("/")
    ):
        return f"[{label}](https://github.com/{repository}/blob/{doc['sha']}/{path}#L{line})"
    return f"`{label}`"


def measurement_rows(doc: dict, series: dict) -> list[dict]:
    if "measurements" in series:
        return series["measurements"]
    return [
        {
            "key": metric["title"].lower(),
            "title": metric["title"],
            "value": value_text(metric["measured"]),
            "scope": metric["scope"],
            "state": "MEASURED" if metric["measured"] is not None else "UNAVAILABLE",
            "basis": "Historical summary; raw-input capture is unavailable.",
            "sources": [],
        }
        for metric in series["metrics"]
    ]


def markdown(doc: dict, series: dict, *, image: str = "") -> str:
    lines = [
        "## AVO quality",
        "",
        f"**Overall: {series['overall']}**",
        "",
        f"Commit: `{series['sha'] or 'unavailable'}` · Run: `{series['run_id'] or 'unavailable'}`",
        "",
    ]
    if series["actions"]:
        lines.extend(["**Required action**", ""])
        lines.extend(f"- {safe_text(item)}" for item in series["actions"])
        lines.append("")
    else:
        lines.extend(["All mandatory gate decisions and required jobs passed.", ""])
    if image:
        lines.extend([f"![Quality dashboard]({image})", ""])
    observations = measurement_rows(doc, series)
    measured = sum(row.get("state") == "MEASURED" for row in observations)
    partial = sum(row.get("state") == "PARTIAL" for row in observations)
    missing = len(observations) - measured - partial
    lines.extend(
        [
            "**Measurements**",
            "",
            f"Evidence completeness: {measured} measured, {partial} partial, {missing} unavailable. Gate decisions are below.",
            "",
            "| Metric | Measured | Scope | Evidence |",
            "|---|---|---|---|",
        ]
    )
    for metric in observations:
        suffix = " (partial)" if metric.get("state") == "PARTIAL" else ""
        lines.append(
            f"| {safe_text(metric['title'])} | {safe_text(metric['value'])}{suffix} | {safe_text(metric['scope'])} | {safe_text(metric['basis'])} {evidence_links(doc, metric.get('sources', []))} |"
        )
    evidence = doc.get("measurement_evidence", {})
    policy = ci_module(
        "avo_ci_write_quality_pr_report", "write_quality_pr_report.py"
    ).GATE_POLICY
    lines.extend(
        [
            "",
            "**Gate decisions**",
            "",
            "| Gate | Decision | Policy | Execution evidence |",
            "|---|---|---|---|",
        ]
    )
    for gate in doc.get("gates", []):
        proof = evidence.get("gates", {}).get(gate["key"], {})
        checks = gate.get("checks") or policy.get(gate["key"], "Unavailable")
        if gate["key"] in {"coverage", "duplication"}:
            metric = next(
                row for row in series["metrics"] if row["title"].lower() == gate["key"]
            )
            if metric["threshold"] is not None:
                checks += f"; {'Minimum' if gate['key'] == 'coverage' else 'Maximum'} {metric['threshold']:g}%"
                if gate["key"] == "coverage" and "coverage_precision" in doc:
                    checks += f"; comparison rounded to {doc['coverage_precision']} decimal places"
        links = evidence_links(doc, proof.get("sources", []))
        if not proof.get("verified"):
            links = f"Unverified capture: {safe_text(proof.get('reason', 'Historical execution summary only.'))}"
        lines.append(
            f"| {safe_text(gate['title'])} | **{gate['status']}** | {safe_text(checks)} | {links} |"
        )
    mutation = next(row for row in series["metrics"] if row["title"] == "Mutation")
    mutation_proof = next((row for row in observations if row["key"] == "mutation"), {})
    threshold = (
        f"Minimum {mutation['threshold']:g}%"
        if mutation["threshold"] is not None
        else "threshold unavailable"
    )
    lines.append(
        f"| Mutation | **{mutation['status']}** | Complete accounting; {threshold}; {safe_text(mutation['scope'])} | {evidence_links(doc, mutation_proof.get('sources', []))} |"
    )
    lines.extend(
        [
            "",
            "<details>",
            "<summary>Execution results</summary>",
            "",
            "| Required job | Result | Test evidence |",
            "|---|---|---|",
        ]
    )
    for job, result in doc.get("jobs", {}).items():
        execution = doc.get("test_evidence", {}).get(job, {})
        counts = execution.get("counts")
        detail = "Job result; testcase counts not captured."
        if isinstance(counts, dict):
            detail = f"{counts['passed']} passed / {counts['failed']} failed / {counts['errors']} errors / {counts['skipped']} skipped; {counts['total']} JUnit testcases."
        if execution:
            detail += f" {execution.get('state', 'UNAVAILABLE')}: {safe_text(execution.get('reason', ''))}"
        lines.append(
            f"| {safe_text(job)} | **{result.upper()}** | {detail} {evidence_links(doc, execution.get('sources', []))} |"
        )
    lines.extend(
        [
            "",
            "Successful execution is not a measured quality score. Uncaptured counts remain unavailable.",
            "",
        ]
    )
    run_url = doc.get("run_url", "")
    if run_url.startswith("https://github.com/"):
        lines.append(f"[Run logs and downloadable artifacts]({run_url})")
    lines.extend(
        [
            "",
            "</details>",
            "",
            "<details>",
            "<summary>Metric diagnostics and artifacts</summary>",
            "",
        ]
    )
    risk = evidence.get("diagnostics", {}).get("code_risk", {})
    crap_observation = next((row for row in observations if row["key"] == "crap"), {})
    verified_crap = crap_observation.get("state") in {"MEASURED", "PARTIAL"}
    functions = sorted(
        (
            row
            for row in risk.get("functions", [])
            if verified_crap and row.get("crap", {}).get("value") is not None
        ),
        key=lambda row: row["crap"]["value"],
        reverse=True,
    )
    if functions:
        lines.extend(
            [
                "CRAP reference 30 is informational. These are the highest observed function scores; unmatched functions remain unmeasured.",
                "",
                "| Function | CC | Function line coverage | CRAP |",
                "|---|---:|---:|---:|",
            ]
        )
        for row in functions[:10]:
            label = f"{row['path']}:{row['line']} {row['qualname']}"
            lines.append(
                f"| {source_link(doc, row['path'], row['line'], label)} | {row['complexity']} | {row['function_coverage']['percent']:.2f}% | {row['crap']['value']:.2f} |"
            )
        lines.append("")
    packages = sorted(
        risk.get("coupling", {}).get("packages", []),
        key=lambda row: row.get("ca", 0) + row.get("ce", 0),
        reverse=True,
    )
    if packages:
        lines.extend(
            [
                "Static package coupling is a review signal. Intra-package and dynamic imports are not measured; no quadrant cutoffs or abstractness score are adopted.",
                "",
                "| Package | CA (used by) | CE (depends on) | Instability |",
                "|---|---:|---:|---:|",
            ]
        )
        for row in packages[:10]:
            instability = (
                "Undefined (no edges)"
                if row.get("instability") is None
                else f"{row['instability']:.3f}"
            )
            lines.append(
                f"| `{safe_text(row['package'])}` | {row['ca']} | {row['ce']} | {instability} |"
            )
        lines.append("")
    if "measurement_evidence" not in doc:
        lines.extend(
            [
                "Historical recorded summaries predate raw-input capture. These values are preserved as legacy diagnostics, including configuration counts.",
                "",
                "| Recorded field | Legacy value |",
                "|---|---|",
            ]
        )
        lines.extend(
            f"| {safe_text(row['title'])} | {safe_text(row.get('metric', 'Unavailable'))} |"
            for row in doc.get("gates", [])
        )
        lines.append("")
    lines.extend(
        [
            "Exception lists and contract definitions are configuration. Observed findings, source locations, waiver reasons, full function tables, raw audits and capture logs are retained in the linked artifacts.",
            "",
            "</details>",
            "",
        ]
    )
    return "\n".join(lines)


def render(series: dict, path: Path) -> dict:
    os.environ.setdefault("MPLBACKEND", "Agg")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(3, 1, figsize=(5.8, 6.4), dpi=160)
    fig.patch.set_facecolor("#f8fafc")
    measurements_view = series.get("presentation") == "measurements"
    fig.suptitle(
        "AVO measurements"
        if measurements_view
        else f"AVO quality  ·  {series['overall']}",
        x=0.08,
        ha="left",
        fontsize=21,
        fontweight="bold",
        color="#101828" if measurements_view else COLORS.get(series["overall"], MUTED),
    )
    fig.text(
        0.08,
        0.91,
        f"Commit {series['sha'][:10] or 'unavailable'}  ·  Run {series['run_id'] or 'unavailable'}",
        fontsize=12,
        color=MUTED,
    )
    for ax, metric in zip(axes, series["metrics"], strict=True):
        measured, threshold = metric["measured"], metric["threshold"]
        band = metric.get("band", threshold_band(metric))
        color = BAND_COLORS.get(band, MUTED)
        text_color = "#855d00" if band == "yellow" else color
        direction = "Minimum" if metric["direction"] == "minimum" else "Maximum"
        margin = {
            "red": "Below minimum"
            if metric["direction"] == "minimum"
            else "Above maximum",
            "yellow": f"Near {direction.lower()}",
            "green": "Clear margin",
            "unknown": "Unavailable" if measured is None else "Threshold unavailable",
        }.get(band, "Unavailable")
        limit = (
            100
            if metric["direction"] == "minimum"
            else max(3, (threshold or 0) * 1.5, (measured or 0) * 1.15)
        )
        ax.set_xlim(0, limit)
        ax.set_ylim(-0.55, 0.8)
        ax.set_facecolor("#f8fafc")
        ax.axis("off")
        ax.text(
            0,
            0.94,
            metric["title"],
            transform=ax.transAxes,
            fontsize=16,
            fontweight="bold",
            color="#101828",
        )
        ax.text(
            1,
            0.94,
            metric.get("measurement_state", "UNAVAILABLE")
            if measurements_view
            else metric["status"],
            transform=ax.transAxes,
            ha="right",
            fontsize=13,
            fontweight="bold",
            color=MUTED if measurements_view else COLORS.get(metric["status"], MUTED),
        )
        ax.text(
            0,
            0.6,
            value_text(measured),
            transform=ax.transAxes,
            fontsize=25,
            fontweight="bold",
            color=text_color,
        )
        ax.text(
            1,
            0.6,
            margin,
            transform=ax.transAxes,
            ha="right",
            fontsize=12,
            fontweight="bold",
            color=text_color,
        )
        ax.barh(0, limit, color="#e4e7ec", height=0.13)
        if measured is not None:
            ax.barh(0, measured, color=color, height=0.13)
        if threshold is not None:
            ax.vlines(threshold, -0.14, 0.14, color="#344054", linewidth=2)
        target = (
            "Threshold unavailable"
            if threshold is None
            else f"{direction} {threshold:g}%"
        )
        ax.text(0, 0.08, target, transform=ax.transAxes, fontsize=13, color="#344054")
        ax.text(
            1,
            0.08,
            f"Scale: 0 to {limit:g}%",
            transform=ax.transAxes,
            ha="right",
            fontsize=12,
            color=MUTED,
        )
        ax.text(
            0, -0.08, metric["scope"], transform=ax.transAxes, fontsize=13, color=MUTED
        )
    fig.text(
        0.08,
        0.055,
        "Red: outside threshold · Yellow: near · Green: clear margin",
        fontsize=10,
        color="#344054",
    )
    fig.text(
        0.08,
        0.025,
        "Colors compare raw values; gate decisions remain separate.",
        fontsize=9,
        color=MUTED,
    )
    fig.subplots_adjust(left=0.08, right=0.92, top=0.84, bottom=0.13, hspace=0.42)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(
        path,
        metadata={"Description": json.dumps(series, sort_keys=True)},
        facecolor=fig.get_facecolor(),
    )
    plt.close(fig)
    return series
