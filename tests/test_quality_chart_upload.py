"""Native chart attachments retain current-run identity without Git writes."""

from __future__ import annotations

import hashlib
import io
import json
import struct
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
import zlib
from types import SimpleNamespace

import pytest
from scripts.ci import upload_quality_chart as uploader

SHA = "a" * 40
RUN_ID = "42"
REPOSITORY_ID = "123456"
TOKEN = "ghp_" + "x" * 36
ASSET = (
    "https://github.com/user-attachments/assets/12345678-1234-4234-8234-123456789abc"
)
SUPPORT_FILES = {
    "hotspots": ("hotspots.png", "hotspots_image_error"),
    "coupling_files": ("coupling-files.png", "coupling_image_error"),
    "mutation_scopes": ("mutation-efficacy.png", "mutation_image_error"),
    "gate_decisions": ("gate-decisions.png", "gate_decisions_image_error"),
}


def chunk(kind, content):
    return (
        struct.pack(">I", len(content))
        + kind
        + content
        + struct.pack(">I", zlib.crc32(kind + content))
    )


def png(series):
    """A complete one-pixel PNG with the renderer's Description metadata."""
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
        + chunk(b"tEXt", b"Description\0" + json.dumps(series).encode("latin1"))
        + chunk(b"IDAT", zlib.compress(b"\0\0\0\0"))
        + chunk(b"IEND", b"")
    )


@pytest.fixture
def chart_files(tmp_path, monkeypatch):
    monkeypatch.setenv("GITHUB_SHA", SHA)
    monkeypatch.setenv("GITHUB_RUN_ID", RUN_ID)
    monkeypatch.setenv("GITHUB_REPOSITORY_ID", REPOSITORY_ID)
    monkeypatch.setenv("QUALITY_CHARTS_TOKEN", TOKEN)
    series = {
        "sha": SHA,
        "run_id": RUN_ID,
        "overall": "FAIL",
        "metrics": [{"title": "Coverage", "measured": 61.0}],
    }
    document = {
        "schema": 2,
        "sha": SHA,
        "run_id": RUN_ID,
        "overall": "FAIL",
        "series": {"dashboard": series},
    }
    chart = tmp_path / "dashboard.png"
    chart.write_bytes(png(series))
    metrics = tmp_path / "quality-metrics.json"
    metrics.write_text(json.dumps(document), encoding="utf-8")
    return chart, metrics, document


def test_failed_quality_result_can_publish_its_exact_dashboard(chart_files):
    chart, metrics, _ = chart_files
    assert uploader.validate_chart(chart, metrics, sha=SHA, run_id=RUN_ID) == (
        chart.read_bytes()
    )


@pytest.mark.parametrize(
    "context",
    [
        {"schema": 1, "mode": "fixture"},
        {"schema": 1, "mode": "local-preview"},
        {"schema": 2, "mode": "ci"},
        {"schema": 1, "mode": "ci", "run_id": "duplicate"},
    ],
)
def test_non_ci_or_invalid_reporting_context_cannot_upload(chart_files, context):
    chart, metrics, document = chart_files
    document["reporting"] = context
    metrics.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(ValueError, match="[Cc]ontext|[Pp]review|[Cc][Ii]|[Rr]eporting"):
        uploader.validate_chart(chart, metrics, sha=SHA, run_id=RUN_ID)


@pytest.mark.parametrize("field,value", [("sha", "b" * 40), ("run_id", "41")])
def test_stale_measurement_document_is_rejected(chart_files, field, value):
    chart, metrics, document = chart_files
    document[field] = value
    metrics.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises((ValueError, RuntimeError)):
        uploader.validate_chart(chart, metrics, sha=SHA, run_id=RUN_ID)


def test_png_for_different_measurements_is_rejected(chart_files):
    chart, metrics, document = chart_files
    document["series"]["dashboard"]["metrics"][0]["measured"] = 99.0
    metrics.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises((ValueError, RuntimeError)):
        uploader.validate_chart(chart, metrics, sha=SHA, run_id=RUN_ID)


def test_recorded_render_failure_rejects_leftover_png(chart_files):
    chart, metrics, document = chart_files
    document["image_error"] = "Current rendering failed; this PNG may be old."
    metrics.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises((ValueError, RuntimeError)):
        uploader.validate_chart(chart, metrics, sha=SHA, run_id=RUN_ID)


