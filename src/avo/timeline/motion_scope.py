"""Exact visual metadata reuse; no media cache or approval authority."""

from .motion_metadata import _basis_matches

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
        "cues": _visual_cues(snapshots["bmap"]),
        "tracks": _without(snapshots["tracks"], {"audioTracks", "basis"}),
    }


def unchanged_visual_items(proposal, original, current):
    """Retain applied direction only when the complete visual assembly is unchanged."""
    if _visual_metadata(original) != _visual_metadata(current):
        return []
    cues = _visual_cues(current["bmap"])
    timed = {
        (cue.get("contentRef") or {}).get("itemId") or cue["cueId"] for cue in cues
    }
    return [
        item["itemId"]
        for item in proposal.get("items", [])
        if item.get("disposition") == "applied" and item["itemId"] in timed
    ]
