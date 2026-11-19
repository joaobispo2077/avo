"""Compare base, current and returned editor facts without applying an edit."""

from collections import defaultdict

FIELDS = (
    "start",
    "end",
    "in",
    "out",
    "enabled",
    "sourceTrack",
    "lane",
    "trackEnabled",
    "outputChannel",
    "markers",
)
OPTIONAL_FIELDS = ("gainDb", "camera", "fade", "alpha")


def _source_identity(model, file_id):
    source = model["sources"].get(file_id)
    if source is None:
        return None
    digest = source.get("sha256")
    return ("sha256", digest) if digest else ("local-path", str(source["locator"]))


def _rows(model):
    for lane in model["tracks"]:
        for clip in lane["clips"]:
            yield {
                **clip,
                "source": _source_identity(model, clip["fileId"]),
                "lane": [lane["kind"], lane["index"]],
                "trackEnabled": lane["enabled"],
                "outputChannel": lane["outputChannel"],
            }


def _signature(row):
    return row["source"], tuple(row["lane"]), row["sourceTrack"], row["in"], row["out"]


def _index(model):
    by_id, by_source = defaultdict(list), defaultdict(list)
    for row in _rows(model):
        if row.get("id"):
            by_id[row["id"]].append(row)
        if row["source"] is not None:
            by_source[_signature(row)].append(row)
    return {"ids": by_id, "source": by_source}


def _by_exact_identity(index, base):
    matches = index["ids"].get(base.get("id"), [])
    if not matches:
        return None, None
    if len(matches) != 1 or matches[0]["source"] != base["source"]:
        return None, "ambiguous-id-or-source"
    return matches[0], "exact"


def _match_return(base, indexes):
    returned = indexes["returned"]
    row, state = _by_exact_identity(returned, base)
    if state is not None:
        return row, state
    signature = _signature(base)
    candidates = returned["source"].get(signature, [])
    if len(indexes["base"]["source"].get(signature, [])) != 1 or len(candidates) != 1:
        return None, "missing-or-repeated-original"
    (candidate,) = candidates
    if candidate.get("id") in indexes["base"]["ids"]:
        return None, "identity-belongs-to-another-occurrence"
    return candidate, "suggested"


def _classify(base, current, returned):
    if current == returned:
        return None
    if returned == base:
        return "preserved"
    if current == base:
        return "proposals"
    return "conflicts"


def _compare_fields(result, identity, confidence, baseline, current, returned, fields):
    for field in fields:
        values = (baseline.get(field), current.get(field), returned.get(field))
        disposition = _classify(*values)
        if disposition is not None:
            result[disposition].append(
                {
                    "id": identity,
                    "field": field,
                    "identity": confidence,
                    "base": values[0],
                    "current": values[1],
                    "returned": values[2],
                }
            )


def _occurrence_match(baseline, indexes):
    identity = baseline.get("id")
    if not identity or len(indexes["base"]["ids"].get(identity, [])) != 1:
        return None, None, "ambiguous-base-occurrence"
    current, current_state = _by_exact_identity(indexes["current"], baseline)
    if current is None:
        return None, None, current_state or "current-occurrence-unavailable"
    returned, strength = _match_return(baseline, indexes)
    return current, returned, strength


def _row_issue(baseline, current, returned):
    if any(
        row.get("rangeStatus") != "observed" for row in (baseline, current, returned)
    ):
        return "unmeasured-occurrence-boundaries"
    if len({row.get("rate") for row in (baseline, current, returned)}) > 1:
        return "source-clock-changed"
    return None


def _compare_occurrence(result, baseline, indexes):
    identity = baseline.get("id")
    current, returned, strength = _occurrence_match(baseline, indexes)
    issue = strength if returned is None else _row_issue(baseline, current, returned)
    if issue:
        result["unresolved"].append({"id": identity, "reason": issue})
        return
    optional = tuple(
        field
        for field in OPTIONAL_FIELDS
        if all(field in row for row in (baseline, current, returned))
    )
    _compare_fields(
        result, identity, strength, baseline, current, returned, FIELDS + optional
    )


def compare_editor_feedback(baseline, current, returned):
    """Return independent field proposals, explicit conflicts and unsupported finishing."""
    result = {key: [] for key in ("proposals", "conflicts", "preserved", "unresolved")}
    result["external"] = dict(returned.get("unknown", {}))
    if (
        len(
            {
                (row.get("rate"), row.get("originFrame"))
                for row in (baseline, current, returned)
            }
        )
        != 1
    ):
        result["unresolved"].append(
            {"id": "sequence", "reason": "sequence-clock-changed"}
        )
        return result
    indexes = {
        key: _index(value)
        for key, value in (
            ("base", baseline),
            ("current", current),
            ("returned", returned),
        )
    }
    for row in _rows(baseline):
        _compare_occurrence(result, row, indexes)
    _compare_fields(
        result, "sequence", "exact", baseline, current, returned, ("markers",)
    )
    return result
