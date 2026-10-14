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
    if status not in {"PASS", "FAIL"}:
        measured = None
    elif measured is None or threshold is None:
        status = "UNAVAILABLE"
    elif measured < threshold if direction == "minimum" else measured > threshold:
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
    statuses = [row["status"] for row in metrics]
    failed = doc.get("overall") == "FAIL" or "FAIL" in statuses or "INVALID" in statuses
    failed = failed or any(row["status"] == "FAIL" for row in doc.get("gates", []))
    failed = failed or any(
        result in {"failure", "cancelled"} for result in jobs.values()
    )
    incomplete = bool(actions) or any(status != "PASS" for status in statuses)
    overall = "FAIL" if failed else "INCOMPLETE" if incomplete else "PASS"
    return {
        "chart": "dashboard",
        "overall": overall,
        "sha": doc.get("sha", ""),
        "run_id": str(doc.get("run_id") or ""),
        "metrics": metrics,
        "actions": list(dict.fromkeys(actions)),
    }


def value_text(value: object) -> str:
    return "Unavailable" if value is None else f"{float(value):.2f}%"


def safe_text(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


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
        lines.extend(["All reported mandatory checks and measurements passed.", ""])
    if image:
        lines.extend([f"![Quality dashboard]({image})", ""])
    lines.extend(
        ["| Metric | Measured | Threshold | Status | Scope |", "|---|---:|---|---|---|"]
    )
    for metric in series["metrics"]:
        direction = "Minimum" if metric["direction"] == "minimum" else "Maximum"
        threshold = (
            "Unavailable"
            if metric["threshold"] is None
            else f"{direction} {metric['threshold']:g}%"
        )
        lines.append(
            f"| {metric['title']} | {value_text(metric['measured'])} | {threshold} | **{metric['status']}** | {safe_text(metric['scope'])} |"
        )
    lines.extend(
        [
            "",
            "<details>",
            "<summary>Gate diagnostics and artifacts</summary>",
            "",
            "| Gate | Status | Evidence |",
            "|---|---|---|",
        ]
    )
    for gate in doc.get("gates", []):
        lines.append(
            f"| {safe_text(gate['title'])} | **{gate['status']}** | {safe_text(gate.get('metric', 'Unavailable'))} |"
        )
    for job, result in doc.get("jobs", {}).items():
        lines.append(f"| {safe_text(job)} | **{result.upper()}** | Required CI job |")
    lines.extend(
        [
            "",
            "Exception and contract counts describe configuration, not a quality score.",
            "",
        ]
    )
    run_url = doc.get("run_url", "")
    if run_url.startswith("https://github.com/"):
        lines.append(f"[Run logs and downloadable artifacts]({run_url})")
    lines.extend(["", "</details>", ""])
    return "\n".join(lines)


def render(series: dict, path: Path) -> dict:
    os.environ.setdefault("MPLBACKEND", "Agg")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(3, 1, figsize=(5.8, 6.4), dpi=160)
    fig.patch.set_facecolor("#f8fafc")
    fig.suptitle(
        f"AVO quality  ·  {series['overall']}",
        x=0.08,
        ha="left",
        fontsize=21,
        fontweight="bold",
        color=COLORS.get(series["overall"], MUTED),
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
        color = COLORS.get(metric["status"], MUTED)
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
            metric["status"],
            transform=ax.transAxes,
            ha="right",
            fontsize=13,
            fontweight="bold",
            color=color,
        )
        ax.text(
            0,
            0.6,
            value_text(measured),
            transform=ax.transAxes,
            fontsize=25,
            fontweight="bold",
            color=color,
        )
        ax.barh(0, limit, color="#e4e7ec", height=0.13)
        if measured is not None:
            ax.barh(0, measured, color=color, height=0.13)
        if threshold is not None:
            ax.vlines(threshold, -0.14, 0.14, color="#344054", linewidth=2)
        direction = "Minimum" if metric["direction"] == "minimum" else "Maximum"
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
    fig.subplots_adjust(left=0.08, right=0.92, top=0.84, bottom=0.08, hspace=0.42)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(
        path,
        metadata={"Description": json.dumps(series, sort_keys=True)},
        facecolor=fig.get_facecolor(),
    )
    plt.close(fig)
    return series
