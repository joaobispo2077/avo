"""Run artifact downloads replace chart-host commits without losing text evidence."""

import hashlib
import json
import socket
import subprocess
import sys
from pathlib import Path

import pytest
from scripts.ci import link_quality_artifacts as linker

PREFIX = "https://github.com/owner/avo/actions/runs/42/artifacts/"
SHA = "a" * 40
ATTACHMENT_URL = (
    "https://github.com/user-attachments/assets/12345678-1234-4abc-8def-123456789abc"
)
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
    monkeypatch.setenv("GITHUB_SHA", SHA)


@pytest.fixture
def attachment(tmp_path):
    chart = tmp_path / "dashboard.png"
    chart.write_bytes(b"\x89PNG\r\n\x1a\ncurrent dashboard")
    payload = {
        "sha": SHA,
        "run_id": "42",
        "chart_sha256": hashlib.sha256(chart.read_bytes()).hexdigest(),
        "url": ATTACHMENT_URL,
        "error": None,
    }
    receipt = tmp_path / "attachment.json"
    receipt.write_text(json.dumps(payload), encoding="utf-8")
    return chart, receipt, payload


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


@pytest.mark.parametrize("charts_url", ["", PREFIX + "11"])
def test_native_attachment_restores_one_inline_dashboard_with_download_fallback(
    charts_url,
):
    result = linker.link_artifacts(
        REPORT,
        charts_url=charts_url,
        metrics_url=PREFIX + "12",
        image_url=ATTACHMENT_URL,
    )
    assert result.count("![") == 1
    assert f"![Quality dashboard]({ATTACHMENT_URL})" in result
    assert ("Download Quality dashboard" in result) is bool(charts_url)
    assert f"[Normalized measurements (JSON)]({PREFIX}12)" in result
    assert "**Overall: FAIL**" in result
    assert "Required action: repair lint." in result
    assert "71.42% | coverage.json SHA-256 abc" in result
    assert "| Lint | FAIL |" in result
    assert "kpi-chart:" not in result
    assert (
        linker.link_artifacts(
            result,
            charts_url=charts_url,
            metrics_url=PREFIX + "12",
            image_url=ATTACHMENT_URL,
        )
        == result
    )


@pytest.mark.parametrize(
    "image_url",
    [
        "",
        PREFIX + "11",
        "https://raw.githubusercontent.com/owner/avo/chart.png",
        "https://github.com/user-attachments/assets/not-a-uuid",
        ATTACHMENT_URL + "?token=secret",
        ATTACHMENT_URL + "#fragment",
        ATTACHMENT_URL + "/extra",
        ATTACHMENT_URL + ")![injected](https://example.com)",
        ATTACHMENT_URL.replace("https://", "http://"),
        ATTACHMENT_URL.replace("github.com/", "github.com.evil.test/"),
        ATTACHMENT_URL.replace("github.com/", "user:secret@github.com/"),
    ],
)
def test_invalid_native_urls_keep_artifact_downloads_and_text(image_url):
    result = linker.link_artifacts(
        REPORT,
        charts_url=PREFIX + "11",
        metrics_url=PREFIX + "12",
        image_url=image_url,
    )
    assert "![" not in result
    assert f"[Download Quality dashboard (PNG archive)]({PREFIX}11)" in result
    assert f"[Normalized measurements (JSON)]({PREFIX}12)" in result
    assert "**Overall: FAIL**" in result and "71.42%" in result


@pytest.mark.parametrize("error", [None, ""])
def test_attachment_receipt_requires_current_identity_and_exact_chart(
    attachment, error
):
    chart, receipt, payload = attachment
    payload["error"] = error
    receipt.write_text(json.dumps(payload), encoding="utf-8")
    assert linker.read_attachment(receipt, chart) == ATTACHMENT_URL


@pytest.mark.parametrize(
    "field,value",
    [
        ("sha", "b" * 40),
        ("sha", "a" * 39),
        ("sha", "g" * 40),
        ("run_id", "41"),
        ("run_id", "42/x"),
        ("chart_sha256", "0" * 64),
        ("chart_sha256", None),
        ("error", "upload failed: unauthorized"),
        ("url", "https://github.com/user-attachments/assets/not-a-uuid"),
        ("url", PREFIX + "11"),
        ("url", ATTACHMENT_URL + "?token=secret"),
    ],
)
def test_stale_failed_or_malformed_attachment_receipts_are_not_embedded(
    attachment, field, value
):
    chart, receipt, payload = attachment
    payload[field] = value
    receipt.write_text(json.dumps(payload), encoding="utf-8")
    assert linker.read_attachment(receipt, chart) == ""


