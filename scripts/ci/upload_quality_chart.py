#!/usr/bin/env python3
"""Upload a verified quality chart as a native attachment, without Git writes."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
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
CHART_ROLES = {
    "dashboard": ("dashboard.png", "image_error", "charts", "chart-attachment.json"),
    "hotspots": (
        "hotspots.png",
        "hotspots_image_error",
        "hotspots",
        "hotspots-attachment.json",
    ),
    "coupling_files": (
        "coupling-files.png",
        "coupling_image_error",
        "coupling",
        "coupling-attachment.json",
    ),
    "mutation_scopes": (
        "mutation-efficacy.png",
        "mutation_image_error",
        "mutation",
        "mutation-attachment.json",
    ),
    "gate_decisions": (
        "gate-decisions.png",
        "gate_decisions_image_error",
        "decisions",
        "gate-decisions-attachment.json",
    ),
}


def validate_chart(
    chart: Path, metrics: Path, *, sha: str, run_id: str, role: str = "dashboard"
) -> bytes:
    """Reject stale files and failed renders; red dashboards remain publishable."""
    from PIL import Image

    if role not in CHART_ROLES:
        raise ValueError("Unsupported quality chart role")
    filename, error_field, _directory, _receipt = CHART_ROLES[role]
    if chart.name != filename:
        raise ValueError("Chart filename does not match its fixed role")
    if not re.fullmatch(r"[0-9a-f]{40}", sha) or not re.fullmatch(
        r"[0-9]{1,20}", run_id
    ):
        raise ValueError("Current commit/run identity is unavailable")
    doc = json.loads(metrics.read_text(encoding="utf-8"))
    if not isinstance(doc, dict):
        raise ValueError("Invalid reporting document")
    spec = importlib.util.spec_from_file_location(
        "avo_ci_upload_measurements",
        Path(__file__).with_name("quality_measurements.py"),
    )
    if spec is None or spec.loader is None:
        raise ValueError("Reporting context validator unavailable")
    validator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(validator)
    if error := validator.validate_reporting_context(doc):
        raise ValueError(error)
    if "reporting" in doc and doc["reporting"]["mode"] != "ci":
        raise ValueError("Preview reporting context cannot authorize CI upload")
    if role != "dashboard" and "reporting" not in doc:
        raise ValueError("Supporting charts require explicit CI reporting context")
    if doc.get("sha") != sha or str(doc.get("run_id")) != run_id:
        raise ValueError("Dashboard measurements belong to a different commit/run")
    if doc.get(error_field):
        raise ValueError("Chart rendering failed")
    collection = doc.get("series")
    series = collection.get(role) if isinstance(collection, dict) else None
    if (
        not isinstance(series, dict)
        or series.get("sha") != sha
        or str(series.get("run_id")) != run_id
    ):
        raise ValueError("Chart series lacks current commit/run identity")
    if role != "dashboard" and (
        type(doc.get("schema")) is not int
        or doc["schema"] != 2
        or type(series.get("schema")) is not int
        or series["schema"] != 1
        or series.get("chart") != role
        or series.get("mode") != "ci"
        or series.get("state") not in ("MEASURED", "PARTIAL")
    ):
        raise ValueError("Supporting chart series is unavailable or invalid")
    content = chart.read_bytes()
    if len(content) > 10 * 1024 * 1024:
        raise ValueError("Chart exceeds the image attachment size limit")
    with Image.open(io.BytesIO(content)) as image:
        if (
            image.format != "PNG"
            or json.loads(image.info.get("Description", "null")) != series
        ):
            raise ValueError("Chart image does not match its measurements")
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
    if name not in {values[0] for values in CHART_ROLES.values()}:
        raise ValueError("Only supported quality chart filenames may be uploaded")
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
    parser.add_argument("--role", choices=tuple(CHART_ROLES), default="dashboard")
    parser.add_argument("--chart", type=Path)
    parser.add_argument(
        "--metrics", type=Path, default=Path("reports/quality/quality-metrics.json")
    )
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    filename, _error, directory, receipt_name = CHART_ROLES[args.role]
    chart = args.chart or Path("reports/quality") / directory / filename
    output = args.out or Path("reports/quality") / receipt_name
    sha, run_id = os.environ.get("GITHUB_SHA", ""), os.environ.get("GITHUB_RUN_ID", "")
    receipt = {
        "role": args.role,
        "filename": filename,
        "sha": sha,
        "run_id": run_id,
        "chart_sha256": "",
        "url": "",
        "error": "",
    }
    try:
        content = validate_chart(
            chart, args.metrics, sha=sha, run_id=run_id, role=args.role
        )
        receipt["chart_sha256"] = hashlib.sha256(content).hexdigest()
        receipt["url"] = upload_chart(
            content,
            token=os.environ.get("QUALITY_CHARTS_TOKEN", ""),
            repository_id=os.environ.get("GITHUB_REPOSITORY_ID", ""),
            name=filename,
        )
    except Exception as exc:
        # Response bodies and exception strings can contain credentials; do not publish them.
        detail = (
            f"HTTP {exc.code}"
            if isinstance(exc, urllib.error.HTTPError)
            else type(exc).__name__
        )
        receipt["error"] = f"Native {args.role} upload unavailable ({detail})"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(receipt["error"] or f"Native {args.role} attachment uploaded")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
