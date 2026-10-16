#!/usr/bin/env python3
"""Fail unless every mandatory CI job supplied a successful result."""

from __future__ import annotations

import json
import os
import sys

MANDATORY_JOBS = (
    "prerequisites-gate",
    "repo-unit-tests",
    "repo-integration-tests",
    "software-quality",
    "usability-gate",
    "mutation-light",
)


def evaluate_needs(needs: object) -> list[str]:
    if not isinstance(needs, dict):
        return ["mandatory job results must be a JSON object"]
    failures = []
    for job in MANDATORY_JOBS:
        evidence = needs.get(job)
        result = evidence.get("result") if isinstance(evidence, dict) else None
        if result != "success":
            failures.append(f"{job}: expected success, received {result!r}")
    return failures


def main() -> int:
    try:
        needs = json.loads(os.environ.get("CI_NEEDS_JSON", ""))
    except json.JSONDecodeError as exc:
        failures = [f"invalid CI_NEEDS_JSON: {exc}"]
    else:
        failures = evaluate_needs(needs)
    if failures:
        print("CI readiness: FAIL", file=sys.stderr)
        for failure in failures:
            print(f"  {failure}", file=sys.stderr)
        return 1
    print("CI readiness: PASS (all mandatory jobs succeeded)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
