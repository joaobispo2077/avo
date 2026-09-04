from __future__ import annotations

from pathlib import Path

from avo.adapters.understand.watch_policy import resolve_watch_policy
from avo.timeline.review_runner import ReviewRunner
from tests.test_timeline_review_integration import FakeQc, FakeTranscript, FakeWatch


def _run(tmp_path: Path, policy, watch: FakeWatch) -> dict:
    tmp_path.mkdir(parents=True, exist_ok=True)
    candidate = tmp_path / "proof.mp4"
    candidate.write_bytes(b"candidate")
    return ReviewRunner(
        review_root=tmp_path / "review",
        transcription=FakeTranscript(),
        watch=watch,
        deterministic_qc=FakeQc(),
        clock=lambda: "2026-09-02T00:00:00Z",
        watch_policy=policy,
    ).run(
        checkpoint="cut-proof",
        candidate=candidate,
        dependencies={"cmap": "b" * 64, "sync-map": "c" * 64},
        render_profile="proof",
        risk_windows=[{"start": 0.2, "end": 0.4, "reason": "join"}],
        terms=["API"],
        names=["Alex"],
    )


def test_policy_context_and_facts_are_forwarded_and_identity_bound(
    tmp_path: Path,
) -> None:
    policy = resolve_watch_policy(
        scopes=[
            (
                "project",
                {
                    "format": "tutorial",
                    "language": "en",
                    "acceptanceCriteria": ["labels readable"],
                },
            )
        ]
    )
    watch = FakeWatch()
    result = _run(tmp_path, policy, watch)
    request = watch.requests[0]
    assert request["policy"]["policyHash"] == policy.policy_hash
    assert request["context"]["format"] == "tutorial"
    assert request["terms"] == ["API"]
    assert request["names"] == ["Alex"]
    assert result["candidate"]["dependencies"]["watch-policy"] == policy.policy_hash


def test_unrelated_policy_resolutions_have_distinct_evidence_identity(
    tmp_path: Path,
) -> None:
    first = resolve_watch_policy(scopes=[("project", {"language": "pt-BR"})])
    second = resolve_watch_policy(scopes=[("project", {"language": "ja"})])
    left = _run(tmp_path / "left", first, FakeWatch())
    right = _run(tmp_path / "right", second, FakeWatch())
    assert first.context["language"] == "pt-BR"
    assert second.context["language"] == "ja"
    assert left["candidate"]["identityHash"] != right["candidate"]["identityHash"]


class MaterializationQc:
    def __init__(self, *, blocked: bool = False) -> None:
        self.blocked = blocked
        self.requests = []

    def check(self, candidate: Path, **request):
        self.requests.append(request)
        fidelity = {
            "kind": "source-fidelity",
            "status": "error" if self.blocked else "pass",
            "disposition": "blocked" if self.blocked else "pass",
            "details": {"offendingNodeIds": ["base-001"] if self.blocked else []},
            "findings": (
                [
                    {
                        "id": "canonical-lock-stale",
                        "classification": "prerequisite",
                        "message": "re-materialize the current assembly",
                    }
                ]
                if self.blocked
                else []
            ),
        }
        return {
            "status": "fail" if self.blocked else "pass",
            "duration": 2,
            "coverage": {"mode": "full", "windows": []},
            "requiredWindows": [],
            "findings": fidelity["findings"],
            "tool": "qc-fixture",
            "toolVersion": "1",
            "evidence": [
                {"kind": kind, "status": "pass", "findings": []}
                for kind in (
                    "lineage",
                    "technical-qc",
                    "sync",
                    "audio-qc",
                    "visual-qc",
                    "accessibility",
                    "rights",
                )
            ]
            + [fidelity],
        }


class CurrentWorkspace:
    def active_dependency_snapshot(self):
        return {
            "cmap": "a" * 64,
            "sync-map": "b" * 64,
            "bmap": "c" * 64,
            "tracks": "d" * 64,
        }


def _materialization() -> dict:
    return {
        "materializationHash": "1" * 64,
        "deliveryFidelityPolicyHash": "2" * 64,
        "pictureLineageHash": "3" * 64,
        "canonicalInputLock": {
            "cmapRevisionHash": "a" * 64,
            "syncRevisionHash": "b" * 64,
            "bmapRevisionHash": "c" * 64,
            "tracksRevisionHash": "d" * 64,
        },
    }


def test_final_review_forwards_and_identity_binds_materialization(
    tmp_path: Path,
) -> None:
    candidate = tmp_path / "master.mp4"
    candidate.write_bytes(b"master")
    qc = MaterializationQc()
    materialization = _materialization()
    result = ReviewRunner(
        review_root=tmp_path / "review",
        transcription=FakeTranscript(),
        watch=FakeWatch(),
        deterministic_qc=qc,
        workspace=CurrentWorkspace(),
        clock=lambda: "2026-09-02T00:00:00Z",
    ).run(
        checkpoint="pre-master",
        candidate=candidate,
        dependencies={"raw": "e" * 64, "sourceUsage": "f" * 64},
        render_profile="master",
        materialization=materialization,
        materialization_path=tmp_path / "assembly.json",
    )
    assert result["state"] == "ai-passed"
    assert result["candidate"]["dependencies"]["materialization"] == "1" * 64
    assert result["candidate"]["dependencies"]["delivery-fidelity-policy"] == "2" * 64
    assert result["candidate"]["dependencies"]["picture-lineage"] == "3" * 64
    assert qc.requests[0]["materialization"] is materialization
    assert qc.requests[0]["current_revision_hashes"]["tracksRevisionHash"] == "d" * 64
    evidence = next(
        item for item in result["evidence"] if item["kind"] == "source-fidelity"
    )
    assert evidence["fidelityDetails"]["offendingNodeIds"] == []


def test_fidelity_prerequisite_classification_blocks_without_fixing(
    tmp_path: Path,
) -> None:
    candidate = tmp_path / "master.mp4"
    candidate.write_bytes(b"master")
    result = ReviewRunner(
        review_root=tmp_path / "review",
        transcription=FakeTranscript(),
        watch=FakeWatch(),
        deterministic_qc=MaterializationQc(blocked=True),
        workspace=CurrentWorkspace(),
        clock=lambda: "2026-09-02T00:00:00Z",
    ).run(
        checkpoint="deliver",
        candidate=candidate,
        dependencies={},
        render_profile="master",
        materialization=_materialization(),
    )
    assert result["state"] == "blocked"
    assert result["approvalGatePath"] is None
