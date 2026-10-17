"""One evidence-bound quality overview shared by CI and release readouts."""

from __future__ import annotations

import html
import importlib.util
import json
import math
import os
import re
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
    text = html.escape(str(value), quote=False).replace("\r", " ").replace("\n", " ")
    for character in ("\\", "|", "[", "]"):
        text = text.replace(character, "\\" + character)
    return text.replace("`", "&#96;")


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
    label = safe_text(name or f"{path}:{line}")
    historical = dict(doc)
    historical.setdefault("reporting", {"mode": "ci"})
    url = ci_module("avo_ci_coupling_dashboard", "coupling_dashboard.py").source_url(
        historical, path, line
    )
    return f"[{label}]({url})" if url else f"`{label}`"


def evidence_description(value: object) -> str:
    """Omit an oversized optional description as a whole, preserving its record."""
    text = safe_text(value)
    if len(text) > 2000:
        return "Description excerpt omitted for publication size; complete evidence remains in quality-metrics.json."
    return text


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


def build_supporting(doc: dict) -> None:
    coupling = ci_module("avo_ci_coupling_dashboard", "coupling_dashboard.py")
    hotspots = ci_module("avo_ci_quality_hotspots", "quality_hotspots.py")
    measurements = ci_module("avo_ci_quality_measurements", "quality_measurements.py")
    safe_doc = doc
    if "metric_definitions" in doc and (error := measurements.definition_error(doc)):
        doc["metric_definitions_error"] = error
        safe_doc = {
            key: value for key, value in doc.items() if key != "metric_definitions"
        }
    doc.setdefault("series", {}).update(
        coupling_files=coupling.build_coupling_series(safe_doc),
        hotspots=hotspots.build_hotspot_series(safe_doc),
    )


def render_supporting(doc: dict, directory: Path) -> None:
    """Save complete text first; optional images fail independently."""
    roles = (
        (
            "hotspots",
            "quality_hotspots.py",
            "avo_ci_quality_hotspots",
            "hotspots",
            "hotspots.png",
            "write_hotspot_indexes",
            "render_hotspots",
            "hotspots_image_error",
        ),
        (
            "coupling_files",
            "coupling_dashboard.py",
            "avo_ci_coupling_dashboard",
            "coupling",
            "coupling-files.png",
            "write_coupling_indexes",
            "render_coupling",
            "coupling_image_error",
        ),
    )
    doc["support_images"] = {}
    for role, filename, name, folder, image, write, render, error in roles:
        series = doc.get("series", {}).get(role)
        if not series:
            continue
        doc.pop(error, None)
        helper = ci_module(name, filename)
        target = directory / folder
        try:
            getattr(helper, write)(series, target)
            if series.get("state") in {"MEASURED", "PARTIAL"}:
                getattr(helper, render)(series, target / image)
                doc["support_images"][role] = f"kpi-chart:{image}"
            else:
                (target / image).unlink(missing_ok=True)
        except Exception as exc:
            (target / image).unlink(missing_ok=True)
            doc[error] = f"{type(exc).__name__}: supporting image unavailable"


def coupling_spacing(series: dict) -> str:
    axes = series.get("axes", {})
    text = f"Spacing: {safe_text(axes.get('transform', 'Unavailable'))}; ticks show raw counts."
    if axes.get("quadrants") == "equal display area":
        text += " Equal-area halves use independent scales around each median; equal areas do not mean equal numeric ranges."
        if any(series.get("references", {}).get(axis) == 0 for axis in ("ce", "ca")):
            text += " At a zero median the lower numeric range is empty."
    return text


