"""In-process bridge from MCP tool calls to ``avo.cli.main(argv)``.

Captures stdout/stderr so CLI JSON prints cannot corrupt MCP stdio framing.

MRTR continuity fields (``requestState`` / ``inputResponses`` / ``ctx``) must
never become CLI flags. Callers should strip them before ``run_bridged``;
``run_bridged`` also strips them defensively (FR-15).
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import asdict, dataclass
from io import StringIO
from typing import Any

# Keep in sync with ``avo.mcp.mrtr.MRTR_KWARG_NAMES`` (no import cycle at module load).
_MRTR_KWARG_NAMES: frozenset[str] = frozenset(
    {
        "request_state",
        "requestState",
        "input_responses",
        "inputResponses",
        "ctx",
    }
)

# Tool kwarg → CLI flag overrides (snake_case keys that are not 1:1 with --kebab).
_FLAG_OVERRIDES: dict[str, str] = {
    "as_json": "--json",
}


@dataclass
class BridgeResult:
    """Structured result envelope for a bridged CLI invocation."""

    ok: bool
    exit_code: int
    stdout: str
    stderr: str
    parsed_json: Any | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _try_parse_json(text: str) -> Any | None:
    stripped = text.strip()
    if not stripped:
        return None
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        return None


def kwargs_to_argv(
    prefix: Sequence[str],
    kwargs: Mapping[str, Any],
    *,
    flag_overrides: Mapping[str, str] | None = None,
) -> list[str]:
    """Map snake_case tool kwargs to a CLI argv list after *prefix*.

    Conventions:
    - ``None`` and empty-string values are omitted
    - ``bool`` True → bare flag; False → omit
    - ``list`` / ``tuple`` → repeat the flag once per item
    - ``as_json`` → ``--json`` (CLI dest name differs from the flag)
    - other keys → ``--{key}`` with underscores replaced by dashes
    """
    kwargs = normalize_cost_arguments(prefix, kwargs)
    overrides = {**_FLAG_OVERRIDES, **(flag_overrides or {})}
    argv = [str(part) for part in prefix]
    for key, value in kwargs.items():
        if value is None or value == "":
            continue
        flag = overrides.get(key, f"--{key.replace('_', '-')}")
        if isinstance(value, bool):
            if value:
                argv.append(flag)
            continue
        if isinstance(value, (list, tuple)):
            for item in value:
                if item is None or item == "":
                    continue
                argv.extend([flag, str(item)])
            continue
        argv.extend([flag, str(value)])
    return argv


def normalize_cost_arguments(prefix, kwargs):
    """Serialize only declared metadata objects, never arbitrary bridge values."""
    from avo.costs_cli import STRUCTURED_REQUESTS

    result = dict(kwargs)
    operation = tuple(prefix)
    if operation in {("pipeline", "run"), ("pipeline", "resume")}:
        if result.get("cost_context") is not None:
            result["cost_context"] = _cost_json("context", result["cost_context"])
    elif (
        len(operation) == 2
        and operation[0] == "costs"
        and operation[1] in STRUCTURED_REQUESTS
    ):
        _normalize_cost_payload(operation[1], result)
    return result


def _normalize_cost_payload(operation, result):
    from avo.costs_cli import STRUCTURED_REQUESTS

    field, schema = STRUCTURED_REQUESTS[operation]
    if operation == "report-manual" and result.get(field) is None:
        result.pop(field, None)
        return
    if field in result:
        result["payload_json"] = _cost_json(schema, result.pop(field))


def _cost_json(kind, value):
    from avo.cost_participation import validate_context_descriptor
    from avo.cost_store import CostError, validate

    if not isinstance(value, Mapping):
        raise CostError("cost metadata must be a structured object, not a client path")
    try:
        raw = json.dumps(value, allow_nan=False, sort_keys=True)
    except (TypeError, ValueError) as exc:
        raise CostError("invalid structured cost metadata") from exc
    if len(raw.encode()) > 32 * 1024 * 1024:
        raise CostError("cost input exceeds 32 MiB")
    if kind == "context":
        validate_context_descriptor(value)
    elif kind == "estimate-request":
        from avo.cost_estimates import validate_estimate_request

        validate_estimate_request(value, allow_input_path=False)
    else:
        validate(kind, value)
    return raw


def run_cli(argv: list[str]) -> BridgeResult:
    """Invoke ``avo.cli.main(argv)`` in-process with stdout/stderr capture.

    Args:
        argv: CLI argv without the program name (same shape as unit tests use).

    Returns:
        BridgeResult with exit code, captured streams, and optional parsed JSON.
    """
    from avo.cli import main

    out_buf = StringIO()
    err_buf = StringIO()
    exit_code = 0
    with redirect_stdout(out_buf), redirect_stderr(err_buf):
        try:
            result = main(list(argv))
            if result is None:
                exit_code = 0
            else:
                exit_code = int(result)
        except SystemExit as exc:
            code = exc.code
            if code is None:
                exit_code = 0
            elif isinstance(code, int):
                exit_code = code
            else:
                exit_code = 1
                err_buf.write(str(code))
        except Exception as exc:
            exit_code = 1
            err_buf.write(f"{type(exc).__name__}: {exc}")

    stdout = out_buf.getvalue()
    stderr = err_buf.getvalue()
    return BridgeResult(
        ok=exit_code == 0,
        exit_code=exit_code,
        stdout=stdout,
        stderr=stderr,
        parsed_json=_try_parse_json(stdout),
    )


def strip_mrtr_kwargs(kwargs: Mapping[str, Any]) -> dict[str, Any]:
    """Drop MRTR / Context keys so they cannot become CLI flags."""
    return {k: v for k, v in kwargs.items() if k not in _MRTR_KWARG_NAMES}


def run_bridged(
    prefix: Sequence[str],
    kwargs: Mapping[str, Any],
    *,
    flag_overrides: Mapping[str, str] | None = None,
) -> BridgeResult:
    """Build argv from *prefix* + *kwargs* and invoke ``run_cli``.

    Strips MRTR fields defensively so a gated-tool retry cannot leak
    ``requestState`` / ``inputResponses`` into argparse argv.
    """
    safe = strip_mrtr_kwargs(kwargs)
    from avo.cost_store import CostError

    try:
        argv = kwargs_to_argv(prefix, safe, flag_overrides=flag_overrides)
    except CostError as exc:
        error = json.dumps({"status": "invalid-input", "message": str(exc)})
        return BridgeResult(False, 2, "", error)
    return run_cli(argv)


def argv_from_parts(*parts: str) -> list[str]:
    """Small helper to build argv lists without accidental None entries."""
    return [str(part) for part in parts if part is not None]
