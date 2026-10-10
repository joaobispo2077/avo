import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from avo.cli import build_parser
from avo.timeline.command_handlers import CommandHandlers


@pytest.mark.parametrize(
    "operation", ["analyze", "preview", "decide", "apply", "status"]
)
def test_trim_parser_exposes_shared_operations(operation):
    argv = ["trim", operation, "--project", "project.json"]
    if operation in {"preview", "decide", "apply"}:
        argv += ["--proposal", "proposal.json"]
    if operation == "decide":
        argv += ["--request", "decisions.json"]
    args = build_parser().parse_args(argv)
    assert args.trim_command == operation
    assert args.project == Path("project.json")


class FakeCuttingService:
    def __init__(self):
        self.calls = []

    def analyze(self, request=None):
        self.calls.append(("analyze", request))
        return {
            "status": "proposed",
            "scope": request.get("scope") if request else None,
        }

    def preview(self, proposal_ref):
        self.calls.append(("preview", proposal_ref))
        return {"status": "blocked", "reason": "verification unavailable"}

    def decide(self, proposal_ref, request):
        self.calls.append(("decide", proposal_ref, request))
        return {"status": "decided"}

    def apply(self, proposal_ref):
        self.calls.append(("apply", proposal_ref))
        return {"status": "no-op"}

    def status(self, proposal_ref=None):
        self.calls.append(("status", proposal_ref))
        return {"status": "disabled"}


def test_shared_trim_does_not_claim_canonical_mutation_during_analysis():
    service = FakeCuttingService()
    handlers = CommandHandlers(SimpleNamespace(workspace=None), cutting_service=service)
    result = handlers.execute(
        "trim", "analyze", {"request": {"scope": {"start": 1, "end": 2}}}
    )
    assert result["mutated"] is False
    assert result["result"]["scope"] == {"start": 1, "end": 2}
    assert service.calls == [("analyze", {"scope": {"start": 1, "end": 2}})]


def test_preview_missing_actual_verification_remains_blocked():
    handlers = CommandHandlers(
        SimpleNamespace(workspace=None), cutting_service=FakeCuttingService()
    )
    result = handlers.execute("trim", "preview", {"proposalRef": Path("proposal.json")})
    assert result["result"]["status"] == "blocked"
    assert result["mutated"] is False


def test_all_keep_apply_reports_no_op_without_claiming_mutation():
    handlers = CommandHandlers(
        SimpleNamespace(workspace=None), cutting_service=FakeCuttingService()
    )
    result = handlers.execute(
        "trim", "apply", {"proposalRef": Path("proposal.json"), "mutation": "cmap"}
    )
    assert result["mutated"] is False


def test_trim_rejects_unrecognized_operation_instead_of_generic_success():
    handlers = CommandHandlers(
        SimpleNamespace(workspace=None), cutting_service=FakeCuttingService()
    )
    with pytest.raises(ValueError, match="unsupported trim"):
        handlers.execute("trim", "anything")


def test_cli_uses_shared_runtime_and_reports_blocked_preview(
    monkeypatch, capsys, tmp_path
):
    from avo import cli
    from avo.adapters import registry

    workspace = SimpleNamespace(pipeline_run_path=tmp_path / "run.json")
    service = FakeCuttingService()
    monkeypatch.setattr(
        cli.TimelineWorkspace, "from_project", lambda *args, **kwargs: workspace
    )
    monkeypatch.setattr(
        registry, "build_cutting_service", lambda *args, **kwargs: service
    )
    exit_code = cli.main(
        ["trim", "preview", "--project", "project.json", "--proposal", "proposal.json"]
    )
    result = json.loads(capsys.readouterr().out)
    assert exit_code == 3
    assert result["result"]["status"] == "blocked"
    assert service.calls == [("preview", Path("proposal.json"))]
