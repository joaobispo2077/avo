"""MRTR (Multi Round-Trip Requests) helpers for gated avo.mcp tools.

Continuity for destructive/confirm gates lives in client-echoed ``requestState``
(FR-15), not a server-side session store (FR-14). This module builds
``InputRequiredResult`` envelopes, interprets retry ``inputResponses``, and
never blocks waiting for the client.

Soft-adapts when the official ``mcp`` SDK types are unavailable: helpers return
plain JSON-shaped dicts that match the MRTR wire fields.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping

from avo.mcp.request_state import (
    DEFAULT_TTL_SECONDS,
    SECRET_ENV,
    RequestStateError,
    RequestStatePayload,
    digest_args,
    encode_request_state,
    generate_key,
    verify_request_state,
)

# Default gate intent for registry ``destructive=True`` tools.
INTENT_CONFIRM_DESTRUCTIVE = "confirm_destructive"

# MCP method that may return InputRequiredResult for tools.
METHOD_TOOLS_CALL = "tools/call"

# Wire resultType for MRTR pause.
RESULT_TYPE_INPUT_REQUIRED = "input_required"

# Allowed inputRequest methods (FR-15) — emit only if the client declared them.
METHOD_ELICITATION_CREATE = "elicitation/create"
METHOD_SAMPLING_CREATE_MESSAGE = "sampling/createMessage"
METHOD_ROOTS_LIST = "roots/list"

ALLOWED_INPUT_REQUEST_METHODS: frozenset[str] = frozenset(
    {
        METHOD_ELICITATION_CREATE,
        METHOD_SAMPLING_CREATE_MESSAGE,
        METHOD_ROOTS_LIST,
    }
)

# Key inside InputRequests / InputResponses maps for the confirm gate.
CONFIRM_ELICITATION_KEY = "confirm_destructive"

# Documented degrade when the client cannot confirm via supported methods.
CAPABILITY_DEGRADE_MESSAGE = (
    "Client lacks elicitation/create (form) for destructive MRTR confirmation. "
    "No unsupported inputRequests were emitted and confirmation was not faked. "
    "Declare elicitation form capability, or run the equivalent via avo CLI / skills."
)

# Kwargs that must never be forwarded to the CLI bridge.
MRTR_KWARG_NAMES: frozenset[str] = frozenset(
    {
        "request_state",
        "requestState",
        "input_responses",
        "inputResponses",
        "ctx",
    }
)

# Process-ephemeral HMAC key (stdio default). Env overrides when set.
_PROCESS_SIGNING_KEY: bytes | None = None

def process_signing_key() -> bytes:
    """Return the process-scoped requestState signing key.

    Prefer ``AVO_MCP_REQUEST_STATE_SECRET`` when set; otherwise generate once
    per process. Does not invent a session store.
    """
    global _PROCESS_SIGNING_KEY
    if _PROCESS_SIGNING_KEY is not None:
        return _PROCESS_SIGNING_KEY
    env = os.environ.get(SECRET_ENV)
    if env:
        key = env.encode("utf-8")
        if not key:
            raise RequestStateError(f"{SECRET_ENV} is empty")
        _PROCESS_SIGNING_KEY = key
    else:
        _PROCESS_SIGNING_KEY = generate_key()
    return _PROCESS_SIGNING_KEY

def reset_process_signing_key_for_tests() -> None:
    """Clear the process key (unit tests only)."""
    global _PROCESS_SIGNING_KEY
    _PROCESS_SIGNING_KEY = None

def build_confirm_request_state(
    *,
    tool: str,
    args: Mapping[str, Any] | None = None,
    key: bytes | str | None = None,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
    intent: str = INTENT_CONFIRM_DESTRUCTIVE,
    method: str = METHOD_TOOLS_CALL,
    now: float | None = None,
) -> str:
    """Encode opaque ``requestState`` for a destructive/confirm gate.

    Pure helper: no side effects, no session dict. Pass a process-ephemeral
    ``key`` from ``generate_key()`` / ``process_signing_key()`` (or env).
    """
    return encode_request_state(
        tool=tool,
        method=method,
        intent=intent,
        args=args,
        ttl_seconds=ttl_seconds,
        now=now,
        key=key if key is not None else process_signing_key(),
        include_args_digest=True,
    )

def verify_confirm_request_state(
    token: str,
    *,
    tool: str,
    args: Mapping[str, Any] | None = None,
    key: bytes | str | None = None,
    intent: str = INTENT_CONFIRM_DESTRUCTIVE,
    method: str = METHOD_TOOLS_CALL,
    now: float | None = None,
) -> RequestStatePayload:
    """Verify echoed ``requestState`` before authorizing a gated tool call."""
    return verify_request_state(
        token,
        tool=tool,
        method=method,
        intent=intent,
        args=args,
        require_args_digest=True,
        now=now,
        key=key if key is not None else process_signing_key(),
    )

def confirm_elicitation_message(tool: str) -> str:
    """Human-facing elicitation message for a destructive tool confirm."""
    return (
        f"Confirm destructive AVO tool '{tool}'. "
        "Set confirm=true only if you intend to run this irreversible or "
        "high-impact operation."
    )

def confirm_elicitation_schema() -> dict[str, Any]:
    """JSON Schema for the confirm form (spec-primitive boolean property)."""
    return {
        "type": "object",
        "properties": {
            "confirm": {
                "type": "boolean",
                "title": "Confirm",
                "description": "True to authorize this destructive tool call",
            }
        },
        "required": ["confirm"],
    }

def _caps_field(caps: Any, name: str) -> Any:
    """Read a capability field from SDK model or mapping."""
    if caps is None:
        return None
    if isinstance(caps, Mapping):
        return caps.get(name)
    return getattr(caps, name, None)

def client_supports_elicitation_create(client_capabilities: Any | None) -> bool:
    """True when the client declared form ``elicitation/create``.

    Matches SDK resolver rules: bare ``elicitation: {}`` counts as form support;
    url-only elicitation does not.
    """
    elicitation = _caps_field(client_capabilities, "elicitation")
    if elicitation is None:
        return False
    form = _caps_field(elicitation, "form")
    url = _caps_field(elicitation, "url")
    return form is not None or url is None

def client_supports_sampling_create_message(client_capabilities: Any | None) -> bool:
    """True when the client declared sampling (``sampling/createMessage``)."""
    return _caps_field(client_capabilities, "sampling") is not None

def client_supports_roots_list(client_capabilities: Any | None) -> bool:
    """True when the client declared roots (``roots/list``)."""
    return _caps_field(client_capabilities, "roots") is not None

def allowed_input_request_methods(
    client_capabilities: Any | None,
) -> frozenset[str]:
    """Return FR-15 methods the client may be asked for in ``inputRequests``."""
    allowed: set[str] = set()
    if client_supports_elicitation_create(client_capabilities):
        allowed.add(METHOD_ELICITATION_CREATE)
    if client_supports_sampling_create_message(client_capabilities):
        allowed.add(METHOD_SAMPLING_CREATE_MESSAGE)
    if client_supports_roots_list(client_capabilities):
        allowed.add(METHOD_ROOTS_LIST)
    return frozenset(allowed)

def input_request_method(entry: Any) -> str | None:
    """Resolve the wire method for an ``inputRequests`` entry."""
    if entry is None:
        return None
    if isinstance(entry, Mapping):
        method = entry.get("method")
        return str(method) if method else METHOD_ELICITATION_CREATE
    method = getattr(entry, "method", None)
    if method:
        return str(method)
    # SDK ``ElicitRequest`` implies elicitation/create.
    type_name = type(entry).__name__
    if "Elicit" in type_name:
        return METHOD_ELICITATION_CREATE
    if "CreateMessage" in type_name or "Sampling" in type_name:
        return METHOD_SAMPLING_CREATE_MESSAGE
    if "ListRoots" in type_name or "Roots" in type_name:
        return METHOD_ROOTS_LIST
    return None

def filter_input_requests(
    input_requests: Mapping[str, Any] | None,
    allowed_methods: frozenset[str] | set[str] | None,
) -> dict[str, Any]:
    """Drop ``inputRequests`` entries whose method is not client-allowed.

    Never invents methods. Entries outside
    :data:`ALLOWED_INPUT_REQUEST_METHODS` are always removed.
    """
    if not input_requests:
        return {}
    allow = (
        frozenset(allowed_methods)
        if allowed_methods is not None
        else ALLOWED_INPUT_REQUEST_METHODS
    )
    allow = allow & ALLOWED_INPUT_REQUEST_METHODS
    out: dict[str, Any] = {}
    for key, entry in input_requests.items():
        method = input_request_method(entry)
        if method is not None and method in allow:
            out[key] = entry
    return out

def extract_client_capabilities(ctx: Any | None) -> Any | None:
    """Pull client capabilities from MCP ``Context`` (or test double)."""
    if ctx is None:
        return None
    caps = getattr(ctx, "client_capabilities", None)
    if callable(caps):
        caps = caps()
    return caps

def resolve_include_elicitation(
    client_capabilities: Any | None = None,
    *,
    include_elicitation: bool | None = None,
    capabilities_provided: bool = False,
) -> bool:
    """Decide whether confirm ``elicitation/create`` may be emitted.

    Explicit ``include_elicitation`` wins. When capability context was not
    supplied (no live ``Context``), default to True so unit tests and
    capability-unaware callers still exercise MRTR. When capability context
    *was* supplied, honor declared methods only (None/empty → False).
    """
    if include_elicitation is not None:
        return include_elicitation
    if not capabilities_provided:
        return True
    return METHOD_ELICITATION_CREATE in allowed_input_request_methods(
        client_capabilities
    )

def capability_degrade_message(tool: str) -> str:
    """Documented failure text when destructive confirm cannot be elicited."""
    return f"{CAPABILITY_DEGRADE_MESSAGE} Tool: {tool}."

def build_confirm_input_requests(*, tool: str) -> dict[str, Any]:
    """Build the ``inputRequests`` map for a destructive confirm gate.

    Shape matches MCP 2026-07-28 ``InputRequests`` (keyed map, not a list).
    Values are plain dicts so callers can soft-adapt without the SDK.
    """
    return {
        CONFIRM_ELICITATION_KEY: {
            "method": METHOD_ELICITATION_CREATE,
            "params": {
                "mode": "form",
                "message": confirm_elicitation_message(tool),
                "requestedSchema": confirm_elicitation_schema(),
            },
        }
    }

def _try_sdk_input_required(
    *,
    input_requests: Mapping[str, Any],
    request_state: str,
) -> Any | None:
    """Return an SDK ``InputRequiredResult`` when ``mcp`` types are available."""
    try:
        from mcp.types import ElicitRequest, ElicitRequestFormParams, InputRequiredResult
    except ImportError:
        return None

    sdk_requests: dict[str, Any] = {}
    for key, raw in input_requests.items():
        if hasattr(raw, "model_dump"):
            sdk_requests[key] = raw
            continue
        if not isinstance(raw, Mapping):
            continue
        method = raw.get("method", METHOD_ELICITATION_CREATE)
        params = raw.get("params") or {}
        if method != METHOD_ELICITATION_CREATE:
            # Soft-adapt: keep unknown methods as raw dicts under the map.
            sdk_requests[key] = dict(raw)
            continue
        if hasattr(params, "model_dump"):
            sdk_requests[key] = ElicitRequest(params=params)
            continue
        form = ElicitRequestFormParams(
            message=str(params.get("message") or ""),
            requestedSchema=dict(params.get("requestedSchema") or params.get("requested_schema") or {}),
            mode="form",
        )
        sdk_requests[key] = ElicitRequest(params=form)
    return InputRequiredResult(
        input_requests=sdk_requests,
        request_state=request_state,
    )

def build_input_required_result(
    *,
    tool: str,
    args: Mapping[str, Any] | None = None,
    key: bytes | str | None = None,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
    now: float | None = None,
    input_requests: Mapping[str, Any] | None = None,
    include_elicitation: bool | None = None,
    client_capabilities: Any | None = None,
    capabilities_provided: bool = False,
    allowed_methods: frozenset[str] | set[str] | None = None,
) -> Any:
    """Build an ``InputRequiredResult`` (SDK type or plain dict soft-adapt).

    Always includes integrity-protected ``requestState``. Confirm
    ``elicitation/create`` is attached only when capability-aware resolution
    allows it. Any ``inputRequests`` are filtered to client-declared methods
    (``elicitation/create``, ``sampling/createMessage``, ``roots/list``).
    """
    token = build_confirm_request_state(
        tool=tool,
        args=args,
        key=key,
        ttl_seconds=ttl_seconds,
        now=now,
    )
    allow_elicit = resolve_include_elicitation(
        client_capabilities,
        include_elicitation=include_elicitation,
        capabilities_provided=capabilities_provided,
    )
    requests: dict[str, Any]
    if input_requests is not None:
        requests = dict(input_requests)
    elif allow_elicit:
        requests = build_confirm_input_requests(tool=tool)
    else:
        requests = {}

    if allowed_methods is not None:
        allow = frozenset(allowed_methods)
    elif capabilities_provided:
        allow = allowed_input_request_methods(client_capabilities)
    else:
        allow = ALLOWED_INPUT_REQUEST_METHODS
    requests = filter_input_requests(requests, allow)

    sdk = _try_sdk_input_required(input_requests=requests, request_state=token)
    if sdk is not None:
        return sdk

    # Soft-adapt wire shape (camelCase aliases per MCP JSON).
    payload: dict[str, Any] = {
        "resultType": RESULT_TYPE_INPUT_REQUIRED,
        "requestState": token,
    }
    if requests:
        payload["inputRequests"] = requests
    return payload

def input_required_to_dict(result: Any) -> dict[str, Any]:
    """Normalize SDK or dict InputRequiredResult to a camelCase wire dict."""
    if isinstance(result, Mapping):
        out = dict(result)
        # Accept snake_case soft-adapt callers.
        if "result_type" in out and "resultType" not in out:
            out["resultType"] = out.pop("result_type")
        if "request_state" in out and "requestState" not in out:
            out["requestState"] = out.pop("request_state")
        if "input_requests" in out and "inputRequests" not in out:
            out["inputRequests"] = out.pop("input_requests")
        return out
    if hasattr(result, "model_dump"):
        dumped = result.model_dump(by_alias=True, mode="json", exclude_none=True)
        return dict(dumped)
    raise TypeError(f"unsupported InputRequiredResult type: {type(result)!r}")

def extract_mrtr_fields(
    kwargs: Mapping[str, Any] | None = None,
    *,
    ctx: Any | None = None,
) -> tuple[str | None, Mapping[str, Any] | None]:
    """Pull ``requestState`` + ``inputResponses`` from Context and/or kwargs.

    Protocol path: MRTR fields arrive on ``CallToolRequestParams`` and are
    exposed via MCP ``Context`` (not tool arguments). Kwargs fallback supports
    direct unit tests without a live session.
    """
    request_state: str | None = None
    input_responses: Mapping[str, Any] | None = None

    if ctx is not None:
        rs = getattr(ctx, "request_state", None)
        ir = getattr(ctx, "input_responses", None)
        if callable(rs):
            rs = rs()
        if callable(ir):
            ir = ir()
        if isinstance(rs, str) and rs:
            request_state = rs
        if isinstance(ir, Mapping) and ir:
            input_responses = ir

    raw = kwargs or {}
    if request_state is None:
        for name in ("request_state", "requestState"):
            val = raw.get(name)
            if isinstance(val, str) and val:
                request_state = val
                break
    if input_responses is None:
        for name in ("input_responses", "inputResponses"):
            val = raw.get(name)
            if isinstance(val, Mapping) and val:
                input_responses = val
                break

    return request_state, input_responses

def bridge_kwargs_from_tool_kwargs(kwargs: Mapping[str, Any]) -> dict[str, Any]:
    """Strip MRTR / Context keys before forwarding to the CLI bridge."""
    return {k: v for k, v in kwargs.items() if k not in MRTR_KWARG_NAMES}

def _response_action_and_content(entry: Any) -> tuple[str | None, Mapping[str, Any] | None]:
    """Normalize an InputResponses entry to (action, content)."""
    if entry is None:
        return None, None
    if hasattr(entry, "action"):
        action = getattr(entry, "action", None)
        content = getattr(entry, "content", None)
        if content is not None and not isinstance(content, Mapping):
            content = None
        return (str(action) if action is not None else None), content
    if isinstance(entry, Mapping):
        action = entry.get("action")
        content = entry.get("content")
        if content is not None and not isinstance(content, Mapping):
            content = None
        return (str(action) if action is not None else None), content
    return None, None

def confirm_response_status(
    input_responses: Mapping[str, Any] | None,
    *,
    key: str = CONFIRM_ELICITATION_KEY,
) -> str:
    """Classify confirm elicitation responses.

    Returns:
        ``missing`` — no usable response for the confirm key (incomplete).
        ``accepted`` — action=accept and confirm=true.
        ``declined`` — decline/cancel, or accept with confirm=false.
        ``incomplete`` — present but not a usable accept/decline shape.
    """
    if not input_responses:
        return "missing"
    entry = input_responses.get(key)
    if entry is None:
        # Some clients may send a single anonymous elicitation response.
        if len(input_responses) == 1:
            entry = next(iter(input_responses.values()))
        else:
            return "missing"
    action, content = _response_action_and_content(entry)
    if action is None:
        return "incomplete"
    if action in ("decline", "cancel"):
        return "declined"
    if action != "accept":
        return "incomplete"
    if content is None:
        return "incomplete"
    confirm = content.get("confirm")
    if confirm is True:
        return "accepted"
    if confirm is False:
        return "declined"
    return "incomplete"

class GateOutcome(str, Enum):
    """Destructive MRTR gate decision."""

    PROCEED = "proceed"
    INPUT_REQUIRED = "input_required"
    REJECT = "reject"

@dataclass(frozen=True)

class GateDecision:
    """Result of evaluating a destructive tool gate (no side effects)."""

    outcome: GateOutcome
    result: Any | None = None
    error_message: str | None = None

def evaluate_destructive_gate(
    *,
    tool: str,
    args: Mapping[str, Any] | None = None,
    request_state: str | None = None,
    input_responses: Mapping[str, Any] | None = None,
    key: bytes | str | None = None,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
    now: float | None = None,
    include_elicitation: bool | None = None,
    client_capabilities: Any | None = None,
    capabilities_provided: bool = False,
) -> GateDecision:
    """Decide whether to pause (InputRequired), proceed, or reject.

    Never authorizes execute on missing/invalid/expired/mismatched
    ``requestState``. Incomplete retries return a new ``InputRequiredResult``.
    When capability context is provided and the client lacks form elicitation
    (with no other allowed confirm method), degrade to documented failure —
    never emit unsupported ``inputRequests`` and never fake confirm.
    """
    status = confirm_response_status(input_responses)
    has_state = isinstance(request_state, str) and bool(request_state)
    allow_elicit = resolve_include_elicitation(
        client_capabilities,
        include_elicitation=include_elicitation,
        capabilities_provided=capabilities_provided,
    )

    def _pause() -> GateDecision:
        if not allow_elicit:
            return GateDecision(
                outcome=GateOutcome.REJECT,
                error_message=capability_degrade_message(tool),
            )
        return GateDecision(
            outcome=GateOutcome.INPUT_REQUIRED,
            result=build_input_required_result(
                tool=tool,
                args=args,
                key=key,
                ttl_seconds=ttl_seconds,
                now=now,
                include_elicitation=True,
                client_capabilities=client_capabilities,
                capabilities_provided=capabilities_provided,
            ),
        )

    # First call / abandoned retry without state: pause (do not wait).
    if not has_state:
        return _pause()

    assert request_state is not None  # for type checkers
    try:
        verify_confirm_request_state(
            request_state,
            tool=tool,
            args=args,
            key=key,
            now=now,
        )
    except RequestStateError as exc:
        return GateDecision(
            outcome=GateOutcome.REJECT,
            error_message=f"requestState rejected: {exc}",
        )

    if status == "accepted":
        return GateDecision(outcome=GateOutcome.PROCEED)

    if status == "declined":
        return GateDecision(
            outcome=GateOutcome.REJECT,
            error_message="destructive tool confirmation was declined or cancelled",
        )

    # Incomplete (or missing responses with valid state): new InputRequiredResult.
    return _pause()

def gate_error_envelope(message: str) -> dict[str, Any]:
    """Bridge-shaped failure envelope for MRTR reject (not a hung waiter)."""
    return {
        "ok": False,
        "exit_code": 1,
        "stdout": "",
        "stderr": message,
        "parsed_json": None,
    }

__all__ = [
    "ALLOWED_INPUT_REQUEST_METHODS",
    "CAPABILITY_DEGRADE_MESSAGE",
    "CONFIRM_ELICITATION_KEY",
    "DEFAULT_TTL_SECONDS",
    "INTENT_CONFIRM_DESTRUCTIVE",
    "METHOD_ELICITATION_CREATE",
    "METHOD_ROOTS_LIST",
    "METHOD_SAMPLING_CREATE_MESSAGE",
    "METHOD_TOOLS_CALL",
    "MRTR_KWARG_NAMES",
    "RESULT_TYPE_INPUT_REQUIRED",
    "GateDecision",
    "GateOutcome",
    "RequestStateError",
    "RequestStatePayload",
    "allowed_input_request_methods",
    "bridge_kwargs_from_tool_kwargs",
    "build_confirm_input_requests",
    "build_confirm_request_state",
    "build_input_required_result",
    "capability_degrade_message",
    "client_supports_elicitation_create",
    "client_supports_roots_list",
    "client_supports_sampling_create_message",
    "confirm_elicitation_message",
    "confirm_elicitation_schema",
    "confirm_response_status",
    "digest_args",
    "evaluate_destructive_gate",
    "extract_client_capabilities",
    "extract_mrtr_fields",
    "filter_input_requests",
    "gate_error_envelope",
    "generate_key",
    "input_request_method",
    "input_required_to_dict",
    "process_signing_key",
    "reset_process_signing_key_for_tests",
    "resolve_include_elicitation",
    "verify_confirm_request_state",
]
