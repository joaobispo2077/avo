#!/usr/bin/env python3
"""Release-cut quality metrics snapshot.

Two modes:

- ``--write-json`` runs inside the Software quality job and writes a SHA-bound
  artifact. It does not write ``docs/quality-metrics.md``.
- ``--metrics`` runs only on a release cut. It renders that doc from the green
  artifact for the exact tip SHA and exits non-zero when the artifact is
  missing, not green, or bound to a different SHA.

Charts and the markdown are a readout. They do not change floors or gates.
Mutation is copied from counts on this cut's JSON, or shown as an em dash.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import sys
import zlib
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MISSING = "\u2014"
SCHEMA = 2
_SHA = re.compile(r"^[0-9a-f]{40}$")
_RECORDED = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$")
_VERSION = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+(?:[-+][0-9A-Za-z.-]+)?$")
CHART_FILES = (("dashboard", "dashboard.png"),)
LEGACY_CHART_FILES = (
    ("status", "status.png"),
    ("coverage", "coverage.png"),
    ("complexity", "complexity.png"),
    ("deadcode", "deadcode.png"),
    ("deps", "deps.png"),
    ("duplication", "duplication.png"),
    ("architecture", "architecture.png"),
)
_PNG = b"\x89PNG\r\n\x1a\n"


class SnapshotError(Exception):
    """The release cut must not publish a snapshot."""


def _load(name: str, filename: str):
    cached = sys.modules.get(name)
    if cached is not None:
        return cached
    path = Path(__file__).resolve().parent / filename
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _report():
    return _load("avo_ci_write_quality_pr_report", "write_quality_pr_report.py")


def _charts():
    return _load("avo_ci_gen_kpi_charts", "gen_kpi_charts.py")


def _dashboard():
    return _load("avo_ci_quality_dashboard", "quality_dashboard.py")


def _measurements():
    return _load("avo_ci_quality_measurements", "quality_measurements.py")


def _mutation_policy(root: Path) -> dict:
    path = root / "scripts" / "ci" / "mutation-config.json"
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SnapshotError(f"mutation policy unavailable: {path}") from exc
    profile = config.get("light") if isinstance(config, dict) else None
    floor = (
        _dashboard().percentage(profile.get("min_killed_percent"))
        if isinstance(profile, dict)
        else None
    )
    if floor is None:
        raise SnapshotError("mutation policy light profile has no valid floor")
    return {"profile": "light", "floor": floor}


def chart_series(snapshot: dict) -> dict[str, dict]:
    """Series embedded in Phase A chart PNGs. No extra numbers."""
    coverage = snapshot["coverage"]
    return {
        "status": _charts().status_chart_series(snapshot),
        "coverage": {
            "chart": "coverage",
            "measured": coverage["measured"],
            "floor": coverage["floor"],
            "state": coverage["state"],
            "step": coverage["step"],
            "reported": coverage["reported"],
            "covered": coverage["covered"],
            "statements": coverage["statements"],
        },
        "complexity": {
            "chart": "complexity",
            "count": snapshot["complexity"]["count"],
            "reported": snapshot["complexity"]["reported"],
        },
        "deadcode": {
            "chart": "deadcode",
            "count": snapshot["deadcode"]["count"],
            "reported": snapshot["deadcode"]["reported"],
        },
        "deps": {
            "chart": "deps",
            "count": snapshot["deps"]["count"],
            "reported": snapshot["deps"]["reported"],
        },
        "duplication": _charts().duplication_chart_series(snapshot),
        "architecture": {
            "chart": "architecture",
            "count": snapshot["architecture"]["count"],
            "reported": snapshot["architecture"]["reported"],
        },
    }


def build_ci_document(
    outcomes: dict[str, str],
    *,
    coverage_json: Path,
    floor: float,
    root: Path,
    sha: str,
    recorded_at: str,
    run_id: str = "",
    collect_evidence: bool = False,
) -> dict:
    """Freeze Software quality sticky fields for one commit. Mutation stays null."""
    report = _report()
    snapshot = _charts().build_snapshot(
        outcomes, coverage_json=coverage_json, floor=floor, root=root
    )
    gates = []
    for key, title in report.GATES:
        gates.append(
            {
                "key": key,
                "title": title,
                "status": report._label(outcomes.get(key, "")),
                "metric": report.gate_metric(
                    key,
                    coverage_json=coverage_json,
                    floor=floor,
                    root=root,
                    outcome=outcomes.get(key, ""),
                ),
                "checks": report.GATE_POLICY.get(key, ""),
            }
        )
    doc = {
        "schema": SCHEMA,
        "sha": sha.strip().lower(),
        "run_id": str(run_id or os.environ.get("GITHUB_RUN_ID", "")).strip(),
        "recorded_at": recorded_at,
        "overall": snapshot["overall"],
        "floor": floor,
        "gates": gates,
        "series": chart_series(snapshot),
        "mutation_policy": _mutation_policy(root),
        "mutation": None,
    }
    if collect_evidence:
        from coverage import Coverage

        coverage_config = root / "pyproject.toml"
        doc["coverage_precision"] = Coverage(
            config_file=str(coverage_config) if coverage_config.is_file() else False
        ).config.precision
        doc["measurement_evidence"] = _measurements().collect(
            doc, root / "reports/quality"
        )
    doc["series"]["dashboard"] = _dashboard().build_series(doc)
    doc["overall"] = doc["series"]["dashboard"]["overall"]
    return doc


def mutation_view(
    payload: object, sha: str, run_id: str = "", policy: object = None
) -> dict | None:
    """Kill rate from killed/survived counts bound to ``sha``. Never a bare score."""
    if not isinstance(payload, dict):
        return None
    if str(payload.get("sha") or "") != sha:
        return None
    if run_id:
        metric = _dashboard().mutation_metric(
            {
                "sha": sha,
                "run_id": run_id,
                "mutation": payload,
                "mutation_policy": policy,
            }
        )
        if metric["measured"] is None:
            return None
        checker = _dashboard().mutation_checker()
        evaluation = checker.mutation_evaluation(
            payload.get("counts", payload), min_killed_percent=metric["threshold"]
        )
        return {
            "killed": evaluation["counts"]["killed"],
            "survived": evaluation["counts"]["survived"],
            "score": metric["measured"],
            "floor": metric["threshold"],
        }
    killed = payload.get("killed")
    survived = payload.get("survived")
    if type(killed) is not int or type(survived) is not int:
        return None
    if killed < 0 or survived < 0:
        return None
    denom = killed + survived
    if denom <= 0:
        return None
    floor = payload.get("floor")
    shown = None
    if type(floor) in (int, float) and not isinstance(floor, bool):
        shown = float(floor)
    return {
        "killed": killed,
        "survived": survived,
        "score": 100.0 * killed / denom,
        "floor": shown,
    }


def _table(rows: list[tuple[str, str]]) -> str:
    lines = ["| Field | Value |", "|---|---|"]
    lines.extend(f"| {label} | {value} |" for label, value in rows)
    return "\n".join(lines)


def _pct(value: float) -> str:
    return f"{value:.2f}%"


def _count_cell(value: object) -> str:
    if value is None:
        return "n/a"
    return str(value)


def _lines(covered: object, statements: object) -> str:
    if covered is None or statements is None:
        return MISSING
    return f"{covered}/{statements}"


def _chart_tables(series: dict, images: dict[str, str]) -> str:
    status = series["status"]
    coverage = series["coverage"]
    measured = coverage["measured"]
    measured_text = MISSING if measured is None else _pct(float(measured))
    parts = [
        "## Chart series",
        "",
        (
            "Rows are the JSON series from the green run. "
            "A PNG ships only when it embeds that same series."
        ),
        "",
        "### Gate status",
        "",
    ]
    if "status" in images:
        parts.extend([f"![Gate status]({images['status']})", ""])
    status_rows = [
        (gate["title"], _charts().status_table_value(gate)) for gate in status["gates"]
    ]
    status_rows.append(("Overall", f"**{status['overall']}**"))
    parts.extend([_table(status_rows), "", "### Coverage", ""])
    if "coverage" in images:
        parts.extend([f"![Coverage]({images['coverage']})", ""])
    parts.extend(
        [
            _table(
                [
                    ("Line coverage", measured_text),
                    ("Floor (fail_under)", f"{float(coverage['floor']):.0f}%"),
                    ("Lines", _lines(coverage["covered"], coverage["statements"])),
                    ("Step", str(coverage["step"])),
                    ("Reported", str(coverage["reported"])),
                ]
            ),
            "",
            "### Complexity allowlist",
            "",
        ]
    )
    if "complexity" in images:
        parts.extend([f"![Complexity allowlist]({images['complexity']})", ""])
    parts.extend(
        [
            _table(
                [
                    ("Allowlisted blocks", _count_cell(series["complexity"]["count"])),
                    ("Reported", str(series["complexity"]["reported"])),
                ]
            ),
            "",
            "### Dead code allowlist",
            "",
        ]
    )
    if "deadcode" in images:
        parts.extend([f"![Dead code allowlist]({images['deadcode']})", ""])
    parts.extend(
        [
            _table(
                [
                    ("Allowlisted items", _count_cell(series["deadcode"]["count"])),
                    ("Reported", str(series["deadcode"]["reported"])),
                ]
            ),
            "",
            "### Dependency exceptions",
            "",
        ]
    )
    if "deps" in images:
        parts.extend([f"![Dependency exceptions]({images['deps']})", ""])
    parts.extend(
        [
            _table(
                [
                    ("npm GHSA exceptions", _count_cell(series["deps"]["count"])),
                    ("Reported", str(series["deps"]["reported"])),
                ]
            ),
            "",
            "### Duplication ceiling",
            "",
        ]
    )
    if "duplication" in images:
        parts.extend([f"![Duplication ceiling]({images['duplication']})", ""])
    parts.extend(
        [
            _table(_charts()._duplication_rows(series["duplication"])),
            "",
            "### Architecture contracts",
            "",
        ]
    )
    if "architecture" in images:
        parts.extend([f"![Architecture contracts]({images['architecture']})", ""])
    parts.extend(
        [
            _table(
                [
                    ("Contracts", _count_cell(series["architecture"]["count"])),
                    ("Reported", str(series["architecture"]["reported"])),
                ]
            ),
            "",
        ]
    )
    return "\n".join(parts)


def _mutation_section(view: dict | None) -> str:
    if view is None:
        return "\n".join(
            [
                "### Mutation",
                "",
                "No kill rate is stored on this cut's JSON.",
                "",
                _table(
                    [
                        ("Mutation", MISSING),
                        ("Note", "see Mutation sticky (`mutation-report`)"),
                    ]
                ),
                "",
            ]
        )
    score = (
        f"{view['score']:.2f}% (killed {view['killed']}, survived {view['survived']})"
    )
    rows = [
        ("Mutation", score),
        ("Killed", str(view["killed"])),
        ("Survived", str(view["survived"])),
    ]
    if view["floor"] is not None:
        rows.append(("Floor", f"{view['floor']:.0f}%"))
    return "\n".join(["### Mutation", "", _table(rows), ""])


def render_markdown(
    doc: dict,
    *,
    version: str,
    tag: str,
    images: dict[str, str],
    mutation: dict | None,
) -> str:
    metadata = _table(
        [
            ("Version", version),
            ("Tag", tag),
            ("SHA", f"`{doc['sha']}`"),
            ("Recorded (UTC)", str(doc["recorded_at"])),
        ]
    )
    if doc["schema"] == SCHEMA:
        return "\n".join(
            [
                "# Quality metrics",
                "",
                (
                    "Release readout of the exact commit and CI run. "
                    "Measurements and thresholds do not replace mandatory checks."
                ),
                "",
                metadata,
                "",
                _dashboard().markdown(
                    doc,
                    doc["series"]["dashboard"],
                    image=images.get("dashboard", ""),
                ),
            ]
        )
    gate_lines = [
        "| Gate | Status | Metric | What this checks |",
        "|---|---|---|---|",
    ]
    for row in doc["gates"]:
        gate_lines.append(
            f"| {row['title']} | **{row['status']}** | {row['metric']} | {row['checks']} |"
        )
    parts = [
        "# Quality metrics",
        "",
        (
            "Release-cut readout of the green Software quality JSON for this tip SHA. "
            "A missing or SHA-mismatched JSON fails the cut. "
            "These tables and charts do not change floors or replace gates."
        ),
        "",
        metadata,
        "",
        f"**Overall: {doc['overall']}**",
        "",
        "\n".join(gate_lines),
        "",
        (
            f"Coverage fail-under **{float(doc['floor']):.0f}%**. "
            "Mutation is separate from Software quality."
        ),
        "",
        _chart_tables(doc["series"], images),
        _mutation_section(mutation),
    ]
    return "\n".join(parts)


def _load_metrics(path: Path) -> dict:
    if not path.is_file():
        raise SnapshotError(f"quality metrics JSON missing: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SnapshotError(f"quality metrics JSON unreadable: {path}") from exc
    if not isinstance(payload, dict):
        raise SnapshotError(f"quality metrics JSON is not an object: {path}")
    return payload


def _validate_measurements(doc: dict) -> None:
    if "coverage_precision" in doc and (
        type(doc["coverage_precision"]) is not int
        or not 0 <= doc["coverage_precision"] <= 9
    ):
        raise SnapshotError("quality coverage comparison precision invalid")
    if "measurement_evidence" not in doc:
        return
    evidence = doc["measurement_evidence"]
    if (
        not isinstance(evidence, dict)
        or type(evidence.get("schema")) is not int
        or evidence["schema"] != 1
        or not isinstance(evidence.get("metrics"), list)
        or not isinstance(evidence.get("gates"), dict)
        or not isinstance(evidence.get("diagnostics"), dict)
    ):
        raise SnapshotError("quality measurement evidence schema invalid")
    observations = evidence["metrics"]
    if not all(
        isinstance(row, dict)
        and row.get("state") in {"MEASURED", "PARTIAL", "UNAVAILABLE"}
        and all(
            isinstance(row.get(field), str)
            for field in ("title", "value", "scope", "basis")
        )
        and isinstance(row.get("sources"), list)
        for row in observations
    ) or [row.get("key") for row in observations] != list(_measurements().KEYS):
        raise SnapshotError("quality measurement evidence catalog invalid")


def _validate(
    doc: dict, sha: str, version: str, expected_run_id: str = ""
) -> tuple[str, list[dict]]:
    if type(doc.get("schema")) is not int or doc["schema"] not in (1, SCHEMA):
        raise SnapshotError("unsupported quality metrics schema")
    if doc["schema"] == 1 and expected_run_id:
        raise SnapshotError("legacy quality metrics cannot validate a current CI run")
    tip = sha.strip().lower()
    if not _SHA.fullmatch(tip):
        raise SnapshotError(f"release tip SHA is not a commit sha: {sha}")
    bound = str(doc.get("sha") or "").strip().lower()
    if bound != tip:
        raise SnapshotError(
            f"quality metrics SHA mismatch: json has {bound or '(empty)'}, "
            f"release tip is {tip}"
        )
    if doc["schema"] == SCHEMA:
        run_id = doc.get("run_id")
        if not isinstance(run_id, str) or not run_id.strip():
            raise SnapshotError("quality metrics run_id missing")
        if expected_run_id and run_id != str(expected_run_id):
            raise SnapshotError("quality metrics run_id mismatch")
    if doc.get("overall") != "PASS":
        raise SnapshotError(
            f"quality metrics are not green: overall {doc.get('overall')!r}"
        )
    recorded = str(doc.get("recorded_at") or "")
    if not _RECORDED.fullmatch(recorded):
        raise SnapshotError("quality metrics recorded_at is missing or not UTC")
    if not _VERSION.fullmatch(version):
        raise SnapshotError(f"unsafe release version: {version}")
    floor = doc.get("floor")
    if isinstance(floor, bool) or not isinstance(floor, (int, float)):
        raise SnapshotError("quality metrics floor missing")
    report = _report()
    gates = doc.get("gates")
    if not isinstance(gates, list) or len(gates) != len(report.GATES):
        raise SnapshotError(
            "quality metrics gates do not match the Software quality sticky"
        )
    rows: list[dict] = []
    for (key, title), row in zip(report.GATES, gates, strict=True):
        if (
            not isinstance(row, dict)
            or row.get("key") != key
            or row.get("title") != title
        ):
            raise SnapshotError(
                "quality metrics gates do not match the Software quality sticky"
            )
        for field in ("status", "metric", "checks"):
            value = row.get(field)
            if not isinstance(value, str) or value == "":
                raise SnapshotError(f"gate {key} missing {field}")
        if row["status"] != "PASS":
            raise SnapshotError(f"quality metrics gate {key} is {row['status']}")
        rows.append(row)
    series = doc.get("series")
    if not isinstance(series, dict):
        raise SnapshotError("quality metrics chart series missing")
    for key, _filename in LEGACY_CHART_FILES:
        if not isinstance(series.get(key), dict):
            raise SnapshotError(f"quality metrics series missing {key}")
    if doc["schema"] == SCHEMA:
        _validate_measurements(doc)
        policy = doc.get("mutation_policy")
        if (
            not isinstance(policy, dict)
            or policy.get("profile") != "light"
            or _dashboard().percentage(policy.get("floor")) is None
        ):
            raise SnapshotError("quality metrics mutation_policy missing or invalid")
        dashboard = series.get("dashboard")
        if not isinstance(dashboard, dict):
            raise SnapshotError("quality metrics series missing dashboard")
        expected = _dashboard().build_series(doc)
        if dashboard != expected:
            raise SnapshotError("quality metrics dashboard does not match its evidence")
        if expected["overall"] != "PASS":
            raise SnapshotError("quality metrics dashboard is not green")
        jobs = doc.get("jobs")
        readiness = _load("avo_ci_check_ci_readiness", "check_ci_readiness.py")
        results = (
            {key: {"result": value} for key, value in jobs.items()}
            if isinstance(jobs, dict)
            else None
        )
        if failures := readiness.evaluate_needs(results):
            raise SnapshotError(
                f"quality metrics mandatory jobs: {'; '.join(failures)}"
            )
        if not isinstance(jobs, dict) or jobs.get("ci-readiness") != "success":
            raise SnapshotError("quality metrics CI readiness did not succeed")
    return tip, rows


def _split_keyword(data: bytes) -> tuple[str, bytes]:
    if b"\x00" not in data:
        raise SnapshotError("PNG text chunk missing keyword")
    key, rest = data.split(b"\x00", 1)
    return key.decode("latin1"), rest


def png_text(path: Path) -> dict[str, str]:
    blob = path.read_bytes()
    if not blob.startswith(_PNG):
        raise SnapshotError(f"{path} is not a PNG")
    pos = 8
    found: dict[str, str] = {}
    while pos + 8 <= len(blob):
        length = int.from_bytes(blob[pos : pos + 4], "big")
        kind = blob[pos + 4 : pos + 8]
        start = pos + 8
        end = start + length
        if end + 4 > len(blob):
            raise SnapshotError(f"{path} PNG chunk truncated")
        data = blob[start:end]
        pos = end + 4
        if kind == b"IEND":
            break
        if kind == b"tEXt":
            key, rest = _split_keyword(data)
            found[key] = rest.decode("latin1")
        elif kind == b"zTXt":
            key, rest = _split_keyword(data)
            if not rest:
                continue
            payload = zlib.decompress(rest[1:]) if rest[0] == 0 else rest[1:]
            found[key] = payload.decode("latin1")
        elif kind == b"iTXt":
            key, rest = _split_keyword(data)
            if len(rest) < 2:
                continue
            flag = rest[0]
            parts = rest[2:].split(b"\x00", 2)
            if len(parts) < 3:
                continue
            text = zlib.decompress(parts[2]) if flag == 1 else parts[2]
            found[key] = text.decode("utf-8")
    return found


def _png_series(path: Path) -> dict:
    raw = png_text(path).get("Description")
    if not raw:
        raise SnapshotError(f"{path.name} has no chart series")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SnapshotError(f"{path.name} chart series is not JSON") from exc
    if not isinstance(payload, dict):
        raise SnapshotError(f"{path.name} chart series is not an object")
    return payload


def _chart_files(schema: int = SCHEMA) -> tuple[tuple[str, str], ...]:
    return LEGACY_CHART_FILES if schema == 1 else CHART_FILES


def _present_charts(src: Path, schema: int = SCHEMA) -> list[tuple[str, str]]:
    return [(key, name) for key, name in _chart_files(schema) if (src / name).is_file()]


def _matching_charts(src: Path, series: dict, schema: int = SCHEMA) -> None:
    present = _present_charts(src, schema)
    if not present:
        return
    if len(present) != len(_chart_files(schema)):
        names = ", ".join(name for _key, name in present)
        raise SnapshotError(f"partial quality chart set: {names}")
    for key, name in _chart_files(schema):
        got = _png_series(src / name)
        if got != series[key]:
            raise SnapshotError(f"chart {name} does not match quality metrics JSON")


def _image_links(out: Path, dest: Path, schema: int = SCHEMA) -> dict[str, str]:
    links = {}
    for key, name in _chart_files(schema):
        target = dest / name
        rel = Path(os.path.relpath(target, start=out.parent)).as_posix()
        links[key] = rel
    return links


def _resolve_mutation(doc: dict, mutation_path: Path | None, sha: str) -> dict | None:
    run_id = doc.get("run_id", "") if doc["schema"] == SCHEMA else ""
    policy = doc.get("mutation_policy")
    embedded = mutation_view(doc.get("mutation"), sha, run_id, policy)
    if embedded is not None:
        return embedded
    if mutation_path is None or not mutation_path.is_file():
        return None
    try:
        payload = json.loads(mutation_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SnapshotError(
            f"mutation metrics JSON unreadable: {mutation_path}"
        ) from exc
    return mutation_view(payload, sha, run_id, policy)


def write_snapshot(
    metrics_path: Path,
    *,
    sha: str,
    version: str,
    out: Path,
    charts_src: Path | None = None,
    charts_dir: Path | None = None,
    mutation_path: Path | None = None,
    expected_run_id: str = "",
) -> str:
    """Write the readout. Raises SnapshotError before creating outputs."""
    doc = _load_metrics(metrics_path)
    tip, _rows = _validate(doc, sha, version, expected_run_id)
    doc["sha"] = tip
    mutation = _resolve_mutation(doc, mutation_path, tip)
    ship = False
    if charts_src is not None and _present_charts(charts_src, doc["schema"]):
        if charts_dir is None or charts_dir.name != version:
            raise SnapshotError(
                f"chart directory must be docs/quality/charts/{version}"
            )
        _matching_charts(charts_src, doc["series"], doc["schema"])
        ship = True
    tag = version if version.startswith("v") else f"v{version}"
    images = (
        _image_links(out, charts_dir, doc["schema"])
        if ship and charts_dir is not None
        else {}
    )
    text = render_markdown(
        doc, version=version, tag=tag, images=images, mutation=mutation
    )
    if ship and charts_dir is not None and charts_src is not None:
        charts_dir.mkdir(parents=True, exist_ok=True)
        for _key, name in _chart_files(doc["schema"]):
            (charts_dir / name).write_bytes((charts_src / name).read_bytes())
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8", newline="\n")
    return text


def _write_json_file(path: Path, doc: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(doc, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write-json", default="")
    parser.add_argument("--metrics", default="")
    parser.add_argument("--coverage", default="reports/quality/coverage.json")
    parser.add_argument("--root", default=str(ROOT))
    parser.add_argument("--floor", type=float, default=None)
    parser.add_argument("--sha", default="")
    parser.add_argument("--run-id", default="")
    parser.add_argument("--recorded-at", default="")
    parser.add_argument("--version", default="")
    parser.add_argument("--out", default="")
    parser.add_argument("--charts-src", default="")
    parser.add_argument("--charts-dir", default="")
    parser.add_argument("--mutation", default="")
    args = parser.parse_args(argv)
    try:
        if args.write_json:
            return _cmd_write_json(args)
        if args.metrics:
            return _cmd_snapshot(args)
    except SnapshotError as exc:
        print(f"quality metrics snapshot failed: {exc}", file=sys.stderr)
        return 1
    parser.error("pass --write-json or --metrics")
    return 2


def _cmd_write_json(args: argparse.Namespace) -> int:
    report = _report()
    root = Path(args.root)
    floor = (
        args.floor
        if args.floor is not None
        else report.coverage_floor_from_pyproject(root / "pyproject.toml")
    )
    sha = (args.sha or os.environ.get("GITHUB_SHA", "")).strip().lower()
    if os.environ.get("GITHUB_ACTIONS") == "true" and not _SHA.fullmatch(sha):
        print(
            "GITHUB_SHA is missing; refusing quality metrics JSON",
            file=sys.stderr,
        )
        return 1
    recorded = args.recorded_at or datetime.now(timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    if not _RECORDED.fullmatch(recorded):
        print("recorded_at must be UTC YYYY-MM-DDTHH:MM:SSZ", file=sys.stderr)
        return 1
    doc = build_ci_document(
        report.outcomes_from_env(),
        coverage_json=Path(args.coverage),
        floor=floor,
        root=root,
        sha=sha,
        recorded_at=recorded,
        run_id=args.run_id,
        collect_evidence=True,
    )
    _write_json_file(Path(args.write_json), doc)
    print(f"wrote {args.write_json}")
    return 0


def _cmd_snapshot(args: argparse.Namespace) -> int:
    if not args.out or not args.version:
        raise SnapshotError("--out and --version are required")
    write_snapshot(
        Path(args.metrics),
        sha=args.sha,
        version=args.version,
        out=Path(args.out),
        charts_src=Path(args.charts_src) if args.charts_src else None,
        charts_dir=Path(args.charts_dir) if args.charts_dir else None,
        mutation_path=Path(args.mutation) if args.mutation else None,
        expected_run_id=args.run_id,
    )
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
