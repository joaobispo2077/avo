"""Export honest fixture previews through the real producers and report helpers."""

from __future__ import annotations

import copy
import html
import json
import os
import re
import sys
from pathlib import Path
from random import Random

import pytest
from scripts.ci import (
    check_ci_readiness,
    quality_dashboard,
    quality_measurements,
    quality_metric_definitions,
    run_quality_gate,
)

ROOT = Path(__file__).resolve().parents[1]
CASES_PATH = ROOT / "tests/fixtures/quality_metrics/preview-cases.json"
CASES = json.loads(CASES_PATH.read_text(encoding="utf-8"))["cases"]
SHA = "a" * 40


def _write_toy_sources(root: Path, kind: str) -> list[str]:
    source = root / "src" / "avo"
    source.mkdir(parents=True, exist_ok=True)
    files = {
        "__init__.py": "",
        "core.py": "def choose(value):\n    if value:\n        return 1\n    return 0\n\ndef identity(value):\n    return value\n",
        "worker.py": "from .core import choose\n\ndef pipeline(value):\n    return choose(value)\n",
        "isolate.py": "def isolated(value):\n    return value\n",
        "hotspot.py": "def decide(value):\n"
        + "".join(
            f"    if value == {index}:\n        return {index}\n" for index in range(12)
        )
        + "    return -1\n",
    }
    if kind == "omitted-coverage":
        files["unmeasured.py"] = "def omitted(value):\n    return value\n"
    if kind == "parse-error":
        files["broken.py"] = "def unfinished(:\n"
    if kind == "crowded":
        random = Random(17)
        names = [f"module_{index:03}" for index in range(120)]
        for index, name in enumerate(names):
            targets = random.sample(
                [target for target in names if target != name], index % 16
            )
            files[f"{name}.py"] = (
                "".join(f"import avo.{target}\n" for target in targets)
                + "\ndef act(value):\n    return value\n"
            )
        files["long_source_identity_" * 5 + ".py"] = (
            "def repeated_name(value):\n    return value\n"
        )
    for name, contents in files.items():
        (source / name).write_text(contents, encoding="utf-8")
    return [
        Path(name).stem
        for name in files
        if name not in {"__init__.py", "broken.py", "unmeasured.py"}
    ]


def _capture(
    root: Path,
    directory: Path,
    gate: str,
    command: list[str],
    artifacts: list[str],
    run_id: str,
) -> int:
    arguments = [
        "--gate",
        gate,
        "--out-dir",
        str(directory / "gates"),
        "--sha",
        SHA,
        "--run-id",
        run_id,
    ]
    for filename in artifacts:
        arguments += ["--artifact", str(directory / filename)]
    result = run_quality_gate.main([*arguments, "--", *command])
    checked = run_quality_gate.validate_receipt(
        directory / "gates" / gate / "gate.json",
        sha=SHA,
        run_id=run_id,
        gate=gate,
        artifact_root=directory,
    )
    assert checked["valid"], checked["reason"]
    assert all(not record.get("reason") for record in checked["receipt"]["artifacts"])
    return result


