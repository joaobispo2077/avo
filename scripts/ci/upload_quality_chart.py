#!/usr/bin/env python3
"""Upload a verified dashboard as a native GitHub attachment, without Git writes."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ASSET_URL = re.compile(
    r"https://github\.com/user-attachments/assets/"
    r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}"
)


def validate_chart(chart: Path, metrics: Path, *, sha: str, run_id: str) -> bytes:
    """Reject stale files and failed renders; red dashboards remain publishable."""
    from PIL import Image

    if not re.fullmatch(r"[0-9a-f]{40}", sha) or not re.fullmatch(
        r"[0-9]{1,20}", run_id
    ):
        raise ValueError("Current commit/run identity is unavailable")
    doc = json.loads(metrics.read_text(encoding="utf-8"))
    if doc.get("sha") != sha or str(doc.get("run_id")) != run_id:
        raise ValueError("Dashboard measurements belong to a different commit/run")
    if doc.get("image_error"):
        raise ValueError("Dashboard rendering failed")
    series = doc.get("series", {}).get("dashboard")
    if (
        not isinstance(series, dict)
        or series.get("sha") != sha
        or str(series.get("run_id")) != run_id
    ):
        raise ValueError("Dashboard series lacks current commit/run identity")
    content = chart.read_bytes()
    if len(content) > 10 * 1024 * 1024:
        raise ValueError("Dashboard exceeds the image attachment size limit")
    with Image.open(io.BytesIO(content)) as image:
        if (
            image.format != "PNG"
            or json.loads(image.info.get("Description", "null")) != series
        ):
            raise ValueError("Dashboard image does not match its measurements")
        image.verify()
    return content


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(
            req.full_url, code, "Upload redirect refused", headers, fp
        )


def upload_chart(
    content: bytes, *, token: str, repository_id: str, name: str = "dashboard.png"
) -> str:
    """Use the native attachment endpoint implemented by GitHub CLI 2.99+."""
    if not token.startswith(("gho_", "ghp_", "github_pat_", "ghu_")) or any(
        c.isspace() for c in token
    ):
        raise ValueError(
            "A supported user credential is required; Actions tokens cannot attach images"
        )
    if not re.fullmatch(r"[1-9][0-9]*", repository_id):
        raise ValueError("Repository ID is unavailable")
    if name != "dashboard.png":
        raise ValueError("Only the dashboard image may be uploaded")
    query = urllib.parse.urlencode(
        {"content_type": "image/png", "name": name, "repository_id": repository_id}
    )
    request = urllib.request.Request(
        f"https://uploads.github.com/user-attachments/assets?{query}",
        data=content,
        method="POST",
        headers={
            "Authorization": f"token {token}",
            "Content-Type": "application/octet-stream",
            "Accept": "application/vnd.github+json",
        },
    )
    with urllib.request.build_opener(NoRedirect).open(request, timeout=30) as response:
        url = json.loads(response.read()).get("url", "")
    if not isinstance(url, str) or not ASSET_URL.fullmatch(url):
        raise ValueError("Upload did not return a native image attachment URL")
    return url


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--chart", type=Path, default=Path("reports/quality/charts/dashboard.png")
    )
    parser.add_argument(
        "--metrics", type=Path, default=Path("reports/quality/quality-metrics.json")
    )
    parser.add_argument(
        "--out", type=Path, default=Path("reports/quality/chart-attachment.json")
    )
    args = parser.parse_args()
    sha, run_id = os.environ.get("GITHUB_SHA", ""), os.environ.get("GITHUB_RUN_ID", "")
    receipt = {"sha": sha, "run_id": run_id, "chart_sha256": "", "url": "", "error": ""}
    try:
        content = validate_chart(args.chart, args.metrics, sha=sha, run_id=run_id)
        receipt["chart_sha256"] = hashlib.sha256(content).hexdigest()
        receipt["url"] = upload_chart(
            content,
            token=os.environ.get("QUALITY_CHARTS_TOKEN", ""),
            repository_id=os.environ.get("GITHUB_REPOSITORY_ID", ""),
        )
    except Exception as exc:
        # Response bodies and exception strings can contain credentials; do not publish them.
        detail = (
            f"HTTP {exc.code}"
            if isinstance(exc, urllib.error.HTTPError)
            else type(exc).__name__
        )
        receipt["error"] = f"Native dashboard upload unavailable ({detail})"
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(receipt["error"] or "Native dashboard attachment uploaded")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
