"""Unit tests for avo.mcp requestState encode/verify (no providers / footage)."""

from __future__ import annotations

import base64
import json
import time

import pytest

from avo.mcp import mrtr, request_state
from avo.mcp.request_state import (
    DEFAULT_TTL_SECONDS,
    PAYLOAD_VERSION,
    RequestStateError,
    digest_args,
    encode_request_state,
    generate_key,
    verify_request_state,
)


def test_digest_args_stable() -> None:
    a = digest_args({"project": "/tmp/p", "force": True})
    b = digest_args({"force": True, "project": "/tmp/p"})
    assert a == b
    assert len(a) == 64
    assert digest_args(None) == digest_args({})


def test_encode_verify_roundtrip() -> None:
    key = generate_key()
    args = {"project": "/tmp/demo", "yes": True}
    token = encode_request_state(
        tool="avo_cleanup_execute",
        args=args,
        key=key,
        ttl_seconds=120,
        now=1_700_000_000.0,
    )
    assert isinstance(token, str)
    assert "." in token
    payload = verify_request_state(
        token,
        tool="avo_cleanup_execute",
        args=args,
        key=key,
        now=1_700_000_000.0,
    )
    assert payload.v == PAYLOAD_VERSION
    assert payload.tool == "avo_cleanup_execute"
    assert payload.method == "tools/call"
    assert payload.intent == "confirm_destructive"
    assert payload.args_digest == digest_args(args)
    assert payload.exp == 1_700_000_000 + 120


def test_mrtr_confirm_helpers_roundtrip() -> None:
    key = generate_key()
    args = {"project": "/tmp/x"}
    token = mrtr.build_confirm_request_state(
        tool="avo_cleanup_execute",
        args=args,
        key=key,
    )
    payload = mrtr.verify_confirm_request_state(
        token,
        tool="avo_cleanup_execute",
        args=args,
        key=key,
    )
    assert payload.intent == mrtr.INTENT_CONFIRM_DESTRUCTIVE
    assert payload.method == mrtr.METHOD_TOOLS_CALL


def test_evaluate_destructive_gate_first_call_and_retry() -> None:
    key = generate_key()
    args = {"project": "/tmp/gate", "as_json": True}
    first = mrtr.evaluate_destructive_gate(
        tool="avo_cleanup_execute", args=args, key=key
    )
    assert first.outcome is mrtr.GateOutcome.INPUT_REQUIRED
    assert first.result is not None
    wire = mrtr.input_required_to_dict(first.result)
    assert wire["resultType"] == "input_required"
    assert wire["requestState"]
    assert "confirm_destructive" in (wire.get("inputRequests") or {})

    token = wire["requestState"]
    incomplete = mrtr.evaluate_destructive_gate(
        tool="avo_cleanup_execute",
        args=args,
        key=key,
        request_state=token,
        input_responses={},
    )
    assert incomplete.outcome is mrtr.GateOutcome.INPUT_REQUIRED

    accepted = mrtr.evaluate_destructive_gate(
        tool="avo_cleanup_execute",
        args=args,
        key=key,
        request_state=token,
        input_responses={
            mrtr.CONFIRM_ELICITATION_KEY: {
                "action": "accept",
                "content": {"confirm": True},
            }
        },
    )
    assert accepted.outcome is mrtr.GateOutcome.PROCEED

    declined = mrtr.evaluate_destructive_gate(
        tool="avo_cleanup_execute",
        args=args,
        key=key,
        request_state=token,
        input_responses={mrtr.CONFIRM_ELICITATION_KEY: {"action": "decline"}},
    )
    assert declined.outcome is mrtr.GateOutcome.REJECT


def test_destructive_handler_returns_input_required_before_bridge() -> None:
    from avo.mcp.tools.cli_tools import _all_bridge_defs, _make_handler

    mrtr.reset_process_signing_key_for_tests()
    defn = next(d for d in _all_bridge_defs() if d.spec.name == "avo_cleanup_execute")
    handler = _make_handler(defn)
    first = handler(project="/tmp/gate-handler", as_json=True)
    wire = mrtr.input_required_to_dict(first)
    assert wire["resultType"] == "input_required"
    token = wire["requestState"]

    incomplete = handler(
        project="/tmp/gate-handler",
        as_json=True,
        requestState=token,
    )
    assert mrtr.input_required_to_dict(incomplete)["resultType"] == "input_required"

    declined = handler(
        project="/tmp/gate-handler",
        as_json=True,
        requestState=token,
        inputResponses={mrtr.CONFIRM_ELICITATION_KEY: {"action": "cancel"}},
    )
    assert declined["ok"] is False
    assert "declined" in declined["stderr"] or "cancelled" in declined["stderr"]


