#!/usr/bin/env python3
"""Embed a verified native chart attachment and link current-run artifacts.

The attachment uploader performs the only network operation. This linker checks
its receipt offline. Missing uploads leave measurements and decisions readable.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from pathlib import Path

_IMAGE = re.compile(r"!\[([^\]]*)\]\(kpi-chart:([A-Za-z0-9._-]+)\)")
START = "<!-- quality-artifacts:start -->"
END = "<!-- quality-artifacts:end -->"
ASSET_URL = re.compile(
    r"https://github\.com/user-attachments/assets/"
    r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}"
)


def current_artifact_url(value: str) -> str:
    """Accept only an upload action's URL for this repository and workflow run."""
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    run_id = os.environ.get("GITHUB_RUN_ID", "")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
        return ""
    if any(part in {".", ".."} for part in repo.split("/")):
        return ""
    if not re.fullmatch(r"[0-9]{1,20}", run_id):
        return ""
    prefix = f"https://github.com/{repo}/actions/runs/{run_id}/artifacts/"
    return value if re.fullmatch(re.escape(prefix) + r"[0-9]+", value) else ""


def read_attachment(path: Path | None, chart: Path) -> str:
    """Accept an upload receipt only for these exact commit/run and PNG bytes."""
    if path is None:
        return ""
    try:
        receipt = json.loads(path.read_text(encoding="utf-8"))
        sha, run_id = (
            os.environ.get("GITHUB_SHA", ""),
            os.environ.get("GITHUB_RUN_ID", ""),
        )
        url = receipt.get("url", "")
        if (
            re.fullmatch(r"[0-9a-f]{40}", sha)
            and re.fullmatch(r"[0-9]{1,20}", run_id)
            and receipt.get("sha") == sha
            and str(receipt.get("run_id")) == run_id
            and not receipt.get("error")
            and receipt.get("chart_sha256")
            == hashlib.sha256(chart.read_bytes()).hexdigest()
            and isinstance(url, str)
            and ASSET_URL.fullmatch(url)
        ):
            return url
    except (OSError, ValueError, TypeError, AttributeError):
        pass
    return ""


def link_artifacts(
    markdown: str, *, charts_url: str, metrics_url: str, image_url: str = ""
) -> str:
    charts_url = current_artifact_url(charts_url)
    metrics_url = current_artifact_url(metrics_url)
    image_url = (
        image_url
        if isinstance(image_url, str) and ASSET_URL.fullmatch(image_url)
        else ""
    )

    def replace(match: re.Match[str]) -> str:
        label = match.group(1) or match.group(2)
        if image_url and match.group(2) == "dashboard.png":
            image = f"![{label}]({image_url})"
            if charts_url:
                image += f"\n\n[Download {label} (PNG archive)]({charts_url})"
            return image
        if charts_url and match.group(2) == "dashboard.png":
            return f"[Download {label} (PNG archive)]({charts_url})"
        return (
            f"**Chart image unavailable ({label}):** "
            "no current-run dashboard artifact. Measurements remain in the table."
        )

    updated = _IMAGE.sub(replace, markdown)
    downloads = [START, "", "**Report downloads**", ""]
    if metrics_url:
        downloads.append(f"[Normalized measurements (JSON)]({metrics_url})")
    else:
        downloads.append("Normalized measurements download unavailable for this run.")
    downloads.extend(
        [
            "",
            (
                "Downloads require GitHub sign-in and are retained for 14 days. "
                "The measurements and gate decisions remain in this comment."
            ),
            "",
            END,
        ]
    )
    section = "\n".join(downloads)
    if START in updated and END in updated:
        before, rest = updated.split(START, 1)
        _, after = rest.split(END, 1)
        return before + section + after
    return updated.rstrip() + "\n\n" + section + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--markdown", required=True)
    parser.add_argument("--attachment", type=Path)
    parser.add_argument(
        "--chart", type=Path, default=Path("reports/quality/charts/dashboard.png")
    )
    parser.add_argument("--no-summary", action="store_true")
    args = parser.parse_args()
    path = Path(args.markdown)
    if not path.is_file():
        print(f"quality artifact linking skipped; missing {path}")
        return 0
    updated = link_artifacts(
        path.read_text(encoding="utf-8"),
        charts_url=os.environ.get("QUALITY_CHARTS_ARTIFACT_URL", ""),
        metrics_url=os.environ.get("QUALITY_METRICS_ARTIFACT_URL", ""),
        image_url=read_attachment(args.attachment, args.chart),
    )
    path.write_text(updated, encoding="utf-8", newline="\n")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary and not args.no_summary:
        with Path(summary).open("a", encoding="utf-8") as handle:
            handle.write("\n" + updated + "\n")
    print(f"Linked current-run quality artifacts in {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
