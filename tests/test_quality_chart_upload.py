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


def run_main(monkeypatch, chart, metrics, receipt):
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "upload_quality_chart.py",
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
def test_failed_upload_is_nonfatal_and_receipt_never_exposes_credentials(
    chart_files, tmp_path, monkeypatch, capsys, failure
):
    chart, metrics, _ = chart_files
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
    receipt = run_main(monkeypatch, chart, metrics, receipt_path)
    assert receipt["sha"] == SHA and receipt["run_id"] == RUN_ID
    assert set(receipt) >= {"sha", "run_id", "chart_sha256", "url", "error"}
    assert not receipt["url"] and receipt["error"]
    assert len(calls) == (0 if failure in {"missing", "no-token"} else 1)
    output = capsys.readouterr()
    assert TOKEN not in receipt_path.read_text(encoding="utf-8")
    assert TOKEN not in output.out + output.err