@pytest.mark.parametrize("damage", ["missing", "signature", "truncated", "crc"])
def test_missing_malformed_or_corrupt_png_is_rejected(chart_files, damage):
    chart, metrics, _ = chart_files
    content = chart.read_bytes()
    if damage == "missing":
        chart.unlink()
    elif damage == "signature":
        chart.write_bytes(b"not a PNG")
    elif damage == "truncated":
        chart.write_bytes(content[:-5])
    else:
        changed = bytearray(content)
        changed[29] ^= 1  # IHDR CRC; dimensions and Description remain readable.
        chart.write_bytes(changed)
    with pytest.raises((ValueError, RuntimeError, OSError, SyntaxError)):
        uploader.validate_chart(chart, metrics, sha=SHA, run_id=RUN_ID)


@pytest.mark.parametrize("payload", ["not JSON", "[]", "{}"])
def test_invalid_or_incomplete_metrics_are_rejected(chart_files, payload):
    chart, metrics, _ = chart_files
    metrics.write_text(payload, encoding="utf-8")
    with pytest.raises((ValueError, RuntimeError, KeyError, AttributeError)):
        uploader.validate_chart(chart, metrics, sha=SHA, run_id=RUN_ID)


class Response(io.BytesIO):
    status = 201

    def getcode(self):
        return self.status


def mock_response(monkeypatch, payload):
    calls = []

    def request(request, **kwargs):
        calls.append((request, kwargs))
        return Response(json.dumps(payload).encode("utf-8"))

    def opener(*handlers):
        assert uploader.NoRedirect in handlers
        return SimpleNamespace(open=request)

    monkeypatch.setattr(urllib.request, "build_opener", opener)
    return calls


def test_upload_sends_only_png_bytes_to_native_attachment_endpoint(
    chart_files, monkeypatch
):
    chart, _, _ = chart_files
    content = chart.read_bytes()
    calls = mock_response(monkeypatch, {"url": ASSET})
    assert (
        uploader.upload_chart(content, token=TOKEN, repository_id=REPOSITORY_ID)
        == ASSET
    )
    assert len(calls) == 1
    request, options = calls[0]
    parsed = urllib.parse.urlsplit(request.full_url)
    assert parsed.scheme == "https" and parsed.netloc == "uploads.github.com"
    assert parsed.path == "/user-attachments/assets"
    query = urllib.parse.parse_qs(parsed.query)
    assert query["repository_id"] == [REPOSITORY_ID]
    assert query["name"] == ["dashboard.png"]
    assert query["content_type"] == ["image/png"]
    assert request.get_method() == "POST"
    assert request.data == content
    assert request.get_header("Content-type") == "application/octet-stream"
    assert request.get_header("Authorization") == f"token {TOKEN}"
    assert options["timeout"] == 30


def test_redirects_are_refused_without_forwarding_credentials():
    request = urllib.request.Request(
        "https://uploads.github.com/user-attachments/assets",
        headers={"Authorization": f"token {TOKEN}"},
    )
    with pytest.raises(urllib.error.HTTPError) as error:
        uploader.NoRedirect().redirect_request(
            request, io.BytesIO(), 307, "redirect", {}, "https://example.com/collect"
        )
    assert error.value.code == 307


@pytest.mark.parametrize("token", ["", " ", "ghs_" + "x" * 36, "not-a-token"])
def test_unsupported_credentials_are_rejected_without_upload(monkeypatch, token):
    calls = mock_response(monkeypatch, {"url": ASSET})
    with pytest.raises((ValueError, RuntimeError)):
        uploader.upload_chart(b"png", token=token, repository_id=REPOSITORY_ID)
    assert not calls


@pytest.mark.parametrize("repository_id", ["", "../123", "123?other=1", "abc"])
def test_malformed_repository_identity_is_rejected_without_upload(
    monkeypatch, repository_id
):
    calls = mock_response(monkeypatch, {"url": ASSET})
    with pytest.raises((ValueError, RuntimeError)):
        uploader.upload_chart(b"png", token=TOKEN, repository_id=repository_id)
    assert not calls


@pytest.mark.parametrize(
    "url",
    [
        "",
        "https://example.com/dashboard.png",
        ASSET.replace("github.com", "github.com.evil.example"),
        ASSET.replace("https://", "http://"),
        "https://github.com/user-attachments/assets/not-an-asset",
        ASSET + "?token=secret",
        ASSET + "#fragment",
        ASSET + ")![injected](https://example.com)",
    ],
)
def test_untrusted_or_malformed_attachment_urls_are_rejected(monkeypatch, url):
    mock_response(monkeypatch, {"url": url})
    with pytest.raises((ValueError, RuntimeError)):
        uploader.upload_chart(b"png", token=TOKEN, repository_id=REPOSITORY_ID)


