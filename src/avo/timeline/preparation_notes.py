"""Inspect literal spoken note candidates from retained original transcript words."""

import re
import unicodedata
from difflib import SequenceMatcher
from itertools import islice

from .contracts import content_hash
from .cutting_contracts import source_interval
from .preparation import _interval, _source_range

TOKEN = re.compile(r"[^\W_]+(?:['’][^\W_]+)*")
QUOTE = re.compile(r'["“”«»]')
MAX_WORDS = 10_000
MAX_NOTES = 100
MAX_NOTE_CHARS = 8192


def _normalized(text):
    return " ".join(TOKEN.findall(unicodedata.normalize("NFKC", text).casefold()))


def _match_language(requested, observed):
    if not isinstance(observed, str) or not observed:
        return False
    first, second = (
        code.casefold().replace("_", "-") for code in (requested, observed)
    )
    return (
        first == second
        or first == second.split("-")[0]
        or second == first.split("-")[0]
    )


def _delimiters(policy):
    phrases = {
        key: _normalized(policy.get(field, ""))
        for key, field in (("open", "openingPhrase"), ("close", "closingPhrase"))
    }
    values = set(phrases.values())
    if len(values) != 2 or not all(
        value and 1 <= len(value.split()) <= 12 for value in values
    ):
        return None
    return phrases


def _marker_score(actual, expected):
    if actual == expected:
        return 1.0
    if len(expected) < 7 or len(actual) < 7:
        return 0.0
    if 2 * min(len(expected), len(actual)) < 0.9 * (len(actual) + len(expected)):
        return 0.0
    return SequenceMatcher(None, actual, expected, autojunk=False).ratio()


def _marker_at(tokens, index, phrases):
    ranked = []
    for kind, phrase in phrases.items():
        count = len(phrase.split())
        score = _marker_score(" ".join(tokens[index : index + count]), phrase)
        if score >= 0.9:
            ranked.append((score, count, kind))
    if not ranked:
        return None
    score, size, kind = max(ranked)
    return kind, size, score < 1 or len(ranked) > 1


def _markers(words, phrases):
    tokens = [_normalized(word["text"]) for word in words]
    next_word = 0
    for index in range(len(tokens)):
        if index < next_word:
            continue
        marker = _marker_at(tokens, index, phrases)
        if marker is not None:
            kind, count, fuzzy = marker
            next_word = index + count
            yield {"kind": kind, "start": index, "end": next_word, "fuzzy": fuzzy}


def _spans(words, phrases):
    opening, depth, issues = None, 0, set()
    for marker in _markers(words, phrases):
        if marker["kind"] == "open":
            if opening is None:
                opening, issues = marker, set()
            else:
                issues.add("nested-delimiter")
            depth += 1
        elif depth:
            depth -= 1
        else:
            continue
        if marker["fuzzy"]:
            issues.add("fuzzy-delimiter")
        if depth == 0:
            yield opening, marker, issues
            opening = None
    if opening is not None:
        yield opening, None, issues | {"missing-closure"}


def _literal(words):
    result = ""
    for word in words:
        value = word["text"]
        separator = (
            " "
            if result and not result[-1].isspace() and not value[:1].isspace()
            else ""
        )
        result += separator + value
        if len(result) > MAX_NOTE_CHARS:
            return result[:MAX_NOTE_CHARS], True
    return result.strip(), False


def _interpretation(body, targets):
    words = _normalized(body).split()
    matches = []
    for target in targets:
        prefix = _normalized(target["phrase"]).split()
        if prefix and words[: len(prefix)] == prefix:
            matches.append(target)
    if len(matches) != 1:
        return {
            "intent": body,
            "stage": None,
            "targetId": None,
            "confidence": "unresolved",
        }
    (match,) = matches
    return {
        "intent": body,
        "stage": match["stage"],
        "targetId": match["targetId"],
        "confidence": "matched-convention",
    }


def _complete_range(rows, source_range, qualified_alignment):
    if not qualified_alignment or any(not row.get("eligibleEdge") for row in rows):
        return None
    _, first, end = source_interval(source_range)
    try:
        points = [_interval(row, (first, end)) for row in rows]
    except (ValueError, KeyError, TypeError):
        return None
    if points != sorted(points) or [last for _, last in points] != sorted(
        last for _, last in points
    ):
        return None
    return _source_range((points[0][0], points[-1][1]), source_range)


def _overlaps_protection(source_range, protected):
    original, first, last = source_interval(source_range)
    for row in protected:
        source, start, end = source_interval(row)
        if original == source and max(first, start) < min(last, end):
            return True
    return False


def _note_text(words, first, body_start, body_end, end, issues):
    literal, long_literal = _literal(words[first:end])
    body, long_body = _literal(words[body_start:body_end])
    if long_literal or long_body:
        issues.add("note-exceeds-budget")
    if QUOTE.search(literal) or (first and QUOTE.search(words[first - 1]["text"])):
        issues.add("quoted-delimiter")
    return literal, body


def _note(words, span, source_range, targets, protected, qualified_alignment):
    opening, closing, issues = span
    first = opening["start"]
    end = closing["end"] if closing else len(words)
    body_end = closing["start"] if closing else end
    literal, body = _note_text(words, first, opening["end"], body_end, end, issues)
    interpretation = _interpretation(body, targets)
    if interpretation["confidence"] == "unresolved":
        issues.add("target-unresolved")
    scope = (
        _complete_range(words[first:end], source_range, qualified_alignment)
        if closing
        else None
    )
    if closing and scope is None:
        issues.add("timing-unverified")
    if scope is not None and _overlaps_protection(scope, protected):
        issues.add("protected-speech")
    identity = {"source": source_range, "words": [first, end], "literal": literal}
    return {
        "noteId": "note-" + content_hash(identity)[:24],
        "literal": literal,
        "body": body,
        "sourceRange": scope,
        "interpretation": interpretation,
        "issues": sorted(issues),
        "status": "unresolved" if issues else "candidate",
        "review": "required",
    }


def _admission(analysis, policy, targets, phrases):
    if (
        not policy.get("enabled")
        or not phrases
        or not targets
        or not policy.get("language")
    ):
        return "disabled", "convention-unselected"
    if not _match_language(policy["language"], analysis.get("language")):
        return "unavailable", "language-unverified"
    words = analysis.get("words") or []
    if not 0 < len(words) <= MAX_WORDS or not all(
        isinstance(word.get("text"), str) for word in words
    ):
        return "unavailable", "transcript-coverage-unavailable"
    return "observed", None


def detect_spoken_notes(analysis, source_range, *, policy, targets, protected=()):
    """Match configured wording without interpreting it as an instruction to act."""
    phrases = _delimiters(policy)
    status, issue = _admission(analysis, policy, targets, phrases)
    if issue:
        return {"status": status, "notes": [], "issues": [issue], "truncated": False}
    words = analysis["words"]
    qualified = (analysis.get("alignment") or {}).get("status") == "pass"
    spans = list(islice(_spans(words, phrases), MAX_NOTES + 1))
    notes = [
        _note(words, span, source_range, targets, protected, qualified)
        for span in spans[:MAX_NOTES]
    ]
    return {
        "status": status,
        "notes": notes,
        "issues": [],
        "truncated": len(spans) > MAX_NOTES,
    }
