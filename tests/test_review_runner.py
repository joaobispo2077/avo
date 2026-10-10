from __future__ import annotations

from pathlib import Path

from avo.adapters.understand.watch_policy import resolve_watch_policy
from avo.timeline.review_runner import (
    ReviewRunner,
    actual_coverage,
    fuse_review_evidence,
)
from tests.test_timeline_review_integration import FakeQc, FakeTranscript, FakeWatch


class RecordingTranscript(FakeTranscript):
    def __init__(self) -> None:
        super().__init__()
        self.calls: list[dict] = []

    def transcribe(self, candidate: Path, **options):
        self.calls.append({"candidate": candidate, **options})
        return super().transcribe(candidate, **options)


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


class SampledWatch(FakeWatch):
    def review(self, candidate: Path, **request):
        result = super().review(candidate, **request)
        result["coverage"] = {
            "mode": "sampled",
            "windows": [],
            "requestedWindows": request["windows"],
            "maxFrames": 18,
        }
        return result


class RequestedWindowsWatch(FakeWatch):
    def review(self, candidate: Path, **request):
        result = super().review(candidate, **request)
        result["coverage"] = {
            "mode": "full",
            "sampling": "frames",
            "windows": [],
            "requestedWindows": request["windows"],
            "maxFrames": 18,
        }
        return result


class AutomatedFailWatch(FakeWatch):
    def review(self, candidate: Path, **request):
        result = super().review(candidate, **request)
        result["status"] = "fail"
        result["disposition"] = "fail"
        result["visionCoverageManifest"]["aggregateStatus"] = "fail"
        return result


def test_requested_windows_do_not_claim_actual_full_review_when_observations_empty(
    tmp_path: Path,
) -> None:
    result = _run(tmp_path, None, RequestedWindowsWatch())
    assert result["state"] == "blocked"
    assert "every required" in result["blocker"]


def test_sampled_watch_evidence_cannot_satisfy_full_review(tmp_path: Path) -> None:
    result = _run(tmp_path, None, SampledWatch())
    assert result["state"] == "blocked"
    assert "full Watch evidence required" in result["blocker"]


def test_automated_fail_is_terminal_and_never_opens_human_gate(tmp_path: Path) -> None:
    result = _run(tmp_path, None, AutomatedFailWatch())
    assert result["state"] == "fail"
    assert result["approvalGatePath"] is None
    assert not (Path(result["reviewPath"]).parent / "approval-gate.md").exists()


def test_actual_coverage_never_infers_duration_from_nominal_full_scope() -> None:
    coverage = actual_coverage(
        {"mode": "full", "durationSeconds": 100, "inspectedRanges": []},
        required_windows=[],
    )
    assert coverage["reviewedSeconds"] == 0
    actual = actual_coverage(
        {
            "mode": "full",
            "durationSeconds": 100,
            "inspectedRanges": [{"start": 0, "end": 10}, {"start": 8, "end": 12}],
            "partiallyInspectedRanges": [{"start": 20, "end": 25}],
            "deterministicallyCheckedRanges": [{"start": 30, "end": 40}],
        },
        required_windows=[],
    )
    assert actual["reviewedSeconds"] == 17
    assert actual["deterministicallyCheckedSeconds"] == 10
    assert actual["uninspectedRanges"] == [
        {"start": 12.0, "end": 20.0},
        {"start": 25.0, "end": 30.0},
        {"start": 40.0, "end": 100.0},
    ]


def test_actual_coverage_accepts_observed_frame_ranges() -> None:
    actual = actual_coverage(
        {
            "durationSeconds": 10,
            "frameRate": {"num": 30, "den": 1},
            "inspectedRanges": [
                {"startFrame": 0, "endFrameExclusive": 90},
            ],
            "deterministicallyCheckedRanges": [
                {"startFrame": 150, "endFrameExclusive": 180},
            ],
        },
        required_windows=[],
    )
    assert actual["reviewedSeconds"] == 3
    assert actual["deterministicallyCheckedSeconds"] == 1
    assert actual["uninspectedRanges"] == [
        {"start": 3.0, "end": 5.0},
        {"start": 6.0, "end": 10.0},
    ]


def test_evidence_fusion_routes_conflicts_to_exact_human_windows() -> None:
    fused = fuse_review_evidence(
        watch_findings=[
            {
                "findingId": "watch-motion",
                "category": "movement",
                "status": "corroborated",
                "severity": "blocking",
                "programRange": {"startFrame": 100, "endFrameExclusive": 120},
                "observed": "insert appears frozen",
                "message": "insert appears frozen",
            }
        ],
        deterministic={
            "sequentialDecode": {"status": "pass", "findings": []},
            "movement": {"status": "pass", "findings": []},
            "transcript": {"status": "pass", "findings": []},
            "waveform": {
                "status": "needs-human-judgment",
                "findings": [],
                "listeningWindows": [{"startFrame": 300, "endFrameExclusive": 315}],
            },
            "flash": {"status": "pass", "findings": []},
            "pacing": {"status": "pass", "findings": []},
        },
    )
    assert fused["status"] == "needs-human-judgment"
    assert {tuple(window.values()) for window in fused["humanReviewWindows"]} == {
        (100, 120),
        (300, 315),
    }


def test_review_transcribes_into_edit_dir_not_nested_transcripts(
    tmp_path: Path,
) -> None:
    policy = resolve_watch_policy(scopes=[("project", {"language": "pt-BR"})])
    tmp_path.mkdir(parents=True, exist_ok=True)
    candidate = tmp_path / "proof.mp4"
    candidate.write_bytes(b"candidate")
    transcription = RecordingTranscript()
    ReviewRunner(
        review_root=tmp_path / "review",
        transcription=transcription,
        watch=FakeWatch(),
        deterministic_qc=FakeQc(),
        clock=lambda: "2026-09-02T00:00:00Z",
        watch_policy=policy,
    ).run(
        checkpoint="cut-proof",
        candidate=candidate,
        dependencies={"cmap": "b" * 64, "sync-map": "c" * 64},
        render_profile="proof",
        risk_windows=[{"start": 0.2, "end": 0.4, "reason": "join"}],
    )
    assert transcription.calls[0]["edit_dir"] == tmp_path


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
    project = {
        "models": {
            "understand": {
                "id": "qwen3.5-4b",
                "source": {
                    "kind": "endpoint",
                    "endpoint": {
                        "baseUrl": "http://127.0.0.1:1234/v1",
                        "servedName": "qwen3.5-4b",
                    },
                },
            }
        }
    }

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


def test_project_understand_pin_is_forwarded_to_watch(tmp_path: Path) -> None:
    candidate = tmp_path / "proof.mp4"
    candidate.write_bytes(b"candidate")
    watch = FakeWatch()
    ReviewRunner(
        review_root=tmp_path / "review",
        transcription=FakeTranscript(),
        watch=watch,
        deterministic_qc=FakeQc(),
        workspace=CurrentWorkspace(),
        clock=lambda: "2026-09-02T00:00:00Z",
    ).run(
        checkpoint="cut-proof",
        candidate=candidate,
        dependencies={"cmap": "b" * 64, "sync-map": "c" * 64},
        render_profile="proof",
    )
    request = watch.requests[0]
    assert request["option_id"] == "qwen3.5-4b"
    assert request["model_pin"] == CurrentWorkspace.project["models"]["understand"]


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
