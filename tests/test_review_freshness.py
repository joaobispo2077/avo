from __future__ import annotations

from avo.timeline.review import evidence_is_fresh, review_contract_hash, stale_evidence


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


def test_watch_freshness_binds_every_review_contract_input():
    inputs = {
        "candidateHash": "a" * 64,
        "dependencyHashes": {"cmap": "b" * 64},
        "policyHash": "c" * 64,
        "coveragePlanHash": "d" * 64,
        "requiredWindowHash": "e" * 64,
        "modelCapabilityHash": "f" * 64,
        "promptHash": "1" * 64,
        "transcriptHash": "2" * 64,
        "termsHash": "3" * 64,
        "adapterToolHash": "4" * 64,
        "estimatorHash": "5" * 64,
    }
    expected = review_contract_hash(**inputs)
    evidence = item("watch", "a" * 64, {"cmap": "b" * 64}, "exact-candidate")
    evidence["policy"] = {"reviewContractHash": expected}
    assert evidence_is_fresh(
        evidence,
        "a" * 64,
        {"cmap": "b" * 64},
        review_contract_sha256=expected,
    )
    for key in inputs:
        changed = dict(inputs)
        changed[key] = {"cmap": "9" * 64} if key == "dependencyHashes" else "9" * 64
        assert review_contract_hash(**changed) != expected
    assert not evidence_is_fresh(
        evidence,
        "a" * 64,
        {"cmap": "b" * 64},
        review_contract_sha256="0" * 64,
    )
