"""Explicit local estimates; no inference, downloads, account access or content storage."""

from __future__ import annotations

import json
from copy import deepcopy
from hashlib import sha256
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from avo.cost_store import CostError, validate
from avo.timeline.contracts import canonical_json_bytes, content_hash


class _Unavailable(ValueError):
    """A safe prerequisite code, never an external exception or source contents."""


def _tokenizer_version():
    try:
        return version("tokenizers")
    except PackageNotFoundError:
        return None


def _read_local(path, limit):
    try:
        with Path(path).expanduser().open("rb") as stream:
            raw = stream.read(limit + 1)
    except OSError as exc:
        raise _Unavailable("local-input-unavailable") from exc
    if len(raw) > limit:
        raise _Unavailable("local-input-size-limit")
    return raw


def validate_estimate_request(request, *, allow_input_path=True):
    validate("estimate-request", request)
    inputs = request["inputs"]
    if not allow_input_path and any(
        key in inputs for key in ("inputPath", "assetsPath", "mappingPath")
    ):
        raise CostError("local estimate paths are unavailable through this transport")
    if any(
        not item.strip() for item in request["limitations"] + request["assumptions"]
    ):
        raise CostError(
            "estimate assumptions and limitations must be meaningful metadata"
        )
    if request["method"] == "manual-range":
        _validate_manual_range(inputs)


def _validate_manual_range(inputs):
    if not inputs["basis"].strip():
        raise CostError("manual estimate requires a stated basis")
    if any(value["minimum"] > value["maximum"] for value in inputs["ranges"].values()):
        raise CostError("manual estimate range minimum exceeds maximum")


def _estimate_result(store, record=None, *, replayed=False, missing=()):
    result = {
        "schemaVersion": "2.0.0",
        "status": "unavailable" if missing else "ok",
        "accountingVideoId": store.identity()["accountingVideoId"],
        "missingPrerequisites": list(missing),
    }
    if record:
        result.update(estimateId=record["estimateId"], replayed=replayed)
    return result


def _replay_estimate(store, request, records):
    record = next(
        (item for item in records if item["operationId"] == request["operationId"]),
        None,
    )
    if record is None:
        return None
    if record.get("requestDigest") != content_hash(request):
        raise CostError(
            "cost estimate operation replay conflicts with accepted content"
        )
    _verify_replay_input(request, record)
    return _estimate_result(store, record, replayed=True)


def _verify_replay_input(request, record):
    path = request["inputs"].get("inputPath")
    if not path:
        return
    try:
        raw = _read_local(path, 32 * 1024 * 1024)
    except _Unavailable as exc:
        if str(exc) == "local-input-size-limit":
            raise CostError(
                "cost estimate operation replay input exceeds its accepted bound"
            ) from exc
        return
    if sha256(raw).hexdigest() != record["inputManifest"]["contentDigest"]:
        raise CostError("cost estimate operation replay input has changed")


def _manifest(
    raw,
    *,
    model=None,
    encoding=None,
    tokenizer_version=None,
    assets_digest=None,
    items=1,
):
    return {
        "contentDigest": sha256(raw).hexdigest(),
        "byteCount": len(raw),
        "itemCount": items,
        "model": model,
        "encoding": encoding,
        "tokenizerVersion": tokenizer_version,
        "assetsDigest": assets_digest,
    }


def _manual_result(inputs):
    raw = canonical_json_bytes(inputs)
    return {
        "methodVersion": "manual-range/1",
        "inputManifest": _manifest(raw, items=len(inputs["ranges"])),
        "tokens": None,
        "ranges": deepcopy(inputs["ranges"]),
        "manualBasis": inputs["basis"],
    }


def _mapping_fields(inputs):
    return {
        key: inputs[key]
        for key in (
            "model",
            "encoding",
            "tokenizer",
            "tokenizerVersion",
            "assetsDigest",
        )
    }