def _produce_evidence(
    case: dict, root: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[dict, Path]:
    kind = case["source_case"]
    names = _write_toy_sources(root, kind)
    directory = root / "reports" / "quality"
    directory.mkdir(parents=True, exist_ok=True)
    run_id = "preview-" + case["id"]
    with monkeypatch.context() as patch:
        patch.setattr(run_quality_gate, "ROOT", root)
        patch.setattr(run_quality_gate, "_tee", lambda _chunk: None)
        patch.setenv("GITHUB_ACTIONS", "false")
        # The primary coverage population is deliberately hypothetical. Function
        # coverage below is actually observed, then bound by the production wrapper.
        omitted = [
            str(root / "src/avo" / name) for name in ("broken.py", "unmeasured.py")
        ]
        coverage_script = (
            "import sys,os,time,importlib,json,coverage; from pathlib import Path; "
            f"sys.path.insert(0,{str(root / 'src')!r}); "
            f"cov=coverage.Coverage(source=[{str(root / 'src/avo')!r}],omit={omitted!r},data_file=None,config_file=False); cov.start(); "
            f"modules=[importlib.import_module('avo.'+name) for name in {names!r}]; "
            "from avo.core import choose,identity; from avo.worker import pipeline; from avo.hotspot import decide; "
            "assert choose(True)==1 and identity(3)==3 and pipeline(True)==1 and decide(0)==0; "
            "cov.stop(); "
            f"output=Path({str(directory / 'coverage.json')!r}); cov.json_report(outfile=str(output)); now=time.time_ns(); os.utime(output,ns=(now,now)); "
            f"Path({str(directory / 'presentation-primary.json')!r}).write_text({json.dumps(case)!r},encoding='utf-8'); "
            "print('Fixture: actual toy function coverage; primary counts are hypothetical presentation inputs.'); "
            f"sys.exit({0 if round(case['coverage']['covered'] / case['coverage']['total'] * 100) >= 68 else 1})"
        )
        coverage_code = _capture(
            root,
            directory,
            "coverage",
            [sys.executable, "-c", coverage_script],
            ["coverage.json", "presentation-primary.json"],
            run_id,
        )
        duplication = case["duplication"]
        percentage = duplication["duplicated"] / duplication["total"] * 100
        payload = {
            "statistics": {
                "total": {
                    "duplicatedLines": duplication["duplicated"],
                    "lines": duplication["total"],
                    "percentage": percentage,
                }
            },
            "duplicates": [],
        }
        target = directory / "jscpd/jscpd-report.json"
        script = (
            "import sys; from pathlib import Path; "
            + f"p=Path({str(target)!r}); p.parent.mkdir(parents=True,exist_ok=True); p.write_text({json.dumps(payload)!r},encoding='utf-8'); "
            + "print('Controlled hypothetical duplication population; no jscpd execution claimed.'); "
            + f"sys.exit({0 if percentage <= 2 else 1})"
        )
        duplication_code = _capture(
            root,
            directory,
            "duplication",
            [sys.executable, "-c", script],
            ["jscpd/jscpd-report.json"],
            run_id,
        )
        risk_command = [
            sys.executable,
            str(ROOT / "scripts/ci/measure_code_risk.py"),
            "--root",
            str(root),
            "--coverage",
            str(directory / "coverage.json"),
            "--coverage-receipt",
            str(directory / "gates/coverage/gate.json"),
            "--out",
            str(directory / "code-risk.json"),
            "--sha",
            SHA,
            "--run-id",
            run_id,
            "--test-outcome",
            "success" if coverage_code == 0 else "failure",
        ]
        assert (
            _capture(
                root, directory, "code-risk", risk_command, ["code-risk.json"], run_id
            )
            == 0
        )
    if kind == "missing-receipt":
        (directory / "gates/code-risk/gate.json").unlink()
    document = {
        "schema": 2,
        "sha": SHA,
        "run_id": run_id,
        "recorded_at": "2026-10-16T12:00:00Z",
        "repository": "",
        "reporting": {"schema": 1, "mode": "fixture"},
        "overall": "PASS",
        "series": {"coverage": {"floor": 68}, "duplication": {"ceiling": 2}},
        "coverage_precision": 0,
        "floor": 68,
        "mutation_policy": {"profile": "light", "floor": 40},
        "gates": [
            {
                "key": key,
                "title": title,
                "status": "PASS" if code == 0 else "FAIL",
                "checks": "Controlled presentation scenario; no AVO CI certification.",
            }
            for key, title, code in (
                ("coverage", "Coverage", coverage_code),
                ("duplication", "Duplication", duplication_code),
            )
        ],
        "jobs": {
            name: "success"
            for name in (*check_ci_readiness.MANDATORY_JOBS, "ci-readiness")
        },
        "fixture": {
            "case": case["id"],
            "primary_population": "hypothetical",
            "supporting_population": "actually measured generated toy Python files",
            "purpose": "Design review only; no current AVO product measurements or CI certification.",
        },
    }
    document["jobs"]["repo-integration-tests"] = case.get(
        "integration_result", "success"
    )
    evidence = quality_measurements.collect(document, directory)
    primary_source = quality_measurements.reference(
        directory / "presentation-primary.json", directory
    )
    for row in evidence["metrics"]:
        if row["key"] == "coverage":
            value = case["coverage"]["covered"] / case["coverage"]["total"] * 100
            quality_measurements.measured(
                row,
                f"{value:.2f}%",
                f"Controlled presentation fixture: {case['coverage']['covered']}/{case['coverage']['total']} hypothetical executable lines; not an AVO coverage observation.",
                [primary_source],
                number=value,
                unit="percent",
            )
            row["scope"] = "hypothetical primary presentation population"
        elif row["key"] == "duplication":
            row["basis"] = (
                "Controlled hypothetical source-line population; no jscpd execution or current AVO result is claimed."
            )
            row["scope"] = "hypothetical primary presentation population"
    mutation = {
        "sha": SHA,
        "run_id": run_id,
        "profile": "light",
        "floor": 40,
        **case["mutation"],
        "total": sum(case["mutation"].values()),
    }
    mutation_path = directory / "mutation-metrics.json"
    mutation_path.write_text(json.dumps(mutation), encoding="utf-8")
    document["mutation"] = mutation
    document["measurement_evidence"] = evidence
    quality_measurements.add_mutation(evidence, document, mutation_path)
    mutation_row = next(row for row in evidence["metrics"] if row["key"] == "mutation")
    mutation_row["scope"] = (
        "hypothetical primary presentation population; light profile"
    )
    mutation_row["basis"] = (
        "Controlled complete mutation counters, not a current AVO mutation run. "
        + mutation_row["basis"]
    )
    document["series"]["dashboard"] = quality_dashboard.build_series(document)
    document["overall"] = document["series"]["dashboard"]["overall"]
    document["metric_definitions"] = quality_metric_definitions.build_definitions(
        document
    )
    quality_dashboard.build_supporting(document)
    return document, directory


def _html(markdown: str, *, title: str, images: bool = True) -> str:
    from markdown_it import MarkdownIt

    replacements = {
        "kpi-chart:dashboard.png": "dashboard.png",
        "kpi-chart:hotspots.png": "hotspots/hotspots.png",
        "kpi-chart:coupling-files.png": "coupling/coupling-files.png",
        "kpi-detail:hotspots.md": "hotspots/hotspots.md",
        "kpi-detail:coupling-index.md": "coupling/coupling-index.md",
        "kpi-chart:mutation-efficacy.png": "mutation/mutation-efficacy.png",
        "kpi-chart:gate-decisions.png": "decisions/gate-decisions.png",
        "kpi-detail:mutation-efficacy.md": "mutation/mutation-efficacy.md",
        "kpi-detail:gate-decisions.md": "decisions/gate-decisions.md",
    }
    for original, relative in replacements.items():
        markdown = markdown.replace(original, relative)
    if not images:
        markdown = re.sub(
            r"!\[[^\]]*\]\([^)]*\)",
            "Image intentionally disabled; the values and source lookup remain in text.",
            markdown,
        )
    renderer = MarkdownIt("commonmark", {"html": True}).enable("table")
    body = renderer.render(markdown)
    body = body.replace(
        "<table>",
        '<div class="table-scroll" tabindex="0" role="region" aria-label="Scrollable evidence table"><table>',
    ).replace("</table>", "</table></div>")
    return (
        "<!doctype html><html lang='en'><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>"
        + html.escape(title)
        + "</title><style>"
        + """
      *{box-sizing:border-box}body{margin:0;padding:24px;background:#0d1117;color:#e6edf3;font:16px/1.6 system-ui,sans-serif}
      main{max-width:1000px;margin:auto;min-width:0}h1,h2,h3{line-height:1.3}h2{border-bottom:1px solid #30363d;padding-bottom:8px}
      a{color:#79c0ff;overflow-wrap:anywhere}p,li,summary{overflow-wrap:anywhere}code{background:#21262d;border-radius:4px;padding:2px 4px;overflow-wrap:anywhere}
      pre{overflow:auto;background:#161b22;padding:12px}img{display:block;max-width:100%;height:auto;border-radius:8px;margin:16px 0}
      .table-scroll{max-width:100%;overflow:auto;margin:12px 0;border:1px solid #30363d;border-radius:6px}table{border-collapse:collapse;min-width:620px;width:100%;font-size:14px}
      th,td{padding:9px 12px;text-align:left;border-bottom:1px solid #30363d;vertical-align:top}th{background:#161b22}details{margin:16px 0}summary{cursor:pointer;font-weight:600}
      :focus-visible{outline:3px solid #79c0ff;outline-offset:3px}.fixture-note{border-left:4px solid #d29922;background:#161b22;padding:12px 16px}
      @media(max-width:600px){body{padding:12px}h2{font-size:22px}h3{font-size:19px}table{font-size:13px}}
      @media(prefers-color-scheme:light){body{background:#fff;color:#1f2328}a{color:#0550ae}code{background:#f0f2f4}pre,th,.fixture-note{background:#f6f8fa}}
    """
        + "</style><main>"
        + body
        + "</main></html>"
    )


def export_preview(
    case: dict, directory: Path, monkeypatch: pytest.MonkeyPatch
) -> dict:
    """Export actual production views for local browser review, never publication."""
    directory = directory.resolve()
    directory.mkdir(parents=True, exist_ok=True)
    document, _evidence = _produce_evidence(
        case, directory / "fixture-source", monkeypatch
    )
    with monkeypatch.context() as patch:
        if case.get("disable_images"):

            def unavailable(*_args, **_kwargs):
                raise OSError(
                    "Images deliberately disabled for preview failure testing."
                )

            patch.setattr(quality_dashboard, "render", unavailable)
            patch.setattr(
                quality_dashboard.ci_module(
                    "avo_ci_coupling_dashboard", "coupling_dashboard.py"
                ),
                "render_coupling",
                unavailable,
            )
            patch.setattr(
                quality_dashboard.ci_module(
                    "avo_ci_quality_hotspots", "quality_hotspots.py"
                ),
                "render_hotspots",
                unavailable,
            )
            for module_name, filename, function in (
                (
                    "avo_ci_quality_mutation_dashboard",
                    "quality_mutation_dashboard.py",
                    "render_mutation",
                ),
                (
                    "avo_ci_quality_gate_decisions",
                    "quality_gate_decisions.py",
                    "render_gates",
                ),
            ):
                patch.setattr(
                    quality_dashboard.ci_module(module_name, filename),
                    function,
                    unavailable,
                )
        try:
            quality_dashboard.render(
                document["series"]["dashboard"], directory / "dashboard.png"
            )
            primary_image = "kpi-chart:dashboard.png"
        except Exception:
            primary_image = ""
            document["image_error"] = (
                "Preview image unavailable; measurements remain in text."
            )
            (directory / "dashboard.png").unlink(missing_ok=True)
        quality_dashboard.render_supporting(document, directory)
    markdown = quality_dashboard.markdown(
        document, document["series"]["dashboard"], image=primary_image
    )
    introduction = f"**Controlled fixture, not AVO CI evidence.** {case['title']}. Primary scores/outcomes are hypothetical.\n\n<details><summary>Preview evidence and limits</summary>\n\nFile coupling, complexity and eligible function CRAP come from actually executed producers over the generated toy sources saved beside this report. No native upload or release certification is authorized.\n\n</details>\n\n"
    markdown = introduction + markdown
    (directory / "quality-gates.md").write_text(markdown, encoding="utf-8")
    (directory / "quality-metrics.json").write_text(
        json.dumps(document, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    for images, filename in ((True, "report.html"), (False, "report-no-images.html")):
        (directory / filename).write_text(
            _html(markdown, title=case["title"], images=images), encoding="utf-8"
        )
    return document


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["id"])
def test_export_current_text_and_graphics_from_real_toy_evidence(
    case, tmp_path_factory, monkeypatch
):
    from PIL import Image

    directory = tmp_path_factory.getbasetemp() / "review" / case["id"]
    baseline = copy.deepcopy(case)
    document = export_preview(case, directory, monkeypatch)
    assert case == baseline
    assert document["reporting"]["mode"] == "fixture"
    assert document["overall"] == case["expected"]["overall"]
    assert [
        metric["band"] for metric in document["series"]["dashboard"]["metrics"]
    ] == case["expected"]["bands"]
    for role, expected_key, folder, image, index in (
        (
            "coupling_files",
            "coupling",
            "coupling",
            "coupling-files.png",
            "coupling-index",
        ),
        ("hotspots", "hotspots", "hotspots", "hotspots.png", "hotspots"),
    ):
        series = document["series"][role]
        assert series["state"] == case["expected"][expected_key]
        assert series["definition_identity"] == {
            key: document["metric_definitions"][key]
            for key in ("catalog_sha256", "policy_sha256")
        }
        assert (
            json.loads(
                (directory / folder / f"{index}.json").read_text(encoding="utf-8")
            )
            == series
        )
        assert (directory / folder / f"{index}.md").is_file()
        path = directory / folder / image
        if case.get("disable_images") or series["state"] == "UNAVAILABLE":
            assert not path.exists()
        else:
            with Image.open(path) as png:
                assert json.loads(png.info["Description"]) == series
    text = (directory / "quality-gates.md").read_text(encoding="utf-8")
    assert "Controlled fixture, not AVO CI evidence" in text
    assert "hypothetical" in text and "File coupling" in text
    no_images = (directory / "report-no-images.html").read_text(encoding="utf-8")
    assert "<img" not in no_images and "<table>" in no_images
    assert "<script" not in no_images and "cdn." not in no_images
    assert document["run_id"] in no_images and SHA in no_images
    if case["id"] == "crowded":
        assert document["series"]["coupling_files"]["file_count"] >= 120
        assert any(
            group["member_count"] > 1
            for group in document["series"]["coupling_files"]["groups"]
        )
    elif case["id"] == "partial":
        assert (
            document["series"]["hotspots"]["population"]["total_population_known"]
            is True
        )
        assert (
            document["series"]["hotspots"]["population"][
                "unmeasured_observed_functions"
            ]
            == 1
        )
    elif case["id"] == "unknown-population":
        assert (
            document["series"]["hotspots"]["population"]["total_population_known"]
            is False
        )
        assert document["series"]["hotspots"]["population"]["source_error_count"] == 1
    elif case["id"] == "image-failure":
        assert (
            "image_error" in document
            and "hotspots_image_error" in document
            and "coupling_image_error" in document
        )
        assert "82.00%" in text and "U0001" in text and "F001" in text


def test_preview_source_function_values_have_independent_small_expectations(
    tmp_path, monkeypatch
):
    document, _directory = _produce_evidence(CASES[0], tmp_path, monkeypatch)
    records = document["measurement_evidence"]["supporting"]["functions"]["records"]
    choose = next(
        row
        for row in records
        if row["module"] == "avo.core" and row["qualname"] == "choose"
    )
    assert choose["complexity"] == 2
    assert choose["function_coverage"]["covered_lines"] == 2
    assert choose["function_coverage"]["num_statements"] == 3
    assert choose["crap"]["value"] == pytest.approx(2 + 4 / 27, rel=0, abs=1e-10)
    assert document["series"]["coupling_files"]["file_count"] == 5
    worker = next(
        row
        for row in document["series"]["coupling_files"]["files"]
        if row["module"] == "avo.worker"
    )
    assert worker["ce"] == 1 and worker["ca"] == 0
    core = next(
        row
        for row in document["series"]["coupling_files"]["files"]
        if row["module"] == "avo.core"
    )
    assert core["ca"] == 1 and core["ce"] == 0


@pytest.mark.parametrize("host_actions", ["false", "true"], ids=["local", "hosted"])
def test_both_reporting_entrypoints_consume_actual_captured_support(
    tmp_path, monkeypatch, host_actions
):
    from PIL import Image
    from scripts.ci import gen_kpi_charts, write_unified_quality_report
    from scripts.ci.write_quality_pr_report import GATES

    monkeypatch.setenv("GITHUB_ACTIONS", host_actions)
    monkeypatch.setenv("GITHUB_REPOSITORY", "host/avo")
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "3")
    monkeypatch.setenv("GITHUB_EVENT_NAME", "pull_request")
    event = tmp_path / "host-event.json"
    event.write_text(
        json.dumps(
            {
                "number": 100,
                "pull_request": {
                    "head": {"sha": "b" * 40},
                    "base": {"sha": "c" * 40},
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event))
    document, evidence = _produce_evidence(CASES[0], tmp_path / "source", monkeypatch)
    document.pop(
        "reporting", None
    )  # Historical input; current writer creates its own context.
    document.update(floor=68, coverage_precision=0)  # Explicit controlled policy.
    known = {row["key"]: row for row in document["gates"]}
    document["gates"] = [
        known.get(key, {"key": key, "title": title, "status": "UNKNOWN"})
        for key, title in GATES
    ]
    assert write_unified_quality_report.quality_evidence(
        document, SHA, document["run_id"]
    )
    quality = evidence / "quality-metrics.json"
    quality.write_text(json.dumps(document), encoding="utf-8")
    with monkeypatch.context() as preview:
        preview.setenv("GITHUB_ACTIONS", "false")
        for name in (
            "GITHUB_REPOSITORY",
            "GITHUB_EVENT_NAME",
            "GITHUB_EVENT_PATH",
            "GITHUB_RUN_ATTEMPT",
        ):
            preview.delenv(name, raising=False)
        combined = write_unified_quality_report.combine(
            quality, None, sha=SHA, run_id=document["run_id"], needs={}
        )
    assert combined["reporting"] == {"schema": 1, "mode": "local-preview"}
    assert os.environ["GITHUB_ACTIONS"] == host_actions
    assert os.environ["GITHUB_EVENT_NAME"] == "pull_request"
    assert combined["overall"] != "PASS"  # Missing jobs never become fixture success.
    assert combined["series"]["coupling_files"]["file_count"] == 5
    assert combined["series"]["hotspots"]["population"]["observed_functions"] == 5
    definitions = combined["metric_definitions"]
    assert definitions["reference"]["sha"] == combined["sha"] == SHA
    assert definitions["policy"]["coverage_floor"] == combined["floor"] == 68
    for role in ("coupling_files", "hotspots"):
        assert combined["series"][role]["definition_identity"] == {
            key: definitions[key] for key in ("catalog_sha256", "policy_sha256")
        }
    assert (
        combined["series"]["coupling_files"]["source_fingerprint"]
        == document["series"]["coupling_files"]["source_fingerprint"]
    )
    output = tmp_path / "entrypoints"
    text, frozen = gen_kpi_charts.generate_dashboard(
        {},
        coverage_json=evidence / "coverage.json",
        floor=68,
        root=tmp_path / "source",
        out_dir=output / "charts",
        document=combined,
    )
    assert "F001" in text and "U0001" in text
    for role, relative in (
        ("dashboard", "charts/dashboard.png"),
        ("hotspots", "hotspots/hotspots.png"),
        ("coupling_files", "coupling/coupling-files.png"),
    ):
        with Image.open(output / relative) as image:
            assert json.loads(image.info["Description"]) == frozen["series"][role]