def run_main(monkeypatch, chart, metrics, receipt, *, role="dashboard"):
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "upload_quality_chart.py",
            "--role",
            role,
            "--chart",
            str(chart),
            "--metrics",
            str(metrics),
            "--out",
            str(receipt),
        ],
    )
    assert uploader.main() == 0
    return json.loads(receipt.read_text(encoding="utf-8"))


def test_success_receipt_binds_native_url_to_current_png_without_git_or_comments(
    chart_files, tmp_path, monkeypatch
):
    chart, metrics, _ = chart_files
    calls = mock_response(monkeypatch, {"url": ASSET})

    def forbidden(*args, **kwargs):
        pytest.fail("Chart attachment upload must never invoke Git or a subprocess")

    monkeypatch.setattr(subprocess, "Popen", forbidden)
    receipt = run_main(monkeypatch, chart, metrics, tmp_path / "receipt.json")
    assert receipt["sha"] == SHA and receipt["run_id"] == RUN_ID
    assert receipt["chart_sha256"] == hashlib.sha256(chart.read_bytes()).hexdigest()
    assert receipt["url"] == ASSET and not receipt["error"]
    assert len(calls) == 1
    assert "user-attachments/assets" in calls[0][0].full_url


@pytest.mark.parametrize("failure", ["denied", "timeout", "missing", "no-token"])
@pytest.mark.parametrize("role", ["dashboard", "mutation_scopes", "gate_decisions"])
def test_failed_upload_is_nonfatal_and_receipt_never_exposes_credentials(
    chart_files, tmp_path, monkeypatch, capsys, failure, role
):
    chart, metrics, _ = (
        chart_files if role == "dashboard" else support_files(chart_files, role)
    )
    calls = []

    def request(*args, **kwargs):
        calls.append(args)
        if failure == "denied":
            raise urllib.error.HTTPError(
                "https://uploads.github.com/user-attachments/assets",
                403,
                "Denied " + TOKEN,
                {},
                io.BytesIO(TOKEN.encode()),
            )
        raise TimeoutError("Private diagnostic contains " + TOKEN)

    monkeypatch.setattr(
        urllib.request, "build_opener", lambda *handlers: SimpleNamespace(open=request)
    )
    if failure == "missing":
        chart.unlink()
    elif failure == "no-token":
        monkeypatch.delenv("QUALITY_CHARTS_TOKEN")
    receipt_path = tmp_path / "receipt.json"
    receipt = run_main(monkeypatch, chart, metrics, receipt_path, role=role)
    assert receipt["sha"] == SHA and receipt["run_id"] == RUN_ID
    assert receipt["role"] == role
    assert set(receipt) >= {"sha", "run_id", "chart_sha256", "url", "error"}
    assert not receipt["url"] and receipt["error"]
    assert len(calls) == (0 if failure in {"missing", "no-token"} else 1)
    output = capsys.readouterr()
    assert TOKEN not in receipt_path.read_text(encoding="utf-8")
    assert TOKEN not in output.out + output.err


def support_files(chart_files, role, *, state="MEASURED"):
    chart, metrics, document = chart_files
    document.update(repository="owner/avo", reporting={"schema": 1, "mode": "ci"})
    series = {
        "schema": 1,
        "chart": role,
        "state": state,
        "mode": "ci",
        "sha": SHA,
        "run_id": RUN_ID,
    }
    document["series"][role] = series
    chart = chart.with_name(SUPPORT_FILES[role][0])
    chart.write_bytes(png(series))
    metrics.write_text(json.dumps(document), encoding="utf-8")
    return chart, metrics, document


@pytest.mark.parametrize("role", SUPPORT_FILES)
@pytest.mark.parametrize("state", ["MEASURED", "PARTIAL"])
def test_support_images_accept_exact_ci_series_without_requiring_green_gates(
    chart_files, role, state
):
    chart, metrics, _ = support_files(chart_files, role, state=state)
    assert (
        uploader.validate_chart(chart, metrics, sha=SHA, run_id=RUN_ID, role=role)
        == chart.read_bytes()
    )


