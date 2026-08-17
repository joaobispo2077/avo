#!/usr/bin/env python3
"""Fail if mutmut CI/CD stats are below the profile floor (task-019)."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "scripts/ci/mutation-config.json"


def score_percent(killed: int, survived: int) -> float:
    denom = killed + survived
    if denom <= 0:
        return 0.0
    return 100.0 * killed / denom


def evaluate(
    stats: dict[str, object],
    *,
    min_killed_percent: float,
) -> tuple[bool, str]:
    killed = int(stats.get("killed") or 0)
    survived = int(stats.get("survived") or 0)
    total = int(stats.get("total") or 0)
    score = score_percent(killed, survived)
    if total <= 0:
        return False, "mutation produced zero mutants (check source_paths / tests)"
    if score < min_killed_percent:
        return (
            False,
            f"mutation score {score:.1f}% < floor {min_killed_percent:.1f}% "
            f"(killed={killed} survived={survived} total={total})",
        )
    return (
        True,
        f"mutation score {score:.1f}% >= floor {min_killed_percent:.1f}% "
        f"(killed={killed} survived={survived} total={total})",
    )


def main() -> int:
    profile = os.environ.get("AVO_MUTATION_PROFILE", "full")
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    if profile not in config:
        print(f"unknown AVO_MUTATION_PROFILE={profile!r}", file=sys.stderr)
        return 2
    floor = float(config[profile]["min_killed_percent"])
    stats_path = Path(
        os.environ.get("AVO_MUTATION_STATS", str(ROOT / "mutants/mutmut-cicd-stats.json"))
    )
    if not stats_path.is_file():
        print(f"missing mutation stats: {stats_path}", file=sys.stderr)
        return 1
    stats = json.loads(stats_path.read_text(encoding="utf-8"))
    ok, message = evaluate(stats, min_killed_percent=floor)
    print(message)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
