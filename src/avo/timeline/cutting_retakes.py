"""Complete-take grouping and evidence-based selection without word assembly."""

import math
import re
import unicodedata
from copy import deepcopy
from fractions import Fraction

from .contracts import ContractError
from .cutting_contracts import source_interval

_NEGATIVES = frozenset(
    ["nao", "nunca", "nem", "jamais", "not", "no", "never", "neither", "without", "sem"]
)
_QUANTIFIERS = frozenset(
    [
        "alguns",
        "algumas",
        "muitos",
        "muitas",
        "todos",
        "todas",
        "nenhum",
        "nenhuma",
        "somente",
        "apenas",
        "some",
        "many",
        "all",
        "every",
        "none",
        "only",
        "few",
        "most",
    ]
)
_NUMBERS = frozenset(
    [
        "zero",
        "um",
        "uma",
        "dois",
        "duas",
        "tres",
        "quatro",
        "cinco",
        "seis",
        "sete",
        "oito",
        "nove",
        "dez",
        "vinte",
        "trinta",
        "quarenta",
        "cinquenta",
        "sessenta",
        "setenta",
        "oitenta",
        "noventa",
        "cem",
        "mil",
        "one",
        "two",
        "three",
        "four",
        "five",
        "six",
        "seven",
        "eight",
        "nine",
        "ten",
        "twenty",
        "thirty",
        "forty",
        "fifty",
        "sixty",
        "seventy",
        "eighty",
        "ninety",
        "hundred",
        "thousand",
    ]
)


def _tokens(text: str) -> tuple[str, ...]:
    plain = unicodedata.normalize("NFKD", text.casefold())
    plain = "".join(char for char in plain if not unicodedata.combining(char))
    return tuple(re.findall(r"\w+", plain))


def _take_id(take: dict) -> str:
    return str(take.get("takeId") or take.get("unitId") or "")


def classify_take(utterance: dict) -> dict:
    categories = []
    for flag, category in (
        ("restart", "restart"),
        ("abandoned", "abandoned-attempt"),
        ("intentionalRepetition", "intentional-repetition"),
    ):
        if utterance.get(flag) is True:
            categories.append(category)
    if utterance.get("complete") is False:
        categories.append("interrupted-speech")
    if (utterance.get("speechEvidence") or {}).get("intelligible") is False:
        categories.append("unclear-delivery")
    return {
        "categories": categories or ["unknown"],
        "requiresHuman": not categories,
        "reasons": [] if categories else ["Delivery intent is not established."],
    }


def group_retakes(utterances: list[dict]) -> list[dict]:
    """Explicit or identical-text groups are search candidates, never approval."""
    groups: dict[str, list[dict]] = {}
    for utterance in utterances:
        take = deepcopy(utterance)
        take["takeId"] = _take_id(take)
        if not take["takeId"]:
            raise ValueError("take requires a stable takeId or unitId")
        identity = str(
            take.get("groupId")
            or "text:" + " ".join(_tokens(str(take.get("text") or "")))
        )
        groups.setdefault(identity, []).append(take)
    return [
        {
            "groupId": identity,
            "attempts": attempts,
            "status": "needs-review",
            "categories": sorted(
                {
                    category
                    for take in attempts
                    for category in classify_take(take)["categories"]
                }
            ),
        }
        for identity, attempts in groups.items()
    ]


def _interval(take: dict) -> tuple[str, Fraction, Fraction] | None:
    try:
        return source_interval(take.get("sourceRange") or {})
    except (ContractError, KeyError, TypeError, ValueError, ZeroDivisionError):
        return None


def _invalid_units(attempts: list[dict]) -> bool:
    intervals = [_interval(take) for take in attempts]
    if None in intervals or len({_take_id(take) for take in attempts}) != len(attempts):
        return True
    for index, left in enumerate(intervals):
        for right in intervals[index + 1 :]:
            if left[0] == right[0] and max(left[1], right[1]) < min(left[2], right[2]):
                return True
    return False


def _protected_signature(take: dict) -> tuple:
    tokens = _tokens(str(take.get("text") or ""))
    lexical = tuple(
        token
        for token in tokens
        if token in _NEGATIVES | _QUANTIFIERS | _NUMBERS
        or any(char.isdigit() for char in token)
    )
    entities = tuple(
        sorted(str(name).casefold() for name in take.get("namedEntities", []))
    )
    return lexical, entities, take.get("quotedSpeech")


