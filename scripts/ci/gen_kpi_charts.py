#!/usr/bin/env python3
"""PNG charts for the Software quality sticky. Visualization only, not a gate.

Numbers come from the same helpers as ``write_quality_pr_report.py``.
Coverage floor is pyproject ``fail_under``. Duplication ceiling is ``.jscpd.json``.
The status chart paints slack against those lines. It does not move them.
Mutation is not measured here.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
IMAGE_PREFIX = "kpi-chart:"
START = "<!-- kpi-charts:start -->"
END = "<!-- kpi-charts:end -->"

PASS_HEX = "#1b7f3a"
FAIL_HEX = "#b00020"
UNKNOWN_HEX = "#5c6770"
FLOOR_HEX = "#1f4e79"
NEUTRAL_HEX = "#1f4e79"
YELLOW_HEX = "#f0b400"
CHIP_PASS_HEX = "#1f4e89"
CHIP_SKIP_HEX = "#5c6770"
EDGE = "#1a1a1a"
JSCPD_REPORT = Path("reports/quality/jscpd/jscpd-report.json")
SLACK_HEX = {"red": FAIL_HEX, "yellow": YELLOW_HEX, "green": PASS_HEX}


def _report():
    name = "avo_ci_write_quality_pr_report"
    cached = sys.modules.get(name)
    if cached is not None:
        return cached
    path = Path(__file__).resolve().parent / "write_quality_pr_report.py"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _plt():
    os.environ.setdefault("MPLBACKEND", "Agg")
    import matplotlib.pyplot as plt

    return plt


def coverage_bar_state(percent: float | None, floor: float, step_outcome: str) -> str:
    """Red unless this run measured coverage at or above the real floor."""
    if percent is None or step_outcome.strip().lower() != "success":
        return "fail"
    if percent < floor:
        return "fail"
    return "pass"


def quarter_mark(line: float) -> float:
    """First quarter of the headroom above the line. That point is green."""
    return line + 0.25 * (100.0 - line)


def slack_band(goodness: float, line: float) -> str:
    """Higher goodness is better. On the line is yellow. The quarter mark is green."""
    if goodness < line:
        return "red"
    if goodness < quarter_mark(line):
        return "yellow"
    return "green"


def _cap100(value: float) -> float:
    return min(100.0, max(0.0, value))


def duplication_percent(root: Path) -> float | None:
    """Line percentage jscpd already computed. Missing file draws no bar."""
    path = root / JSCPD_REPORT
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    statistics = payload.get("statistics")
    if not isinstance(statistics, dict):
        return None
    total = statistics.get("total")
    if not isinstance(total, dict):
        return None
    raw = total.get("percentage")
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return None
    return float(raw)


def _chip_row(gate: dict) -> dict:
    return {"title": gate["title"], "status": gate["status"], "kind": "chip"}


def _bar_row(
    gate: dict,
    *,
    measured: float,
    drawn: float,
    line: float,
    goodness: float,
) -> dict:
    return {
        "title": gate["title"],
        "status": gate["status"],
        "kind": "bar",
        "measured": measured,
        "drawn": _cap100(drawn),
        "line": line,
        "slack": slack_band(goodness, line),
    }


def status_chart_series(snapshot: dict) -> dict:
    """Bars are coverage and duplication only. Every other gate is a chip."""
    coverage = snapshot["coverage"]
    duplication = snapshot["duplication"]
    rows = []
    for gate in snapshot["gates"]:
        key = gate["key"]
        if key == "coverage" and coverage["measured"] is not None:
            measured = float(coverage["measured"])
            line = float(coverage["floor"])
            rows.append(
                _bar_row(
                    gate,
                    measured=measured,
                    drawn=measured,
                    line=line,
                    goodness=measured,
                )
            )
        elif key == "duplication" and duplication.get("percent") is not None:
            measured = float(duplication["percent"])
            line = 100.0 - float(duplication["ceiling"])
            goodness = 100.0 - measured
            rows.append(
                _bar_row(
                    gate,
                    measured=measured,
                    drawn=goodness,
                    line=line,
                    goodness=goodness,
                )
            )
        else:
            rows.append(_chip_row(gate))
    return {
        "chart": "status",
        "overall": snapshot["overall"],
        "axis_max": 100,
        "gates": rows,
    }


def status_chart_cell(row: dict) -> str:
    if row.get("kind") != "bar":
        return "chip"
    drawn = float(row["drawn"])
    line = float(row["line"])
    slack = str(row["slack"])
    measured = float(row["measured"])
    if abs(measured - drawn) > 1e-9:
        return f"{drawn:.2f} · measured {measured:.2f}% · line {line:.2f} · {slack}"
    return f"{drawn:.2f} · line {line:.2f} · {slack}"


def status_table_value(row: dict) -> str:
    return f"{status_chart_cell(row)} · **{row['status']}**"


def _count_block(count: int | None, reported: str) -> dict:
    return {"count": count, "reported": reported}


def build_snapshot(
    outcomes: dict[str, str],
    *,
    coverage_json: Path,
    floor: float,
    root: Path,
) -> dict:
    report = _report()
    gates = []
    for key, title in report.GATES:
        outcome = outcomes.get(key, "")
        gates.append(
            {
                "key": key,
                "title": title,
                "status": report._label(outcome),
                "metric": report.gate_metric(
                    key, coverage_json=coverage_json, floor=floor, root=root
                ),
            }
        )
    numbers = report.coverage_numbers(coverage_json)
    coverage_step = outcomes.get("coverage", "")
    percent = numbers["percent"]
    return {
        "overall": report.overall_label(outcomes),
        "floor": floor,
        "gates": gates,
        "coverage": {
            "measured": percent,
            "covered": numbers["covered"],
            "statements": numbers["statements"],
            "floor": floor,
            "step": report._label(coverage_step),
            "state": coverage_bar_state(percent, floor, coverage_step),
            "reported": report.coverage_detail(coverage_json, floor),
        },
        "complexity": _count_block(
            report.complexity_allowlisted(root),
            report.gate_metric(
                "complexity", coverage_json=coverage_json, floor=floor, root=root
            ),
        ),
        "deadcode": _count_block(
            report.deadcode_allowlisted(root),
            report.gate_metric(
                "deadcode", coverage_json=coverage_json, floor=floor, root=root
            ),
        ),
        "deps": _count_block(
            report.npm_exception_count(root),
            report.gate_metric(
                "deps", coverage_json=coverage_json, floor=floor, root=root
            ),
        ),
        "duplication": {
            "ceiling": report.duplication_ceiling(root),
            "percent": duplication_percent(root),
            "reported": report.gate_metric(
                "duplication", coverage_json=coverage_json, floor=floor, root=root
            ),
        },
        "architecture": _count_block(
            report.architecture_contracts(root),
            report.gate_metric(
                "architecture", coverage_json=coverage_json, floor=floor, root=root
            ),
        ),
        "mutation": {"value": None, "sticky": "mutation-report"},
    }


def _save(fig, path: Path, series: dict) -> dict:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(
        path,
        format="png",
        metadata={"Description": json.dumps(series, sort_keys=True)},
        bbox_inches="tight",
        facecolor="white",
    )
    _plt().close(fig)
    return series


def _figure(title: str, title_color: str):
    plt = _plt()
    fig, ax = plt.subplots(figsize=(8.0, 4.6), dpi=120)
    fig.patch.set_facecolor("white")
    ax.set_facecolor("white")
    ax.set_title(title, color=title_color, fontsize=14, fontweight="bold", loc="left")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.tick_params(labelsize=11, colors=EDGE)
    return fig, ax


def _chip_color(status: str) -> str:
    """Status pills. Yellow and green are reserved for score bars."""
    if status == "PASS":
        return CHIP_PASS_HEX
    if status in {"FAIL", "CANCELLED"}:
        return FAIL_HEX
    if status == "SKIPPED":
        return CHIP_SKIP_HEX
    return UNKNOWN_HEX


def _draw_score_bar(ax, y: float, row: dict) -> None:
    drawn = float(row["drawn"])
    ax.barh(
        y,
        drawn,
        color=SLACK_HEX[str(row["slack"])],
        edgecolor="none",
        linewidth=0,
        height=0.62,
        zorder=2,
    )
    line = float(row["line"])
    if 0.0 <= line <= 100.0:
        ax.plot(
            [line, line],
            [y - 0.5, y + 0.5],
            color=EDGE,
            linewidth=2.2,
            solid_capstyle="butt",
            zorder=4,
        )
    ax.text(
        102,
        y,
        row["status"],
        va="center",
        ha="left",
        fontsize=10,
        fontweight="bold",
        color=EDGE,
        clip_on=False,
        zorder=5,
    )


def _draw_chip(ax, y: float, row: dict) -> None:
    from matplotlib.patches import Rectangle

    paint = _chip_color(str(row["status"]))
    ax.add_patch(
        Rectangle(
            (1.2, y - 0.22),
            18,
            0.44,
            facecolor=paint,
            edgecolor=EDGE,
            zorder=2,
            linewidth=0.6,
        )
    )
    ax.text(
        10.2,
        y,
        row["status"],
        va="center",
        ha="center",
        fontsize=8,
        fontweight="bold",
        color="white",
        zorder=3,
    )


def render_status(snapshot: dict, path: Path) -> dict:
    series = status_chart_series(snapshot)
    overall = series["overall"]
    title_color = PASS_HEX if overall == "PASS" else FAIL_HEX
    fig, ax = _figure(f"Software quality: {overall}", title_color)
    rows = series["gates"]
    positions = list(range(len(rows)))
    ax.set_yticks(positions)
    ax.set_yticklabels([row["title"] for row in rows])
    for y, row in zip(positions, rows, strict=True):
        if row["kind"] == "bar":
            _draw_score_bar(ax, float(y), row)
        else:
            _draw_chip(ax, float(y), row)
    ax.set_xlim(0, 100)
    ax.set_xticks([0, 25, 50, 75, 100])
    ax.annotate(
        "0 to 100",
        xy=(1, 0),
        xycoords="axes fraction",
        xytext=(10, -28),
        textcoords="offset points",
        ha="left",
        va="top",
        fontsize=11,
        color=EDGE,
        annotation_clip=False,
    )
    ax.invert_yaxis()
    return _save(fig, path, series)


def render_coverage(snapshot: dict, path: Path) -> dict:
    block = snapshot["coverage"]
    series = {
        "chart": "coverage",
        "measured": block["measured"],
        "floor": block["floor"],
        "state": block["state"],
        "step": block["step"],
        "reported": block["reported"],
        "covered": block["covered"],
        "statements": block["statements"],
    }
    state = block["state"]
    if block["measured"] is None:
        title = f"Coverage: not measured (floor {block['floor']:.0f}%)"
        title_color = FAIL_HEX
        bar_color = FAIL_HEX
    else:
        measured = float(block["measured"])
        floor = float(block["floor"])
        bar_color = SLACK_HEX[slack_band(measured, floor)]
        title_color = bar_color
        if state == "pass":
            title = f"Coverage: {measured:.2f}% (floor {floor:.0f}%)"
        else:
            title = (
                f"Coverage: {measured:.2f}% (step {block['step']}, floor {floor:.0f}%)"
            )
    fig, ax = _figure(title, title_color)
    labels: list[str] = []
    values: list[float] = []
    colors: list[str] = []
    hatches: list[str] = []
    if block["measured"] is not None:
        labels.append("This run")
        values.append(min(100.0, max(0.0, float(block["measured"]))))
        colors.append(bar_color)
        hatches.append("")
    labels.append(f"Floor {block['floor']:.0f}%")
    values.append(float(block["floor"]))
    colors.append(FLOOR_HEX)
    hatches.append("")
    bars = ax.bar(labels, values, color=colors, edgecolor=EDGE, width=0.55)
    for bar, hatch in zip(bars, hatches, strict=True):
        bar.set_hatch(hatch)
    for bar, value in zip(bars, values, strict=True):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            value + 1.5,
            f"{value:.2f}%",
            ha="center",
            va="bottom",
            fontsize=12,
            color=EDGE,
        )
    if block["measured"] is None:
        ax.text(
            0.02,
            0.95,
            "not measured this run",
            transform=ax.transAxes,
            color=FAIL_HEX,
            fontsize=12,
            fontweight="bold",
            va="top",
        )
    ax.set_ylim(0, 100)
    ax.set_ylabel("line coverage %")
    return _save(fig, path, series)


def _render_count(series: dict, path: Path, *, title: str, noun: str) -> dict:
    fig, ax = _figure(title, EDGE)
    count = series["count"]
    if count is None:
        ax.text(
            0.5,
            0.5,
            "n/a",
            transform=ax.transAxes,
            ha="center",
            va="center",
            fontsize=20,
            color=UNKNOWN_HEX,
        )
        ax.set_axis_off()
    else:
        bars = ax.bar([noun], [count], color=NEUTRAL_HEX, edgecolor=EDGE, width=0.45)
        ax.set_ylim(0, max(count * 1.35, 1))
        ax.text(
            bars[0].get_x() + bars[0].get_width() / 2,
            count,
            str(count),
            ha="center",
            va="bottom",
            fontsize=12,
            color=EDGE,
        )
    return _save(fig, path, series)


def render_complexity(snapshot: dict, path: Path) -> dict:
    block = snapshot["complexity"]
    series = {
        "chart": "complexity",
        "count": block["count"],
        "reported": block["reported"],
    }
    return _render_count(
        series, path, title="Complexity allowlisted blocks", noun="Allowlisted"
    )


def render_deadcode(snapshot: dict, path: Path) -> dict:
    block = snapshot["deadcode"]
    series = {
        "chart": "deadcode",
        "count": block["count"],
        "reported": block["reported"],
    }
    return _render_count(
        series, path, title="Dead code allowlisted items", noun="Allowlisted"
    )


def render_deps(snapshot: dict, path: Path) -> dict:
    block = snapshot["deps"]
    series = {"chart": "deps", "count": block["count"], "reported": block["reported"]}
    return _render_count(series, path, title="npm GHSA exceptions", noun="Exceptions")


def duplication_chart_series(snapshot: dict) -> dict:
    """Unmeasured duplication stays a ceiling mark. A measured bar uses slack."""
    block = snapshot["duplication"]
    ceiling = int(block["ceiling"])
    series = {
        "chart": "duplication",
        "ceiling": ceiling,
        "reported": block["reported"],
    }
    percent = block.get("percent")
    if percent is None:
        return series
    measured = float(percent)
    line = 100.0 - float(ceiling)
    series["measured"] = measured
    series["slack"] = slack_band(100.0 - measured, line)
    return series


def render_duplication(snapshot: dict, path: Path) -> dict:
    series = duplication_chart_series(snapshot)
    ceiling = int(series["ceiling"])
    if "slack" not in series:
        fig, ax = _figure(
            f"Duplication ceiling {ceiling}% (configured, not measured)",
            EDGE,
        )
        bars = ax.bar(
            ["Ceiling"], [ceiling], color=NEUTRAL_HEX, edgecolor=EDGE, width=0.45
        )
        ax.set_ylim(0, max(10, ceiling * 1.4))
        ax.set_ylabel("percent")
        ax.text(
            bars[0].get_x() + bars[0].get_width() / 2,
            ceiling,
            f"{ceiling}%",
            ha="center",
            va="bottom",
            fontsize=12,
            color=EDGE,
        )
        return _save(fig, path, series)
    measured = float(series["measured"])
    color = SLACK_HEX[str(series["slack"])]
    drawn = min(100.0, max(0.0, measured))
    fig, ax = _figure(f"Duplication: {measured:.2f}% (ceiling {ceiling}%)", color)
    ax.bar(["This run"], [drawn], color=color, edgecolor="none", width=0.45)
    ax.plot([-0.4, 0.4], [ceiling, ceiling], color=EDGE, linewidth=2.0, zorder=4)
    ax.set_ylim(0, min(100.0, max(10.0, float(ceiling) * 2.0, drawn * 1.35, 4.0)))
    ax.set_ylabel("duplicated lines %")
    ax.text(
        0,
        drawn,
        f"{measured:.2f}%",
        ha="center",
        va="bottom",
        fontsize=12,
        color=EDGE,
    )
    return _save(fig, path, series)


def render_architecture(snapshot: dict, path: Path) -> dict:
    block = snapshot["architecture"]
    series = {
        "chart": "architecture",
        "count": block["count"],
        "reported": block["reported"],
    }
    return _render_count(series, path, title="Architecture contracts", noun="Contracts")


def _table(rows: list[tuple[str, str]]) -> str:
    lines = ["| Field | Value |", "|---|---|"]
    lines.extend(f"| {label} | {value} |" for label, value in rows)
    return "\n".join(lines)


def _image(alt: str, filename: str) -> str:
    return f"![{alt}]({IMAGE_PREFIX}{filename})"


def _pct(value: float) -> str:
    return f"{value:.2f}%"


def _lines(series: dict) -> str:
    covered = series["covered"]
    statements = series["statements"]
    if covered is None or statements is None:
        return "—"
    return f"{covered}/{statements}"


def build_chart_markdown(snapshot: dict, rendered: dict[str, dict]) -> str:
    """Heading, image placeholder, then a table built from the plotted series."""
    status = rendered["status"]
    coverage = rendered["coverage"]
    complexity = rendered["complexity"]
    deadcode = rendered["deadcode"]
    deps = rendered["deps"]
    duplication = rendered["duplication"]
    architecture = rendered["architecture"]
    status_rows = [
        (gate["title"], status_table_value(gate)) for gate in status["gates"]
    ]
    status_rows.append(("Overall", f"**{status['overall']}**"))
    measured = (
        "—" if coverage["measured"] is None else _pct(float(coverage["measured"]))
    )
    parts = [
        "## KPI charts",
        "",
        f"**Overall: {snapshot['overall']}**",
        "",
        "Charts show this run's Software quality numbers. They are not gates and do not change floors.",
        "",
        "### Gate status",
        "",
        _image("Gate status", "status.png"),
        "",
        _table(status_rows),
        "",
        (
            "Coverage bar is the measured percent. Duplication is inverted: "
            "0% draws at 100 and the line is 100 minus the ceiling. "
            "Color is slack against that line. Yellow still passes. "
            "Chips are the gates without a 0 to 100 score."
        ),
        "",
        "### Coverage",
        "",
        _image("Coverage", "coverage.png"),
        "",
        _table(
            [
                ("Line coverage", measured),
                ("Floor (fail_under)", f"{float(coverage['floor']):.0f}%"),
                ("Lines", _lines(coverage)),
                ("Step", coverage["step"]),
                ("Reported", coverage["reported"]),
            ]
        ),
        "",
        "### Complexity allowlist",
        "",
        _image("Complexity allowlist", "complexity.png"),
        "",
        _table(
            [
                ("Allowlisted blocks", _count_cell(complexity["count"])),
                ("Reported", complexity["reported"]),
            ]
        ),
        "",
        "### Dead code allowlist",
        "",
        _image("Dead code allowlist", "deadcode.png"),
        "",
        _table(
            [
                ("Allowlisted items", _count_cell(deadcode["count"])),
                ("Reported", deadcode["reported"]),
            ]
        ),
        "",
        "### Dependency exceptions",
        "",
        _image("Dependency exceptions", "deps.png"),
        "",
        _table(
            [
                ("npm GHSA exceptions", str(deps["count"])),
                ("Reported", deps["reported"]),
            ]
        ),
        "",
        "### Duplication ceiling",
        "",
        _image("Duplication ceiling", "duplication.png"),
        "",
        _table(_duplication_rows(duplication)),
        "",
        _duplication_note(duplication),
        "",
        "### Architecture contracts",
        "",
        _image("Architecture contracts", "architecture.png"),
        "",
        _table(
            [
                ("Contracts", _count_cell(architecture["count"])),
                ("Reported", architecture["reported"]),
            ]
        ),
        "",
        "### Mutation",
        "",
        "Mutation is not part of Software quality. See the Mutation sticky (`mutation-report`).",
        "",
        _table(
            [
                ("Mutation", "—"),
                ("Sticky", "`mutation-report`"),
            ]
        ),
        "",
    ]
    return "\n".join(parts)


def _count_cell(count: int | None) -> str:
    return "n/a" if count is None else str(count)


def _duplication_rows(series: dict) -> list[tuple[str, str]]:
    rows = [
        ("Ceiling", f"{series['ceiling']}%"),
        ("Reported", str(series["reported"])),
    ]
    if "measured" not in series:
        return rows
    return [
        ("Duplicated lines", f"{float(series['measured']):.2f}%"),
        ("Ceiling", f"{series['ceiling']}%"),
        ("Slack", str(series["slack"])),
        ("Reported", str(series["reported"])),
    ]


def _duplication_note(series: dict) -> str:
    if "measured" not in series:
        return "Configured jscpd ceiling only. This chart is not a measured duplication rate."
    return "Color is slack against the ceiling. Yellow still passes."


def render_charts(snapshot: dict, out_dir: Path) -> dict[str, dict]:
    out_dir.mkdir(parents=True, exist_ok=True)
    return {
        "status": render_status(snapshot, out_dir / "status.png"),
        "coverage": render_coverage(snapshot, out_dir / "coverage.png"),
        "complexity": render_complexity(snapshot, out_dir / "complexity.png"),
        "deadcode": render_deadcode(snapshot, out_dir / "deadcode.png"),
        "deps": render_deps(snapshot, out_dir / "deps.png"),
        "duplication": render_duplication(snapshot, out_dir / "duplication.png"),
        "architecture": render_architecture(snapshot, out_dir / "architecture.png"),
    }


def upsert_section(existing: str, section: str) -> str:
    block = f"{START}\n{section.rstrip()}\n{END}\n"
    if START in existing and END in existing:
        pre, rest = existing.split(START, 1)
        _old, post = rest.split(END, 1)
        return pre.rstrip() + "\n\n" + block + post.lstrip("\n")
    if not existing.strip():
        return block
    return existing.rstrip() + "\n\n" + block


def failure_section(overall: str, reason: str) -> str:
    safe = " ".join(reason.split())[:300]
    return "\n".join(
        [
            "## KPI charts",
            "",
            f"**Overall: {overall}**",
            "",
            f"**Chart generation failed:** {safe}. No image is embedded.",
            "",
            "### Mutation",
            "",
            "Mutation is not part of Software quality. See the Mutation sticky (`mutation-report`).",
            "",
            "| Field | Value |",
            "|---|---|",
            "| Mutation | — |",
            "| Sticky | `mutation-report` |",
            "",
        ]
    )


def generate(
    outcomes: dict[str, str],
    *,
    coverage_json: Path,
    floor: float,
    root: Path,
    out_dir: Path,
) -> tuple[str, dict]:
    snapshot = build_snapshot(
        outcomes, coverage_json=coverage_json, floor=floor, root=root
    )
    rendered = render_charts(snapshot, out_dir)
    snapshot["charts"] = rendered
    return build_chart_markdown(snapshot, rendered), snapshot


def resolve_outcomes(outcomes_json: Path) -> dict[str, str]:
    """Prefer the report sidecar so charts cannot diverge from the table."""
    report = _report()
    if outcomes_json.is_file():
        try:
            loaded = report.load_gate_outcomes(outcomes_json)
        except json.JSONDecodeError as exc:
            print(f"ignoring unreadable gate outcomes {outcomes_json}: {exc}")
            loaded = None
        if loaded is not None:
            print(f"gate outcomes from {outcomes_json}")
            return loaded
    print("gate outcomes from Q_* environment")
    return report.outcomes_from_env()


def _write_append(path: Path, section: str) -> None:
    existing = path.read_text(encoding="utf-8") if path.is_file() else ""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(upsert_section(existing, section), encoding="utf-8", newline="\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--append", required=True)
    parser.add_argument("--coverage", default="reports/quality/coverage.json")
    parser.add_argument("--out-dir", default="reports/quality/charts")
    parser.add_argument("--floor", type=float, default=None)
    parser.add_argument("--root", default=str(ROOT))
    parser.add_argument(
        "--outcomes",
        default="",
        help="Gate outcome sidecar. Default: gate-outcomes.json beside --append.",
    )
    args = parser.parse_args()
    root = Path(args.root)
    report = _report()
    floor = (
        args.floor
        if args.floor is not None
        else report.coverage_floor_from_pyproject(root / "pyproject.toml")
    )
    append = Path(args.append)
    outcomes_path = (
        Path(args.outcomes) if args.outcomes else report.gate_outcomes_path(append)
    )
    outcomes = resolve_outcomes(outcomes_path)
    try:
        section, snapshot = generate(
            outcomes,
            coverage_json=Path(args.coverage),
            floor=floor,
            root=root,
            out_dir=Path(args.out_dir),
        )
        snap_path = Path(args.out_dir) / "kpi-snapshot.json"
        snap_path.parent.mkdir(parents=True, exist_ok=True)
        snap_path.write_text(
            json.dumps(snapshot, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
    except Exception as exc:
        traceback.print_exc()
        section = failure_section(report.overall_label(outcomes), str(exc))
        print(f"kpi chart generation failed: {exc}")
    _write_append(append, section)
    print(f"wrote chart section to {append}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
