"""Batch caching must finish with fresh byte verification before publication."""

import hashlib
import os
from unittest.mock import patch

import pytest

from avo.timeline import contracts
from avo.timeline.proof_validation_stage import (
    in_proof_validation_batch,
    proof_pixel_observations,
    proof_validation_batch,
)


def replace_preserving_metadata(path):
    before = path.stat()
    path.write_bytes(b"replaced")
    os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))


@pytest.mark.parametrize("name", ["source.bin", "generator.py", "generated.mkv"])
def test_batch_end_freshly_rejects_preserved_metadata_changes(tmp_path, name):
    path = tmp_path / name
    path.write_bytes(b"original")
    with pytest.raises(contracts.ContractError, match="changed"):
        with proof_validation_batch():
            contracts.file_fingerprint(path)
            replace_preserving_metadata(path)
    assert not in_proof_validation_batch()
    assert proof_pixel_observations() is None


def test_reused_windows_hash_once_and_close_with_one_fresh_hash(tmp_path):
    path = tmp_path / "source.bin"
    path.write_bytes(b"original")
    with patch.object(contracts.hashlib, "sha256", wraps=hashlib.sha256) as hashing:
        with proof_validation_batch():
            for _ in range(3):
                with contracts.fingerprint_stage(reuse_current=True):
                    contracts.file_fingerprint(path)
                    contracts.file_fingerprint(path)
            assert hashing.call_count == 1
        assert hashing.call_count == 2


def test_closing_guard_rehashes_every_distinct_observed_file(tmp_path):
    first, second = tmp_path / "first", tmp_path / "second"
    first.write_bytes(b"original")
    second.write_bytes(b"original")
    with patch.object(contracts.hashlib, "sha256", wraps=hashlib.sha256) as hashing:
        with contracts.fingerprint_stage(verify_on_exit=True):
            contracts.file_fingerprint(first)
            contracts.file_fingerprint(second)
            contracts.file_fingerprint(first)
        assert hashing.call_count == 4


def test_default_nested_stage_remains_fresh(tmp_path):
    path = tmp_path / "source.bin"
    path.write_bytes(b"original")
    with contracts.fingerprint_stage():
        old = contracts.file_fingerprint(path)
        replace_preserving_metadata(path)
        with contracts.fingerprint_stage():
            new = contracts.file_fingerprint(path)
    assert old["sha256"] != new["sha256"]


def test_no_silent_rebase_within_shared_stage(tmp_path):
    path = tmp_path / "source.bin"
    path.write_bytes(b"original")
    with contracts.fingerprint_stage():
        contracts.file_fingerprint(path)
        replace_preserving_metadata(path)
        stat = path.stat()
        os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))
        with pytest.raises(contracts.ContractError, match="changed"):
            contracts.file_fingerprint(path)


def test_exit_guard_ignores_cached_stat_identity(tmp_path):
    path = tmp_path / "source.bin"
    path.write_bytes(b"original")
    key = contracts._fingerprint_key(path)
    with patch.object(contracts, "_fingerprint_key", return_value=key):
        with pytest.raises(contracts.ContractError, match="changed"):
            with contracts.fingerprint_stage(verify_on_exit=True):
                original = contracts.file_fingerprint(path)
                replace_preserving_metadata(path)
                assert contracts.file_fingerprint(path) == original


def test_reuse_without_parent_still_has_local_cache(tmp_path):
    path = tmp_path / "source.bin"
    path.write_bytes(b"original")
    with patch.object(contracts.hashlib, "sha256", wraps=hashlib.sha256) as hashing:
        with contracts.fingerprint_stage(reuse_current=True) as observations:
            contracts.file_fingerprint(path)
            contracts.file_fingerprint(path)
            assert observations
        assert hashing.call_count == 1
        contracts.file_fingerprint(path)
        assert hashing.call_count == 2


def test_pixel_cache_is_batch_local_and_exception_safe():
    assert not in_proof_validation_batch()
    assert proof_pixel_observations() is None
    with pytest.raises(RuntimeError, match="abort"):
        with proof_validation_batch():
            assert in_proof_validation_batch()
            first = proof_pixel_observations()
            first["asset"] = {"verified": True}
            assert proof_pixel_observations() is first
            raise RuntimeError("abort")
    assert not in_proof_validation_batch()
    assert proof_pixel_observations() is None
    with proof_validation_batch():
        assert proof_pixel_observations() == {}
        assert proof_pixel_observations() is not first


def test_exception_restores_parent_fingerprint_cache(tmp_path):
    path = tmp_path / "source.bin"
    path.write_bytes(b"original")
    with contracts.fingerprint_stage() as parent:
        contracts.file_fingerprint(path)
        with pytest.raises(RuntimeError):
            with proof_validation_batch():
                contracts.file_fingerprint(path)
                raise RuntimeError("abort")
        with contracts.fingerprint_stage(reuse_current=True) as restored:
            assert restored is parent


def test_nested_pixel_batches_restore_outer_cache():
    with proof_validation_batch():
        outer = proof_pixel_observations()
        outer["outer"] = True
        with proof_validation_batch():
            assert proof_pixel_observations() == {}
            assert proof_pixel_observations() is not outer
        assert proof_pixel_observations() is outer
