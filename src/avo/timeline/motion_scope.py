"""Exact visual metadata reuse; no media cache or approval authority."""

from bisect import bisect_left
from itertools import accumulate

from .mapping import _time
from .motion_metadata import _basis_matches, cue_item_claims, cue_item_identity

AUDIO_KINDS = {"music", "sfx", "ambience"}


def _usable_root(name, previous, actual):
    if name == "sync-map" and previous is actual is None:
        return True
    if not previous or not actual or actual.get("availability") == "unavailable":
        return False
    allowed = {"valid", "stale"} if name == "animation" else {"valid"}
    return actual.get("activeState") in allowed


def visual_roots_match(expected, current):
    if not all(
        _usable_root(name, expected.get(name), current.get(name))
        for name in ("cmap", "sync-map", "bmap", "tracks", "animation")
    ):
        return False
    roots = {name: expected.get(name) for name in ("cmap", "sync-map")}
    roots["animation"] = {
        key: expected["animation"][key] for key in ("revisionId", "sha256")
    }
    return _basis_matches(roots, current)


def _without(snapshot, keys):
    return {key: value for key, value in snapshot.items() if key not in keys}


def _visual_cues(snapshot):
    return [cue for cue in snapshot.get("cues", []) if cue["kind"] not in AUDIO_KINDS]


def _visual_metadata(snapshots):
    return {
        "animation": snapshots["animation"],
        "bmap": _without(snapshots["bmap"], {"cues", "basis"}),
        "tracks": _without(snapshots["tracks"], {"audioTracks", "basis"}),
    }


def _timed_item_ids(proposal, cues):
    claims = cue_item_claims(proposal.get("items", []))
    timed, ambiguous = set(), set()
    for cue in cues:
        identity, conflicts = cue_item_identity(cue, claims)
        if conflicts:
            ambiguous.update({identity, *conflicts})
        else:
            timed.add(identity)
    return timed - ambiguous


def _plain_text_metadata(cue):
    content = cue.get("contentRef") or {}
    if (
        cue["kind"] != "text"
        or not isinstance(content.get("text"), str)
        or set(content) - {"text", "itemId"}
        or cue.get("componentRef")
        or cue.get("assetRef")
        or cue.get("audio")
    ):
        return None
    return (
        _without(cue, {"start", "end", "contentRef"}),
        content.get("itemId"),
    )


def _cue_span(cue):
    start, end = cue["start"], cue["end"]
    if start["domain"] != "cmap-output" or end["domain"] != "cmap-output":
        raise ValueError("Local visual reuse requires canonical program timing")
    first, last = _time(start), _time(end)
    if not 0 <= first < last:
        raise ValueError("Local visual reuse requires a nonempty cue interval")
    return first, last


def _changed_text_cues(original, current):
    identifiers = [cue["cueId"] for cue in original]
    if len(set(identifiers)) != len(identifiers) or identifiers != [
        cue["cueId"] for cue in current
    ]:
        return None
    changed = []
    for before, after in zip(original, current, strict=True):
        if before == after:
            continue
        stable = _plain_text_metadata(before)
        if stable is None or stable != _plain_text_metadata(after):
            return None
        changed.extend((before, after))
    return changed


def _affected_items(proposal, current, changed):
    claims = cue_item_claims(proposal.get("items", []))
    affected = {cue_item_identity(cue, claims)[0] for cue in changed}
    spans = sorted(_cue_span(cue) for cue in changed)
    starts = [first for first, _ in spans]
    latest_ends = list(accumulate((last for _, last in spans), max))
    for cue in current:
        first, last = _cue_span(cue)
        previous = bisect_left(starts, last) - 1
        if previous >= 0 and latest_ends[previous] > first:
            affected.add(cue_item_identity(cue, claims)[0])
    return affected


def unchanged_visual_items(proposal, original, current):
    """Retain applied direction outside qualified local plain-text edits."""
    if _visual_metadata(original) != _visual_metadata(current):
        return []
    cues = _visual_cues(current["bmap"])
    timed = _timed_item_ids(proposal, cues)
    changed = _changed_text_cues(_visual_cues(original["bmap"]), cues)
    if changed is None:
        return []
    if changed:
        timed -= _affected_items(proposal, cues, changed)
    return [
        item["itemId"]
        for item in proposal.get("items", [])
        if item.get("disposition") == "applied" and item["itemId"] in timed
    ]