def _protected_difference(attempts: list[dict], evidence: dict) -> bool:
    complete = [take for take in attempts if take.get("complete") is True]
    signatures = {_protected_signature(take) for take in complete}
    partial_difference = any(
        _partial_qualifier_difference(take, signatures)
        for take in attempts
        if take.get("complete") is not True
    )
    return (
        bool(evidence.get("protectedDifferences"))
        or len(signatures) > 1
        or partial_difference
    )


def _partial_qualifier_difference(take: dict, complete_signatures: set) -> bool:
    partial = _protected_signature(take)
    for complete in complete_signatures:
        if not set(partial[0]).issubset(complete[0]) or not set(partial[1]).issubset(
            complete[1]
        ):
            return True
        if partial[2] is not None and partial[2] != complete[2]:
            return True
    return False


def _quality(take: dict, checks: dict) -> tuple:
    values = tuple(
        _score(checks.get(key, 0))
        for key in ("intelligibility", "cadence", "visualUsability")
    )
    order = take.get("sourceOrder", _interval(take)[1])
    return *values, -float(order), _take_id(take)


def _score(value) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("quality observation must be numeric")
    if not math.isfinite(value) or not 0 <= value <= 1:
        raise ValueError("quality observation must be finite and between zero and one")
    return float(value)


def _result(action: str, attempts: list[dict], reason: str, selected=None) -> dict:
    categories = {
        category for take in attempts for category in classify_take(take)["categories"]
    }
    if action == "replace":
        categories.discard("unknown")
        categories.add("restart")
    return {
        "action": action,
        "selectedTakeId": _take_id(selected) if selected else None,
        "rejectedTakeIds": [_take_id(take) for take in attempts if take is not selected]
        if selected
        else [],
        "categories": sorted(categories),
        "reasons": [reason],
        "requiresHuman": action == "needs-review",
    }


def _review_reason(attempts: list[dict], evidence: dict) -> str | None:
    if _invalid_units(attempts):
        return "Missing, overlapping or ambiguous complete-unit source bounds."
    if evidence.get("conflict") or _protected_difference(attempts, evidence):
        return "Conflicting evidence or protected meaning differs between attempts."
    if evidence.get("semanticEquivalence") is not True:
        return "Meaning equivalence is not corroborated."
    if evidence.get("restartConfirmed") is not True:
        return "Independent evidence has not established accidental retaking."
    return None


def _eligible_candidates(attempts: list[dict], per_take: dict) -> list[dict]:
    candidates = []
    for take in attempts:
        checks = per_take.get(_take_id(take)) or {}
        eligible = all(
            (
                take.get("complete") is True,
                checks.get("acousticComplete") is True,
                checks.get("intelligible") is True,
                not checks.get("conflicting"),
                _visual_known(take, checks),
            )
        )
        if eligible:
            candidates.append(take)
    return candidates


def _visual_known(take: dict, checks: dict) -> bool:
    if take.get("visualRelevant") is False:
        return True
    value = checks.get("visualUsability")
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def select_retake(group: dict, evidence: dict) -> dict:
    attempts = group.get("attempts") or []
    intentional = evidence.get("intentionalRepetition") or any(
        take.get("intentionalRepetition") is True for take in attempts
    )
    if intentional:
        return _result(
            "keep", attempts, "Intentional repetition/self-correction remains intact."
        )
    reason = _review_reason(attempts, evidence)
    if reason:
        return _result("needs-review", attempts, reason)
    per_take = evidence.get("perTake") or {}
    candidates = _eligible_candidates(attempts, per_take)
    if not candidates:
        return _result(
            "needs-review",
            attempts,
            "No complete acoustically usable equivalent replacement exists.",
        )
    try:
        selected = max(
            candidates, key=lambda take: _quality(take, per_take[_take_id(take)])
        )
    except (ValueError, TypeError, OverflowError):
        return _result(
            "needs-review", attempts, "Quality observations are invalid or incomplete."
        )
    return _result(
        "replace",
        attempts,
        "One verified equivalent complete take selected by delivery quality.",
        selected,
    )