def supporting_markdown(doc: dict) -> list[str]:
    lines = []
    series = doc.get("series", {})
    hotspots = series.get("hotspots", {})
    coupling = series.get("coupling_files", {})
    shared = ci_module("avo_ci_coupling_dashboard", "coupling_dashboard.py")
    if hotspots:
        lines.extend(["", "### Complexity and CRAP review", ""])
        if hotspots.get("state") not in {"MEASURED", "PARTIAL"}:
            lines.append(
                f"Unavailable: {safe_text(hotspots.get('reason', 'No verified function evidence.'))}"
            )
        else:
            population = hotspots["population"]
            lines.extend(
                [
                    f"{population['observed_functions']} observed functions; {population['measured_crap_functions']} measured CRAP; {population['unmeasured_observed_functions']} observed functions unmeasured; {population['source_error_count']} source-analysis errors. "
                    + (
                        "Total population known."
                        if population["total_population_known"]
                        else "Total population unknown beyond observed functions."
                    ),
                    "CRAP reference 30 is informational. Existing complexity policy and exceptions remain separate.",
                    "",
                ]
            )
            image = doc.get("support_images", {}).get("hotspots")
            if image:
                lines.extend([f"![Complexity and CRAP hotspots]({image})", ""])
            elif doc.get("hotspots_image_error"):
                lines.extend(
                    [
                        "Hotspot image unavailable; values and source lookup remain below.",
                        "",
                    ]
                )
            by_id = {row["id"]: row for row in hotspots["functions"]}
            for key, title in (
                ("complexity", "Cyclomatic complexity"),
                ("crap", "CRAP"),
            ):
                ranking = hotspots["rankings"][key]
                lines.extend(
                    [
                        f"**{title}: {ranking['shown']}/{ranking['eligible']} eligible candidates shown**. {ranking['selection']}; ties: {ranking['tie_rule']}.",
                        "",
                        "| ID | Full source identity | Observed value | Unit |",
                        "|---|---|---:|---|",
                    ]
                )
                for identifier in ranking["ids"]:
                    row = by_id[identifier]
                    value = (
                        row["complexity"]
                        if key == "complexity"
                        else row["crap"]["value"]
                    )
                    lines.append(
                        f"| {identifier} | {shared.source_label(row, function=True)} | {value:g} | {ranking['unit']} |"
                    )
                lines.append("")
        lines.extend(
            [
                "",
                "[Complete function index: hotspots.md (text archive)](kpi-detail:hotspots.md)",
                "",
            ]
        )
    if coupling:
        lines.extend(["", "### File coupling: CE / CA", ""])
        if coupling.get("state") != "MEASURED":
            lines.append(
                f"Unavailable: {safe_text(coupling.get('reason', 'No verified file/module evidence.'))}"
            )
        else:
            refs = coupling["references"]
            lines.extend(
                [
                    f"{coupling['file_count']} actual files at {len(coupling['groups'])} positions; {coupling['edge_count']} distinct internal module edges; {coupling['namespace_count']} namespace containers excluded from file points.",
                    f"CE is horizontal (uses others); CA is vertical (used by others). Median references: CE {refs['ce']:g}, CA {refs['ca']:g}; all measured actual files including isolates, equality on the lower side. {coupling_spacing(coupling)} Regions describe connectivity, not architectural health or gate status.",
                    "",
                ]
            )
            image = doc.get("support_images", {}).get("coupling_files")
            if image:
                lines.extend([f"![Indexed file coupling]({image})", ""])
            elif doc.get("coupling_image_error"):
                lines.extend(
                    [
                        "Coupling image unavailable; exact positions and source lookup remain below.",
                        "",
                    ]
                )
            # Keep displayed coordinates and their complete memberships together.
            # Large populations use a deterministic group excerpt with the full text route.
            groups = coupling["groups"]
            selected = []
            member_count = 0
            for group in groups:
                if selected and member_count + group["member_count"] > 80:
                    break
                selected.append(group)
                member_count += group["member_count"]
            lines.extend(
                [
                    f"Lookup excerpt: {len(selected)}/{len(groups)} coordinate groups; {member_count}/{coupling['file_count']} files. Groups ordered by CE then CA; all members of each shown group are retained.",
                    "",
                    "<details>",
                    "<summary>Indexed positions and files (bidirectional lookup)</summary>",
                    "",
                    "| Position | CE | CA | Members | File ID and complete source identity |",
                    "|---|---:|---:|---:|---|",
                ]
            )
            by_id = {row["id"]: row for row in coupling["files"]}
            for group in selected:
                for identifier in group["file_ids"]:
                    row = by_id[identifier]
                    lines.append(
                        f"| {group['id']} | {group['ce']} | {group['ca']} | {group['member_count']} | {identifier}: {shared.source_label(row)} |"
                    )
            lines.extend(["", "</details>", ""])
        lines.extend(
            [
                "",
                "[Complete bidirectional file index: coupling-index.md (text archive)](kpi-detail:coupling-index.md)",
                "",
            ]
        )
    return lines


def bounded_report(lines: list[str], *, limit: int = 48000) -> str:
    """Bound whole diagnostic sections/rows without dropping essential overview."""
    text = "\n".join(lines)
    if len(text) <= limit:
        return text
    # Existing artifacts retain exact full observations and complete supporting indexes.
    # Reduce diagnostics first; do not silently slice a table row or source identity.
    start = text.find("<details>\n<summary>Metric diagnostics and artifacts</summary>")
    if start >= 0:
        end = text.find("</details>", start)
        if end >= 0:
            text = (
                text[:start]
                + "Diagnostic excerpt omitted for publication size. Complete observations and reasons remain in normalized JSON and linked text artifacts.\n"
                + text[end + len("</details>") :]
            )
    for summary, route in (
        (
            "Execution results",
            "complete testcase events and raw JUnit execution artifacts",
        ),
        (
            "Indexed positions and files (bidirectional lookup)",
            "[complete coupling-index.md text archive](kpi-detail:coupling-index.md)",
        ),
    ):
        if len(text) <= limit:
            break
        pattern = (
            r"(?:Lookup excerpt:[^\n]*\n\n)?<details>\s*<summary>"
            + re.escape(summary)
            + r"</summary>.*?</details>"
        )
        text = re.sub(
            pattern,
            f"Inline detail excerpt omitted for publication size; inspect {route}. Full normalized measurements retain all records.",
            text,
            flags=re.DOTALL,
        )
    if len(text) > limit:
        raise ValueError(
            "Essential quality report exceeds publication budget; text fallback required"
        )
    return text


