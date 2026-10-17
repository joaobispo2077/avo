"""Freeze and render informational function hotspots from verified observations."""

from __future__ import annotations

import copy
import importlib.util
import json
import os
import sys
from pathlib import Path


def _shared():
    name = "avo_ci_coupling_dashboard"
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(
            name, Path(__file__).with_name("coupling_dashboard.py")
        )
        if spec is None or spec.loader is None:
            raise RuntimeError("Supporting view helpers are unavailable.")
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return sys.modules[name]


def build_hotspot_series(document: dict) -> dict:
    supporting = document.get("measurement_evidence", {}).get("supporting", {})
    data = supporting.get("functions", {}) if supporting.get("schema") == 1 else {}
    series = _shared().context(document, "hotspots")
    series.update(
        state="UNAVAILABLE",
        reason=data.get("reason") or "Verified function measurements are unavailable.",
        grain="function or method",
        scope="src/avo; same-function complexity and line coverage",
        functions=[],
        population={
            "observed_functions": 0,
            "measured_crap_functions": 0,
            "unmeasured_observed_functions": 0,
            "source_error_count": 0,
            "total_population_known": False,
        },
        source_errors=[],
        crap_reference={"value": 30, "role": "informational"},
        rankings={},
    )
    if data.get("state") in {"MEASURED", "PARTIAL"}:
        records = sorted(
            data["records"], key=lambda row: (row["path"], row["line"], row["qualname"])
        )
        for index, original in enumerate(records, 1):
            row = copy.deepcopy(original)
            row.update(
                observation_id=row["id"],
                id=f"U{index:04}",
                source_url=_shared().source_url(document, row["path"], row["line"]),
            )
            series["functions"].append(row)
        errors = data.get("source_errors", [])
        series.update(state=data["state"], source_errors=copy.deepcopy(errors))
        series["population"].update(
            observed_functions=data["observed_functions"],
            measured_crap_functions=data["measured_crap_functions"],
            unmeasured_observed_functions=data["unmeasured_observed_functions"],
            source_error_count=len(errors),
            total_population_known=data["total_population_known"],
        )
    for key in ("complexity", "crap"):
        eligible = [
            row
            for row in series["functions"]
            if key == "complexity" or row["crap"]["status"] == "MEASURED"
        ]

        def value(row, key=key):
            return row["complexity"] if key == "complexity" else row["crap"]["value"]

        ranked = sorted(
            eligible,
            key=lambda row: (-value(row), row["path"], row["line"], row["qualname"]),
        )
        series["rankings"][key] = {
            "ids": [row["id"] for row in ranked[:10]],
            "shown": min(10, len(ranked)),
            "eligible": len(ranked),
            "observed": len(series["functions"]),
            "maximum": value(ranked[0]) if ranked else None,
            "selection": "highest observed values, capped at 10",
            "tie_rule": "descending value, then canonical path, definition line, qualified name",
            "unit": "independent paths" if key == "complexity" else "CRAP score",
        }
    return series


def write_hotspot_indexes(series: dict, directory: Path) -> dict:
    shared = _shared()
    lines = shared.index_header(
        series, "AVO complexity and CRAP: complete function index"
    )
    population = series["population"]
    known = (
        "Total function population known."
        if population["total_population_known"]
        else "Total function population unknown beyond observed functions because source analysis is incomplete/unavailable."
    )
    lines.extend(
        [
            "",
            f"{population['observed_functions']} observed functions; {population['measured_crap_functions']} measured CRAP; {population['unmeasured_observed_functions']} observed functions without CRAP; {population['source_error_count']} source-analysis errors. {known}",
            "",
            "CRAP = CC² × (1 − function line coverage)³ + CC. Reference 30 is informational, not a gate. Complexity policies and exceptions remain separate; no universal CC ceiling is inferred.",
            "Rank/chart labels use up to six significant digits; full rows retain the original CRAP values. Coverage percentages display two decimals; their exact covered/total counts and frozen JSON remain available.",
        ]
    )
    by_id = {row["id"]: row for row in series["functions"]}
    for key, title in (("complexity", "Cyclomatic complexity"), ("crap", "CRAP")):
        ranking = series["rankings"][key]
        lines.extend(
            [
                "",
                f"## {title} review candidates",
                "",
                f"{ranking['shown']}/{ranking['eligible']} eligible candidates shown; {ranking['observed']} functions observed. {ranking['selection']}; ties: {ranking['tie_rule']}.",
                "",
                "| Rank | Function ID | Full source identity | Observed value | Unit |",
                "|---:|---|---|---:|---|",
            ]
        )
        for index, identifier in enumerate(ranking["ids"], 1):
            row = by_id[identifier]
            value = row["complexity"] if key == "complexity" else row["crap"]["value"]
            lines.append(
                f"| {index} | {identifier} | {shared.source_label(row, function=True)} | {value:g} | {ranking['unit']} |"
            )
    lines.extend(
        [
            "",
            "## All observed functions",
            "",
            "| Function ID | Complete source identity | CC | Same-function coverage | CRAP | CRAP state / reason | Source SHA-256 |",
            "|---|---|---:|---|---:|---|---|",
        ]
    )
    for row in series["functions"]:
        coverage = row["function_coverage"]
        observed = coverage.get("percent")
        detail = (
            f"{coverage['covered_lines']}/{coverage['num_statements']} lines; {observed:.2f}%"
            if observed is not None
            else f"Unavailable: {shared.safe_text(coverage.get('reason', 'not captured'))}"
        )
        crap = row["crap"]
        score = "Unavailable" if crap["value"] is None else str(crap["value"])
        lines.append(
            f"| {row['id']} | {shared.source_label(row, function=True)} | {row['complexity']} | {detail} | {score} | {shared.safe_text(crap['status'])}: {shared.safe_text(crap.get('reason', ''))} | {row['source_sha256']} |"
        )
    if series["source_errors"]:
        lines.extend(
            ["", "## Source-analysis errors (not counted as unmeasured functions)", ""]
        )
        lines.extend(
            f"- {shared.safe_text(json.dumps(error, sort_keys=True))}"
            for error in series["source_errors"]
        )
    return shared.write_indexes(series, directory, "hotspots", lines)


