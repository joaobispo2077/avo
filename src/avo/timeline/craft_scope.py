"""Pure canonical-start ownership and untrimmed context for selected production."""

from copy import deepcopy
from fractions import Fraction

from .contracts import content_hash, validate_document
from .motion_metadata import METADATA_LIMITS, _check_budget

SCHEMA = "avo.editing-craft-run.schema.json#/$defs/productionScope"


class CraftScopeError(ValueError):
    pass


def validate_scope_request(request):
    _check_budget(request, METADATA_LIMITS)
    validate_document(request, SCHEMA)
    previous, identities = 0, set()
    for chunk in request["chunks"]:
        if chunk["chunkId"] in identities:
            raise CraftScopeError("Production chunk identities must be unique")
        identities.add(chunk["chunkId"])
        if chunk["startFrame"] != previous or chunk["endFrameExclusive"] <= previous:
            raise CraftScopeError(
                "Production chunks must form an ordered complete partition"
            )
        previous = chunk["endFrameExclusive"]
    if previous != request["clock"]["programEndFrame"]:
        raise CraftScopeError(
            "Production partition must retain the complete program extent"
        )
    if set(request["selectedChunkIds"]) - identities:
        raise CraftScopeError(
            "Selected production chunk is not in the original partition"
        )


def _frame(value, rate):
    validate_document(value, "avo.timeline-common.schema.json#/$defs/timeValue")
    if value["domain"] != "cmap-output":
        raise CraftScopeError("Production ownership needs canonical output timing")
    base = value["timebase"]
    return Fraction(value["ticks"] * base["num"], base["den"]) * rate


def _intervals(parts, rate, cue_ids):
    result = []
    for part in parts:
        if part["cueId"] in cue_ids:
            raise CraftScopeError(
                "Canonical cue cannot belong to two production contributions"
            )
        cue_ids.add(part["cueId"])
        first, last = (_frame(part["timing"][key], rate) for key in ("start", "end"))
        if first < 0 or first >= last:
            raise CraftScopeError(
                "Canonical production interval must be positive and nonempty"
            )
        result.append((first, last))
    return result


def _consumers(intervals, chunks, selected):
    return [
        chunk["chunkId"]
        for chunk in chunks
        if chunk["chunkId"] in selected
        and any(
            first < chunk["endFrameExclusive"] and chunk["startFrame"] < last
            for first, last in intervals
        )
    ]


def _classify_item(item, request, rate, cue_ids):
    parts = item.get("parts", [])
    if item.get("identityConflicts") or not parts:
        return "unresolvedItemIds", item["itemId"]
    intervals = _intervals(parts, rate, cue_ids)
    first = min(start for start, _ in intervals)
    chunks, selected = request["chunks"], set(request["selectedChunkIds"])
    owner = next(
        (
            chunk["chunkId"]
            for chunk in chunks
            if chunk["startFrame"] <= first < chunk["endFrameExclusive"]
        ),
        None,
    )
    if owner is None:
        return "unresolvedItemIds", item["itemId"]
    consumers = _consumers(intervals, chunks, selected)
    if not consumers:
        return "outsideItemIds", item["itemId"]
    return "production" if owner in selected else "context", {
        "itemId": item["itemId"],
        "ownerChunkId": owner,
        "canonicalStartFrame": {"num": first.numerator, "den": first.denominator},
        "consumerChunkIds": consumers,
        "parts": deepcopy(parts),
    }


def build_scope_plan(items, request, *, basis_heads):
    """Classify once; original parts and absolute timing remain available to every consumer."""
    try:
        validate_scope_request(request)
        _check_budget(items, METADATA_LIMITS)
        validate_document(
            basis_heads, "avo.motion-review.schema.json#/properties/basisHeads"
        )
        if not isinstance(items, list) or len(items) > 500:
            raise CraftScopeError(
                "Production planning requires at most 500 current motion items"
            )
        identities = [item["itemId"] for item in items]
        if len(identities) != len(set(identities)):
            raise CraftScopeError("Production item identities must be unique")
        rate = request["clock"]["frameRate"]
        rate = Fraction(rate["num"], rate["den"])
        result = {
            "contractVersion": "1.0.0",
            "requestHash": content_hash(request),
            "request": deepcopy(request),
            "basisHeads": deepcopy(basis_heads),
            "production": [],
            "context": [],
            "outsideItemIds": [],
            "unresolvedItemIds": [],
            "approval": "not-granted",
        }
        cue_ids = set()
        for item in items:
            group, row = _classify_item(item, request, rate, cue_ids)
            result[group].append(row)
        result["complete"] = not result["unresolvedItemIds"]
        result["scopeHash"] = content_hash(result)
        validate_document(
            result, "avo.editing-craft-run.schema.json#/$defs/productionScopePlan"
        )
        return result
    except (ValueError, KeyError, TypeError, ZeroDivisionError) as error:
        if isinstance(error, CraftScopeError):
            raise
        raise CraftScopeError(str(error)) from error