def context_markdown(doc: dict, series: dict) -> list[str]:
    lines = []
    context = doc.get("reporting", {})
    if context:
        if context.get("mode") != "ci":
            lines.extend(
                [
                    "**Local / fixture preview**. This is not CI or release certification.",
                    "",
                ]
            )
        if context.get("pr_number"):
            lines.extend([f"PR: #{context['pr_number']}", ""])
        lines.extend(
            [
                f"PR head: `{context.get('head_sha') or 'Unavailable'}`",
                f"PR base: `{context.get('base_sha') or 'Unavailable'}`",
                f"Tested revision: `{series['sha'] or 'Unavailable'}`",
                f"Attempt: {context.get('run_attempt', 'Unavailable')}. Passed producer evidence may come from earlier attempts of the same run.",
                "",
            ]
        )
    return lines


def execution_case_markdown(execution: dict) -> list[str]:
    lines = []
    cases = execution.get("cases") or []
    noteworthy = [case for case in cases if case["outcome"] != "passed"]
    if noteworthy:
        lines.extend(
            [
                "",
                f"Recorded skip/failure reasons: {min(30, len(noteworthy))}/{len(noteworthy)} non-passing testcase events shown; complete events and full reasons remain in the raw JUnit evidence.",
                "",
                "| Suite / case | Outcome | Recorded reason |",
                "|---|---|---|",
            ]
        )
        for case in noteworthy[:30]:
            identity = ":".join(
                str(case.get(key) or "Unavailable")
                for key in ("suite", "classname", "name")
            )
            reason = case.get("reason") or "Reason unavailable"
            suffix = (
                " (excerpt; full reason in JUnit evidence)"
                if case.get("reason_truncated")
                else ""
            )
            lines.append(
                f"| {safe_text(identity)} | {case['outcome']} | {safe_text(reason)}{suffix} |"
            )
        lines.append("")
    return lines


def findings_markdown(
    doc: dict, observations: list[dict], summaries: list[dict]
) -> list[str]:
    lines = []
    findings = [
        row
        for row in observations
        if row.get("key") in {"dependencies", "deadcode", "architecture", "tree"}
    ]
    if findings or summaries:
        lines.extend(["", "**Findings and accepted debt**", ""])
        for row in findings:
            lines.append(
                f"- {safe_text(row['title'])}: {safe_text(row['value'])} ({safe_text(row.get('state', 'UNAVAILABLE'))}). {evidence_links(doc, row.get('sources', []))}"
            )
        for summary in summaries:

            def shown(key, summary=summary):
                value = summary.get(key)
                return "Unavailable" if value is None else str(value)

            lines.append(
                f"- {safe_text(summary['tool'])}: {shown('configured_entries')} configured entries; {shown('matched_findings')} matched findings; {shown('unique_affected')} unique affected path/name identities; stale: {shown('stale_entries')}; {shown('unwaived_findings')} unwaived findings. Groups are non-additive; these counts are not defect removal."
            )
    return lines


def definition_markdown(doc: dict) -> list[str]:
    measurements = ci_module("avo_ci_quality_measurements", "quality_measurements.py")
    if error := measurements.definition_error(doc):
        return ["", f"Metric-definition identity unavailable: {safe_text(error)}", ""]
    block = doc["metric_definitions"]
    reference = block["reference"]
    path, sha = reference["path"], reference["sha"]
    route = f"`{path}` at `{sha}`"
    if (
        doc.get("reporting", {}).get("mode") == "ci"
        and measurements.validate_reporting_context(doc) is None
    ):
        route = f"[{path}](https://github.com/{doc['repository']}/blob/{sha}/{path})"
    lines = [
        "",
        "**Metric definitions used**",
        "",
        f"Catalog SHA-256: `{block['catalog_sha256']}`. Effective-policy SHA-256: `{block['policy_sha256']}`.",
        f"Reviewed definition source: {route}. Full semantic definitions and frozen policy are retained in the normalized JSON.",
        "",
        "| Metric ID | Definition revision | Definition SHA-256 | Classification / unit |",
        "|---|---:|---|---|",
    ]
    for entry in block["entries"]:
        lines.append(
            f"| {entry['id']} | {entry['revision']} | `{entry['sha256']}` | {safe_text(entry['classification'])}; {safe_text(entry['unit'])} |"
        )
    lines.extend(
        [
            "",
            "Definition revision, artifact schema and measured repository values are separate. Ordinary snapshot tests never rewrite their reviewed baselines.",
            "",
        ]
    )
    return lines