def test_reject_tampered_mac() -> None:
    key = generate_key()
    token = encode_request_state(tool="avo_cleanup_execute", args={}, key=key)
    body, mac = token.rsplit(".", 1)
    # Flip a mid-alphabet character (not the last sextet): trailing base64url
    # padding bits can make last-char flips decode to the same MAC bytes.
    assert len(mac) > 2
    mid = len(mac) // 2
    flipped_ch = "A" if mac[mid] != "A" else "B"
    bad = f"{body}.{mac[:mid]}{flipped_ch}{mac[mid + 1 :]}"
    with pytest.raises(RequestStateError, match="integrity"):
        verify_request_state(bad, tool="avo_cleanup_execute", args={}, key=key)


def test_reject_tampered_payload() -> None:
    key = generate_key()
    token = encode_request_state(tool="avo_cleanup_execute", args={}, key=key)
    body_b64, mac = token.rsplit(".", 1)
    pad = "=" * (-len(body_b64) % 4)
    raw = json.loads(base64.urlsafe_b64decode(body_b64 + pad))
    raw["tool"] = "avo_other_tool"
    new_body = (
        base64.urlsafe_b64encode(
            json.dumps(raw, sort_keys=True, separators=(",", ":")).encode("utf-8")
        )
        .rstrip(b"=")
        .decode("ascii")
    )
    bad = f"{new_body}.{mac}"
    with pytest.raises(RequestStateError, match="integrity"):
        verify_request_state(bad, tool="avo_other_tool", args={}, key=key)


def test_reject_expired() -> None:
    key = generate_key()
    now = 1_700_000_000.0
    token = encode_request_state(
        tool="avo_cleanup_execute",
        args={},
        key=key,
        ttl_seconds=10,
        now=now,
    )
    with pytest.raises(RequestStateError, match="expired"):
        verify_request_state(
            token,
            tool="avo_cleanup_execute",
            args={},
            key=key,
            now=now + 11,
        )


def test_reject_tool_mismatch() -> None:
    key = generate_key()
    token = encode_request_state(tool="avo_cleanup_execute", args={}, key=key)
    with pytest.raises(RequestStateError, match="tool binding"):
        verify_request_state(token, tool="avo_pipeline_status", args={}, key=key)


def test_reject_method_mismatch() -> None:
    key = generate_key()
    token = encode_request_state(
        tool="avo_cleanup_execute",
        method="tools/call",
        args={},
        key=key,
    )
    with pytest.raises(RequestStateError, match="method binding"):
        verify_request_state(
            token,
            tool="avo_cleanup_execute",
            method="prompts/get",
            args={},
            key=key,
        )


def test_reject_args_digest_mismatch() -> None:
    key = generate_key()
    token = encode_request_state(
        tool="avo_cleanup_execute",
        args={"project": "/a"},
        key=key,
    )
    with pytest.raises(RequestStateError, match="args_digest"):
        verify_request_state(
            token,
            tool="avo_cleanup_execute",
            args={"project": "/b"},
            key=key,
        )


def test_reject_wrong_key() -> None:
    key_a = generate_key()
    key_b = generate_key()
    token = encode_request_state(tool="avo_cleanup_execute", args={}, key=key_a)
    with pytest.raises(RequestStateError, match="integrity"):
        verify_request_state(token, tool="avo_cleanup_execute", args={}, key=key_b)


def test_resolve_signing_key_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(request_state.SECRET_ENV, "unit-test-secret")
    token = encode_request_state(tool="avo_cleanup_execute", args={})
    payload = verify_request_state(token, tool="avo_cleanup_execute", args={})
    assert payload.tool == "avo_cleanup_execute"


def test_default_ttl_constant() -> None:
    assert DEFAULT_TTL_SECONDS == 600
    assert time.time() > 0  # clock available for live encode
