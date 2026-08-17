# Human review-package comprehension study for SC-003.

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Callable
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from .contracts import content_hash, file_fingerprint, validate_document
from .review import write_review_package
from .store import atomic_write_json, now_iso

REQUIRED_REVIEWERS = 5
PASS_THRESHOLD = 4
MAX_SECONDS = 120.0
ANSWER_FIELDS = (
    "whatChanged",
    "whereWhy",
    "staleDependencies",
    "evidenceStatuses",
    "candidateSha256",
    "dependencyLockSha256",
    "checkpoint",
)


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON must contain an object: {path}")
    return value


def _reviewer_hash(token: str) -> str:
    if len(token.strip()) < 3:
        raise ValueError("reviewer token must contain at least three characters")
    return hashlib.sha256(token.strip().encode("utf-8")).hexdigest()


def _expected_answers(manifest: dict[str, Any]) -> dict[str, Any]:
    change_summary = manifest.get("changeSummary") or {}
    windows: list[dict[str, Any]] = list(change_summary.get("windows") or [])
    evidence_statuses: dict[str, str] = {}
    stale: list[str] = list(change_summary.get("staleDependencies") or [])
    for item in manifest.get("evidence") or []:
        kind = str(item["kind"])
        evidence_statuses[kind] = str(item["status"])
        if item.get("status") == "stale":
            stale.append(kind)
        for window in (item.get("scope") or {}).get("windows") or []:
            normalized = {
                "start": float(window["start"]),
                "end": float(window["end"]),
                "reason": str(window["reason"]),
            }
            if normalized not in windows:
                windows.append(normalized)
    return {
        "whatChanged": str(
            change_summary.get("headline")
            or "candidate bytes and exact canonical dependency snapshot"
        ),
        "whereWhy": windows
        or [{"scope": "full-program", "reason": "checkpoint review"}],
        "staleDependencies": sorted(stale),
        "evidenceStatuses": dict(sorted(evidence_statuses.items())),
        "candidateSha256": manifest["candidate"]["sha256"],
        "dependencyLockSha256": manifest["dependencyLockSha256"],
        "checkpoint": manifest["checkpoint"],
    }


def _questions(package_id: str) -> str:
    return "\n".join(
        [
            f"# Review comprehension questionnaire: {package_id}",
            "",
            "Read approval-gate.md. Do not inspect scoring.json. Answer JSON fields:",
            "",
            "- whatChanged: what changed in this candidate?",
            "- whereWhy: where did it change and why? Copy the shown windows/reasons, or full-program scope.",
            "- staleDependencies: list every stale evidence/dependency kind.",
            "- evidenceStatuses: map every evidence kind to its status.",
            "- candidateSha256: exact candidate SHA-256.",
            "- dependencyLockSha256: exact dependency-lock SHA-256.",
            "- checkpoint: exact approval checkpoint.",
            "",
            "Complete within 120 seconds of begin.",
            "",
        ]
    )


def prepare_study(
    output_dir: Path,
    review_paths: list[Path],
    *,
    actor: str,
    clock: Callable[[], str] = now_iso,
) -> dict[str, Any]:
    if len(review_paths) != REQUIRED_REVIEWERS:
        raise ValueError(
            f"SC-003 requires exactly {REQUIRED_REVIEWERS} representative packages"
        )
    resolved = [Path(path).resolve() for path in review_paths]
    if len(set(resolved)) != REQUIRED_REVIEWERS:
        raise ValueError("study review packages must be unique")
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    study_path = root / "study.json"
    if study_path.exists():
        raise ValueError(f"study already exists: {study_path}")
    packages = []
    scoring = {"schemaVersion": "1.0.0", "packages": {}}
    for index, source in enumerate(resolved, start=1):
        manifest = _load_json(source)
        validate_document(manifest, "avo.review-evidence.schema.json")
        if manifest["state"] not in {"ai-passed", "needs-human-judgment"}:
            raise ValueError(f"review package is not human-reviewable: {source}")
        if not manifest.get("changeSummary"):
            raise ValueError(
                f"review package lacks structured change summary: {source}"
            )
        package_id = f"package-{index:02d}"
        package_dir = root / "packages" / package_id
        review_json, approval_gate = write_review_package(
            package_dir, deepcopy(manifest)
        )
        if approval_gate is None:
            raise ValueError(f"approval package could not be generated: {source}")
        questions = package_dir / "questions.md"
        questions.write_text(_questions(package_id), encoding="utf-8")
        answers_template = package_dir / "answers-template.json"
        atomic_write_json(
            answers_template,
            {
                "whatChanged": "",
                "whereWhy": [],
                "staleDependencies": [],
                "evidenceStatuses": {},
                "candidateSha256": "",
                "dependencyLockSha256": "",
                "checkpoint": "",
            },
        )
        packages.append(
            {
                "packageId": package_id,
                "reviewPath": review_json.relative_to(root).as_posix(),
                "approvalGatePath": approval_gate.relative_to(root).as_posix(),
                "questionsPath": questions.relative_to(root).as_posix(),
                "answersTemplatePath": answers_template.relative_to(root).as_posix(),
                "sourceReviewSha256": file_fingerprint(source)["sha256"],
            }
        )
        expected = _expected_answers(manifest)
        scoring["packages"][package_id] = {
            field: content_hash(value) for field, value in expected.items()
        }
    atomic_write_json(root / "scoring.json", scoring)
    study = {
        "schemaVersion": "1.0.0",
        "studyId": f"review-comprehension-{uuid4().hex[:12]}",
        "createdAt": clock(),
        "actor": actor,
        "requiredReviewers": REQUIRED_REVIEWERS,
        "passThreshold": PASS_THRESHOLD,
        "maxSeconds": MAX_SECONDS,
        "packages": packages,
        "sessions": [],
        "state": "collecting",
        "summary": {"completed": 0, "passed": 0},
    }
    atomic_write_json(study_path, study)
    return {**study, "studyPath": str(study_path)}


