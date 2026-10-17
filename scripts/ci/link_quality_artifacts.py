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
_DETAIL = re.compile(r"\[([^\]]*)\]\(kpi-detail:(hotspots\.md|coupling-index\.md)\)")
CHART_FILES = {
    "dashboard": "dashboard.png",
    "hotspots": "hotspots.png",
    "coupling_files": "coupling-files.png",
}
START = "<!-- quality-artifacts:start -->"
END = "<!-- quality-artifacts:end -->"
ASSET_URL = re.compile(
    r"https://github\.com/user-attachments/assets/"
    r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}"
)


def current_artifact_url(value: str) -> str:
    """Accept only an upload action's URL for this repository and workflow run."""
    if not isinstance(value, str):
        return ""
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


def read_attachment(path: Path | None, chart: Path, *, role: str = "dashboard") -> str:
    """Accept an upload receipt only for these exact commit/run and PNG bytes."""
    if path is None or role not in CHART_FILES or chart.name != CHART_FILES[role]:
        return ""
    try:
        receipt = json.loads(path.read_text(encoding="utf-8"))
        sha, run_id = (
            os.environ.get("GITHUB_SHA", ""),
            os.environ.get("GITHUB_RUN_ID", ""),
        )
        url = receipt.get("url", "")
        legacy = (
            role == "dashboard" and "role" not in receipt and "filename" not in receipt
        )
        role_matches = (
            receipt.get("role") == role and receipt.get("filename") == CHART_FILES[role]
        )
        if (
            (legacy or role_matches)
            and re.fullmatch(r"[0-9a-f]{40}", sha)
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
    markdown: str,
    *,
    charts_url: str,
    metrics_url: str,
    image_url: str = "",
    hotspots_url: str = "",
    coupling_url: str = "",
    hotspots_image_url: str = "",
    coupling_image_url: str = "",
) -> str:
    charts_url = current_artifact_url(charts_url)
    metrics_url = current_artifact_url(metrics_url)
    hotspots_url = current_artifact_url(hotspots_url)
    coupling_url = current_artifact_url(coupling_url)
    images = {
        "dashboard.png": (image_url, charts_url),
        "hotspots.png": (hotspots_image_url, hotspots_url),
        "coupling-files.png": (coupling_image_url, coupling_url),
    }
    images = {
        filename: (
            url if isinstance(url, str) and ASSET_URL.fullmatch(url) else "",
            archive,
        )
        for filename, (url, archive) in images.items()
    }

    def replace(match: re.Match[str]) -> str:
        label = match.group(1) or match.group(2)
        filename = match.group(2)
        native, archive = images.get(filename, ("", ""))
        archive_kind = (
            "PNG archive" if filename == "dashboard.png" else "chart and text archive"
        )
        download = f"[Download {label} ({archive_kind})]({archive})" if archive else ""
        if native:
            image = f"![{label}]({native})"
            if download:
                image += "\n\n" + download
            return image
        if download:
            return download
        return (
            f"**Chart image unavailable ({label}):** "
            "no current-run image or archive for this chart. Measurements remain in the table."
        )

    updated = _IMAGE.sub(replace, markdown)
    details = {"hotspots.md": hotspots_url, "coupling-index.md": coupling_url}

    def detail(match: re.Match[str]) -> str:
        label, filename = match.groups()
        url = details[filename]
        if url:
            return f"[{label} ({filename}; complete text index, archive)]({url})"
        return f"**Complete text index unavailable for this run ({filename}).**"

    updated = _DETAIL.sub(detail, updated)
    downloads = [START, "", "**Report downloads**", ""]
    if metrics_url:
        downloads.append(f"[Normalized measurements (JSON)]({metrics_url})")
    else:
        downloads.append("Normalized measurements download unavailable for this run.")
    for filename, url in details.items():
        if url:
            downloads.extend(["", f"[{filename} and supporting data (archive)]({url})"])
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
    parser.add_argument("--hotspots-attachment", type=Path)
    parser.add_argument("--coupling-attachment", type=Path)
    parser.add_argument(
        "--hotspots-chart",
        type=Path,
        default=Path("reports/quality/hotspots/hotspots.png"),
    )
    parser.add_argument(
        "--coupling-chart",
        type=Path,
        default=Path("reports/quality/coupling/coupling-files.png"),
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
        hotspots_url=os.environ.get("QUALITY_HOTSPOTS_ARTIFACT_URL", ""),
        coupling_url=os.environ.get("QUALITY_COUPLING_ARTIFACT_URL", ""),
        hotspots_image_url=read_attachment(
            args.hotspots_attachment, args.hotspots_chart, role="hotspots"
        ),
        coupling_image_url=read_attachment(
            args.coupling_attachment, args.coupling_chart, role="coupling_files"
        ),
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
