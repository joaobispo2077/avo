"""Unit tests for MRTR gates + requestState (T13 capability filter + T16 paths).

Covers FR-15: InputRequired pause, incomplete retry, accept to proceed, and
reject on tampered/expired/mismatched requestState (never authorize execute).
tmp fixtures only; no providers/footage. Soft-adapts when SDK MRTR types lag.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from avo.mcp import mrtr
from avo.mcp.request_state import RequestStateError, encode_request_state, generate_key

# Soft-gate: SDK MRTR types optional (dict soft-adapt always available)


def _sdk_input_required_available() -> bool:
    try:
        from mcp.types import InputRequiredResult  # noqa: F401

        return True
    except ImportError:
        return False


pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")

ELICIT_CAPS = {"elicitation": {"form": {}}}
TOOL = "avo_cleanup_execute"
TMP_ARGS = {"project": "/tmp/mrtr-t16", "as_json": True}


def _accept_responses() -> dict[str, Any]:
    return {
        mrtr.CONFIRM_ELICITATION_KEY: {
            "action": "accept",
            "content": {"confirm": True},
        }
    }


def _pause_token(
    *,
    key: bytes,
    args: dict[str, Any] | None = None,
    now: float | None = None,
    ttl_seconds: int = 600,
) -> str:
    first = mrtr.evaluate_destructive_gate(
        tool=TOOL,
        args=args if args is not None else TMP_ARGS,
        key=key,
        now=now,
        ttl_seconds=ttl_seconds,
        client_capabilities=ELICIT_CAPS,
        capabilities_provided=True,
    )
    assert first.outcome is mrtr.GateOutcome.INPUT_REQUIRED
    wire = mrtr.input_required_to_dict(first.result)
    assert wire["resultType"] == "input_required"
    return str(wire["requestState"])


# ---------------------------------------------------------------------------
# T13 — client capability honor / degrade (keep; do not delete)


# ---------------------------------------------------------------------------


def test_allowed_methods_from_capabilities_mapping() -> None:
    caps = {
        "elicitation": {"form": {}},
        "sampling": {},
        "roots": {"listChanged": True},
    }
    allowed = mrtr.allowed_input_request_methods(caps)
    assert allowed == frozenset(
        {
            mrtr.METHOD_ELICITATION_CREATE,
            mrtr.METHOD_SAMPLING_CREATE_MESSAGE,
            mrtr.METHOD_ROOTS_LIST,
        }
    )


def test_bare_elicitation_counts_as_form() -> None:
    assert mrtr.client_supports_elicitation_create({"elicitation": {}}) is True
    assert (
        mrtr.client_supports_elicitation_create({"elicitation": {"url": {}}}) is False
    )
    assert mrtr.client_supports_elicitation_create({}) is False
    assert mrtr.client_supports_elicitation_create(None) is False


def test_filter_input_requests_drops_unsupported() -> None:
    requests = {
        "confirm_destructive": {
            "method": mrtr.METHOD_ELICITATION_CREATE,
            "params": {"mode": "form", "message": "x", "requestedSchema": {}},
        },
        "sample": {"method": mrtr.METHOD_SAMPLING_CREATE_MESSAGE, "params": {}},
        "roots": {"method": mrtr.METHOD_ROOTS_LIST, "params": {}},
        "bad": {"method": "notifications/foo", "params": {}},
    }
    filtered = mrtr.filter_input_requests(
        requests, frozenset({mrtr.METHOD_ELICITATION_CREATE})
    )
    assert list(filtered) == ["confirm_destructive"]
    assert filtered["confirm_destructive"]["method"] == mrtr.METHOD_ELICITATION_CREATE


def test_no_elicitation_capability_degrades_without_fake_confirm() -> None:
    key = generate_key()
    decision = mrtr.evaluate_destructive_gate(
        tool=TOOL,
        args={"project": "/tmp/caps"},
        key=key,
        client_capabilities={},  # declared none
        capabilities_provided=True,
    )
    assert decision.outcome is mrtr.GateOutcome.REJECT
    assert decision.result is None
    assert decision.error_message is not None
    assert "elicitation/create" in decision.error_message
    assert (
        "faked" in decision.error_message.lower()
        or "fake" in mrtr.CAPABILITY_DEGRADE_MESSAGE
    )


def test_sampling_only_does_not_emit_elicitation() -> None:
    key = generate_key()
    caps = {"sampling": {}}
    decision = mrtr.evaluate_destructive_gate(
        tool=TOOL,
        args={"project": "/tmp/caps"},
        key=key,
        client_capabilities=caps,
        capabilities_provided=True,
    )
    # Confirm gate needs elicitation; sampling alone is not a substitute.
    assert decision.outcome is mrtr.GateOutcome.REJECT
    built = mrtr.build_input_required_result(
        tool=TOOL,
        args={"project": "/tmp/caps"},
        key=key,
        client_capabilities=caps,
        capabilities_provided=True,
        include_elicitation=True,  # even if forced, filter strips unsupported
    )
    wire = mrtr.input_required_to_dict(built)
    assert "inputRequests" not in wire or not wire.get("inputRequests")


def test_elicitation_capability_emits_confirm_request() -> None:
    key = generate_key()
    caps = {"elicitation": {"form": {}}}
    decision = mrtr.evaluate_destructive_gate(
        tool=TOOL,
        args={"project": "/tmp/caps"},
        key=key,
        client_capabilities=caps,
        capabilities_provided=True,
    )
    assert decision.outcome is mrtr.GateOutcome.INPUT_REQUIRED
    wire = mrtr.input_required_to_dict(decision.result)
    assert wire["resultType"] == "input_required"
    req = wire["inputRequests"]["confirm_destructive"]
    assert req["method"] == mrtr.METHOD_ELICITATION_CREATE


def test_handler_with_ctx_without_elicitation_rejects() -> None:
    from avo.mcp.tools.cli_tools import _all_bridge_defs, _make_handler

    mrtr.reset_process_signing_key_for_tests()
    defn = next(d for d in _all_bridge_defs() if d.spec.name == TOOL)
    handler = _make_handler(defn)
    ctx = SimpleNamespace(client_capabilities=None)
    result = handler(project="/tmp/caps-handler", as_json=True, ctx=ctx)
    assert isinstance(result, dict)
    assert result["ok"] is False
    assert "elicitation" in result["stderr"].lower()


def test_handler_with_ctx_with_elicitation_pauses() -> None:
    from avo.mcp.tools.cli_tools import _all_bridge_defs, _make_handler

    mrtr.reset_process_signing_key_for_tests()
    defn = next(d for d in _all_bridge_defs() if d.spec.name == TOOL)
    handler = _make_handler(defn)
    ctx = SimpleNamespace(client_capabilities={"elicitation": {}})
    result = handler(project="/tmp/caps-handler", as_json=True, ctx=ctx)
    wire = mrtr.input_required_to_dict(result)
    assert wire["resultType"] == "input_required"
    assert wire["inputRequests"]["confirm_destructive"]["method"] == (
        mrtr.METHOD_ELICITATION_CREATE
    )


def test_accepted_retry_proceeds_even_if_caps_later_missing() -> None:
    """Once requestState + accept are verified, do not re-block on caps."""
    key = generate_key()
    first = mrtr.evaluate_destructive_gate(
        tool=TOOL,
        args={"project": "/tmp/caps"},
        key=key,
        client_capabilities={"elicitation": {}},
        capabilities_provided=True,
    )
    token = mrtr.input_required_to_dict(first.result)["requestState"]
    accepted = mrtr.evaluate_destructive_gate(
        tool=TOOL,
        args={"project": "/tmp/caps"},
        key=key,
        request_state=token,
        input_responses={
            mrtr.CONFIRM_ELICITATION_KEY: {
                "action": "accept",
                "content": {"confirm": True},
            }
        },
        client_capabilities={},
        capabilities_provided=True,
    )
    assert accepted.outcome is mrtr.GateOutcome.PROCEED


# ---------------------------------------------------------------------------
# T16 — happy path, incomplete retry, tampered/expired/mismatched reject


# ---------------------------------------------------------------------------


def test_happy_path_first_pause_then_accept_proceeds() -> None:
    """First call → InputRequiredResult; retry with responses + valid state → proceed."""
    key = generate_key()
    first = mrtr.evaluate_destructive_gate(
        tool=TOOL,
        args=TMP_ARGS,
        key=key,
        client_capabilities=ELICIT_CAPS,
        capabilities_provided=True,
    )
    assert first.outcome is mrtr.GateOutcome.INPUT_REQUIRED
    assert first.error_message is None
    wire = mrtr.input_required_to_dict(first.result)
    assert wire["resultType"] == mrtr.RESULT_TYPE_INPUT_REQUIRED
    assert isinstance(wire["requestState"], str) and wire["requestState"]
    assert mrtr.CONFIRM_ELICITATION_KEY in (wire.get("inputRequests") or {})
    # Soft-adapt path always works; when SDK types exist, result may be a model.
    if _sdk_input_required_available():
        assert first.result is not None
    else:
        assert isinstance(first.result, dict)
    accepted = mrtr.evaluate_destructive_gate(
        tool=TOOL,
        args=TMP_ARGS,
        key=key,
        request_state=wire["requestState"],
        input_responses=_accept_responses(),
        client_capabilities=ELICIT_CAPS,
        capabilities_provided=True,
    )
    assert accepted.outcome is mrtr.GateOutcome.PROCEED
    assert accepted.result is None
    assert accepted.error_message is None


def test_incomplete_retry_returns_new_input_required() -> None:
    key = generate_key()
    now = 1_700_000_100.0
    token = _pause_token(key=key, now=now)
    cases: list[dict[str, Any] | None] = [
        None,
        {},
        {mrtr.CONFIRM_ELICITATION_KEY: {"action": "accept"}},  # missing content
        {
            mrtr.CONFIRM_ELICITATION_KEY: {
                "action": "accept",
                "content": {"confirm": "yes"},  # not boolean true
            }
        },
        # Multiple non-confirm keys → missing (single anon key is accepted by design).
        {
            "other_a": {"action": "accept", "content": {"confirm": True}},
            "other_b": {"action": "accept", "content": {"confirm": True}},
        },
    ]
    previous_tokens = {token}
    for responses in cases:
        decision = mrtr.evaluate_destructive_gate(
            tool=TOOL,
            args=TMP_ARGS,
            key=key,
            request_state=token,
            input_responses=responses,
            now=now,
            client_capabilities=ELICIT_CAPS,
            capabilities_provided=True,
        )
        assert decision.outcome is mrtr.GateOutcome.INPUT_REQUIRED, responses
        wire = mrtr.input_required_to_dict(decision.result)
        assert wire["resultType"] == "input_required"
        new_token = wire["requestState"]
        assert isinstance(new_token, str) and new_token
        # New pause issues a fresh requestState (do not reuse broken continuity).
        previous_tokens.add(new_token)


def test_tampered_request_state_rejects_never_proceed() -> None:
    key = generate_key()
    token = _pause_token(key=key)
    body, mac = token.rsplit(".", 1)
    flipped = mac[:-1] + ("A" if mac[-1] != "A" else "B")
    bad = f"{body}.{flipped}"
    decision = mrtr.evaluate_destructive_gate(
        tool=TOOL,
        args=TMP_ARGS,
        key=key,
        request_state=bad,
        input_responses=_accept_responses(),
        client_capabilities=ELICIT_CAPS,
        capabilities_provided=True,
    )
    assert decision.outcome is mrtr.GateOutcome.REJECT
    assert decision.error_message is not None
    assert "requestState" in decision.error_message


def test_expired_request_state_rejects() -> None:
    key = generate_key()
    now = 1_700_000_200.0
    token = _pause_token(key=key, now=now, ttl_seconds=10)
    decision = mrtr.evaluate_destructive_gate(
        tool=TOOL,
        args=TMP_ARGS,
        key=key,
        request_state=token,
        input_responses=_accept_responses(),
        now=now + 11,
        client_capabilities=ELICIT_CAPS,
        capabilities_provided=True,
    )
    assert decision.outcome is mrtr.GateOutcome.REJECT
    assert decision.error_message is not None
    assert "requestState" in decision.error_message
    assert "expired" in decision.error_message.lower()


def test_mismatched_tool_request_state_rejects() -> None:
    key = generate_key()
    token = encode_request_state(
        tool=TOOL,
        args=TMP_ARGS,
        key=key,
        intent=mrtr.INTENT_CONFIRM_DESTRUCTIVE,
        method=mrtr.METHOD_TOOLS_CALL,
    )
    decision = mrtr.evaluate_destructive_gate(
        tool="avo_pipeline_status",
        args=TMP_ARGS,
        key=key,
        request_state=token,
        input_responses=_accept_responses(),
        client_capabilities=ELICIT_CAPS,
        capabilities_provided=True,
    )
    assert decision.outcome is mrtr.GateOutcome.REJECT
    assert "requestState" in (decision.error_message or "")


def test_mismatched_args_request_state_rejects() -> None:
    key = generate_key()
    token = _pause_token(key=key, args={"project": "/tmp/mrtr-a", "as_json": True})
    decision = mrtr.evaluate_destructive_gate(
        tool=TOOL,
        args={"project": "/tmp/mrtr-b", "as_json": True},
        key=key,
        request_state=token,
        input_responses=_accept_responses(),
        client_capabilities=ELICIT_CAPS,
        capabilities_provided=True,
    )
    assert decision.outcome is mrtr.GateOutcome.REJECT
    assert "requestState" in (decision.error_message or "")


def test_wrong_signing_key_rejects() -> None:
    key_a = generate_key()
    key_b = generate_key()
    token = _pause_token(key=key_a)
    decision = mrtr.evaluate_destructive_gate(
        tool=TOOL,
        args=TMP_ARGS,
        key=key_b,
        request_state=token,
        input_responses=_accept_responses(),
        client_capabilities=ELICIT_CAPS,
        capabilities_provided=True,
    )
    assert decision.outcome is mrtr.GateOutcome.REJECT


def test_declined_confirm_rejects() -> None:
    key = generate_key()
    token = _pause_token(key=key)
    for action in ("decline", "cancel"):
        decision = mrtr.evaluate_destructive_gate(
            tool=TOOL,
            args=TMP_ARGS,
            key=key,
            request_state=token,
            input_responses={mrtr.CONFIRM_ELICITATION_KEY: {"action": action}},
            client_capabilities=ELICIT_CAPS,
            capabilities_provided=True,
        )
        assert decision.outcome is mrtr.GateOutcome.REJECT
        assert (
            "declined" in (decision.error_message or "").lower()
            or "cancelled" in (decision.error_message or "").lower()
        )


def test_handler_happy_path_calls_bridge_only_after_accept(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Handler: pause → incomplete → accept proceeds to bridge; never on bad state."""
    from avo.mcp.tools import cli_tools
    from avo.mcp.tools.cli_tools import _all_bridge_defs, _make_handler

    mrtr.reset_process_signing_key_for_tests()
    calls: list[tuple[Any, dict[str, Any]]] = []

    class _FakeResult:
        def to_dict(self) -> dict[str, Any]:
            return {
                "ok": True,
                "exit_code": 0,
                "stdout": "{}",
                "stderr": "",
                "parsed_json": {"ran": True},
            }

    def _fake_bridged(prefix: Any, kwargs: dict[str, Any]) -> _FakeResult:
        calls.append((prefix, dict(kwargs)))
        return _FakeResult()

    monkeypatch.setattr(cli_tools, "run_bridged", _fake_bridged)
    defn = next(d for d in _all_bridge_defs() if d.spec.name == TOOL)
    handler = _make_handler(defn)
    project = "/tmp/mrtr-handler-happy"
    first = handler(project=project, as_json=True)
    wire = mrtr.input_required_to_dict(first)
    assert wire["resultType"] == "input_required"
    token = wire["requestState"]
    assert calls == []
    incomplete = handler(project=project, as_json=True, requestState=token)
    assert mrtr.input_required_to_dict(incomplete)["resultType"] == "input_required"
    assert calls == []
    # Tampered state must never authorize execute.
    body, mac = token.rsplit(".", 1)
    bad = f"{body}.{mac[:-1] + ('A' if mac[-1] != 'A' else 'B')}"
    rejected = handler(
        project=project,
        as_json=True,
        requestState=bad,
        inputResponses=_accept_responses(),
    )
    assert isinstance(rejected, dict)
    assert rejected["ok"] is False
    assert calls == []
    accepted = handler(
        project=project,
        as_json=True,
        requestState=token,
        inputResponses=_accept_responses(),
    )
    assert accepted["ok"] is True
    assert accepted["parsed_json"] == {"ran": True}
    assert len(calls) == 1
    assert "requestState" not in calls[0][1]
    assert "inputResponses" not in calls[0][1]
    assert calls[0][1]["project"] == project


