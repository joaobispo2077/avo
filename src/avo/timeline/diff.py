"""Stable-ID operations shared by canonical timeline collections."""

from itertools import chain
from typing import Any


def _item_changes(before, after):
    for stable_id, item in before.items():
        if stable_id not in after:
            yield "remove", stable_id, {"before": item}
    for stable_id, item in after.items():
        if stable_id not in before:
            yield "add", stable_id, {"after": item}
        elif before[stable_id] != item:
            yield "replace", stable_id, {"before": before[stable_id], "after": item}


def _order_changes(before, after):
    for stable_id in set(before) & set(after):
        first, last = before.index(stable_id), after.index(stable_id)
        if first != last:
            yield "move", stable_id, {"fromOrder": first, "toOrder": last}


def stable_id_diff(
    parent: dict[str, Any] | None,
    child: dict[str, Any],
    reason: str,
    *,
    collection: str,
    id_key: str,
    actor_intent: str,
) -> list[dict[str, Any]]:
    before = (parent or {}).get(collection) or []
    after = child.get(collection) or []
    before_by = {item[id_key]: item for item in before}
    after_by = {item[id_key]: item for item in after}
    changes = chain(
        _item_changes(before_by, after_by),
        _order_changes(
            [item[id_key] for item in before], [item[id_key] for item in after]
        ),
    )
    return [
        {
            "opId": f"diff-{ordinal:04d}",
            "op": op,
            "target": {"collection": collection, "stableId": stable_id},
            "reason": reason,
            "actorIntent": actor_intent,
            "affectedTimeRanges": [],
            **values,
        }
        for ordinal, (op, stable_id, values) in enumerate(changes, 1)
    ]
