#!/usr/bin/env python3
"""Retain run-bound per-source outcomes from mutmut 3.7 metadata (report-only)."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import importlib.util
import json
import math
import os
import re
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "scripts/ci/mutation-config.json"
_SPEC = importlib.util.spec_from_file_location(
    "avo_ci_mutation_scope_checker", Path(__file__).with_name("check_mutation.py")
)
assert _SPEC and _SPEC.loader
_CHECKER = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_CHECKER)
MUTANT_STATUSES = _CHECKER.MUTANT_STATUSES
TOOL = {"name": "mutmut", "version": "3.7.0"}
# mutmut 3.7's status_by_exit_code; unknown codes are suspicious. In its
# duplicate -24 mapping the final value is timeout (SIGXCPU), not killed.
STATUS_BY_EXIT_CODE = {
    1: "killed",
    3: "killed",
    0: "survived",
    5: "no_tests",
    33: "no_tests",
    2: "check_was_interrupted_by_user",
    None: "not_checked",
    34: "skipped",
    35: "suspicious",
    36: "timeout",
    37: "caught_by_type_check",
    -24: "timeout",
    24: "timeout",
    152: "timeout",
    255: "timeout",
    -11: "segfault",
    -9: "segfault",
}
_OMITTED = ("not_checked", "caught_by_type_check", "untested", "unaccounted")


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _read(path: Path):
    raw = path.read_bytes()
    return json.loads(raw, object_pairs_hook=_pairs), hashlib.sha256(raw).hexdigest()


def _identity(payload, *, sha, run_id, profile):
    if (
        not isinstance(payload, dict)
        or not isinstance(sha, str)
        or not re.fullmatch(r"[0-9a-f]{40}", sha)
        or not isinstance(run_id, str)
        or not run_id
        or payload.get("sha") != sha
        or payload.get("run_id") != run_id
        or payload.get("profile") != profile
    ):
        raise ValueError(
            "mutation scope identity does not match this commit/run/profile"
        )


def _safe_path(value, *, source=False):
    if (
        not isinstance(value, str)
        or not value
        or "\\" in value
        or ":" in value
        or any(ord(char) < 32 for char in value)
        or PurePosixPath(value).is_absolute()
        or PurePosixPath(value).as_posix() != value
        or any(part in {".", ".."} for part in value.split("/"))
        or (source and (not value.startswith("src/avo/") or not value.endswith(".py")))
    ):
        raise ValueError(f"unsafe mutation source/evidence path: {value!r}")
    return value


def _inside(root, relative):
    path = root / _safe_path(relative)
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError(f"mutation path escapes repository: {relative}")
    return path


def _profile(profile, config=None):
    config = config if config is not None else _read(CONFIG_PATH)[0]
    spec = config.get(profile) if isinstance(config, dict) else None
    if not isinstance(spec, dict):
        raise ValueError("unknown mutation profile")
    floor = spec.get("min_killed_percent")
    if (
        type(floor) not in (int, float)
        or not math.isfinite(floor)
        or not 0 <= floor <= 100
    ):
        raise ValueError("invalid aggregate mutation floor")
    paths = spec.get("source_paths")
    if not isinstance(paths, list) or not paths:
        raise ValueError("mutation profile has no source paths")
    paths = [_safe_path(path, source=True) for path in paths]
    if len({path.casefold() for path in paths}) != len(paths):
        raise ValueError("duplicate mutation source path")
    return floor, sorted(paths)


def _aggregate_counts(stats):
    if not isinstance(stats, dict):
        raise ValueError("mutation aggregate counters must be an object")
    counts = _CHECKER.normalize_mutation_counts(stats.get("counts", stats))
    counts["unaccounted"] = counts["total"] - sum(
        counts[key] for key in MUTANT_STATUSES
    )
    return counts


def _outcome(code):
    if code is not None and type(code) is not int:
        raise ValueError("invalid mutant outcome; expected integer exit code or null")
    return STATUS_BY_EXIT_CODE.get(code, "suspicious")


def _mutant_counts(mutants, path, seen):
    if not isinstance(mutants, list):
        raise ValueError("mutation scope mutants must be an array")
    counts = dict.fromkeys((*MUTANT_STATUSES, "total", "unaccounted"), 0)
    module = path.removeprefix("src/").removesuffix(".py").replace("/", ".")
    module = module.removesuffix(".__init__")
    for mutant in mutants:
        if not isinstance(mutant, dict):
            raise ValueError("invalid mutation identity record")
        name, code = mutant.get("id"), mutant.get("exit_code")
        if (
            not isinstance(name, str)
            or len(name) > 1000
            or not name.startswith(module + ".")
            or "__mutmut_" not in name
            or any(ord(char) < 32 for char in name)
            or name in seen
            or (code is not None and type(code) is not int)
        ):
            raise ValueError("invalid or duplicate mutant identity/outcome")
        seen.add(name)
        status = _outcome(code)
        if mutant.get("status") != status:
            raise ValueError("mutant status differs from its actual exit code")
        counts[status] += 1
        counts["total"] += 1
    return counts


def _measurement(counts):
    result = _CHECKER.mutation_evaluation(counts, min_killed_percent=0)
    if not counts["total"]:
        state, reason = "UNAVAILABLE", "Zero mutants; efficacy unavailable."
    elif not result["complete"]:
        state, reason = "PARTIAL", str(result["reason"])
    else:
        state, reason = "MEASURED", "Every mutant has a killed/survived verdict."
    return {
        "state": state,
        "reason": reason,
        "counts": counts,
        "complete": result["complete"],
        "score": result["score"],
        "unresolved": result["unresolved"],
    }


def _reconcile(rows, aggregate):
    known = [row["counts"] for row in rows if row["counts"] is not None]
    missing = len(known) != len(rows)
    summed = {key: sum(counts[key] for counts in known) for key in aggregate}
    keys = [key for key in aggregate if key not in _OMITTED]
    pairs = [(summed[key], aggregate[key]) for key in keys]
    # The upstream aggregate omits these buckets. Its unaccounted remainder
    # must reconcile with their actual per-mutant metadata outcomes.
    pairs.append(
        (sum(summed[key] for key in _OMITTED), sum(aggregate[key] for key in _OMITTED))
    )
    if any(
        actual > expected or (not missing and actual != expected)
        for actual, expected in pairs
    ):
        raise ValueError(
            "mutation scope counts do not reconcile with aggregate counters"
        )
    if missing:
        return (
            "PARTIAL",
            "Missing metadata; complete scope population cannot be reconciled.",
        )
    if any(row["state"] != "MEASURED" for row in rows):
        return (
            "PARTIAL",
            "Scope counters reconcile; some efficacy measurements are unavailable.",
        )
    return (
        "MEASURED",
        "All scope counters reconcile with the aggregate; threshold applies to the aggregate only.",
    )


def capture_scopes(
    *, root: Path, stats_path: Path, profile: str, sha: str, run_id: str, config=None
) -> dict:
    floor, paths = _profile(profile, config)
    if not stats_path.resolve().is_relative_to(root.resolve()):
        raise ValueError("aggregate mutation evidence path escapes repository")
    stats, stats_digest = _read(stats_path)
    _identity(stats, sha=sha, run_id=run_id, profile=profile)
    aggregate = _aggregate_counts(stats)
    rows, seen = [], set()
    for path in paths:
        source = _inside(root, path)
        metadata_path = "mutants/" + path + ".meta"
        meta = _inside(root, metadata_path)
        row = {
            "path": path,
            "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            "metadata": None,
            "mutants": [],
            "state": "UNAVAILABLE",
            "reason": "Mutation metadata is missing; no per-scope measurement retained.",
            "counts": None,
            "complete": False,
            "score": None,
            "unresolved": None,
        }
        if meta.is_file():
            data, digest = _read(meta)
            outcomes = data.get("exit_code_by_key") if isinstance(data, dict) else None
            if not isinstance(outcomes, dict):
                raise ValueError(f"invalid mutation metadata: {metadata_path}")
            row["metadata"] = {
                "path": metadata_path,
                "artifact_path": "scope-evidence/" + path + ".meta",
                "sha256": digest,
            }
            row["mutants"] = [
                {"id": name, "exit_code": code, "status": _outcome(code)}
                for name, code in sorted(outcomes.items())
            ]
            row.update(_measurement(_mutant_counts(row["mutants"], path, seen)))
        rows.append(row)
    state, reason = _reconcile(rows, aggregate)
    return {
        "schema": 1,
        "tool": TOOL.copy(),
        "sha": sha,
        "run_id": run_id,
        "profile": profile,
        "floor": floor,
        "threshold_scope": "aggregate",
        "state": state,
        "reason": reason,
        "aggregate": {
            "path": stats_path.relative_to(root).as_posix(),
            "artifact_path": "mutmut-cicd-stats-light.json"
            if profile == "light"
            else "mutmut-cicd-stats.json",
            "sha256": stats_digest,
            "counts": aggregate,
        },
        "scopes": rows,
    }


def validate_scopes(payload, *, sha, run_id, profile, aggregate) -> dict:
    """Validate frozen scope evidence without importing or executing mutmut."""
    _identity(payload, sha=sha, run_id=run_id, profile=profile)
    if type(payload.get("schema")) is not int or payload["schema"] != 1:
        raise ValueError("unsupported mutation scope schema")
    if payload.get("state") == "UNAVAILABLE" and payload.get("scopes") == []:
        if not isinstance(payload.get("reason"), str) or not payload["reason"]:
            raise ValueError("missing mutation scope diagnostic")
        return payload
    _identity(aggregate, sha=sha, run_id=run_id, profile=profile)
    floor, paths = _profile(profile)
    if (
        payload.get("tool") != TOOL
        or payload.get("threshold_scope") != "aggregate"
        or type(payload.get("floor")) not in (int, float)
        or payload["floor"] != floor
        or aggregate.get("floor") != floor
    ):
        raise ValueError("mutation scope tool/profile/aggregate policy mismatch")
    expected = _aggregate_counts(aggregate)
    proof = payload.get("aggregate")
    if (
        not isinstance(proof, dict)
        or proof.get("counts") != expected
        or any(
            type(value) is not int or value < 0 for value in proof["counts"].values()
        )
    ):
        raise ValueError("mutation scope aggregate counters mismatch")
    _safe_path(proof.get("path"))
    if proof.get("artifact_path") != (
        "mutmut-cicd-stats-light.json"
        if profile == "light"
        else "mutmut-cicd-stats.json"
    ):
        raise ValueError("mutation aggregate artifact path differs from its profile")
    _digest(proof.get("sha256"))
    rows = payload.get("scopes")
    if (
        not isinstance(rows, list)
        or [row.get("path") for row in rows if isinstance(row, dict)] != paths
    ):
        raise ValueError(
            "mutation scope population differs from configured source paths"
        )
    seen = set()
    for row in rows:
        path = _safe_path(row["path"], source=True)
        _digest(row.get("source_sha256"))
        metadata = row.get("metadata")
        if metadata is None:
            if (
                row.get("state") != "UNAVAILABLE"
                or row.get("counts") is not None
                or row.get("score") is not None
                or row.get("unresolved") is not None
                or row.get("complete") is not False
                or row.get("mutants") != []
            ):
                raise ValueError(
                    "missing mutation metadata cannot provide measured outcomes"
                )
            continue
        if (
            not isinstance(metadata, dict)
            or metadata.get("path") != "mutants/" + path + ".meta"
            or metadata.get("artifact_path") != "scope-evidence/" + path + ".meta"
        ):
            raise ValueError("mutation metadata path does not belong to its source")
        _digest(metadata.get("sha256"))
        counts = _mutant_counts(row.get("mutants"), path, seen)
        derived = _measurement(counts)
        if (
            row.get("counts") != counts
            or any(
                type(value) is not int or value < 0 for value in row["counts"].values()
            )
            or type(row.get("complete")) is not bool
            or type(row.get("unresolved")) is not int
            or (row.get("score") is not None and type(row["score"]) not in (int, float))
            or any(
                row.get(key) != derived[key]
                for key in ("state", "complete", "score", "unresolved")
            )
        ):
            raise ValueError(
                "mutation scope derived measurement differs from actual outcomes"
            )
    state, _ = _reconcile(rows, expected)
    if payload.get("state") != state:
        raise ValueError("mutation scope overall state differs from its evidence")
    return payload


def _digest(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ValueError("invalid mutation evidence SHA-256")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stats", default=str(ROOT / "mutants/mutmut-cicd-stats.json"))
    parser.add_argument(
        "--profile", default=os.environ.get("AVO_MUTATION_PROFILE", "light")
    )
    parser.add_argument(
        "--out", default=str(ROOT / "reports/mutation/mutation-scopes.json")
    )
    args = parser.parse_args(argv)
    output = Path(args.out)
    identity = {
        "sha": os.environ.get("GITHUB_SHA", "").strip().lower(),
        "run_id": os.environ.get("GITHUB_RUN_ID", "").strip(),
        "profile": args.profile,
    }
    try:
        if importlib.metadata.version("mutmut") != TOOL["version"]:
            raise ValueError(
                "mutation scope exporter supports installed mutmut 3.7.0 only"
            )
        payload = capture_scopes(root=ROOT, stats_path=Path(args.stats), **identity)
        proofs = [payload["aggregate"]] + [
            row["metadata"] for row in payload["scopes"] if row["metadata"] is not None
        ]
        for proof in proofs:
            raw = _inside(ROOT, proof["path"]).read_bytes()
            if hashlib.sha256(raw).hexdigest() != proof["sha256"]:
                raise ValueError("mutation evidence changed during capture")
            destination = _inside(output.parent, proof["artifact_path"])
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(raw)
    except (
        OSError,
        ValueError,
        TypeError,
        importlib.metadata.PackageNotFoundError,
    ) as exc:
        payload = {
            "schema": 1,
            **identity,
            "state": "UNAVAILABLE",
            "reason": f"Per-scope mutation evidence unavailable: {exc}",
            "scopes": [],
        }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(f"mutation scope evidence: {payload['state']} ({output})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