@pytest.mark.parametrize(
    "variable,value",
    [
        ("GITHUB_SHA", ""),
        ("GITHUB_SHA", "a" * 39),
        ("GITHUB_SHA", "g" * 40),
        ("GITHUB_RUN_ID", ""),
        ("GITHUB_RUN_ID", "42/x"),
    ],
)
def test_invalid_current_identity_rejects_attachment(
    attachment, monkeypatch, variable, value
):
    chart, receipt, _ = attachment
    monkeypatch.setenv(variable, value)
    assert linker.read_attachment(receipt, chart) == ""


@pytest.mark.parametrize(
    "damage", ["changed_chart", "missing_chart", "missing_receipt"]
)
def test_changed_or_missing_attachment_files_are_unavailable(attachment, damage):
    chart, receipt, _ = attachment
    if damage == "changed_chart":
        chart.write_bytes(chart.read_bytes() + b"tampered")
    elif damage == "missing_chart":
        chart.unlink()
    else:
        receipt.unlink()
    assert linker.read_attachment(receipt, chart) == ""


@pytest.mark.parametrize("body", ["{", "[]", "null", '"not an object"', "{}"])
def test_unreadable_or_incomplete_attachment_receipt_is_unavailable(attachment, body):
    chart, receipt, _ = attachment
    receipt.write_text(body, encoding="utf-8")
    assert linker.read_attachment(receipt, chart) == ""


def test_absent_or_directory_attachment_paths_are_unavailable(attachment, tmp_path):
    chart, receipt, _ = attachment
    assert linker.read_attachment(None, chart) == ""
    assert linker.read_attachment(tmp_path, chart) == ""
    assert linker.read_attachment(receipt, tmp_path) == ""


def test_linker_cli_embeds_verified_receipt_without_network_or_git(
    attachment, tmp_path, monkeypatch
):
    chart, receipt, _ = attachment

    def forbidden(*args, **kwargs):
        raise AssertionError("Attachment linking must remain offline")

    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setenv("QUALITY_CHARTS_TOKEN", "unused")
    monkeypatch.setenv("QUALITY_CHARTS_ARTIFACT_URL", PREFIX + "11")
    monkeypatch.setenv("QUALITY_METRICS_ARTIFACT_URL", PREFIX + "12")
    report = tmp_path / "report.md"
    report.write_text(REPORT, encoding="utf-8")
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "link_quality_artifacts.py",
            "--markdown",
            str(report),
            "--attachment",
            str(receipt),
            "--chart",
            str(chart),
        ],
    )
    assert linker.main() == 0
    result = report.read_text(encoding="utf-8")
    assert result.count("![") == 1
    assert ATTACHMENT_URL in result and "71.42%" in result
    assert "Download Quality dashboard" in result
    assert result.strip() == summary.read_text(encoding="utf-8").strip()


SUPPORT_REPORT = (
    REPORT
    + "\n![Function hotspots](kpi-chart:hotspots.png)\n"
    + "[Complete function index](kpi-detail:hotspots.md)\n"
    + "![File coupling](kpi-chart:coupling-files.png)\n"
    + "[Complete file index](kpi-detail:coupling-index.md)\n"
)
HOTSPOTS_URL = ATTACHMENT_URL.replace("12345678-", "22345678-", 1)
COUPLING_URL = ATTACHMENT_URL.replace("12345678-", "32345678-", 1)


def test_three_image_roles_and_text_indexes_link_independently():
    result = linker.link_artifacts(
        SUPPORT_REPORT,
        charts_url=PREFIX + "11",
        metrics_url=PREFIX + "12",
        image_url=ATTACHMENT_URL,
        hotspots_url=PREFIX + "13",
        coupling_url=PREFIX + "14",
        hotspots_image_url=HOTSPOTS_URL,
        coupling_image_url=COUPLING_URL,
    )
    assert result.count("![") == 3
    assert f"![Function hotspots]({HOTSPOTS_URL})" in result
    assert f"![File coupling]({COUPLING_URL})" in result
    assert "hotspots.md" in result and "coupling-index.md" in result
    assert "complete text index" in result
    assert "kpi-chart:" not in result and "kpi-detail:" not in result
    assert "Required action: repair lint." in result and "71.42%" in result


