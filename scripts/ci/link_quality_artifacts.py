#!/usr/bin/env python3
"""Link current-run Actions artifacts in the quality report without Git writes.

The workflow uploads the PNG and normalized JSON first. Their artifact URLs are
download links, not embeddable images. Missing uploads leave the measurements
and gate decisions readable in the PR comment and job summary.
"""

from __future__ import annotations

import argparse
import os
import re
from pathlib import Path

_IMAGE = re.compile(r"!\[([^\]]*)\]\(kpi-chart:([A-Za-z0-9._-]+)\)")
START = "<!-- quality-artifacts:start -->"
END = "<!-- quality-artifacts:end -->"


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


def link_artifacts(markdown: str, *, charts_url: str, metrics_url: str) -> str:
    charts_url = current_artifact_url(charts_url)
    metrics_url = current_artifact_url(metrics_url)

    def replace(match: re.Match[str]) -> str:
        label = match.group(1) or match.group(2)
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