def begin_session(
    study_path: Path,
    *,
    reviewer_token: str,
    package_id: str,
    clock: Callable[[], str] = now_iso,
) -> dict[str, Any]:
    path = Path(study_path)
    study = _load_json(path)
    if study.get("state") != "collecting":
        raise ValueError("study is no longer collecting responses")
    package_ids = {item["packageId"] for item in study["packages"]}
    if package_id not in package_ids:
        raise ValueError(f"unknown package: {package_id}")
    reviewer_hash = _reviewer_hash(reviewer_token)
    if any(item["reviewerHash"] == reviewer_hash for item in study["sessions"]):
        raise ValueError("reviewer already has a study session")
    if any(item["packageId"] == package_id for item in study["sessions"]):
        raise ValueError("package already assigned to another reviewer")
    session = {
        "sessionId": f"session-{uuid4().hex[:12]}",
        "reviewerHash": reviewer_hash,
        "packageId": package_id,
        "startedAt": clock(),
        "completedAt": None,
        "elapsedSeconds": None,
        "answersCorrect": None,
        "passed": None,
    }
    study["sessions"].append(session)
    atomic_write_json(path, study)
    package = next(
        item for item in study["packages"] if item["packageId"] == package_id
    )
    resolved_package = dict(package)
    for key in (
        "reviewPath",
        "approvalGatePath",
        "questionsPath",
        "answersTemplatePath",
    ):
        resolved_package[key] = str((path.parent / package[key]).resolve())
    return {**session, **resolved_package, "studyPath": str(path.resolve())}


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def complete_session(
    study_path: Path,
    *,
    session_id: str,
    answers: dict[str, Any],
    clock: Callable[[], str] = now_iso,
) -> dict[str, Any]:
    path = Path(study_path)
    study = _load_json(path)
    session = next(
        (item for item in study["sessions"] if item["sessionId"] == session_id), None
    )
    if session is None:
        raise ValueError(f"unknown session: {session_id}")
    if session["completedAt"] is not None:
        raise ValueError("session is already complete")
    completed_at = clock()
    elapsed = (
        _parse_time(completed_at) - _parse_time(session["startedAt"])
    ).total_seconds()
    if elapsed < 0:
        raise ValueError("completion time precedes session start")
    scoring = _load_json(path.parent / "scoring.json")
    expected = scoring["packages"][session["packageId"]]
    correctness = {
        field: content_hash(answers.get(field)) == expected[field]
        for field in ANSWER_FIELDS
    }
    passed = elapsed <= float(study["maxSeconds"]) and all(correctness.values())
    session.update(
        {
            "completedAt": completed_at,
            "elapsedSeconds": elapsed,
            "answersCorrect": correctness,
            "passed": passed,
        }
    )
    completed = [item for item in study["sessions"] if item["completedAt"] is not None]
    passed_count = sum(bool(item["passed"]) for item in completed)
    study["summary"] = {"completed": len(completed), "passed": passed_count}
    if len(completed) >= int(study["requiredReviewers"]):
        study["state"] = (
            "passed" if passed_count >= int(study["passThreshold"]) else "failed"
        )
    atomic_write_json(path, study)
    return {
        "sessionId": session_id,
        "elapsedSeconds": elapsed,
        "answersCorrect": correctness,
        "passed": passed,
        "studyState": study["state"],
        "summary": study["summary"],
    }


def study_status(study_path: Path) -> dict[str, Any]:
    study = _load_json(study_path)
    return {
        "studyId": study["studyId"],
        "state": study["state"],
        "summary": study["summary"],
        "requiredReviewers": study["requiredReviewers"],
        "passThreshold": study["passThreshold"],
        "maxSeconds": study["maxSeconds"],
        "availablePackages": [
            item["packageId"]
            for item in study["packages"]
            if not any(
                session["packageId"] == item["packageId"]
                for session in study["sessions"]
            )
        ],
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m avo.timeline.review_study")
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare")
    prepare.add_argument("--output", type=Path, required=True)
    prepare.add_argument("--review", type=Path, action="append", required=True)
    prepare.add_argument("--actor", required=True)
    begin = commands.add_parser("begin")
    begin.add_argument("--study", type=Path, required=True)
    begin.add_argument("--reviewer-token", required=True)
    begin.add_argument("--package-id", required=True)
    complete = commands.add_parser("complete")
    complete.add_argument("--study", type=Path, required=True)
    complete.add_argument("--session-id", required=True)
    complete.add_argument("--answers", type=Path, required=True)
    status = commands.add_parser("status")
    status.add_argument("--study", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "prepare":
        result = prepare_study(args.output, args.review, actor=args.actor)
    elif args.command == "begin":
        result = begin_session(
            args.study,
            reviewer_token=args.reviewer_token,
            package_id=args.package_id,
        )
    elif args.command == "complete":
        result = complete_session(
            args.study,
            session_id=args.session_id,
            answers=_load_json(args.answers),
        )
    else:
        result = study_status(args.study)
    print(json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
