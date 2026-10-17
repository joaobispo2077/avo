#!/usr/bin/env python3
"""Select expensive CI work and guard PR publication using read-only GitHub data."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path


def select_run(
    workflow: str,
    event_name: str,
    repository: str,
    branch: str,
    sha: str,
    pulls: object,
) -> tuple[bool, str]:
    if event_name != "push" or not branch.startswith("feature/"):
        return True, "This event requires full validation."
    if not repository or not sha or not isinstance(pulls, list):
        return True, "PR identity is uncertain; running full validation."
    for pr in pulls:
        try:
            matches = (
                pr["state"] == "open"
                and type(pr["number"]) is int
                and pr["number"] > 0
                and pr["head"]["repo"]["full_name"] == repository
                and pr["head"]["ref"] == branch
                and pr["head"]["sha"] == sha
                and pr["base"]["repo"]["full_name"] == repository
                and isinstance(pr["base"]["ref"], str)
                and bool(pr["base"]["ref"])
                and (
                    workflow == "engine-binary"
                    or pr["base"]["ref"] in {"develop", "release", "main"}
                )
            )
        except (KeyError, TypeError):
            return True, "PR response is incomplete; running full validation."
        if matches:
            return False, "An open PR validates this feature commit; push work skipped."
    return True, "No eligible open PR validates this commit; running full validation."


def is_current_pr(event: dict, current: object, repository: str) -> bool:
    """A stale/closed PR or failed lookup must never authorize publication."""
    try:
        expected = event["pull_request"]
        if (
            not repository
            or current["state"] != "open"
            or type(current["number"]) is not int
            or current["number"] != event["number"]
        ):
            return False
        for side in ("head", "base"):
            for field in ("sha", "ref"):
                value = expected[side][field]
                if (
                    not isinstance(value, str)
                    or not value
                    or current[side][field] != value
                ):
                    return False
            source = expected[side]["repo"]["full_name"]
            if (
                not isinstance(source, str)
                or not source
                or current[side]["repo"]["full_name"] != source
            ):
                return False
        return expected["base"]["repo"]["full_name"] == repository
    except (KeyError, TypeError):
        return False


def github_api(endpoint: str, *args: str) -> object:
    result = subprocess.run(
        ["gh", "api", "--method", "GET", endpoint, *args],
        check=True,
        capture_output=True,
        text=True,
        timeout=20,
    )
    return json.loads(result.stdout)


def output(name: str, value: str) -> None:
    if os.environ.get("GITHUB_OUTPUT"):
        with Path(os.environ["GITHUB_OUTPUT"]).open("a", encoding="utf-8") as stream:
            stream.write(f"{name}={value}\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workflow", choices=("ci", "engine-binary"), required=True)
    parser.add_argument("--check-pr-current", action="store_true")
    args = parser.parse_args(argv)
    event_name = os.environ.get("GITHUB_EVENT_NAME", "")
    repository = os.environ.get("GITHUB_REPOSITORY", "")
    branch = os.environ.get("GITHUB_REF_NAME", "")
    sha = os.environ.get("GITHUB_SHA", "")
    if args.check_pr_current:
        number = ""
        try:
            if event_name == "pull_request":
                event = json.loads(
                    Path(os.environ["GITHUB_EVENT_PATH"]).read_text(encoding="utf-8")
                )
                candidate = event["number"]
                if type(candidate) is int and candidate > 0 and repository:
                    current = github_api(f"repos/{repository}/pulls/{candidate}")
                    if is_current_pr(event, current, repository):
                        number = str(candidate)
        except (OSError, KeyError, TypeError, ValueError, subprocess.SubprocessError):
            pass
        output("number", number)
        print("PR publication permitted." if number else "PR publication skipped.")
        return 0

    pulls = []
    try:
        if event_name == "push" and branch.startswith("feature/"):
            if not repository or not sha:
                raise ValueError("Missing repository or commit identity")
            # One exact match is sufficient. If the first page has none, run CI.
            pulls = github_api(
                f"repos/{repository}/pulls",
                "-f",
                "state=open",
                "-f",
                f"head={repository.split('/')[0]}:{branch}",
                "-f",
                "per_page=100",
            )
        run, reason = select_run(
            args.workflow, event_name, repository, branch, sha, pulls
        )
        if not run:
            candidate = next(
                pr
                for pr in pulls
                if not select_run(
                    args.workflow, event_name, repository, branch, sha, [pr]
                )[0]
            )
            # GitHub does not start pull_request workflows for conflicted PRs.
            current = github_api(f"repos/{repository}/pulls/{candidate['number']}")
            run, reason = select_run(
                args.workflow, event_name, repository, branch, sha, [current]
            )
            if not run and current.get("mergeable") is not True:
                run, reason = (
                    True,
                    "PR mergeability is unconfirmed; running full validation.",
                )
    except (OSError, ValueError, subprocess.SubprocessError):
        run, reason = True, "PR lookup unavailable; running full validation."
    output("run_full_ci", str(run).lower())
    output("reason", reason)
    print(reason)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with Path(os.environ["GITHUB_STEP_SUMMARY"]).open(
            "a", encoding="utf-8"
        ) as stream:
            stream.write(f"## CI selection\n\n{reason}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
