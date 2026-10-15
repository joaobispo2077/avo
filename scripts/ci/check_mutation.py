#!/usr/bin/env python3
"""Fail if mutmut CI/CD stats are below the profile floor (task-019)."""

from __future__ import annotations

import json
import math
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "scripts/ci/mutation-config.json"
MUTANT_STATUSES = (
    "killed",
    "survived",
    "no_tests",
    "skipped",
    "suspicious",
    "timeout",
    "check_was_interrupted_by_user",
    "segfault",
    "not_checked",
    "caught_by_type_check",
    "untested",
)
COUNT_ALIASES = {
    "timeout": "timeouts",
    "check_was_interrupted_by_user": "check_was_interrupted",
}


def normalize_mutation_counts(stats: object) -> dict[str, int]:
    """Validate mutmut export counters without coercing or inventing results."""
    if not isinstance(stats, dict):
        raise ValueError("mutation stats JSON must be an object")
    counts = {}
    for name in (*MUTANT_STATUSES, "total"):
        names = (name, COUNT_ALIASES.get(name, name))
        values = [stats[key] for key in dict.fromkeys(names) if key in stats]
        if not values and name in {"killed", "survived", "total"}:
            raise ValueError(f"mutation stats missing required count: {name}")
        if any(type(value) is not int or value < 0 for value in values):
            raise ValueError(f"mutation count {name} must be a nonnegative integer")
        if len(set(values)) > 1:
            raise ValueError(f"mutation count {name} has conflicting aliases")
        counts[name] = values[0] if values else 0
    if sum(counts[name] for name in MUTANT_STATUSES) > counts["total"]:
        raise ValueError("mutation status counts exceed total")
    return counts


def score_percent(killed: int, survived: int) -> float:
    denom = killed + survived
    if denom <= 0:
        return 0.0
    return 100.0 * killed / denom


def mutation_evaluation(
    stats: object,
    *,
    min_killed_percent: float,
) -> dict[str, object]:
    """A score is evidence only when every mutant has a test verdict.

    mutmut 3.7 exports omit not_checked and caught_by_type_check although they
    contribute to total. Never infer a kill or equivalent from that remainder.
    """
    result: dict[str, object] = {
        "status": "INVALID",
        "complete": False,
        "score": None,
        "counts": {},
        "unresolved": None,
        "reason": "",
    }
    try:
        counts = normalize_mutation_counts(stats)
        if (
            type(min_killed_percent) not in (int, float)
            or not math.isfinite(min_killed_percent)
            or not 0 <= min_killed_percent <= 100
        ):
            raise ValueError("mutation floor must be a finite percentage from 0 to 100")
    except ValueError as exc:
        result["reason"] = str(exc)
        return result
    result["counts"] = counts
    unresolved = {
        name: count
        for name, count in counts.items()
        if name not in {"killed", "survived", "total"} and count
    }
    unaccounted = counts["total"] - sum(counts[name] for name in MUTANT_STATUSES)
    if unaccounted:
        unresolved["unaccounted"] = unaccounted
    result["unresolved"] = sum(unresolved.values())
    if not counts["total"]:
        result["status"] = "INCOMPLETE"
        result["reason"] = "mutation produced zero mutants (check source_paths / tests)"
    elif unresolved:
        result["status"] = "INCOMPLETE"
        details = ", ".join(f"{name}={count}" for name, count in unresolved.items())
        result["reason"] = f"mutation incomplete: {details}; efficacy unavailable"
    else:
        score = score_percent(counts["killed"], counts["survived"])
        passed = score >= min_killed_percent
        result.update(status="PASS" if passed else "FAIL", complete=True, score=score)
        comparison = ">=" if passed else "<"
        result["reason"] = (
            f"mutation score {score:.1f}% {comparison} floor {min_killed_percent:.1f}% "
            f"(killed={counts['killed']} survived={counts['survived']} "
            f"total={counts['total']})"
        )
    return result


def evaluate(
    stats: object,
    *,
    min_killed_percent: float,
) -> tuple[bool, str]:
    result = mutation_evaluation(stats, min_killed_percent=min_killed_percent)
    return result["status"] == "PASS", str(result["reason"])


def main() -> int:
    profile = os.environ.get("AVO_MUTATION_PROFILE", "full")
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    if profile not in config:
        print(f"unknown AVO_MUTATION_PROFILE={profile!r}", file=sys.stderr)
        return 2
    floor = float(config[profile]["min_killed_percent"])
    stats_path = Path(
        os.environ.get(
            "AVO_MUTATION_STATS", str(ROOT / "mutants/mutmut-cicd-stats.json")
        )
    )
    if not stats_path.is_file():
        print(f"missing mutation stats: {stats_path}", file=sys.stderr)
        return 1
    try:
        stats = json.loads(stats_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"invalid mutation stats: {exc}", file=sys.stderr)
        return 1
    ok, message = evaluate(stats, min_killed_percent=floor)
    print(message)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
