"""Render source-indexed file coupling from already verified observations."""

from __future__ import annotations

import copy
import html
import json
import math
import os
import re
from collections import defaultdict
from pathlib import Path
from statistics import median
from urllib.parse import quote

REGIONS = {
    "few_connections": "Few internal connections",
    "widely_used": "Widely used / fewer dependencies",
    "many_dependencies": "Many dependencies / fewer consumers",
    "high_connectivity": "High connectivity to inspect",
}
LIMITATIONS = [
    "Distinct static internal module imports, including same-package imports.",
    "External and dynamic imports, runtime calls and architectural health are not measured.",
    "Namespace targets contribute to degrees but are not actual-file points.",
]
AXES = {
    "x": "ce",
    "y": "ca",
    "transform": "piecewise log2(1 + count) around raw median",
    "ticks": "raw counts",
    "quadrants": "equal display area",
    "median_position": 0.5,
    "zero_median": "zero at division; lower numeric range empty",
    "equality": "lower",
}


def context(document: dict, chart: str) -> dict:
    """Keep the supporting view bound to its canonical document identity."""
    supporting = document.get("measurement_evidence", {}).get("supporting", {})
    result = {
        "schema": 1,
        "chart": chart,
        "sha": document.get("sha", ""),
        "run_id": str(document.get("run_id") or ""),
        "mode": document.get("reporting", {}).get("mode", "unavailable"),
        "source_fingerprint": supporting.get("source_fingerprint"),
        "sources": copy.deepcopy(supporting.get("sources", [])),
    }
    definitions = document.get("metric_definitions")
    if isinstance(definitions, dict):
        result["definition_identity"] = {
            key: definitions.get(key) for key in ("catalog_sha256", "policy_sha256")
        }
    return result


def source_url(document: dict, path: str, line: int | None = None) -> str | None:
    """Only verified CI context can claim a measured-revision source link."""
    repository = document.get("repository", "")
    sha = document.get("sha", "")
    parts = path.split("/")
    if (
        document.get("reporting", {}).get("mode") != "ci"
        or not re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9_.-]+", repository
        )
        or repository.split("/")[-1] in {".", ".."}
        or not re.fullmatch(r"[a-fA-F0-9]{40}", sha)
        or not path.startswith("src/avo/")
        or not path.endswith(".py")
        or any(part in {"", ".", ".."} for part in parts)
        or "\\" in path
        or any(ord(character) < 32 for character in path)
    ):
        return None
    anchor = f"#L{line}" if type(line) is int and line > 0 else ""
    return f"https://github.com/{repository}/blob/{sha}/{quote(path, safe='/')}{anchor}"


def safe_text(value: object) -> str:
    text = html.escape(str(value), quote=False).replace("\r", " ").replace("\n", " ")
    for character in ("\\", "|", "[", "]"):
        text = text.replace(character, f"\\{character}")
    return text.replace("`", "&#96;")


def source_label(row: dict, *, function: bool = False) -> str:
    name = row["path"]
    if function:
        name += f":{row['line']} {row['qualname']}"
    label = safe_text(name)
    return f"[{label}]({row['source_url']})" if row.get("source_url") else label


def index_header(series: dict, title: str) -> list[str]:
    lines = [
        f"# {title}",
        "",
        f"State: **{safe_text(series['state'])}**. {safe_text(series['reason'])}",
        "",
        f"Commit: `{safe_text(series['sha'] or 'unavailable')}` · Run: `{safe_text(series['run_id'] or 'unavailable')}` · Mode: `{safe_text(series['mode'])}`",
        "",
        f"Source fingerprint: `{safe_text(series.get('source_fingerprint') or 'unavailable')}`",
        "",
    ]
    for source in series["sources"]:
        lines.append(
            f"- Evidence: {safe_text(source.get('artifact', 'unavailable'))}/{safe_text(source.get('path', 'unavailable'))}; SHA-256 `{safe_text(source.get('sha256', 'unavailable'))}`."
        )
    if "definition_identity" in series:
        for key, digest in series["definition_identity"].items():
            lines.append(f"- Metric definition {key}: `{safe_text(digest)}`.")
    return lines


