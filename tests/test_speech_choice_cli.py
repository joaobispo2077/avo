"""Native and MCP evidence choices share exact-byte mutation guards."""

import hashlib
import json

import pytest

from avo.mcp.bridge import run_bridged, run_cli
from avo.mcp.tools.cli_tools import _decision_gate_args
from tests.test_preparation_cli import definition
from tests.test_speech_recovery import recovery
from tests.test_speech_recovery_choices import decision


@pytest.mark.parametrize("choice", ["original", "recovered", "reject", "defer"])
def test_native_choice_and_mcp_replay_use_retained_evidence_without_inference(
    tmp_path,
    monkeypatch,
    choice,
):
    cutting, cmap, service, port, request = recovery(tmp_path)
    shown = service.recover(request)
    choose = decision(service, shown, choice)
    path = tmp_path / "choice.json"
    path.write_text(json.dumps(choose), encoding="utf-8")
    selections = []

    def build(workspace, *, recover=False):
        selections.append(recover)
        return service

    monkeypatch.setattr("avo.adapters.registry.build_preparation_service", build)
    native = run_cli(
        [
            "preparation",
            "recover-decide",
            "--project",
            str(cutting.workspace.project_path),
            "--request",
            str(path),
            "--json",
        ]
    )
    assert native.exit_code == 0, native.stderr
    head = service.store.head_hash()
    bridge = run_bridged(
        definition("recover-decide").cli_prefix,
        {
            "project": str(cutting.workspace.project_path),
            "request": str(path),
            "as_json": True,
        },
    )
    assert bridge.exit_code == 0, bridge.stderr
    assert bridge.parsed_json == native.parsed_json
    assert (
        native.parsed_json["status"]
        == {
            "original": "selected",
            "recovered": "selected",
            "reject": "rejected",
            "defer": "deferred",
        }[choice]
    )
    assert native.parsed_json["cutApproval"] == "not-granted"
    assert service.store.head_hash() == head
    assert selections == [choice == "recovered"] * 2
    assert len(port.calls) == 1
    assert cutting.workspace.store("cmap").head_hash() == cmap["contentHash"]


def test_choice_confirmation_binds_the_exact_request_bytes(tmp_path):
    path = tmp_path / "choice.json"
    raw = b'{"choice":"defer"}'
    path.write_bytes(raw)
    tool = definition("recover-decide")
    arguments = {"project": str(tmp_path / "project.json"), "request": str(path)}
    guarded = _decision_gate_args(tool, arguments)
    assert tool.spec.destructive is True
    assert guarded["_decisionDocumentSha256"] == hashlib.sha256(raw).hexdigest()


def test_choice_changed_after_confirmation_is_rejected_before_service_setup(
    tmp_path,
    monkeypatch,
):
    path = tmp_path / "choice.json"
    path.write_text("{}", encoding="utf-8")

    def forbidden(*args, **kwargs):
        pytest.fail("changed choice reached service construction")

    monkeypatch.setattr("avo.adapters.registry.build_preparation_service", forbidden)
    result = run_cli(
        [
            "preparation",
            "recover-decide",
            "--project",
            str(tmp_path / "absent.json"),
            "--request",
            str(path),
            "--request-sha256",
            "f" * 64,
        ]
    )
    assert result.exit_code == 2


def test_recovered_choice_requires_its_exact_result_before_workspace_loading(tmp_path):
    path = tmp_path / "choice.json"
    path.write_text(
        json.dumps(
            {
                "contractVersion": "1.0.0",
                "operation": "recover-decide",
                "operationId": "bad-choice",
                "actor": "creator",
                "reason": "review",
                "requestRef": {
                    "locator": "documents/speech-recovery-request/absent.json",
                    "sha256": "a" * 64,
                },
                "resultRef": None,
                "intervalIndex": 0,
                "choice": "recovered",
                "expectedLedgerHash": "b" * 64,
                "expectedDecisionRefs": [],
            }
        ),
        encoding="utf-8",
    )
    result = run_cli(
        [
            "preparation",
            "recover-decide",
            "--project",
            str(tmp_path / "absent.json"),
            "--request",
            str(path),
        ]
    )
    assert result.exit_code == 2
    assert "resultRef" in result.stderr
