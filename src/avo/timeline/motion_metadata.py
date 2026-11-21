"""Shared bounded JSON motion metadata; no authoring, persistence or media imports."""

MAX_DOCUMENT_BYTES = 4 * 1024 * 1024
LIFECYCLE = ("preEntry", "entrance", "hold", "payoff", "exit")


METADATA_LIMITS = {
    "nodes": 200000,
    "depth": 32,
    "items": 20000,
    "text": 65536,
    "characters": MAX_DOCUMENT_BYTES,
}


class MotionReviewError(ValueError):
    pass


def cue_item_claims(items):
    claims = {}
    for item in items:
        if isinstance(item.get("cueId"), str) and item["cueId"]:
            claims.setdefault(item["cueId"], set()).add(item["itemId"])
    return claims


def cue_item_identity(cue, claims):
    explicit = (cue.get("contentRef") or {}).get("itemId")
    if explicit is not None and not isinstance(explicit, str):
        raise MotionReviewError("Canonical item identity must be a string")
    proposed = claims.get(cue["cueId"], set())
    if explicit:
        return explicit, sorted(proposed - {explicit})
    if len(proposed) == 1:
        return next(iter(proposed)), []
    return cue["cueId"], sorted(proposed)


def _basis_matches(expected, actual):
    for name, reference in expected.items():
        current = actual.get(name)
        if reference is None or current is None:
            if reference != current:
                return False
        elif any(current.get(key) != value for key, value in reference.items()):
            return False
    return True


def _budget_text(value, limits, statistics):
    if not isinstance(value, str) or len(value) > limits["text"]:
        raise MotionReviewError("Metadata text budget exceeded")
    statistics["characters"] += len(value)
    if statistics["characters"] > limits["characters"]:
        raise MotionReviewError("Metadata character budget exceeded")


def _budget_children(value, limits, statistics):
    if isinstance(value, str):
        _budget_text(value, limits, statistics)
        return ()
    if isinstance(value, dict):
        if len(value) > limits["items"]:
            raise MotionReviewError("Metadata object budget exceeded")
        for key in value:
            _budget_text(key, limits, statistics)
        return value.values()
    if isinstance(value, list):
        if len(value) > limits["items"]:
            raise MotionReviewError("Metadata array budget exceeded")
        return value
    if value is not None and not isinstance(value, (int, float, bool)):
        raise MotionReviewError("Metadata must contain JSON values")
    return ()


def _check_budget(value, limits):
    stack, nodes, statistics = [(value, 0)], 0, {"characters": 0}
    while stack:
        current, depth = stack.pop()
        nodes += 1
        if nodes > limits["nodes"] or depth > limits["depth"]:
            raise MotionReviewError("Metadata node/depth budget exceeded")
        stack.extend(
            (child, depth + 1)
            for child in _budget_children(current, limits, statistics)
        )
