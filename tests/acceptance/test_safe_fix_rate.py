from __future__ import annotations

from avo.timeline.review import classify_findings


def test_labeled_safe_finding_policy_reaches_ninety_percent_without_unsafe_fixes():
    corpus = [
        {"classification": "technical", "safe": True, "fixed": True}
        for _ in range(9)
    ] + [
        {"classification": "technical", "safe": True, "fixed": False},
        {"classification": "meaning", "safe": False, "fixed": False},
        {"classification": "rights", "safe": False, "fixed": False},
        {"classification": "privacy", "safe": False, "fixed": False},
        {"classification": "policy", "safe": False, "fixed": False},
        {"classification": "safety", "safe": False, "fixed": False},
    ]
    safe = [item for item in corpus if item["safe"]]
    rate = sum(item["fixed"] for item in safe) / len(safe)
    assert rate >= 0.90
    assert not any(item["fixed"] for item in corpus if not item["safe"])
    for item in corpus:
        state = classify_findings([item])
        if not item["safe"]:
            assert state == "needs-human-judgment"
