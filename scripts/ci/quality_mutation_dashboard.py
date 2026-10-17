"""Evidence-bound aggregate and informational per-source mutation graphics."""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import math
import os
import re
import sys
from pathlib import Path

GREEN, RED, AMBER = "#18794e", "#b42318", "#8a5700"
INK, MUTED, BG, LINE = "#182230", "#475467", "#f7f9fc", "#d0d5dd"


def load(name: str):
    key = "avo_ci_" + name
    if key not in sys.modules:
        spec = importlib.util.spec_from_file_location(
            key, Path(__file__).with_name(name + ".py")
        )
        if spec is None or spec.loader is None:
            raise RuntimeError(f"Quality view helper unavailable: {name}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[key] = module
        spec.loader.exec_module(module)
    return sys.modules[key]


def sources(*groups: list) -> list:
    unique = {
        json.dumps(row, sort_keys=True, separators=(",", ":")): row
        for group in groups
        for row in group
    }
    return [copy.deepcopy(unique[key]) for key in sorted(unique)]


def fingerprint(refs: list) -> str | None:
    return (
        hashlib.sha256(
            json.dumps(refs, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        if refs
        else None
    )


def aggregate(
    document: dict, *, primary_series: dict | None = None
) -> tuple[dict, dict, list]:
    dashboard = load("quality_dashboard")
    primary = (
        primary_series
        if primary_series is not None
        else dashboard.build_series(document)
    )
    metric = copy.deepcopy(
        next(row for row in primary["metrics"] if row["title"] == "Mutation")
    )
    observation = next(
        (
            row
            for row in document.get("measurement_evidence", {}).get("metrics", [])
            if row.get("key") == "mutation"
        ),
        {},
    )
    refs = observation.get("sources", [])
    if not refs:
        metric.update(
            measured=None,
            status="UNAVAILABLE",
            band="unknown",
            detail="Current mutation input proof is unavailable.",
        )
    valid = metric["status"] in {"PASS", "FAIL", "INCOMPLETE"} and bool(refs)
    evaluation = (
        dashboard.mutation_checker().mutation_evaluation(
            document.get("mutation", {}).get("counts", document.get("mutation", {})),
            min_killed_percent=metric["threshold"],
        )
        if valid
        else {}
    )
    return metric, evaluation, sources(refs)


def scope_label(row: dict) -> str:
    if row.get("counts") is None:
        return "UNAVAILABLE"
    if row["counts"]["total"] == 0:
        return "ZERO MUTANTS"
    if row["state"] != "MEASURED":
        return "INCOMPLETE"
    margin = {
        "red": "below reference",
        "yellow": "near reference",
        "green": "clear margin",
        "unknown": "reference unavailable",
    }[row["reference_band"]]
    return f"{row['score']:.2f}% · {margin}"


def _display_rows(rows: list) -> list:
    return sorted(
        rows,
        key=lambda row: (
            row["state"] == "MEASURED",
            row["score"] if row["score"] is not None else -1,
            row["path"],
        ),
    )[:12]


def _scope_data(document: dict) -> dict:
    data = document.get("measurement_evidence", {}).get("mutation_scopes", {})
    if data.get("schema") != 1:
        return {}
    if (
        data.get("profile") != document.get("mutation_policy", {}).get("profile")
        or data.get("threshold_scope") != "aggregate"
        or data.get("source_fingerprint") != fingerprint(data.get("sources", []))
        or (data.get("scopes") and not data.get("sources"))
    ):
        return {
            "state": "UNAVAILABLE",
            "reason": "Per-source mutation profile or proof fingerprint does not match this document.",
            "sources": [],
            "scopes": [],
        }
    return data


def build_mutation_series(
    document: dict, *, primary_series: dict | None = None
) -> dict:
    data = _scope_data(document)
    metric, evaluation, aggregate_refs = aggregate(
        document, primary_series=primary_series
    )
    refs = sources(aggregate_refs, data.get("sources", []))
    series = load("coupling_dashboard").context(document, "mutation_scopes")
    floor = metric["threshold"]
    rows = []
    for index, original in enumerate(
        sorted(data.get("scopes", []), key=lambda row: row["path"]), 1
    ):
        row = copy.deepcopy(original)
        row.update(
            id=f"M{index:03}",
            source_url=load("coupling_dashboard").source_url(document, row["path"])
            if row.get("source_sha256")
            else None,
            reference_role="informational; aggregate reference only",
            reference_band=load("quality_dashboard").threshold_band(
                {
                    "measured": row.get("score"),
                    "threshold": floor,
                    "direction": "minimum",
                }
            ),
            gate=None,
        )
        rows.append(row)
    available = metric["measured"] is not None
    state = (
        "MEASURED"
        if available and data.get("state") == "MEASURED"
        else "PARTIAL"
        if available or rows
        else "UNAVAILABLE"
    )
    shown = _display_rows(rows)
    series.update(
        state=state,
        reason=data.get("reason")
        or "Per-source mutation evidence was not retained; aggregate evidence is shown separately.",
        sources=refs,
        source_fingerprint=fingerprint(refs),
        aggregate=metric,
        counts=copy.deepcopy(evaluation.get("counts", {})),
        complete=evaluation.get("complete", False),
        unresolved=evaluation.get("unresolved"),
        policy={
            "profile": document.get("mutation_policy", {}).get("profile"),
            "floor": floor,
            "threshold_scope": "aggregate",
            "clear_percent": floor + 0.25 * (100 - floor)
            if floor is not None
            else None,
            "band_rule": "minimum-quarter-remaining-v1",
        },
        scopes=rows,
        display={
            "ids": [row["id"] for row in shown],
            "shown": len(shown),
            "total": len(rows),
            "selection": "unavailable/incomplete first, then lowest measured efficacy; canonical path breaks ties; capped at 12",
        },
    )
    return series


def _check_context(series: dict, document: dict, chart: str) -> None:
    if type(series.get("schema")) is not int or series["schema"] != 1:
        raise ValueError(f"{chart}: frozen schema is invalid")
    expected = load("coupling_dashboard").context(document, chart)
    for key in ("schema", "chart", "sha", "run_id", "mode", "definition_identity"):
        if series.get(key) != expected.get(key):
            raise ValueError(f"{chart}: frozen {key} does not match its document")
    if series.get("source_fingerprint") != fingerprint(series.get("sources", [])):
        raise ValueError(f"{chart}: source fingerprint mismatch")


def validate_frozen_series(series: dict, document: dict) -> bool:
    """Validate stored values using the frozen document, never today's catalog."""
    try:
        return _validate_frozen_series(series, document)
    except (KeyError, TypeError, AttributeError) as exc:
        raise ValueError("Frozen mutation scopes have an invalid shape") from exc


def _validate_frozen_series(series: dict, document: dict) -> bool:
    _check_context(series, document, "mutation_scopes")
    data = _scope_data(document)
    _validate_scope_bindings(series, document, data)
    if series.get("counts") and series["scopes"]:
        producer = load("mutation_scopes")
        producer._reconcile(
            series["scopes"], producer._aggregate_counts(document["mutation"])
        )
    refs = _validate_aggregate(series, document)
    available = series["aggregate"]["measured"] is not None
    state = (
        "MEASURED"
        if available and data.get("state") == "MEASURED"
        else "PARTIAL"
        if available or series["scopes"]
        else "UNAVAILABLE"
    )
    if series.get("state") != state or series.get("sources") != sources(
        refs, data.get("sources", [])
    ):
        raise ValueError(
            "Frozen mutation state or sources disagree with captured evidence"
        )
    display = series["display"]
    ids = [row["id"] for row in series["scopes"]]
    selected = display["ids"]
    if (
        not isinstance(selected, list)
        or len(selected) > 12
        or len(selected) != len(set(selected))
        or any(value not in ids for value in selected)
        or type(display.get("shown")) is not int
        or display["shown"] != len(selected)
        or type(display.get("total")) is not int
        or display["total"] != len(ids)
        or not isinstance(display.get("selection"), str)
    ):
        raise ValueError("Frozen mutation display does not identify retained sources")
    return True


def _validate_scope_bindings(series: dict, document: dict, data: dict) -> None:
    rows = series["scopes"]
    captured = sorted(data.get("scopes", []), key=lambda row: row["path"])
    if not isinstance(rows, list) or len(rows) != len(captured):
        raise ValueError(
            "Frozen mutation source population differs from captured evidence"
        )
    for index, (row, original) in enumerate(zip(rows, captured, strict=True), 1):
        _scope_accounting(row)
        if (
            any(row.get(key) != value for key, value in original.items())
            or row.get("id") != f"M{index:03}"
            or row.get("gate") is not None
            or row.get("reference_band") not in {"red", "yellow", "green", "unknown"}
            or not isinstance(row.get("reference_role"), str)
            or row.get("source_url")
            != (
                load("coupling_dashboard").source_url(document, row["path"])
                if row.get("source_sha256")
                else None
            )
        ):
            raise ValueError(
                "Frozen mutation source binding differs from captured evidence"
            )
    paths = [row["path"] for row in rows]
    if paths != sorted(set(paths)):
        raise ValueError("Frozen mutation source paths are not unique and ordered")


def _aggregate_accounting(document: dict) -> tuple[dict, list]:
    """Read captured outcomes and policy, without rebuilding presentation rules."""
    policy = document.get("mutation_policy") or {}
    payload = document.get("mutation") or {}
    observation = next(
        (
            row
            for row in document.get("measurement_evidence", {}).get("metrics", [])
            if row.get("key") == "mutation"
        ),
        {},
    )
    refs = observation.get("sources", [])
    valid = (
        bool(document.get("sha"))
        and payload.get("sha") == document["sha"]
        and bool(document.get("run_id"))
        and str(payload.get("run_id") or "") == str(document["run_id"])
        and policy.get("profile") in {"light", "full"}
        and payload.get("profile") == policy.get("profile")
        and type(payload.get("floor")) in {int, float}
        and payload.get("floor") == policy.get("floor")
        and bool(refs)
    )
    result = (
        load("check_mutation").mutation_evaluation(
            payload.get("counts", payload), min_killed_percent=policy.get("floor")
        )
        if valid
        else {}
    )
    if result.get("status") in {"PASS", "FAIL"} and (
        observation.get("state") not in {"MEASURED", "PARTIAL"}
        or observation.get("unit") != "percent"
        or type(observation.get("number")) not in {int, float}
        or observation["number"] != result["score"]
    ):
        return {}, sources(refs)
    return result, sources(refs)


def _validate_aggregate(series: dict, document: dict) -> list:
    metric, policy = series["aggregate"], series["policy"]
    expected_policy = document.get("mutation_policy", {})
    floor = load("quality_dashboard").percentage(expected_policy.get("floor"))
    if (
        metric.get("status")
        not in {"PASS", "FAIL", "INCOMPLETE", "INVALID", "UNAVAILABLE"}
        or (
            policy.get("floor") is not None
            and type(policy["floor"]) not in {int, float}
        )
        or (
            metric.get("threshold") is not None
            and type(metric["threshold"]) not in {int, float}
        )
        or policy.get("floor") != floor
        or policy.get("profile") != expected_policy.get("profile")
        or policy.get("threshold_scope") != "aggregate"
        or not isinstance(policy.get("band_rule"), str)
        or not policy["band_rule"]
        or (
            policy.get("clear_percent") is not None
            and load("quality_dashboard").percentage(policy["clear_percent"]) is None
        )
        or metric.get("threshold") != floor
        or metric.get("direction") != "minimum"
        or metric.get("band") not in {"red", "yellow", "green", "unknown"}
    ):
        raise ValueError("Frozen mutation policy differs from its captured policy")
    evaluation, refs = _aggregate_accounting(document)
    expected = (
        evaluation if metric.get("status") in {"PASS", "FAIL", "INCOMPLETE"} else {}
    )
    if metric.get("status") in {"PASS", "FAIL", "INCOMPLETE"} and (
        not expected or metric["status"] != expected["status"]
    ):
        raise ValueError(
            "Frozen mutation aggregate decision disagrees with captured evidence"
        )
    if (
        metric.get("measured") != expected.get("score")
        or (
            metric.get("measured") is not None
            and type(metric["measured"]) not in {int, float}
        )
        or series.get("counts") != expected.get("counts", {})
        or any(type(count) is not int for count in series["counts"].values())
        or type(series.get("complete")) is not bool
        or series["complete"] != expected.get("complete", False)
        or series.get("unresolved") != expected.get("unresolved")
        or (
            series.get("unresolved") is not None
            and type(series["unresolved"]) is not int
        )
    ):
        raise ValueError(
            "Frozen mutation aggregate accounting disagrees with captured evidence"
        )
    return refs


def _scope_accounting(row: dict) -> None:
    path = row["path"]
    if (
        not path.startswith("src/avo/")
        or not path.endswith(".py")
        or any(part in {"", ".", ".."} for part in path.split("/"))
        or "\\" in path
    ):
        raise ValueError("Frozen mutation source path is not canonical")
    if row.get("source_sha256") is not None and not re.fullmatch(
        r"[a-f0-9]{64}", row["source_sha256"]
    ):
        raise ValueError("Frozen mutation source hash is invalid")
    if row.get("counts") is None:
        if (
            row.get("score") is not None
            or row.get("complete")
            or row.get("unresolved") is not None
            or row.get("state") != "UNAVAILABLE"
        ):
            raise ValueError("Unavailable scope accounting must not invent a score")
        return
    result = load("check_mutation").mutation_evaluation(
        row["counts"], min_killed_percent=0
    )
    state = (
        "MEASURED"
        if result["complete"]
        else "PARTIAL"
        if result["counts"].get("total")
        else "UNAVAILABLE"
    )
    score_matches = (
        row.get("score") is None
        if result["score"] is None
        else type(row.get("score")) in {int, float}
        and math.isclose(row["score"], result["score"], rel_tol=1e-12)
    )
    if (
        result["status"] == "INVALID"
        or not score_matches
        or row.get("complete") != result["complete"]
        or row.get("unresolved") != result["unresolved"]
        or row.get("state") != state
    ):
        raise ValueError("Frozen scope accounting is inconsistent")


def write_mutation_indexes(series: dict, directory: Path) -> dict:
    shared = load("coupling_dashboard")
    lines = shared.index_header(
        series, "AVO mutation efficacy: aggregate and complete source index"
    )
    metric, policy = series["aggregate"], series["policy"]
    lines += [
        "",
        f"Aggregate decision: **{shared.safe_text(metric['status'])}**. Efficacy: {load('quality_dashboard').value_text(metric['measured'])}.",
        f"Policy: minimum {policy['floor']:g}%; {shared.safe_text(policy['profile'])} profile; aggregate only. Clear margin begins at {policy['clear_percent']:g}%; visual band is not another gate."
        if policy["floor"] is not None
        else "Policy: unavailable; no threshold inferred.",
        f"Complete execution: {series['complete']}; unresolved: {series['unresolved']}. Counts: {shared.safe_text(json.dumps(series['counts'], sort_keys=True))}.",
        "",
        "Per-source efficacy and red/yellow/green reference bands are informational. The aggregate minimum is a reference only; there is no per-source gate.",
        f"Image selection: {series['display']['shown']}/{series['display']['total']} retained source rows; {series['display']['selection']}."
        if series["scopes"]
        else "Per-source breakdown was not retained; source population and individual denominators are unavailable.",
        "",
        "| ID | Complete source identity | State | Efficacy | Informational band | Killed | Survived | Total | Unresolved | Source SHA-256 | Reason |",
        "|---|---|---|---:|---|---:|---:|---:|---:|---|---|",
    ]
    for row in series["scopes"]:
        counts = row.get("counts") or {}
        state = (
            row["state"]
            if row["state"] == "MEASURED"
            else row["state"] + ": " + scope_label(row)
        )
        unresolved = row.get("unresolved")
        lines.append(
            f"| {row['id']} | {shared.source_label(row)} | {state} | {load('quality_dashboard').value_text(row.get('score'))} | {row['reference_band']} (informational) | {counts.get('killed', 'Unavailable')} | {counts.get('survived', 'Unavailable')} | {counts.get('total', 'Unavailable')} | {unresolved if unresolved is not None else 'Unavailable'} | {row.get('source_sha256') or 'Unavailable'} | {shared.safe_text(row['reason'])} |"
        )
    lines += ["", "## Complete per-source counters and metadata", ""]
    for row in series["scopes"]:
        metadata = row.get("metadata")
        lines.append(
            f"- {row['id']}: counts {shared.safe_text(json.dumps(row.get('counts'), sort_keys=True))}; metadata {shared.safe_text(json.dumps(metadata, sort_keys=True))}."
        )
    return shared.write_indexes(series, directory, "mutation-efficacy", lines)


def canvas(title: str, subtitle: str, height: float, series: dict):
    os.environ.setdefault("MPLBACKEND", "Agg")
    import matplotlib.pyplot as plt

    fig = plt.figure(figsize=(13.5, height), dpi=150, facecolor=BG)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set(xlim=(0, 1), ylim=(0, height))
    ax.axis("off")
    ax.text(0.045, height - 0.3, title, fontsize=23, weight="bold", color=INK, va="top")
    ax.text(0.045, height - 0.78, subtitle, fontsize=11, color=MUTED, va="top")
    ax.text(
        0.045,
        height - 1.12,
        load("coupling_dashboard")._image_source_context(series),
        fontsize=10,
        color=MUTED,
        va="top",
    )
    return fig, ax


def box(ax, x: float, y: float, width: float, height: float, color: str, border=None):
    from matplotlib.patches import FancyBboxPatch

    ax.add_patch(
        FancyBboxPatch(
            (x, y),
            width,
            height,
            boxstyle="round,pad=0.003,rounding_size=0.008",
            linewidth=0.7 if border else 0,
            edgecolor=border or color,
            facecolor=color,
        )
    )


def save(fig, path: Path, series: dict) -> None:
    import matplotlib.pyplot as plt

    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fig.savefig(
            path,
            facecolor=BG,
            metadata={
                "Description": json.dumps(series, sort_keys=True, allow_nan=False)
            },
        )
    except Exception:
        path.unlink(missing_ok=True)
        raise
    finally:
        plt.close(fig)


def short(value: str, length: int) -> str:
    return value if len(value) <= length else value[: length - 1] + "…"


def render_mutation(series: dict, path: Path) -> None:
    """Render frozen scope rows; unavailable evidence never resembles zero kills."""
    path.unlink(missing_ok=True)
    metric, policy = series["aggregate"], series["policy"]
    rows = {row["id"]: row for row in series["scopes"]}
    selected = [rows[key] for key in series["display"]["ids"]]
    height = 7.2 + 0.53 * max(1, len(selected))
    fig, ax = canvas(
        "Mutation efficacy",
        "Test detection strength and execution completeness",
        height,
        series,
    )
    band_color = {"red": RED, "yellow": AMBER, "green": GREEN}.get(
        metric["band"], MUTED
    )
    ax.text(
        0.045,
        height - 1.85,
        f"{str(policy['profile'] or 'Unspecified').upper()} PROFILE · AGGREGATE",
        fontsize=11,
        weight="bold",
        color=INK,
    )
    ax.text(
        0.915,
        height - 1.85,
        f"{metric['status']}  {load('quality_dashboard').value_text(metric['measured'])}",
        fontsize=19,
        weight="bold",
        ha="right",
        color=band_color,
    )
    bar = fig.add_axes(
        [0.07, (height - 3.25) / height, 0.78, 0.9 / height], facecolor=BG
    )
    floor, clear = policy["floor"], policy["clear_percent"]
    if floor is not None:
        for start, end, color in (
            (0, floor, "#fce9e7"),
            (floor, clear, "#fff3cf"),
            (clear, 100, "#e8f3ed"),
        ):
            bar.axvspan(start, end, color=color)
        bar.axvline(floor, color=INK, linestyle="--", linewidth=1.5)
        bar.text(
            floor, 0.55, f"{floor:g}% minimum", fontsize=10, ha="center", weight="bold"
        )
    if metric["measured"] is not None:
        bar.barh([0], [metric["measured"]], height=0.4, color=band_color)
    else:
        bar.text(
            50,
            0,
            "Efficacy unavailable · inspect accounting",
            fontsize=11,
            ha="center",
            color=MUTED,
        )
    bar.set(
        xlim=(0, 100), ylim=(-0.75, 0.9), yticks=[], xticks=[0, 20, 40, 60, 80, 100]
    )
    bar.set_xticklabels(
        [f"{n}%" for n in (0, 20, 40, 60, 80, 100)], fontsize=10, color=MUTED
    )
    for spine in bar.spines.values():
        spine.set_visible(False)
    bar.tick_params(length=0)
    ax.text(
        0.045,
        height - 3.62,
        "Red: below minimum · yellow: passing near minimum · green: clear margin",
        fontsize=10,
        color=MUTED,
    )
    ax.text(
        0.045,
        height - 3.98,
        f"The {floor:g}% policy applies to the combined profile."
        if floor is not None
        else "Aggregate policy unavailable.",
        fontsize=11,
        weight="bold",
        color=INK,
    )
    _outcomes(ax, series, height - 4.65)
    y = height - 5.85
    ax.text(
        0.045,
        y,
        f"PER-SOURCE EFFICACY · {len(selected)}/{len(rows)} shown · INFORMATIONAL"
        if rows
        else "PER-SOURCE BREAKDOWN · NOT RETAINED",
        fontsize=12,
        weight="bold",
        color=INK,
    )
    ax.text(
        0.045,
        y - 0.32,
        "Red/yellow/green compare to the aggregate reference only; no per-source gate is adopted.",
        fontsize=10,
        color=MUTED,
    )
    for index, row in enumerate(selected):
        _scope_row(ax, row, y - 0.95 - index * 0.53, floor)
    if not selected:
        ax.text(0.045, y - 0.95, short(series["reason"], 110), fontsize=10, color=MUTED)
    ax.text(
        0.045,
        0.47,
        "Missing, zero-mutant and unresolved scopes remain distinct. Complete paths, counts and evidence: mutation-efficacy.md / .json",
        fontsize=9.2,
        color=MUTED,
    )
    ax.text(
        0.045,
        0.20,
        f"Selection: {short(series['display']['selection'], 135)}",
        fontsize=9.2,
        color=MUTED,
    )
    save(fig, path, series)


def _outcomes(ax, series: dict, y: float) -> None:
    counts = series["counts"]
    total = counts.get("total")
    ax.text(
        0.045, y + 0.35, "OUTCOME ACCOUNTING", fontsize=11, weight="bold", color=INK
    )
    if not total:
        ax.text(
            0.045,
            y,
            "Zero mutants" if total == 0 else "Outcome counts unavailable",
            fontsize=12,
            color=MUTED,
        )
        return
    x = 0.045
    for count, color in (
        (counts["killed"], GREEN),
        (counts["survived"], RED),
        (series["unresolved"] or 0, AMBER),
    ):
        if count:
            width = 0.87 * count / total
            box(ax, x, y, width, 0.22, color)
            x += width
    ax.text(
        0.045,
        y - 0.30,
        f"{counts['killed']} killed · {counts['survived']} survived · {series['unresolved']} unresolved · {total} total",
        fontsize=11,
        weight="bold",
        color=INK,
    )
    ax.text(
        0.045,
        y - 0.56,
        "Green = killed · red = survived · amber = unresolved. Efficacy requires complete outcomes.",
        fontsize=9.3,
        color=MUTED,
    )


def _scope_row(ax, row: dict, y: float, floor: float | None) -> None:
    box(ax, 0.045, y - 0.10, 0.87, 0.43, "#edf0f4")
    ax.text(
        0.058,
        y + 0.15,
        f"{row['id']}  {short(row['path'], 64)}",
        fontsize=10.2,
        color=INK,
        family="monospace",
    )
    label = scope_label(row)
    color = {"red": RED, "yellow": AMBER, "green": GREEN}.get(
        row["reference_band"], MUTED
    )
    ax.text(0.902, y + 0.15, label, fontsize=10, color=color, ha="right", weight="bold")
    if row.get("score") is not None:
        box(ax, 0.058, y - 0.015, 0.40, 0.065, "#d0d5dd")
        if row["score"] > 0:
            box(ax, 0.058, y - 0.015, 0.40 * row["score"] / 100, 0.065, color)
        if floor is not None:
            ax.plot(
                [0.058 + 0.40 * floor / 100] * 2,
                [y - 0.035, y + 0.07],
                color=MUTED,
                linestyle="--",
                linewidth=0.8,
            )
    counts = row.get("counts")
    detail = (
        f"{counts['killed']} killed / {counts['survived']} survived / {counts['total']} total; unresolved {row['unresolved']}"
        if counts is not None
        else row["reason"]
    )
    ax.text(0.49, y - 0.015, short(detail, 68), fontsize=9.1, color=MUTED)