def write_indexes(series: dict, directory: Path, stem: str, lines: list[str]) -> dict:
    directory.mkdir(parents=True, exist_ok=True)
    paths = {"json": directory / f"{stem}.json", "markdown": directory / f"{stem}.md"}
    paths["json"].write_text(
        json.dumps(series, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    paths["markdown"].write_text("\n".join(lines) + "\n", encoding="utf-8")
    return paths


def _region(ce: int, ca: int, references: dict) -> str:
    if ce > references["ce"]:
        return "high_connectivity" if ca > references["ca"] else "many_dependencies"
    return "widely_used" if ca > references["ca"] else "few_connections"


def build_coupling_series(document: dict) -> dict:
    """Freeze IDs and group membership once, without re-reading source evidence."""
    supporting = document.get("measurement_evidence", {}).get("supporting", {})
    graph = supporting.get("coupling", {}) if supporting.get("schema") == 1 else {}
    series = context(document, "coupling_files")
    series.update(
        state="UNAVAILABLE",
        reason=graph.get("reason") or "Verified file/module coupling is unavailable.",
        grain="actual Python source file",
        scope="src/avo/**/*.py; static internal module imports",
        limitations=LIMITATIONS,
        files=[],
        groups=[],
        namespaces=[],
        file_count=0,
        namespace_count=0,
        node_count=None,
        edge_count=None,
        topology_sha256=None,
        edges=[],
        axes=copy.deepcopy(AXES),
        references={
            "ce": None,
            "ca": None,
            "population": "all measured actual files, including isolates",
            "equality": "lower",
            "role": "informational",
        },
        regions=REGIONS,
    )
    if graph.get("state") != "MEASURED":
        return series
    actual = sorted(
        (row for row in graph["modules"] if row["kind"] == "file"),
        key=lambda row: row["path"],
    )
    if not actual:
        series["reason"] = (
            "No measured actual files; quadrant references are unavailable."
        )
        return series
    series["references"].update(
        ce=median(row["ce"] for row in actual), ca=median(row["ca"] for row in actual)
    )
    grouped = defaultdict(list)
    for index, node in enumerate(actual, 1):
        row = copy.deepcopy(node)
        row.update(
            id=f"F{index:03}",
            source_url=source_url(document, row["path"]),
            region=_region(row["ce"], row["ca"], series["references"]),
        )
        series["files"].append(row)
        grouped[(row["ce"], row["ca"])].append(row["id"])
    for index, ((ce, ca), members) in enumerate(sorted(grouped.items()), 1):
        series["groups"].append(
            {
                "id": f"G{index:02}",
                "ce": ce,
                "ca": ca,
                "file_ids": members,
                "member_count": len(members),
                "region": _region(ce, ca, series["references"]),
            }
        )
    group_ids = {
        identifier: group["id"]
        for group in series["groups"]
        for identifier in group["file_ids"]
    }
    for row in series["files"]:
        row["group_id"] = group_ids[row["id"]]
    series.update(
        state="MEASURED",
        namespaces=copy.deepcopy(
            sorted(
                (row for row in graph["modules"] if row["kind"] == "namespace"),
                key=lambda row: row["module"],
            )
        ),
        file_count=len(actual),
        namespace_count=sum(row["kind"] == "namespace" for row in graph["modules"]),
        node_count=graph["node_count"],
        edge_count=graph["edge_count"],
        topology_sha256=graph["topology_sha256"],
        edges=copy.deepcopy(sorted(graph["edges"])),
    )
    return series


def write_coupling_indexes(series: dict, directory: Path) -> dict:
    lines = index_header(
        series, "AVO file coupling: complete position and source index"
    )
    references = series["references"]
    lines.extend(
        [
            "",
            f"{series['file_count']} actual files; {series['namespace_count']} namespace containers; {series['edge_count']} distinct internal edges.",
            "",
            "CE (horizontal): modules used. CA (vertical): modules using the file.",
            f"Display spacing: {series['axes']['transform']}; tick labels are raw counts. No coordinate jitter.",
            f"Informational median references: CE {references['ce']}, CA {references['ca']}; {references['population']}; equality belongs to the {references['equality']} side. Regions are review cues, not quality gates or architectural verdicts.",
            "",
            *[f"- {item}" for item in series["limitations"]],
            "",
            "## Position to files",
            "",
            "| Position | CE | CA | Members | File IDs | Descriptive region |",
            "|---|---:|---:|---:|---|---|",
        ]
    )
    for group in series["groups"]:
        lines.append(
            f"| {group['id']} | {group['ce']} | {group['ca']} | {group['member_count']} | {', '.join(group['file_ids'])} | {REGIONS[group['region']]} |"
        )
    lines.extend(
        [
            "",
            "## Files to position",
            "",
            "| File | Position | Complete source identity | Module | CA | CE | Instability | Source SHA-256 |",
            "|---|---|---|---|---:|---:|---:|---|",
        ]
    )
    for row in series["files"]:
        instability = (
            "Undefined (0/0)" if row["instability"] is None else str(row["instability"])
        )
        lines.append(
            f"| {row['id']} | {row['group_id']} | {source_label(row)} | {safe_text(row['module'])} | {row['ca']} | {row['ce']} | {instability} | {row['sha256']} |"
        )
    if series["namespaces"]:
        lines.extend(
            [
                "",
                "## Namespace containers (not file points)",
                "",
                "| Module | CA | CE |",
                "|---|---:|---:|",
            ]
        )
        lines.extend(
            f"| {safe_text(row['module'])} | {row['ca']} | {row['ce']} |"
            for row in series["namespaces"]
        )
    return write_indexes(series, directory, "coupling-index", lines)


def _ticks(maximum: int) -> list[int]:
    ticks = [0]
    value = 1
    while value <= maximum:
        ticks.append(value)
        value = 2 * value + 1
    if maximum not in ticks:
        if len(ticks) > 1 and math.log2(1 + maximum) - math.log2(1 + ticks[-1]) < 0.35:
            ticks.pop()
        ticks.append(maximum)
    return ticks


def axis_position(count: float, reference: float, maximum: float) -> float:
    """Disclose median-centered halves without changing raw counts or ordering."""
    value, split = math.log2(1 + count), math.log2(1 + reference)
    if count <= reference:
        return 0.5 * value / split if reference else 0.5
    return 0.5 + 0.5 * (value - split) / (math.log2(1 + maximum) - split)


def _position_index(series: dict, columns: int = 3) -> list[list[tuple]]:
    """Index every position with its first source and explicit remaining count."""
    groups = series["groups"]
    files = {row["id"]: row for row in series["files"]}
    blocks = [[] for _ in range(columns)]
    per_column = math.ceil(len(groups) / columns)
    for index, group in enumerate(groups, 1):
        first = files[group["file_ids"][0]]
        name = first["module"].removeprefix("avo.")
        if len(name) > 24:
            name = "…" + name[-23:]
        others = f" +{group['member_count'] - 1}" if group["member_count"] > 1 else ""
        label = f"{index:02}/{group['id']}  {group['ca']}/{group['ce']} ×{group['member_count']}  {first['id']} {name}{others}"
        blocks[(index - 1) // per_column].append((group["region"], label))
    return blocks


def _number_groups(fig, ax, series: dict, colors: dict) -> None:
    """Number dots directly; only colliding numbers get a short local tether."""
    from matplotlib.transforms import Bbox

    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    pixels = fig.dpi / 72
    bounds = ax.get_window_extent(renderer)
    occupied = [item.get_window_extent(renderer).padded(2) for item in ax.texts]
    max_ce = max(row["ce"] for row in series["files"])
    max_ca = max(row["ca"] for row in series["files"])
    coordinates = [
        (
            axis_position(g["ce"], series["references"]["ce"], max_ce),
            axis_position(g["ca"], series["references"]["ca"], max_ca),
        )
        for g in series["groups"]
    ]
    points = [ax.transData.transform(point) for point in coordinates]
    point_boxes = [Bbox.from_bounds(x - 10, y - 10, 20, 20) for x, y in points]
    for index, (group, point, (x, y)) in enumerate(
        zip(series["groups"], coordinates, points, strict=True), 1
    ):
        label = str(index)
        measured = fig.text(0, 0, label, fontsize=9, fontweight="bold")
        extent = measured.get_window_extent(renderer)
        width, height = extent.width + 2, extent.height + 2
        measured.remove()
        rectangle = Bbox.from_bounds(x - width / 2, y - height / 2, width, height)
        if not any(rectangle.overlaps(other) for other in occupied):
            ax.text(
                *point,
                label,
                ha="center",
                va="center",
                fontsize=9,
                fontweight="bold",
                color="#ffffff",
                zorder=4,
            )
        else:
            candidates = []
            for radius in (12, 18, 24, 30):
                for dx, dy in (
                    (radius, 0),
                    (-radius, 0),
                    (0, radius),
                    (0, -radius),
                    (radius, radius),
                    (-radius, radius),
                    (radius, -radius),
                    (-radius, -radius),
                ):
                    box = Bbox.from_bounds(
                        x + dx * pixels - width / 2,
                        y + dy * pixels - height / 2,
                        width,
                        height,
                    )
                    if not (bounds.contains(*box.p0) and bounds.contains(*box.p1)):
                        continue
                    obstacles = (
                        occupied + point_boxes[: index - 1] + point_boxes[index:]
                    )
                    cost = sum(box.overlaps(other) for other in obstacles)
                    candidates.append((cost, dx * dx + dy * dy, dx, dy, box))
            _cost, _distance, dx, dy, rectangle = min(
                candidates, key=lambda item: item[:2]
            )
            ax.annotate(
                label,
                point,
                xytext=(dx, dy),
                textcoords="offset points",
                ha="center",
                va="center",
                fontsize=9,
                fontweight="bold",
                color=colors[group["region"]],
                zorder=5,
                bbox={"facecolor": "#f8fafc", "edgecolor": "none", "pad": 0.5},
                arrowprops={
                    "arrowstyle": "-",
                    "color": colors[group["region"]],
                    "linewidth": 0.7,
                    "shrinkA": 2,
                    "shrinkB": 4,
                },
            )
        occupied.append(rectangle)


def _image_source_context(series: dict) -> str:
    sha = series["sha"][:10] or "unavailable"
    fingerprint = str(series.get("source_fingerprint") or "unavailable")[:10]
    if series["mode"] == "local-preview":
        source = f"Working-tree preview · source {fingerprint} · HEAD reference {sha}"
    elif series["mode"] == "fixture":
        source = f"Fixture source reference {fingerprint}"
    else:
        source = f"Commit {sha}"
    return f"{source} · Run {series['run_id'] or 'unavailable'}"


def render_coupling(series: dict, path: Path) -> None:
    """Render exact numbered positions and their complete index on one image."""
    path.unlink(missing_ok=True)
    if series["state"] != "MEASURED" or not series["files"]:
        raise ValueError("File coupling is unavailable; no image was produced.")
    if series.get("axes") != AXES:
        raise ValueError("Coupling axis metadata does not describe this renderer.")
    os.environ.setdefault("MPLBACKEND", "Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle

    colors = {
        "widely_used": "#166534",
        "high_connectivity": "#b42318",
        "few_connections": "#926400",
        "many_dependencies": "#166534",
    }
    blocks = _position_index(series)
    line_height = 0.19
    index_height = max(len(block) for block in blocks) * line_height
    plot_height = 6.3
    height = 1.3 + plot_height + 2.65 + index_height + 0.3
    fig = plt.figure(figsize=(14, height), dpi=150)
    plot_bottom = height - 1.3 - plot_height
    ax = fig.add_axes((0.075, plot_bottom / height, 0.90, plot_height / height))
    fig.patch.set_facecolor("#f8fafc")
    ax.set(xlim=(-0.025, 1.025), ylim=(-0.025, 1.025))
    for x, y, color in (
        (-0.025, 0.5, "#e4f0e6"),
        (0.5, 0.5, "#f7e4e1"),
        (-0.025, -0.025, "#f6efd9"),
        (0.5, -0.025, "#e4f0e6"),
    ):
        ax.add_patch(Rectangle((x, y), 0.525, 0.525, facecolor=color, zorder=0))
    ax.axvline(0.5, color="#8b918e", linewidth=1.2)
    ax.axhline(0.5, color="#8b918e", linewidth=1.2)
    max_ce = max(row["ce"] for row in series["files"])
    max_ca = max(row["ca"] for row in series["files"])
    references = series["references"]
    for index, group in enumerate(series["groups"], 1):
        x = axis_position(group["ce"], references["ce"], max_ce)
        y = axis_position(group["ca"], references["ca"], max_ca)
        color = colors[group["region"]]
        ax.scatter(
            [x],
            [y],
            s=150,
            facecolor=color,
            edgecolor="#ffffff",
            linewidth=0.65,
            zorder=3,
        )
    for axis, maximum, reference in (
        (ax.xaxis, max_ce, references["ce"]),
        (ax.yaxis, max_ca, references["ca"]),
    ):
        values = sorted(set(_ticks(maximum) + [reference]))
        axis.set_ticks(
            [axis_position(value, reference, maximum) for value in values],
            [f"{value:g}" for value in values],
        )
    ax.set_xlabel(
        "CE · efferent (uses other modules) →",
        fontsize=12,
        color="#344054",
        labelpad=10,
    )
    ax.set_ylabel(
        "CA · afferent (used by other modules) →",
        fontsize=12,
        color="#344054",
        labelpad=10,
    )
    ax.tick_params(labelsize=11, colors="#344054")
    for spine in ax.spines.values():
        spine.set_color("#a7ada9")
    for x, y, label, region, alignment in (
        (0.47, 0.955, "WIDELY USED\nFewer dependencies", "widely_used", "right"),
        (
            0.53,
            0.955,
            "HIGH CONNECTIVITY\nInspect context",
            "high_connectivity",
            "left",
        ),
        (
            0.015,
            0.08,
            "ISOLATED / EDGE\nFew internal connections",
            "few_connections",
            "left",
        ),
        (
            0.985,
            0.08,
            "MORE DEPENDENCIES\nOrchestration candidates",
            "many_dependencies",
            "right",
        ),
    ):
        ax.text(
            x,
            y,
            label,
            ha=alignment,
            va="center",
            fontsize=10,
            fontweight="bold",
            color=colors[region],
            zorder=2,
        )

    def caption(y_inches, text, **kwargs):
        fig.text(0.075, y_inches / height, text, color="#344054", **kwargs)

    caption(
        height - 0.38,
        "Coupling · afferent (CA) vs efferent (CE)",
        fontsize=20,
        fontweight="bold",
    )
    caption(
        height - 0.70,
        f"{series['file_count']} actual files · {len(series['groups'])} exact positions · {series['edge_count']} distinct internal import edges",
        fontsize=12,
    )
    caption(height - 0.98, _image_source_context(series), fontsize=9.5)
    caption(
        plot_bottom - 0.65,
        f"Informational medians: CE {references['ce']:g} / CA {references['ca']:g}; all actual files including isolates. Equality stays lower.",
        fontsize=11,
    )
    caption(
        plot_bottom - 0.91,
        "Equal quadrants: independently scaled log2(1 + count) halves around medians; raw count ticks. Exact dots; colliding numbers use short tethers.",
        fontsize=10,
    )
    empty = []
    for axis, reference, maximum in (
        ("CE", references["ce"], max_ce),
        ("CA", references["ca"], max_ca),
    ):
        if reference == 0:
            empty.append(f"{axis}: zero at division; lower numeric range empty")
        if maximum == reference:
            empty.append(f"{axis}: upper numeric range empty")
    caption(
        plot_bottom - 1.15,
        "; ".join(empty)
        if empty
        else "Colors describe connectivity, not gates or architectural health. Static internal imports only.",
        fontsize=10,
        fontweight="bold",
    )
    if empty:
        caption(
            plot_bottom - 1.36,
            "Colors describe connectivity, not gates or architectural health. Static imports only.",
            fontsize=10,
        )
    legend_y = plot_bottom - 1.62
    for column, row, region, text in (
        (0, 0, "widely_used", "Widely used: more consumers, fewer dependencies"),
        (
            1,
            0,
            "high_connectivity",
            "High connectivity: many imports and consumers; inspect context",
        ),
        (0, 1, "few_connections", "Isolated / edge: few measured internal connections"),
        (
            1,
            1,
            "many_dependencies",
            "More dependencies: few consumers; orchestration candidate",
        ),
    ):
        fig.text(
            0.075 + column * 0.455,
            (legend_y - row * 0.23) / height,
            "■ " + text,
            fontsize=9,
            color=colors[region],
        )
    caption(
        plot_bottom - 2.16,
        "Position index · dot/G ID · CA/CE (raw counts) · ×file count · first file",
        fontsize=12,
        fontweight="bold",
    )
    caption(
        plot_bottom - 2.42,
        "Short names; +N means other files at this position. Every full path and member: coupling-index.md / .json",
        fontsize=10,
    )
    index_top = plot_bottom - 2.70
    for column, block in enumerate(blocks):
        for index, (region, label) in enumerate(block):
            fig.text(
                0.075 + column * 0.305,
                (index_top - index * line_height) / height,
                label,
                fontsize=8.1,
                color=colors[region],
                family="monospace",
            )
    _number_groups(fig, ax, series, colors)
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