def _draw_ranking(ax, series: dict, key: str, title: str, color: str) -> None:
    ranking = series["rankings"][key]
    by_id = {row["id"]: row for row in series["functions"]}
    rows = [by_id[identifier] for identifier in ranking["ids"]]
    values = [
        row["complexity"] if key == "complexity" else row["crap"]["value"]
        for row in rows
    ]
    labels = []
    for row in rows:
        basename = Path(row["path"]).name
        short_name = basename if len(basename) <= 16 else basename[:13] + "…"
        labels.append(f"{row['id']}  {short_name}:{row['line']}")
    ax.set_facecolor("#f8fafc")
    ax.set_title(
        f"{title} · {ranking['shown']}/{ranking['eligible']} eligible shown",
        loc="left",
        fontsize=14,
        fontweight="bold",
        color="#101828",
        pad=12,
    )
    ax.set_xlim(0, max([30 if key == "crap" else 1, *values]) * 1.18)
    ax.set_yticks(range(len(rows)), labels, fontsize=11, color="#344054")
    ax.invert_yaxis()
    ax.tick_params(axis="y", length=0, pad=9)
    ax.tick_params(axis="x", labelsize=10, colors="#475467")
    ax.set_xlabel(ranking["unit"], fontsize=11, color="#475467")
    if rows:
        ax.barh(range(len(rows)), values, height=0.58, color=color)
        for index, value in enumerate(values):
            ax.annotate(
                f"{value:g}",
                (value, index),
                xytext=(5, 0),
                textcoords="offset points",
                va="center",
                fontsize=11,
                fontweight="bold",
                color="#344054",
            )
    else:
        ax.text(
            0.02,
            0.5,
            "No measured candidates; inspect the completeness notes.",
            transform=ax.transAxes,
            fontsize=11,
            color="#475467",
        )
    if key == "crap":
        ax.axvline(
            30,
            color="#475467",
            linestyle="--",
            linewidth=1.4,
            label="30 · informational reference",
        )
        ax.legend(loc="lower right", fontsize=9, framealpha=0.95)
    ax.grid(axis="x", alpha=0.15, color="#98a2b3")
    ax.set_axisbelow(True)
    for side in ("left", "right", "top"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color("#98a2b3")


def render_hotspots(series: dict, path: Path) -> None:
    path.unlink(missing_ok=True)
    if series["state"] not in {"MEASURED", "PARTIAL"} or not series["functions"]:
        raise ValueError("Function hotspots are unavailable; no image was produced.")
    os.environ.setdefault("MPLBACKEND", "Agg")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(2, 1, figsize=(10, 9), dpi=150)
    fig.patch.set_facecolor("#f8fafc")
    fig.text(
        0.08,
        0.96,
        "AVO function review candidates",
        fontsize=21,
        fontweight="bold",
        color="#101828",
    )
    population = series["population"]
    fig.text(
        0.08,
        0.925,
        f"{population['observed_functions']} observed · {population['measured_crap_functions']} CRAP measured · {population['unmeasured_observed_functions']} observed without CRAP · {series['state']}",
        fontsize=11,
        color="#344054",
    )
    fig.text(
        0.08,
        0.895,
        f"Commit {series['sha'][:10] or 'unavailable'} · Run {series['run_id'] or 'unavailable'} · {series['mode']}",
        fontsize=10,
        color="#475467",
    )
    _draw_ranking(axes[0], series, "complexity", "Cyclomatic complexity", "#24689d")
    _draw_ranking(axes[1], series, "crap", "CRAP · same-function inputs", "#655294")
    known = (
        "Total population known."
        if population["total_population_known"]
        else "Total population unknown beyond observed functions."
    )
    fig.text(
        0.08,
        0.075,
        f"{population['source_error_count']} source-analysis errors. {known}",
        fontsize=10,
        color="#344054",
    )
    fig.text(
        0.08,
        0.045,
        "Rank: descending value, then path / line / qualified name. U IDs link both views to full source.",
        fontsize=10,
        color="#344054",
    )
    fig.text(
        0.08,
        0.018,
        "Informational review cues; enforcement remains separate. Complete inputs and source lookup: hotspots.md / .json.",
        fontsize=9.5,
        color="#344054",
    )
    fig.subplots_adjust(left=0.29, right=0.94, top=0.84, bottom=0.16, hspace=0.55)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fig.savefig(
            path,
            facecolor=fig.get_facecolor(),
            metadata={
                "Description": json.dumps(series, sort_keys=True, allow_nan=False)
            },
        )
    except Exception:
        path.unlink(missing_ok=True)
        raise
    finally:
        plt.close(fig)
