from pathlib import Path
from types import SimpleNamespace

from avo.cli import _deliver, _pipeline, _review, build_parser


def test_human_final_delivery_is_explicit_and_does_not_prepare(monkeypatch):
    argv = [
        "deliver",
        "adopt-human-final",
        "--project",
        "project.json",
        "--master",
        "master.mp4",
        "--materialization",
        "assembly.json",
        "--human-final-disposition",
        "human.json",
    ]
    for kind in ("json", "txt", "md", "srt"):
        argv.extend([f"--transcript-{kind}", f"transcript.{kind}"])
    args = build_parser().parse_args(argv)
    calls = []
    monkeypatch.setattr(
        "avo.cli.TimelineWorkspace.from_project", lambda *a, **k: object()
    )
    monkeypatch.setattr("avo.cli._load_json", lambda path: {"kind": "assembly"})
    monkeypatch.setattr("avo.cli._merge_materialization_dependencies", lambda a, b: {})
    monkeypatch.setattr("avo.cli._emit", lambda value: None)
    monkeypatch.setattr(
        "avo.timeline.delivery.DeliveryService",
        lambda workspace: SimpleNamespace(adopt_existing=lambda **kw: calls.append(kw)),
    )
    assert _deliver(args) == 0
    assert calls[0]["review_path"] is None
    assert calls[0]["human_final_disposition_path"] == Path("human.json")


def test_human_final_pipeline_dispatches_archive_without_faking_stages(monkeypatch):
    args = build_parser().parse_args(
        [
            "pipeline",
            "adopt-human-final-delivery",
            "--project",
            "project.json",
            "--human-final-disposition",
            "human.json",
            "--actor",
            "creator",
            "--reason",
            "explicit human authority",
            "--archive",
        ]
    )
    calls = []
    monkeypatch.setattr(
        "avo.cli.TimelineWorkspace.from_project", lambda *a, **k: object()
    )
    monkeypatch.setattr("avo.cli._emit", lambda value: None)
    monkeypatch.setattr(
        "avo.timeline.pipeline.TimelinePipeline",
        lambda workspace: SimpleNamespace(
            adopt_human_final_delivery=lambda **kw: calls.append(kw)
        ),
    )
    assert _pipeline(args) == 0
    assert calls == [
        {
            "human_final_disposition_path": Path("human.json"),
            "actor": "creator",
            "reason": "explicit human authority",
            "archive": True,
        }
    ]


def test_human_final_decision_binds_actual_decision_and_automated_evidence(
    monkeypatch, tmp_path
):
    decision = tmp_path / "decision.json"
    prior = tmp_path / "prior.json"
    evidence = tmp_path / "failed-analysis.json"
    for path in (decision, prior, evidence):
        path.write_text("{}", encoding="utf-8")
    args = build_parser().parse_args(
        [
            "review",
            "decide-human-final",
            "--project",
            "project.json",
            "--candidate",
            "master.mp4",
            "--materialization",
            "assembly.json",
            "--proof-plan",
            "plan.json",
            "--decision-record",
            str(decision),
            "--source-approval",
            str(prior),
            "--evidence",
            f"transcript={evidence}",
            "--actor",
            "creator",
            "--reason",
            "explicit human approval",
        ]
    )
    calls = []
    monkeypatch.setattr(
        "avo.cli.TimelineWorkspace.from_project", lambda *a, **k: object()
    )
    monkeypatch.setattr("avo.cli._load_json", lambda path: {"kind": "assembly"})
    monkeypatch.setattr("avo.cli._merge_materialization_dependencies", lambda a, b: {})
    monkeypatch.setattr("avo.cli._emit", lambda value: None)
    monkeypatch.setattr(
        "avo.timeline.approval_service.ApprovalService",
        lambda workspace: SimpleNamespace(
            decide_human_final=lambda **kw: calls.append(kw)
        ),
    )
    assert _review(args) == 0
    assert calls[0]["automated_evidence_paths"] == {"transcript": evidence}
    assert calls[0]["decision_ref"]["path"] == str(decision)
    assert len(calls[0]["decision_ref"]["sha256"]) == 64
    assert calls[0]["proof_plan_path"] == Path("plan.json")
