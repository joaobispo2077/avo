from __future__ import annotations

import pytest

from avo.cli import _review, build_parser


def test_review_policy_accepts_all_watch_invocation_controls() -> None:
    args = build_parser().parse_args(
        [
            "review",
            "policy",
            "--project",
            "avo.project.json",
            "--watch-whisper-model",
            "small",
            "--watch-device",
            "cuda:1",
            "--watch-max-frames",
            "24",
            "--watch-repair-max-frames",
            "6",
            "--watch-analysis-attempts",
            "2",
            "--watch-tool-attempts",
            "3",
            "--watch-working-directory",
            "edit/watch",
            "--watch-format",
            "tutorial",
            "--watch-language",
            "en",
            "--watch-acceptance-criterion",
            "labels readable",
            "--watch-risk-note",
            "private screen",
        ]
    )
    assert args.review_command == "policy"
    assert args.watch_device == "cuda:1"
    assert args.watch_max_frames == 24
    assert args.watch_acceptance_criterion == ["labels readable"]


def test_review_run_watch_flags_are_optional() -> None:
    args = build_parser().parse_args(
        [
            "review",
            "run",
            "--project",
            "avo.project.json",
            "--candidate",
            "proof.mp4",
            "--dependency",
            "cmap=" + "a" * 64,
        ]
    )
    assert args.watch_device is None
    assert args.watch_risk_note is None


def test_final_review_requires_canonical_materialization(monkeypatch) -> None:
    args = build_parser().parse_args(
        [
            "review",
            "run",
            "--project",
            "avo.project.json",
            "--checkpoint",
            "pre-master",
            "--candidate",
            "master.mp4",
            "--dependency",
            "cmap=" + "a" * 64,
        ]
    )
    monkeypatch.setattr(
        "avo.cli.TimelineWorkspace.from_project",
        lambda *args, **kwargs: object(),
    )
    with pytest.raises(ValueError, match="requires --materialization"):
        _review(args)


def test_delivery_prepare_requires_materialization_argument() -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args(
            [
                "deliver",
                "prepare",
                "--project",
                "avo.project.json",
                "--master",
                "master.mp4",
            ]
        )
