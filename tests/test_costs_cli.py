"""Current and historic report routing without paid calls."""

import json

import pytest

from avo.cli import main
from avo.cost_store import CostStore
from test_costs import fact


def project(tmp_path):
    path = tmp_path / "avo.project.json"
    path.write_text(
        json.dumps({"rawDir": str(tmp_path), "provider": "channel", "videoId": "video"})
    )
    return path


def test_report_alias_read_only(tmp_path, capsys):
    path = project(tmp_path)
    assert main(["costs", "--project", str(path), "--json"]) == 0
    first = json.loads(capsys.readouterr().out)
    assert main(["metrics", "--project", str(path), "--json"]) == 0
    assert first == json.loads(capsys.readouterr().out)
    assert not (tmp_path / "edit").exists()


def test_explicit_project_before_operation_is_preserved(tmp_path, capsys):
    path = project(tmp_path)
    source = tmp_path / "usage.json"
    source.write_text(json.dumps([fact()]))
    assert (
        main(
            ["costs", "--project", str(path), "--json", "import", "--file", str(source)]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["imported"] == 1


def test_import_report_price_and_history(tmp_path, capsys):
    path = project(tmp_path)
    source = tmp_path / "usage.json"
    source.write_text(json.dumps([fact()]))
    assert (
        main(
            ["costs", "import", "--project", str(path), "--file", str(source), "--json"]
        )
        == 0
    )
    capsys.readouterr()
    assert main(["costs", "--project", str(path), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["tokens"]["total"] == 120
    assert (
        main(
            ["costs", "snapshot", "--project", str(path), "--stage", "final", "--json"]
        )
        == 2
    )
    assert "cleanup" in capsys.readouterr().err


def test_corrupt_input_is_sanitized(tmp_path, capsys):
    path = project(tmp_path)
    bad = tmp_path / "bad.json"
    bad.write_text('{"prompt":"PRIVATE", "broken":}')
    assert main(["costs", "import", "--project", str(path), "--file", str(bad)]) == 2
    assert "PRIVATE" not in capsys.readouterr().err


def test_history_default_is_readable_not_raw_evidence(monkeypatch, capsys):
    from avo import cost_history

    video = {
        "provider": "channel",
        "videoId": "video",
        "amounts": [],
        "tokens": {"total": 120},
        "coverage": "partial",
        "cutoff": None,
    }
    monkeypatch.setattr(
        cost_history,
        "history",
        lambda **_: {"videos": [video], "diagnostics": [], "message": ""},
    )
    assert main(["costs", "--history"]) == 0
    output = capsys.readouterr().out
    assert output.startswith("channel/video:")
    assert "Tokens: 120" in output


@pytest.fixture
def local_cost_state(monkeypatch, tmp_path):
    from avo import avo_state

    monkeypatch.setattr(avo_state, "state_dir", lambda: tmp_path / "state")


def _cost_context(tmp_path, path, capsys, **changes):
    # Import lazily: continuity fixtures reuse this module's project helper.
    from test_cost_continuity import context_descriptor

    descriptor = context_descriptor(**changes)
    source = tmp_path / "context-input.json"
    source.write_text(json.dumps(descriptor), encoding="utf-8")
    assert (
        main(
            [
                "costs",
                "context",
                "--project",
                str(path),
                "--descriptor",
                str(source),
                "--json",
            ]
        )
        == 0
    )
    return descriptor, json.loads(capsys.readouterr().out)


def _ledger_bytes(store):
    return {
        str(path.relative_to(store.root)): path.read_bytes()
        for path in store.root.rglob("*.json")
    }


@pytest.mark.parametrize("mode", ["agent", "identity-unknown", "human-ci"])
def test_context_cli_declares_known_unknown_or_bounded_human_ci(
    tmp_path, capsys, local_cost_state, mode
):
    path = project(tmp_path)
    from test_cost_continuity import context_descriptor

    descriptor = context_descriptor(mode=mode)
    if mode == "identity-unknown":
        descriptor["agent"].update(family="unknown", version=None)
    if mode == "human-ci":
        descriptor["agent"].update(family="human-ci", version=None)
        descriptor["scope"]["ending"] = {
            "kind": "event",
            "reference": "ci-completed",
        }
    _, result = _cost_context(tmp_path, path, capsys, **descriptor)
    assert result["schemaVersion"] == "2.0.0"
    assert result["participationId"]
    store = CostStore(tmp_path)
    declarations = store.documents("participations")
    assert len(declarations) == 1
    assert declarations[0]["mode"] == mode
    assert declarations[0]["kind"] == (
        "declare-no-external-agent" if mode == "human-ci" else "declare"
    )
    assert main(["costs", "report", "--project", str(path), "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    missing = any(
        item["code"] == "host-agent-unaccounted" for item in report["diagnostics"]
    )
    assert missing is (mode != "human-ci")
    assert report["pendingTurn"] is (False if mode == "human-ci" else None)


def test_context_cli_replay_is_idempotent_and_changed_payload_is_rejected(
    tmp_path, capsys, local_cost_state
):
    path = project(tmp_path)
    descriptor, first = _cost_context(tmp_path, path, capsys)
    store = CostStore(tmp_path)
    before = _ledger_bytes(store)
    _, second = _cost_context(tmp_path, path, capsys)
    assert second["replayed"] is True
    assert second["participationId"] == first["participationId"]
    assert _ledger_bytes(store) == before
    descriptor["scope"]["runAliases"] = ["different-scope"]
    source = tmp_path / "changed-context.json"
    source.write_text(json.dumps(descriptor), encoding="utf-8")
    assert (
        main(
            [
                "costs",
                "context",
                "--project",
                str(path),
                "--descriptor",
                str(source),
                "--json",
            ]
        )
        == 2
    )
    assert json.loads(capsys.readouterr().err)["status"] == "invalid-input"
    assert _ledger_bytes(store) == before


def test_context_cli_reuses_an_existing_authorized_source_binding(
    tmp_path, capsys, local_cost_state
):
    from test_cost_continuity import profile

    path = project(tmp_path)
    store = CostStore(tmp_path)
    store.initialize("channel", "video")
    source = tmp_path / "authorized-source.json"
    source.write_text(json.dumps([fact()]), encoding="utf-8")
    binding = store.bind(
        source=source, agent="codex", session_id="session", boundary="beginning"
    )
    supplied_profile = profile()
    store.append_record("profiles", supplied_profile)
    attachment = {
        "bindingId": binding["bindingId"],
        "profileId": supplied_profile["profileId"],
    }
    bindings_before = store.documents("bindings")
    _, first = _cost_context(tmp_path, path, capsys, sourceAttachment=attachment)
    _, resumed = _cost_context(
        tmp_path,
        path,
        capsys,
        sourceAttachment=attachment,
        operationId="context-resume-1",
    )
    assert resumed["participationId"] == first["participationId"]
    assert resumed["diagnostics"] == []
    assert store.documents("bindings") == bindings_before
    assert not store.documents("batches")


def test_malformed_context_cli_is_rejected_before_accounting_mutation(
    tmp_path, capsys, local_cost_state
):
    from test_cost_continuity import context_descriptor

    path = project(tmp_path)
    source = tmp_path / "invalid-context.json"
    descriptor = context_descriptor(prompt="PRIVATE-CONTEXT-SENTINEL")
    source.write_text(json.dumps(descriptor), encoding="utf-8")
    assert (
        main(
            [
                "costs",
                "context",
                "--project",
                str(path),
                "--descriptor",
                str(source),
                "--json",
            ]
        )
        == 2
    )
    output = capsys.readouterr()
    assert "PRIVATE-CONTEXT-SENTINEL" not in output.err + output.out
    assert not (tmp_path / "edit" / "costs").exists()
    assert not (tmp_path / "state").exists()


def test_observe_cli_accepts_attributed_manual_packet_once(
    tmp_path, capsys, local_cost_state
):
    from test_cost_continuity import evidence, packet, profile

    path = project(tmp_path)
    _, context = _cost_context(tmp_path, path, capsys)
    store = CostStore(tmp_path)
    store.append_record("profiles", profile())
    row = fact(tokens={"input": 100, "output": 20}, semantics={})
    usage = packet(
        store,
        [row],
        evidence_rows=[
            evidence(
                row,
                participation_id=context["participationId"],
                nature="manual",
                acquisition="imported",
            )
        ],
    )
    source = tmp_path / "typed-usage.json"
    source.write_text(json.dumps(usage), encoding="utf-8")
    command = [
        "costs",
        "observe",
        "--project",
        str(path),
        "--file",
        str(source),
        "--json",
    ]
    assert main(command) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["schemaVersion"] == "2.0.0"
    assert result["accountingVideoId"] == store.identity()["accountingVideoId"]
    before = _ledger_bytes(store)
    assert main(command) == 0
    assert json.loads(capsys.readouterr().out)["replayed"] is True
    assert _ledger_bytes(store) == before
    assert main(["costs", "report", "--project", str(path), "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["tokens"]["total"] == 120
    assert report["usageByNature"]["manual"]["total"] == 120
    assert report["usageByNature"]["measured"]["total"] is None
    assert store.documents("batches")[0]["evidence"][0]["acquisition"] == "imported"


def test_observe_cli_cannot_promote_a_synthetic_profile_to_native_measurement(
    tmp_path, capsys, local_cost_state
):
    from test_cost_continuity import evidence, packet, profile

    path = project(tmp_path)
    _, context = _cost_context(tmp_path, path, capsys)
    store = CostStore(tmp_path)
    store.append_record("profiles", profile())
    row = fact()
    usage = packet(
        store,
        [row],
        evidence_rows=[
            evidence(
                row,
                participation_id=context["participationId"],
            )
        ],
    )
    source = tmp_path / "unqualified-measured.json"
    source.write_text(json.dumps(usage), encoding="utf-8")
    before = _ledger_bytes(store)
    assert (
        main(
            [
                "costs",
                "observe",
                "--project",
                str(path),
                "--file",
                str(source),
                "--json",
            ]
        )
        == 2
    )
    assert "qualified" in capsys.readouterr().err
    assert _ledger_bytes(store) == before


@pytest.mark.parametrize("host_present", [True, False])
def test_cli_summary_separates_host_from_internal_services(
    tmp_path, capsys, local_cost_state, host_present
):
    from test_cost_continuity import evidence, packet, profile, receipt

    path = project(tmp_path)
    _, context = _cost_context(tmp_path, path, capsys)
    store = CostStore(tmp_path)
    store.append_record("profiles", profile())
    service = fact(
        "service-1",
        serviceClass="pipeline-service",
        agent="qwen",
        tokens={
            "input": 300 if host_present else 2_100_000,
            "output": 50 if host_present else 0,
        },
        semantics={},
    )
    service_profile = profile(agent="qwen")
    store.append_record("profiles", service_profile)
    service_packet = packet(
        store,
        [service],
        evidence_rows=[
            evidence(
                service,
                participation_id="pipeline-service:qwen",
                profile_id=service_profile["profileId"],
            )
        ],
        receipts=[
            receipt(
                profile_id=service_profile["profileId"],
                keys=CostStore.keys_for([service]),
            )
        ],
        operation_id="service-packet",
    )
    service_packet["profileId"] = service_profile["profileId"]
    store.ingest_packet(service_packet, allow_synthetic=True)
    if host_present:
        host = fact("host-1", tokens={"input": 1000, "output": 200}, semantics={})
        store.ingest_packet(
            packet(
                store,
                [host],
                evidence_rows=[
                    evidence(host, participation_id=context["participationId"])
                ],
            ),
            allow_synthetic=True,
        )
    assert main(["costs", "report", "--project", str(path), "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["tokens"]["total"] == (1550 if host_present else 2_100_000)
    assert report["usageByNature"]["measured"]["total"] == report["tokens"]["total"]
    groups = report["breakdowns"]["serviceClass"]
    assert groups["pipeline-service"]["tokens"]["total"] == (
        350 if host_present else 2_100_000
    )
    if host_present:
        assert groups["host-agent"]["tokens"]["total"] == 1200
    else:
        assert any(
            item["code"] == "host-agent-unaccounted" for item in report["diagnostics"]
        )
        assert report["coverage"] != "complete-for-declared-sources"
        assert main(["costs", "report", "--project", str(path)]) == 0
        assert "agente executor não contabilizado" in capsys.readouterr().out.lower()