def _offline_assets(inputs):
    if inputs["tokenizer"] != "tokenizers-json":
        raise _Unavailable("unsupported-offline-tokenizer")
    installed = _tokenizer_version()
    if not installed or installed != inputs["tokenizerVersion"]:
        raise _Unavailable("tokenizer-version-unavailable")
    if not inputs.get("assetsPath") or not inputs.get("mappingPath"):
        raise _Unavailable("explicit-local-tokenizer-assets-and-mapping-required")
    raw = _read_local(inputs["assetsPath"], 64 * 1024 * 1024)
    if sha256(raw).hexdigest() != inputs["assetsDigest"]:
        raise _Unavailable("tokenizer-assets-digest-mismatch")
    _verify_mapping(inputs)
    return raw


def _verify_mapping(inputs):
    try:
        mapping = json.loads(_read_local(inputs["mappingPath"], 1024 * 1024))
    except (ValueError, UnicodeError) as exc:
        raise _Unavailable("tokenizer-mapping-unavailable") from exc
    if mapping != {"schemaVersion": "1.0.0", **_mapping_fields(inputs)}:
        raise _Unavailable("tokenizer-model-mapping-mismatch")


def _visible_content(inputs):
    if "content" in inputs:
        try:
            raw = inputs["content"].encode("utf-8")
        except UnicodeError as exc:
            raise CostError("invalid supplied text encoding") from exc
    else:
        raw = _read_local(inputs["inputPath"], 32 * 1024 * 1024)
    if len(raw) > 32 * 1024 * 1024:
        raise CostError("estimate input exceeds 32 MiB")
    try:
        return raw, raw.decode("utf-8")
    except UnicodeError as exc:
        raise _Unavailable("supported-utf8-text-required") from exc


def _tokenizer_result(inputs):
    assets = _offline_assets(inputs)
    raw, text = _visible_content(inputs)
    try:
        from tokenizers import Tokenizer

        tokenizer = Tokenizer.from_str(assets.decode("utf-8"))
        count = len(tokenizer.encode(text, add_special_tokens=False).ids)
    except Exception as exc:
        raise _Unavailable("offline-tokenizer-unavailable") from exc
    return {
        "methodVersion": "tokenizers-json/" + inputs["tokenizerVersion"],
        "inputManifest": _manifest(
            raw,
            model=inputs["model"],
            encoding=inputs["encoding"],
            tokenizer_version=inputs["tokenizerVersion"],
            assets_digest=inputs["assetsDigest"],
        ),
        "tokens": {"input": count},
        "ranges": None,
    }


def _estimate_owner(request, view):
    if request["participationId"] not in {
        fact["participationId"] for fact in view["participations"]
    }:
        raise CostError("cost estimate references an unknown participation")


def _estimate_record(store, request, value, view):
    from avo.avo_state import now_iso

    record = {
        "schemaVersion": "2.0.0",
        "accountingVideoId": store.identity()["accountingVideoId"],
        "operationId": request["operationId"],
        "participationId": request["participationId"],
        "scope": deepcopy(request["scope"]),
        "method": request["method"],
        **value,
        "assumptions": deepcopy(request["assumptions"]),
        "limitations": deepcopy(request["limitations"]),
        "provenance": deepcopy(request["provenance"]),
        "createdAt": now_iso(),
        "requestDigest": content_hash(request),
        "priceScheduleIds": sorted(content_hash(price) for price in view["prices"]),
    }
    if "pricingContext" in request:
        record["pricingContext"] = deepcopy(request["pricingContext"])
    return record


def _publish_estimate(store, request, record):
    try:
        saved = store.append_record("estimates", record)
    except CostError:
        replay = _replay_estimate(store, request, store.capture()["estimates"])
        if replay:
            store.amend_if_closed()
            return replay
        raise
    return _estimate_result(store, saved)


def create_estimate(store, request, *, allow_input_path=True):
    """Count only explicitly supplied material or retain a justified manual range."""
    validate_estimate_request(request, allow_input_path=allow_input_path)
    if not store.identity():
        raise CostError("initialize accounting before creating an estimate")
    view = store.capture()
    replay = _replay_estimate(store, request, view["estimates"])
    if replay:
        store.amend_if_closed()
        return replay
    _estimate_owner(request, view)
    try:
        value = (
            _manual_result(request["inputs"])
            if request["method"] == "manual-range"
            else _tokenizer_result(request["inputs"])
        )
    except _Unavailable as exc:
        return _estimate_result(store, missing=[str(exc)])
    return _publish_estimate(
        store, request, _estimate_record(store, request, value, view)
    )