@pytest.mark.parametrize("role", SUPPORT_FILES)
@pytest.mark.parametrize(
    "problem",
    [
        "missing-context",
        "preview-series",
        "unavailable",
        "chart",
        "schema",
        "sha",
        "run_id",
        "document-sha",
        "document-run_id",
        "filename",
        "image-error",
        "metadata",
        "missing-image",
        "corrupt-image",
    ],
)
def test_support_upload_rejects_missing_invalid_or_mismatched_evidence(
    chart_files, role, problem
):
    chart, metrics, document = support_files(chart_files, role)
    series = document["series"][role]
    if problem == "missing-context":
        del document["reporting"]
    elif problem == "preview-series":
        series["mode"] = "fixture"
    elif problem == "unavailable":
        series["state"] = "UNAVAILABLE"
    elif problem == "chart":
        series["chart"] = "dashboard"
    elif problem == "schema":
        series["schema"] = True
    elif problem == "sha":
        series["sha"] = "b" * 40
    elif problem == "run_id":
        series["run_id"] = "41"
    elif problem == "document-sha":
        document["sha"] = "b" * 40
    elif problem == "document-run_id":
        document["run_id"] = "41"
    elif problem == "filename":
        wrong_name = chart.with_name("arbitrary.png")
        wrong_name.write_bytes(chart.read_bytes())
        chart = wrong_name
    elif problem == "image-error":
        document[SUPPORT_FILES[role][1]] = "render failed"
    elif problem == "missing-image":
        chart.unlink()
    elif problem == "corrupt-image":
        chart.write_bytes(b"not a PNG")
    else:
        chart.write_bytes(png({**series, "state": "PARTIAL"}))
    metrics.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises((ValueError, OSError)):
        uploader.validate_chart(chart, metrics, sha=SHA, run_id=RUN_ID, role=role)


@pytest.mark.parametrize("role", SUPPORT_FILES)
def test_support_render_error_does_not_disable_other_image_roles(chart_files, role):
    chart, metrics, document = support_files(chart_files, role)
    document["image_error"] = "primary image failed"
    for other, (_, error_field) in SUPPORT_FILES.items():
        if other != role:
            document[error_field] = "other image failed independently"
    metrics.write_text(json.dumps(document), encoding="utf-8")
    assert (
        uploader.validate_chart(chart, metrics, sha=SHA, run_id=RUN_ID, role=role)
        == chart.read_bytes()
    )


@pytest.mark.parametrize(
    "name",
    [
        "dashboard.png",
        "hotspots.png",
        "coupling-files.png",
        "mutation-efficacy.png",
        "gate-decisions.png",
    ],
)
def test_native_upload_accepts_only_bounded_chart_names(monkeypatch, name):
    calls = mock_response(monkeypatch, {"url": ASSET})
    assert (
        uploader.upload_chart(
            b"png", token=TOKEN, repository_id=REPOSITORY_ID, name=name
        )
        == ASSET
    )
    query = urllib.parse.parse_qs(urllib.parse.urlsplit(calls[0][0].full_url).query)
    assert query["name"] == [name]


@pytest.mark.parametrize("name", ["other.png", "../dashboard.png", "hotspots.svg", ""])
def test_native_upload_refuses_unbounded_names_before_network(monkeypatch, name):
    calls = mock_response(monkeypatch, {"url": ASSET})
    with pytest.raises(ValueError):
        uploader.upload_chart(
            b"png", token=TOKEN, repository_id=REPOSITORY_ID, name=name
        )
    assert calls == []


@pytest.mark.parametrize(
    "role,relative_chart,relative_receipt",
    [
        ("dashboard", "charts/dashboard.png", "chart-attachment.json"),
        ("hotspots", "hotspots/hotspots.png", "hotspots-attachment.json"),
        ("coupling_files", "coupling/coupling-files.png", "coupling-attachment.json"),
        (
            "mutation_scopes",
            "mutation/mutation-efficacy.png",
            "mutation-attachment.json",
        ),
        (
            "gate_decisions",
            "decisions/gate-decisions.png",
            "gate-decisions-attachment.json",
        ),
    ],
)
def test_role_cli_uses_fixed_paths_and_records_role_and_filename(
    chart_files, tmp_path, monkeypatch, role, relative_chart, relative_receipt
):
    chart, metrics, _ = (
        chart_files if role == "dashboard" else support_files(chart_files, role)
    )
    target = tmp_path / "reports" / "quality" / relative_chart
    target.parent.mkdir(parents=True)
    target.write_bytes(chart.read_bytes())
    monkeypatch.chdir(tmp_path)
    mock_response(monkeypatch, {"url": ASSET})
    monkeypatch.setattr(
        sys, "argv", ["uploader", "--role", role, "--metrics", str(metrics)]
    )
    assert uploader.main() == 0
    receipt = json.loads(
        (tmp_path / "reports" / "quality" / relative_receipt).read_text()
    )
    assert receipt["role"] == role
    assert receipt["filename"] == target.name
    assert receipt["url"] == ASSET and not receipt["error"]


def test_unknown_role_is_rejected_before_upload(chart_files, monkeypatch):
    calls = mock_response(monkeypatch, {"url": ASSET})
    monkeypatch.setattr(sys, "argv", ["uploader", "--role", "arbitrary"])
    with pytest.raises(SystemExit):
        uploader.main()
    assert calls == []