def markdown(doc: dict, series: dict, *, image: str = "") -> str:
    lines = [
        "## AVO quality",
        "",
        f"**Overall: {series['overall']}**",
        "",
        f"Commit: `{series['sha'] or 'unavailable'}` · Run: `{series['run_id'] or 'unavailable'}`",
        "",
    ]
    lines.extend(context_markdown(doc, series))
    if series["actions"]:
        lines.extend(["**Required action**", ""])
        lines.extend(f"- {safe_text(item)}" for item in series["actions"])
        lines.append("")
    else:
        lines.extend(["All mandatory gate decisions and required jobs passed.", ""])
    if image:
        lines.extend([f"![Quality dashboard]({image})", ""])
    elif doc.get("image_error"):
        lines.extend(
            ["Dashboard image unavailable; current measurements remain in text.", ""]
        )
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
        ]
    )
    unavailable = [
        safe_text(row["title"])
        for row in observations
        if row.get("state") not in {"MEASURED", "PARTIAL"}
    ]
    if unavailable:
        lines.extend(["Unavailable evidence: " + "; ".join(unavailable) + ".", ""])
    lines.extend(["| Metric | Measured | Scope | Evidence |", "|---|---|---|---|"])
    for metric in observations:
        if "hotspots" in doc.get("series", {}) and metric.get("key") not in {
            "coverage",
            "duplication",
            "mutation",
        }:
            continue
        suffix = " (partial)" if metric.get("state") == "PARTIAL" else ""
        lines.append(
            f"| {safe_text(metric['title'])} | {safe_text(metric['value'])}{suffix} | {safe_text(metric['scope'])} | {evidence_description(metric['basis'])} {evidence_links(doc, metric.get('sources', []))} |"
        )
    lines.extend(supporting_markdown(doc))
    evidence = doc.get("measurement_evidence", {})
    summaries = evidence.get("diagnostics", {}).get("exception_summaries", [])
    lines.extend(findings_markdown(doc, observations, summaries))
    policy = ci_module(
        "avo_ci_write_quality_pr_report", "write_quality_pr_report.py"
    ).GATE_POLICY
    executions = doc.get("test_evidence", {})
    if executions:
        lines.extend(["", "**Executed test evidence**", ""])
        for job, execution in executions.items():
            counts = execution.get("counts")
            summary = (
                f"{counts['passed']} passed / {counts['failed']} failed / {counts['errors']} errors / {counts['skipped']} skipped; {counts['total']} testcase events"
                if counts
                else "Testcase counts unavailable"
            )
            lines.append(
                f"- {safe_text(job)}: {summary}. {safe_text(execution.get('state', 'UNAVAILABLE'))}. Repeated events are not additional unique tests."
            )
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
    for job in doc.get("jobs", {}):
        lines.extend(execution_case_markdown(doc.get("test_evidence", {}).get(job, {})))
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
    secondary = [
        row
        for row in observations
        if row.get("key") not in {"coverage", "duplication", "mutation"}
    ]
    lines.extend(definition_markdown(doc))
    if secondary and "hotspots" in doc.get("series", {}):
        lines.extend(
            [
                "| Informational observation | Measured | Scope / completeness | Evidence |",
                "|---|---|---|---|",
            ]
        )
        for row in secondary:
            lines.append(
                f"| {safe_text(row['title'])} | {safe_text(row['value'])} ({safe_text(row.get('state', 'UNAVAILABLE'))}) | {safe_text(row['scope'])}. {safe_text(row['basis'])} | {evidence_links(doc, row.get('sources', []))} |"
            )
        lines.append("")
    for summary in summaries:
        members = summary.get("members", [])
        lines.extend(
            [
                f"**{safe_text(summary['tool'])} accepted exceptions: {min(30, len(members))}/{len(members)} observed matches shown**; order retained from analyzer. Complete entries/reasons are in its evidence artifact.",
                "",
                "| Source identity | Disposition | Recorded rationale |",
                "|---|---|---|",
            ]
        )
        for member in members[:30]:
            identity = f"{member.get('path', 'Unavailable')}:{member.get('line', 'Unavailable')} {member.get('name', 'Unavailable')}"
            lines.append(
                f"| {safe_text(identity)} | {safe_text(member.get('disposition', 'Unavailable'))} | {safe_text(member.get('reason') or 'Rationale unavailable')} |"
            )
        lines.append("")
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
    if functions and "hotspots" not in doc.get("series", {}):
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
    return bounded_report(lines)


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
