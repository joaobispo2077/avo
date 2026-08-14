from __future__ import annotations

import time

import pytest
from pathlib import Path

from avo.timeline.review import write_review_package
from avo.timeline.review_study import (
    _expected_answers, begin_session, complete_session, prepare_study, study_status,
)


def package(index: int):
    candidate = chr(97 + index) * 64
    return {
        "schemaVersion": "1.0.0",
        "checkpoint": "pre-master",
        "candidate": {
            "sha256": candidate,
            "byteSize": 100 + index,
            "path": f"/candidate-{index}.mp4",
            "dependencies": {"cmap": "b" * 64},
            "renderProfile": "pre-master",
            "identityHash": "c" * 64,
        },
        "dependencyLockSha256": "d" * 64,
        "changeSummary": {
            "headline": f"CMap revision {index + 1} trims one idle pause",
            "items": [{
                "artifactType": "cmap",
                "revisionId": f"cmap-r{index + 1:04d}",
                "reason": "remove idle pause without changing meaning",
                "operationCounts": {"replace": 1},
                "targets": [f"segment-{index + 1:02d}"],
                "truncatedTargets": 0,
            }],
            "windows": [{
                "start": float(index), "end": float(index + 1),
                "reason": f"idle-pause-{index}",
            }],
            "staleDependencies": [],
        },
        "state": "ai-passed",
        "evidence": [{
            "evidenceId": f"watch-{index}",
            "kind": "watch",
            "tool": {"name": "watch", "version": "1", "model": None},
            "runAt": "2026-08-14T00:00:00Z",
            "candidateHash": candidate,
            "candidateIdentityHash": "c" * 64,
            "dependencyLockSha256": "d" * 64,
            "dependencyHashes": {"cmap": "b" * 64},
            "dependencyProfile": "exact-candidate",
            "scope": {"mode": "full", "windows": [], "rationale": "full"},
            "coverage": {"requiredWindows": 0, "reviewedWindows": 0},
            "status": "pass",
            "findings": [],
            "artifacts": [],
            "attempt": 1,
        }],
        "attempts": [],
        "unresolvedRisks": [],
        "approval": None,
    }


def test_five_review_packages_expose_comprehension_fields_under_120_seconds(tmp_path: Path):
    successful = 0
    timings = []
    for index in range(5):
        started = time.perf_counter()
        _, markdown = write_review_package(tmp_path / str(index), package(index))
        text = markdown.read_text(encoding="utf-8")
        answers = {
            "what": "What changed" in text,
            "actualChange": f"CMap revision {index + 1} trims one idle pause" in text,
            "whereWhy": "Where and why" in text,
            "stale": "Stale dependencies" in text,
            "evidence": "Evidence matrix" in text,
            "hashes": "Candidate SHA-256" in text and "Dependency lock" in text,
            "question": "Exact decision question" in text,
        }
        elapsed = time.perf_counter() - started
        timings.append(elapsed)
        successful += int(all(answers.values()) and elapsed < 120)
    assert successful >= 4
    assert max(timings) < 120


def test_human_study_records_anonymous_four_of_five_result(tmp_path: Path):
    review_paths = []
    manifests = []
    for index in range(5):
        manifest = package(index)
        manifest["evidence"][0]["scope"]["windows"] = manifest["changeSummary"]["windows"]
        review_path, _ = write_review_package(tmp_path / "sources" / str(index), manifest)
        review_paths.append(review_path)
        manifests.append(manifest)

    prepared = prepare_study(
        tmp_path / "study", review_paths, actor="study-coordinator",
        clock=lambda: "2026-08-14T12:00:00Z",
    )
    study_path = Path(prepared["studyPath"])
    persisted_study = __import__("json").loads(study_path.read_text(encoding="utf-8"))
    assert persisted_study["packages"][0]["reviewPath"] == "packages/package-01/review.json"
    assert persisted_study["packages"][0]["answersTemplatePath"] == "packages/package-01/answers-template.json"
    raw_tokens = []
    last = None
    for index in range(5):
        token = f"reviewer-{index}"
        raw_tokens.append(token)
        started = begin_session(
            study_path, reviewer_token=token, package_id=f"package-{index + 1:02d}",
            clock=lambda index=index: f"2026-08-14T12:{index:02d}:00Z",
        )
        assert Path(started["reviewPath"]).is_absolute()
        assert Path(started["reviewPath"]).is_file()
        template_path = Path(started["answersTemplatePath"])
        assert template_path.is_absolute() and template_path.is_file()
        template = __import__("json").loads(template_path.read_text(encoding="utf-8"))
        assert set(template) == {
            "whatChanged", "whereWhy", "staleDependencies", "evidenceStatuses",
            "candidateSha256", "dependencyLockSha256", "checkpoint",
        }
        answers = _expected_answers(manifests[index])
        if index == 4:
            answers["candidateSha256"] = "0" * 64
        last = complete_session(
            study_path, session_id=started["sessionId"], answers=answers,
            clock=lambda index=index: f"2026-08-14T12:{index:02d}:45Z",
        )
    assert last is not None
    assert last["studyState"] == "passed"
    assert last["summary"] == {"completed": 5, "passed": 4}
    assert study_status(study_path)["availablePackages"] == []
    persisted = study_path.read_text(encoding="utf-8")
    assert all(token not in persisted for token in raw_tokens)


def test_judgment_package_cannot_be_mistaken_for_approval(tmp_path: Path):
    manifest = package(0)
    manifest["state"] = "needs-human-judgment"
    manifest["unresolvedRisks"] = [{
        "classification": "rights",
        "message": "licence scope needs creator confirmation",
    }]
    _, markdown = write_review_package(tmp_path / "judgment", manifest)
    text = markdown.read_text(encoding="utf-8")
    assert "Creator judgment required" in text
    assert "cannot authorize approval" in text
    assert "Do you approve this exact" not in text


def test_human_study_rejects_generic_change_copy(tmp_path: Path):
    review_paths = []
    for index in range(5):
        manifest = package(index)
        if index == 0:
            del manifest["changeSummary"]
        review_paths.append(
            write_review_package(tmp_path / "sources" / str(index), manifest)[0]
        )
    with pytest.raises(ValueError, match="structured change summary"):
        prepare_study(tmp_path / "study", review_paths, actor="coordinator")


def test_human_study_rejects_duplicate_reviewer_and_late_response(tmp_path: Path):
    review_paths = [
        write_review_package(tmp_path / "sources" / str(index), package(index))[0]
        for index in range(5)
    ]
    prepared = prepare_study(tmp_path / "study", review_paths, actor="coordinator")
    study_path = Path(prepared["studyPath"])
    first = begin_session(
        study_path, reviewer_token="anonymous-one", package_id="package-01",
        clock=lambda: "2026-08-14T12:00:00Z",
    )
    with pytest.raises(ValueError, match="already"):
        begin_session(
            study_path, reviewer_token="anonymous-one", package_id="package-02",
        )
    result = complete_session(
        study_path, session_id=first["sessionId"],
        answers=_expected_answers(package(0)),
        clock=lambda: "2026-08-14T12:02:01Z",
    )
    assert result["elapsedSeconds"] == 121
    assert result["passed"] is False
