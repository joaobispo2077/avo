"""Opaque MRTR ``requestState`` encode / verify helpers.

Continuity for gated tool calls lives in client-echoed ``requestState`` (FR-15),
not a server-side session store (FR-14). Tokens are integrity-protected (HMAC),
time-bounded (TTL), and bound to MCP method + tool (+ optional args digest).

Treat every decoded token as attacker-controlled until ``verify_request_state``
succeeds. No process-global map keyed by JSON-RPC id; no Redis/DB.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from dataclasses import dataclass
from typing import Any, Mapping, MutableMapping

# Wire format version for the integrity-protected payload.
PAYLOAD_VERSION = 1

# Default TTL for destructive confirm gates (seconds).
DEFAULT_TTL_SECONDS = 600

# Env hook for multi-worker HTTP later; local stdio prefers ephemeral keys.
SECRET_ENV = "AVO_MCP_REQUEST_STATE_SECRET"

# Opaque token: base64url(payload_json) + "." + base64url(hmac_sha256)
_TOKEN_SEP = "."


class RequestStateError(ValueError):
    """Raised when ``requestState`` is missing, malformed, expired, or mismatched."""


@dataclass(frozen=True)
class RequestStatePayload:
    """Verified (or freshly built) integrity-protected request continuity fields."""

    v: int
    tool: str
    method: str
    exp: int
    intent: str
    args_digest: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable dict (stable key order for signing)."""
        data: dict[str, Any] = {
            "v": self.v,
            "tool": self.tool,
            "method": self.method,
            "exp": self.exp,
            "intent": self.intent,
        }
        if self.args_digest is not None:
            data["args_digest"] = self.args_digest
        return data

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> RequestStatePayload:
        """Parse a mapping into a payload; raises ``RequestStateError`` if invalid."""
        try:
            v = int(raw["v"])
            tool = str(raw["tool"])
            method = str(raw["method"])
            exp = int(raw["exp"])
            intent = str(raw["intent"])
        except (KeyError, TypeError, ValueError) as exc:
            raise RequestStateError("requestState payload missing required fields") from exc
        if v != PAYLOAD_VERSION:
            raise RequestStateError(f"unsupported requestState version: {v}")
        if not tool or not method or not intent:
            raise RequestStateError("requestState tool/method/intent must be non-empty")
        if exp <= 0:
            raise RequestStateError("requestState exp must be a positive unix timestamp")
        args_digest = raw.get("args_digest")
        if args_digest is not None:
            args_digest = str(args_digest)
            if len(args_digest) != 64 or any(c not in "0123456789abcdef" for c in args_digest):
                raise RequestStateError("requestState args_digest must be sha256 hex")
        return cls(
            v=v,
            tool=tool,
            method=method,
            exp=exp,
            intent=intent,
            args_digest=args_digest,
        )


def canonical_json_bytes(value: Any) -> bytes:
    """Deterministic UTF-8 JSON for hashing and HMAC (sorted keys, compact)."""
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def digest_args(args: Mapping[str, Any] | None) -> str:
    """SHA-256 hex digest of tool args (or empty object when args is None)."""
    payload: Mapping[str, Any] = {} if args is None else dict(args)
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def generate_key(nbytes: int = 32) -> bytes:
    """Return a fresh ephemeral HMAC key (process-local stdio default)."""
    return secrets.token_bytes(nbytes)


def resolve_signing_key(explicit: bytes | str | None = None) -> bytes:
    """Resolve HMAC key: explicit → env ``AVO_MCP_REQUEST_STATE_SECRET`` → error.

    Callers that want a process-ephemeral key should call ``generate_key()`` once
    at server start and pass it explicitly. This helper never invents a silent
    global session store.
    """
    if explicit is not None:
        if isinstance(explicit, str):
            key = explicit.encode("utf-8")
        else:
            key = explicit
        if not key:
            raise RequestStateError("signing key must be non-empty")
        return key
    env = os.environ.get(SECRET_ENV)
    if env:
        key = env.encode("utf-8")
        if not key:
            raise RequestStateError(f"{SECRET_ENV} is empty")
        return key
    raise RequestStateError(
        "no requestState signing key: pass key= or set " + SECRET_ENV
    )


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(text: str) -> bytes:
    pad = "=" * (-len(text) % 4)
    try:
        return base64.urlsafe_b64decode(text + pad)
    except (ValueError, TypeError) as exc:
        raise RequestStateError("requestState is not valid base64url") from exc


def _sign(payload_bytes: bytes, key: bytes) -> bytes:
    return hmac.new(key, payload_bytes, hashlib.sha256).digest()