@pytest.mark.parametrize(
    "failed",
    ["hotspots_image_url", "hotspots_url", "coupling_image_url", "coupling_url"],
)
def test_one_support_upload_failure_retains_other_images_downloads_and_text(failed):
    kwargs = {
        "charts_url": PREFIX + "11",
        "metrics_url": PREFIX + "12",
        "image_url": ATTACHMENT_URL,
        "hotspots_url": PREFIX + "13",
        "coupling_url": PREFIX + "14",
        "hotspots_image_url": HOTSPOTS_URL,
        "coupling_image_url": COUPLING_URL,
    }
    kwargs[failed] = ""
    result = linker.link_artifacts(SUPPORT_REPORT, **kwargs)
    assert ATTACHMENT_URL in result and "71.42%" in result
    assert ("![Function hotspots]" in result) is (failed != "hotspots_image_url")
    assert ("![File coupling]" in result) is (failed != "coupling_image_url")
    assert (PREFIX + "13" in result) is (failed != "hotspots_url")
    assert (PREFIX + "14" in result) is (failed != "coupling_url")


def test_support_links_reject_stale_archive_and_injected_native_urls():
    result = linker.link_artifacts(
        SUPPORT_REPORT,
        charts_url="",
        metrics_url=PREFIX + "12",
        hotspots_url=PREFIX.replace("/42/", "/41/") + "13",
        coupling_url=PREFIX + "14",
        hotspots_image_url=HOTSPOTS_URL + "?token=private",
        coupling_image_url=COUPLING_URL,
    )
    assert "private" not in result and "/runs/41/" not in result
    assert "![Function hotspots]" not in result
    assert "![File coupling]" in result
    assert "Complete text index unavailable" in result


@pytest.mark.parametrize(
    "role,filename",
    [("hotspots", "hotspots.png"), ("coupling_files", "coupling-files.png")],
)
def test_support_receipts_require_exact_role_and_fixed_filename(
    attachment, role, filename
):
    old_chart, receipt, payload = attachment
    chart = old_chart.with_name(filename)
    chart.write_bytes(old_chart.read_bytes())
    # An old dashboard-only receipt cannot authorize a supporting chart.
    assert linker.read_attachment(receipt, chart, role=role) == ""
    payload.update(role=role, filename=filename)
    receipt.write_text(json.dumps(payload), encoding="utf-8")
    assert linker.read_attachment(receipt, chart, role=role) == ATTACHMENT_URL
    for key, value in (("role", "dashboard"), ("filename", "arbitrary.png")):
        damaged = {**payload, key: value}
        receipt.write_text(json.dumps(damaged), encoding="utf-8")
        assert linker.read_attachment(receipt, chart, role=role) == ""


def test_explicit_dashboard_receipt_requires_its_filename(attachment):
    chart, receipt, payload = attachment
    payload["role"] = "dashboard"
    receipt.write_text(json.dumps(payload), encoding="utf-8")
    assert linker.read_attachment(receipt, chart) == ""
    payload["filename"] = "dashboard.png"
    receipt.write_text(json.dumps(payload), encoding="utf-8")
    assert linker.read_attachment(receipt, chart) == ATTACHMENT_URL


def test_support_cli_uses_role_receipts_without_network_or_credential_fallback(
    tmp_path, monkeypatch
):
    for role, relative, url in (
        ("hotspots", "hotspots/hotspots.png", HOTSPOTS_URL),
        ("coupling_files", "coupling/coupling-files.png", COUPLING_URL),
    ):
        chart = tmp_path / "reports" / "quality" / relative
        chart.parent.mkdir(parents=True)
        chart.write_bytes(b"bound image " + role.encode())
        (tmp_path / f"{role}.json").write_text(
            json.dumps(
                {
                    "role": role,
                    "filename": chart.name,
                    "sha": SHA,
                    "run_id": "42",
                    "chart_sha256": hashlib.sha256(chart.read_bytes()).hexdigest(),
                    "url": url,
                    "error": "",
                }
            ),
            encoding="utf-8",
        )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("QUALITY_HOTSPOTS_ARTIFACT_URL", PREFIX + "13")
    monkeypatch.setenv("QUALITY_COUPLING_ARTIFACT_URL", PREFIX + "14")
    report = tmp_path / "report.md"
    report.write_text(SUPPORT_REPORT, encoding="utf-8")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "linker",
            "--markdown",
            str(report),
            "--no-summary",
            "--hotspots-attachment",
            str(tmp_path / "hotspots.json"),
            "--coupling-attachment",
            str(tmp_path / "coupling_files.json"),
        ],
    )

    def forbidden(*args, **kwargs):
        pytest.fail("Supporting image linking must remain offline")

    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    assert linker.main() == 0
    result = report.read_text(encoding="utf-8")
    assert "![Function hotspots]" in result and "![File coupling]" in result
    assert HOTSPOTS_URL in result and COUPLING_URL in result
    assert "kpi-detail:" not in result