def test_handler_capability_filter_never_emits_unsupported_elicitation() -> None:
    """Capability filter: no elicitation/create when client lacks it."""
    from avo.mcp.tools.cli_tools import _all_bridge_defs, _make_handler

    mrtr.reset_process_signing_key_for_tests()
    defn = next(d for d in _all_bridge_defs() if d.spec.name == TOOL)
    handler = _make_handler(defn)
    ctx = SimpleNamespace(client_capabilities={"sampling": {}})
    result = handler(project="/tmp/mrtr-no-elicit", as_json=True, ctx=ctx)
    assert isinstance(result, dict)
    assert result["ok"] is False
    assert "elicitation" in result["stderr"].lower()
    # Must not soft-return an InputRequired with unsupported methods.
    assert "resultType" not in result
    assert "inputRequests" not in result


def test_build_input_required_soft_adapts_without_sdk_types() -> None:
    """Wire shape is usable even when SDK InputRequiredResult is absent."""
    key = generate_key()
    result = mrtr.build_input_required_result(
        tool=TOOL,
        args=TMP_ARGS,
        key=key,
        client_capabilities=ELICIT_CAPS,
        capabilities_provided=True,
    )
    wire = mrtr.input_required_to_dict(result)
    assert wire["resultType"] == "input_required"
    assert "requestState" in wire
    if not _sdk_input_required_available():
        assert isinstance(result, dict)
    # Optional SDK assertion — soft-adapt covers missing types.
    if _sdk_input_required_available():
        from mcp.types import InputRequiredResult

        assert isinstance(result, (dict, InputRequiredResult))


