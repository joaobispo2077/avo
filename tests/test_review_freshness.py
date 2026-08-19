from __future__ import annotations

from avo.timeline.review import evidence_is_fresh, stale_evidence


def item(kind, candidate, dependencies, profile):
    return {
        "kind": kind,
        "candidateHash": candidate,
        "candidateIdentityHash": "1" * 64,
        "dependencyLockSha256": "2" * 64,
        "dependencyHashes": dependencies,
        "dependencyProfile": profile,
        "status": "pass",
    }


def test_exact_candidate_evidence_requires_exact_bytes_and_lock():
    evidence = item("watch", "a" * 64, {"cmap": "b" * 64}, "exact-candidate")
    assert evidence_is_fresh(evidence, "a" * 64, {"cmap": "b" * 64})
    assert not evidence_is_fresh(evidence, "c" * 64, {"cmap": "b" * 64})
    assert not evidence_is_fresh(evidence, "a" * 64, {"cmap": "d" * 64})


def test_raw_sync_evidence_survives_bmap_change_only():
    evidence = item(
        "sync",
        "a" * 64,
        {"raw": "b" * 64, "sync-map": "c" * 64, "bmap": "d" * 64},
        "raw-sync",
    )
    current = {
        "raw": "b" * 64,
        "sync-map": "c" * 64,
        "bmap": "e" * 64,
        "tracks": "f" * 64,
    }
    assert evidence_is_fresh(evidence, "9" * 64, current)
    current["sync-map"] = "0" * 64
    assert not evidence_is_fresh(evidence, "9" * 64, current)


def test_rights_facts_follow_source_usage_lock():
    evidence = item(
        "rights",
        "a" * 64,
        {"rawInventory": "b" * 64, "sourceUsage": "c" * 64},
        "source-rights",
    )
    assert evidence_is_fresh(
        evidence,
        "9" * 64,
        {"rawInventory": "b" * 64, "sourceUsage": "c" * 64, "bmap": "d" * 64},
    )
    assert not evidence_is_fresh(
        evidence,
        "9" * 64,
        {"rawInventory": "b" * 64, "sourceUsage": "e" * 64},
    )


def test_stale_evidence_keeps_history():
    items = [item("watch", "a" * 64, {"cmap": "b" * 64}, "exact-candidate")]
    result = stale_evidence(items, "c" * 64, {"cmap": "b" * 64})
    assert result[0]["status"] == "stale"
    assert items[0]["status"] == "pass"
