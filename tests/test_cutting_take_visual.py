import hashlib

import pytest

from avo.adapters.understand.watch_skill import WatchSkillAdapter


def source_and_take(tmp_path):
    source = tmp_path / "original.mkv"
    source.write_bytes(b"authorized synthetic source")
    take = {
        "takeId": "a",
        "sourceRange": {
            "sourceId": "s",
            "startTicks": 0,
            "endTicksExclusive": 1000,
            "timebase": {"num": 1, "den": 1000},
        },
    }
    return source, hashlib.sha256(source.read_bytes()).hexdigest(), take


def reviewed(finding=None):
    return {
        "status": "pass",
        "model": "actual-model",
        "promptSha256": "a" * 64,
        "reviewContractHash": "b" * 64,
        "capabilityIdentityHash": "c" * 64,
        "coverage": {
            "frameRate": {"num": 30, "den": 1},
            "observedFrames": [0, 15, 29],
            "coverageHoles": [],
        },
        "findings": [finding] if finding else [],
    }


def test_visual_review_binds_original_and_cannot_claim_hearing(tmp_path, monkeypatch):
    source, digest, take = source_and_take(tmp_path)
    adapter = WatchSkillAdapter()
    calls = []

    def review(path, **request):
        calls.append(request)
        return reviewed(
            {
                "category": "visual-quality",
                "observed": "takeId=a; usability=usable",
                "programRange": {"startFrame": 0, "endFrameExclusive": 30},
            }
        )

    monkeypatch.setattr(adapter, "review", review)
    result = adapter.review_original_takes(
        source, source_sha256=digest, takes=[take], raw_dir=tmp_path
    )
    assert result["sourceSha256"] == digest
    assert result["perTake"]["a"]["visualUsability"] == 1
    assert result["claimScope"] == "sampled-still-images"
    assert "acousticComplete" not in result["perTake"]["a"]
    assert len(calls) == 1
    assert calls[0]["scope"] == "windows"


def test_model_pass_without_explicit_take_observation_is_unknown(tmp_path, monkeypatch):
    source, digest, take = source_and_take(tmp_path)
    adapter = WatchSkillAdapter()
    monkeypatch.setattr(adapter, "review", lambda *a, **k: reviewed())
    result = adapter.review_original_takes(
        source, source_sha256=digest, takes=[take], raw_dir=tmp_path
    )
    assert result["perTake"]["a"]["visualUsability"] is None


def test_source_fingerprint_or_unbounded_policy_cannot_run(tmp_path):
    source, digest, take = source_and_take(tmp_path)
    adapter = WatchSkillAdapter()
    with pytest.raises(ValueError, match="fingerprint"):
        adapter.review_original_takes(
            source, source_sha256="0" * 64, takes=[take], raw_dir=tmp_path
        )
    with pytest.raises(ValueError, match="resource"):
        adapter.review_original_takes(
            source,
            source_sha256=digest,
            takes=[take],
            raw_dir=tmp_path,
            policy={"effective": {"concurrency": 2}},
        )