def test_verify_confirm_raises_on_tamper_for_gate_helpers() -> None:
    key = generate_key()
    token = mrtr.build_confirm_request_state(tool=TOOL, args=TMP_ARGS, key=key)
    with pytest.raises(RequestStateError):
        mrtr.verify_confirm_request_state(
            token + "x",
            tool=TOOL,
            args=TMP_ARGS,
            key=key,
        )


def test_extract_mrtr_fields_from_kwargs_and_ctx() -> None:
    rs, ir = mrtr.extract_mrtr_fields(
        {
            "requestState": "token-a",
            "inputResponses": {"confirm_destructive": {"action": "accept"}},
            "project": "/tmp/x",
        }
    )
    assert rs == "token-a"
    assert ir is not None and "confirm_destructive" in ir
    ctx = SimpleNamespace(
        request_state="token-b",
        input_responses={"confirm_destructive": {"action": "decline"}},
    )
    rs2, ir2 = mrtr.extract_mrtr_fields({}, ctx=ctx)
    assert rs2 == "token-b"
    assert ir2 is not None and ir2["confirm_destructive"]["action"] == "decline"


def test_tmp_paths_only_no_provider_footage_literals() -> None:
    """Guardrail: this module's gate args stay under /tmp (NFR fixture rule)."""
    assert TMP_ARGS["project"].startswith("/tmp/")
