"""Run artifact downloads replace chart-host commits without losing text evidence."""

import socket
import subprocess
import sys
from pathlib import Path

import pytest
from scripts.ci import link_quality_artifacts as linker

PREFIX = "https://github.com/owner/avo/actions/runs/42/artifacts/"
REPORT = (
    "## AVO quality\n\n**Overall: FAIL**\n\n"
    "Commit: `abc` · Run: `42`\n\nRequired action: repair lint.\n\n"
    "![Quality dashboard](kpi-chart:dashboard.png)\n\n"
    "| Metric | Measured | Evidence |\n| Coverage | 71.42% | coverage.json SHA-256 abc |\n"
    "| Gate | Decision |\n| Lint | FAIL |\n"
)


@pytest.fixture(autouse=True)
def current_run(monkeypatch):
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/avo")
    monkeypatch.setenv("GITHUB_RUN_ID", "42")


def test_artifacts_are_download_links_and_preserve_report_evidence():
    result = linker.link_artifacts(
        REPORT, charts_url=PREFIX + "11", metrics_url=PREFIX + "12"
    )
    assert f"[Download Quality dashboard (PNG archive)]({PREFIX}11)" in result
    assert f"[Normalized measurements (JSON)]({PREFIX}12)" in result
    assert "GitHub sign-in" in result
    assert "14 days" in result
    assert "![" not in result
    assert "kpi-chart:" not in result
    for evidence in (
        "**Overall: FAIL**",
        "Commit: `abc` · Run: `42`",
        "Required action: repair lint.",
        "71.42% | coverage.json SHA-256 abc",
        "| Lint | FAIL |",
    ):
        assert evidence in result


@pytest.mark.parametrize(
    "value",
    [
        "",
        PREFIX + "",
        PREFIX + "12?token=secret",
        PREFIX + "12#fragment",
        PREFIX + "12/extra",
        PREFIX + "../12",
        PREFIX + "12)![injected](https://example.com)",
        "https://github.com/owner/avo/actions/runs/41/artifacts/12",
        "https://github.com/other/avo/actions/runs/42/artifacts/12",
        "https://github.com/owner/other/actions/runs/42/artifacts/12",
        "https://github.com.evil.test/owner/avo/actions/runs/42/artifacts/12",
        "http://github.com/owner/avo/actions/runs/42/artifacts/12",
        "https://raw.githubusercontent.com/owner/avo/ci/quality-kpi-charts/chart.png",
    ],
)
def test_foreign_stale_or_malformed_downloads_remain_unavailable(value):
    result = linker.link_artifacts(REPORT, charts_url=value, metrics_url=value)
    assert "Chart image unavailable" in result
    assert "Normalized measurements download unavailable" in result
    assert "**Overall: FAIL**" in result
    assert "71.42%" in result
    assert "kpi-chart:" not in result
    assert "https://" not in result


@pytest.mark.parametrize(
    "charts_ok,metrics_ok", [(False, False), (True, False), (False, True)]
)
def test_uploads_fail_independently(charts_ok, metrics_ok):
    result = linker.link_artifacts(
        REPORT,
        charts_url=PREFIX + "11" if charts_ok else "",
        metrics_url=PREFIX + "12" if metrics_ok else "",
    )
    assert ("Download Quality dashboard" in result) is charts_ok
    assert ("Normalized measurements (JSON)" in result) is metrics_ok
    assert "71.42%" in result


@pytest.mark.parametrize(
    "repo,run_id",
    [("", "42"), ("owner/avo", ""), ("../avo", "42"), ("owner/avo", "42/x")],
)
def test_unavailable_or_invalid_identity_rejects_downloads(monkeypatch, repo, run_id):
    monkeypatch.setenv("GITHUB_REPOSITORY", repo)
    monkeypatch.setenv("GITHUB_RUN_ID", run_id)
    assert linker.current_artifact_url(PREFIX + "12") == ""


def test_render_failure_still_links_json_and_keeps_text():
    report = REPORT.replace(
        "![Quality dashboard](kpi-chart:dashboard.png)", "Dashboard image unavailable."
    )
    result = linker.link_artifacts(report, charts_url="", metrics_url=PREFIX + "12")
    assert "Dashboard image unavailable." in result
    assert "Normalized measurements (JSON)" in result
    assert "71.42%" in result


def test_metadata_section_is_idempotent():
    once = linker.link_artifacts(
        REPORT, charts_url=PREFIX + "11", metrics_url=PREFIX + "12"
    )
    twice = linker.link_artifacts(
        once, charts_url=PREFIX + "11", metrics_url=PREFIX + "12"
    )
    assert once == twice
    assert twice.count(linker.START) == 1


def test_publisher_never_calls_network_or_git(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Report linking must not invoke a process or network")

    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    # Even legacy credentials must not activate the removed hosting fallback.
    monkeypatch.setenv("GH_TOKEN", "unused")
    monkeypatch.setenv("KPI_CHART_UPLOAD_TOKEN", "unused")
    monkeypatch.setenv("QUALITY_CHARTS_ARTIFACT_URL", PREFIX + "11")
    monkeypatch.setenv("QUALITY_METRICS_ARTIFACT_URL", PREFIX + "12")
    report = tmp_path / "report.md"
    report.write_text(REPORT, encoding="utf-8")
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    monkeypatch.setattr(
        sys, "argv", ["link_quality_artifacts.py", "--markdown", str(report)]
    )
    assert linker.main() == 0
    assert (
        summary.read_text(encoding="utf-8").strip()
        == report.read_text(encoding="utf-8").strip()
    )
    assert "Normalized measurements (JSON)" in report.read_text(encoding="utf-8")


def test_missing_report_is_nonfatal(tmp_path, monkeypatch):
    monkeypatch.setattr(
        sys,
        "argv",
        ["link_quality_artifacts.py", "--markdown", str(tmp_path / "missing.md")],
    )
    assert linker.main() == 0
    assert not list(Path(tmp_path).iterdir())
