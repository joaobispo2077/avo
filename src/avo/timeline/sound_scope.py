"""Pure ownership checks for explicitly selected sound chunks, without trimming context."""

from copy import deepcopy
from fractions import Fraction

from .contracts import content_hash
from .craft_scope import validate_scope_request
from .sound_choices import _sound_document, _unique_sound_ids
from .sound_fitting import SoundPlanningError


def _rate(clock):
    value = clock["frameRate"]
    return Fraction(value["num"], value["den"])


def _same_clock(left, right):
    return (
        _rate(left) == _rate(right)
        and left["programEndFrame"] == right["programEndFrame"]
    )


def _value(frame):
    return {"num": frame.numerator, "den": frame.denominator}


def _owner(scope, frame):
    owner = next(
        (
            c["chunkId"]
            for c in scope["chunks"]
            if c["startFrame"] <= frame < c["endFrameExclusive"]
        ),
        None,
    )
    if owner is None:
        raise SoundPlanningError(
            "Sound canonical start is outside the production clock"
        )
    return owner


def _interval(choice, scope, clock):
    if choice is None or choice["fit"]["status"] == "silence":
        return None
    fit = choice["fit"]
    if fit["status"] != "fit":
        raise SoundPlanningError("Unresolved sound cannot acquire production ownership")
    if not _same_clock(fit["clock"], clock):
        raise SoundPlanningError(
            "Previous sound clock cannot map to selected chunks; use explicit unscoped removal"
        )
    first = Fraction(
        fit["event"]["scheduledAudioStartSample"], fit["clock"]["sampleRate"]
    ) * _rate(clock)
    last = Fraction(fit["scheduledAudioEndSample"], fit["clock"]["sampleRate"]) * _rate(
        clock
    )
    if first < 0 or last <= first:
        raise SoundPlanningError(
            "Sound production interval must be positive and nonempty"
        )
    return {
        "startFrame": _value(first),
        "endFrame": _value(last),
        "ownerChunkId": _owner(scope, first),
    }


def _fraction(value):
    return Fraction(value["num"], value["den"])


def _consumers(scope, intervals, owner):
    if not intervals:
        return [owner]
    return [
        c["chunkId"]
        for c in scope["chunks"]
        if c["chunkId"] in scope["selectedChunkIds"]
        and any(
            _fraction(i["startFrame"]) < c["endFrameExclusive"]
            and c["startFrame"] < _fraction(i["endFrame"])
            for i in intervals
        )
    ]


def _contribution(choice, previous, scope, clock):
    current, prior = _interval(choice, scope, clock), _interval(previous, scope, clock)
    active = current or prior
    first = (
        _fraction(active["startFrame"])
        if active
        else Fraction(choice["fit"]["opportunity"]["programFrame"])
    )
    owner = _owner(scope, first)
    if owner not in scope["selectedChunkIds"]:
        raise SoundPlanningError("Sound production requires its canonical start chunk")
    if prior and prior["ownerChunkId"] not in scope["selectedChunkIds"]:
        raise SoundPlanningError(
            "Sound revision also requires its previous canonical start chunk"
        )
    return {
        "eventId": choice["eventId"],
        "itemId": choice["itemId"],
        "ownerChunkId": owner,
        "canonicalStartFrame": _value(first),
        "consumerChunkIds": _consumers(
            scope, [i for i in (current, prior) if i], owner
        ),
        "current": current,
        "previous": prior,
    }


def project_sound_scope(request, clock, choices, previous):
    if "productionScope" not in request:
        return None
    try:
        scope = request["productionScope"]
        validate_scope_request(scope)
        if not _same_clock(scope["clock"], clock):
            raise SoundPlanningError(
                "Production scope differs from the frozen sound clock"
            )
        choices = _sound_document(choices, "frozenChoices")
        previous = _sound_document(list(previous), "frozenChoices")
        _unique_sound_ids(choices, "eventId")
        before = _unique_sound_ids(previous, "eventId")
        result = {
            "contractVersion": "1.0.0",
            "requestHash": content_hash(scope),
            "request": deepcopy(scope),
            "basisHeads": deepcopy(request["expectedBasis"]),
            "contributions": [
                _contribution(c, before.get(c["eventId"]), scope, clock)
                for c in choices
            ],
            "approval": "not-granted",
        }
        result["scopeHash"] = content_hash(result)
        return _sound_document(result, "productionScopePlan")
    except (ValueError, TypeError, KeyError, ZeroDivisionError) as error:
        raise SoundPlanningError(str(error)) from error


def _review_intervals(contributions, unchanged_ids):
    return [
        (_fraction(interval["startFrame"]), _fraction(interval["endFrame"]))
        for row in contributions
        if row["eventId"] not in unchanged_ids
        for interval in (row["current"], row["previous"])
        if interval is not None
    ]


def sound_review_scope(projection, *, unchanged_ids=frozenset()):
    """Find chunks intersecting the previous or current audible contribution."""
    request = projection["request"]
    intervals = _review_intervals(projection["contributions"], unchanged_ids)
    affected = [
        chunk["chunkId"]
        for chunk in request["chunks"]
        if any(
            first < chunk["endFrameExclusive"] and chunk["startFrame"] < end
            for first, end in intervals
        )
    ]
    selected = set(request["selectedChunkIds"])
    return {
        "affectedChunkIds": affected,
        "outsideProductionChunkIds": [key for key in affected if key not in selected],
        "approval": "not-granted",
    }


def require_sound_scope_parent(request, snapshots):
    if "productionScope" not in request:
        return
    head = request["expectedBasis"]["bmap"]
    if head is None:
        return
    basis, current = (
        snapshots["bmap"].get("basis") or {},
        request["expectedBasis"]["cmap"],
    )
    if head.get("activeState") != "valid" or any(
        basis.get(k) != current[k] for k in ("revisionId", "sha256")
    ):
        raise SoundPlanningError(
            "Scoped sound production requires a valid BMap on the exact current cut"
        )
