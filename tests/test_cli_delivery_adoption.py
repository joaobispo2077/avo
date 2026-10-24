from pathlib import Path
from types import SimpleNamespace

import pytest

from avo.cli import _deliver, _review, build_parser


def test_adopt_cli_dispatches_existing_artifacts_without_preparing(monkeypatch):
    argv = [
        "deliver",
        "adopt",
        "--project",
        "project.json",
        "--master",
        "master.mp4",
        "--materialization",
        "assembly.json",
        "--review",
        "review.json",
    ]
    for kind in ("json", "txt", "md", "srt"):
        argv.extend([f"--transcript-{kind}", f"transcript.{kind}"])
    args = build_parser().parse_args(argv)
    calls = []
    monkeypatch.setattr(
        "avo.cli.TimelineWorkspace.from_project", lambda *a, **k: object()
    )
    monkeypatch.setattr("avo.cli._load_json", lambda p: {"kind": "assembly"})
    monkeypatch.setattr("avo.cli._merge_materialization_dependencies", lambda a, b: {})
    monkeypatch.setattr("avo.cli._emit", lambda result: None)
    monkeypatch.setattr(
        "avo.timeline.delivery.DeliveryService",
        lambda workspace: SimpleNamespace(
            adopt_existing=lambda **kwargs: calls.append(kwargs)
        ),
    )
    assert _deliver(args) == 0
    assert calls[0]["master"] == Path("master.mp4")
    assert calls[0]["review_path"] == Path("review.json")
    assert calls[0]["transcript_artifacts"] == {
        kind: Path(f"transcript.{kind}") for kind in ("json", "txt", "md", "srt")
    }


def test_adopt_cli_requires_each_existing_sidecar():
    with pytest.raises(SystemExit):
        build_parser().parse_args(
            [
                "deliver",
                "adopt",
                "--project",
                "project.json",
                "--master",
                "master.mp4",
                "--materialization",
                "assembly.json",
                "--review",
                "review.json",
            ]
        )


def test_review_reuse_transcript_is_explicit():
    args = build_parser().parse_args(
        [
            "review",
            "run",
            "--project",
            "project.json",
            "--reuse-transcript",
        ]
    )
    assert args.reuse_transcript is True


def test_pipeline_adoption_is_separate_from_normal_stage_advancement():
    args = build_parser().parse_args(
        [
            "pipeline",
            "adopt-delivery",
            "--project",
            "project.json",
            "--approval",
            "approval.json",
            "--actor",
            "creator",
            "--reason",
            "adopt existing master",
        ]
    )
    assert args.pipeline_command == "adopt-delivery"
    assert args.approval == Path("approval.json")
    assert args.regression is None


def test_candidate_decision_cli_calls_gated_service(monkeypatch):
    args = build_parser().parse_args(
        [
            "review",
            "decide-candidate",
            "--project",
            "project.json",
            "--checkpoint",
            "deliver",
            "--review",
            "review.json",
            "--materialization",
            "assembly.json",
            "--actor",
            "creator",
            "--reason",
            "accepted exact candidate",
            "--defer-snapshot",
        ]
    )
    calls = []
    monkeypatch.setattr(
        "avo.cli.TimelineWorkspace.from_project", lambda *a, **k: object()
    )
    monkeypatch.setattr("avo.cli._emit", lambda result: None)
    monkeypatch.setattr(
        "avo.timeline.approval_service.ApprovalService",
        lambda workspace: SimpleNamespace(
            decide_candidate=lambda **kwargs: calls.append(kwargs)
        ),
    )
    assert _review(args) == 0
    assert calls[0]["checkpoint"] == "deliver"
    assert calls[0]["source_approval_ref"] is None
    assert calls[0]["finalize_snapshot"] is False