def encode_request_state(
    *,
    tool: str,
    method: str = "tools/call",
    intent: str = "confirm_destructive",
    args: Mapping[str, Any] | None = None,
    args_digest: str | None = None,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
    now: float | None = None,
    key: bytes | str | None = None,
    include_args_digest: bool = True,
) -> str:
    """Build an opaque integrity-protected ``requestState`` token.

    Parameters
    ----------
    tool:
        MCP tool name (e.g. ``avo_cleanup_execute``).
    method:
        Originating MCP method (default ``tools/call``).
    intent:
        Server-defined gate intent (e.g. ``confirm_destructive``).
    args / args_digest:
        Salient parameters digest for cross-request replay binding. When
        ``include_args_digest`` is true, digest is taken from ``args_digest`` or
        computed from ``args``.
    ttl_seconds:
        Lifetime from ``now`` (default 600s).
    key:
        HMAC key bytes/str, or resolve via ``AVO_MCP_REQUEST_STATE_SECRET``.
    """
    if ttl_seconds <= 0:
        raise RequestStateError("ttl_seconds must be positive")
    signing_key = resolve_signing_key(key)
    clock = time.time() if now is None else float(now)
    digest: str | None = None
    if include_args_digest:
        digest = args_digest if args_digest is not None else digest_args(args)
    payload = RequestStatePayload(
        v=PAYLOAD_VERSION,
        tool=str(tool),
        method=str(method),
        exp=int(clock) + int(ttl_seconds),
        intent=str(intent),
        args_digest=digest,
    )
    if not payload.tool or not payload.method or not payload.intent:
        raise RequestStateError("tool/method/intent must be non-empty")
    body = canonical_json_bytes(payload.to_dict())
    mac = _sign(body, signing_key)
    return f"{_b64url_encode(body)}{_TOKEN_SEP}{_b64url_encode(mac)}"


def decode_request_state_unverified(token: str) -> RequestStatePayload:
    """Parse payload bytes without checking HMAC or expiry.

    **Unsafe for authorize/execute.** Prefer ``verify_request_state``.
    """
    if not token or not isinstance(token, str):
        raise RequestStateError("requestState must be a non-empty string")
    if _TOKEN_SEP not in token:
        raise RequestStateError("requestState token format invalid")
    body_b64, _mac_b64 = token.rsplit(_TOKEN_SEP, 1)
    if not body_b64:
        raise RequestStateError("requestState token format invalid")
    body = _b64url_decode(body_b64)
    try:
        raw = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RequestStateError("requestState payload is not valid JSON") from exc
    if not isinstance(raw, MutableMapping):
        raise RequestStateError("requestState payload must be a JSON object")
    return RequestStatePayload.from_mapping(raw)


def verify_request_state(
    token: str,
    *,
    tool: str,
    method: str = "tools/call",
    intent: str | None = None,
    args: Mapping[str, Any] | None = None,
    args_digest: str | None = None,
    require_args_digest: bool = True,
    now: float | None = None,
    key: bytes | str | None = None,
) -> RequestStatePayload:
    """Verify integrity, TTL, and method/tool(/intent/args) binding.

    Raises ``RequestStateError`` on any failure. Never authorizes execute on
    unsigned, expired, or mismatched state.
    """
    if not token or not isinstance(token, str):
        raise RequestStateError("requestState must be a non-empty string")
    if _TOKEN_SEP not in token:
        raise RequestStateError("requestState token format invalid")

    body_b64, mac_b64 = token.rsplit(_TOKEN_SEP, 1)
    if not body_b64 or not mac_b64:
        raise RequestStateError("requestState token format invalid")

    body = _b64url_decode(body_b64)
    presented_mac = _b64url_decode(mac_b64)
    signing_key = resolve_signing_key(key)
    expected_mac = _sign(body, signing_key)
    if not hmac.compare_digest(presented_mac, expected_mac):
        raise RequestStateError("requestState integrity check failed")

    try:
        raw = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RequestStateError("requestState payload is not valid JSON") from exc
    if not isinstance(raw, MutableMapping):
        raise RequestStateError("requestState payload must be a JSON object")

    # Re-canonicalize and refuse extra/unordered drift: body must equal
    # canonical encoding of the parsed payload (prevents ambiguous JSON).
    payload = RequestStatePayload.from_mapping(raw)
    if body != canonical_json_bytes(payload.to_dict()):
        raise RequestStateError("requestState payload encoding mismatch")

    clock = time.time() if now is None else float(now)
    if payload.exp < int(clock):
        raise RequestStateError("requestState expired")

    if payload.tool != tool:
        raise RequestStateError("requestState tool binding mismatch")
    if payload.method != method:
        raise RequestStateError("requestState method binding mismatch")
    if intent is not None and payload.intent != intent:
        raise RequestStateError("requestState intent binding mismatch")

    if require_args_digest:
        expected = args_digest if args_digest is not None else digest_args(args)
        if payload.args_digest is None:
            raise RequestStateError("requestState missing args_digest")
        if not hmac.compare_digest(payload.args_digest, expected):
            raise RequestStateError("requestState args_digest mismatch")
    elif args_digest is not None or args is not None:
        expected = args_digest if args_digest is not None else digest_args(args)
        if payload.args_digest is not None and not hmac.compare_digest(
            payload.args_digest, expected
        ):
            raise RequestStateError("requestState args_digest mismatch")

    return payload


__all__ = [
    "DEFAULT_TTL_SECONDS",
    "PAYLOAD_VERSION",
    "SECRET_ENV",
    "RequestStateError",
    "RequestStatePayload",
    "canonical_json_bytes",
    "decode_request_state_unverified",
    "digest_args",
    "encode_request_state",
    "generate_key",
    "resolve_signing_key",
    "verify_request_state",
]
