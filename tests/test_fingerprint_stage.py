"""Fingerprint reuse is opt-in, stage-local and refreshed across final validation."""

import hashlib
import os
from unittest.mock import patch

from avo.timeline import contracts


def test_default_fingerprints_are_not_cached(tmp_path):
    source = tmp_path / "source.bin"
    source.write_bytes(b"original")
    with patch.object(contracts.hashlib, "sha256", wraps=hashlib.sha256) as hashing:
        contracts.file_fingerprint(source)
        contracts.file_fingerprint(source)
    assert hashing.call_count == 2


def test_same_stage_reuses_bytes_but_not_mutable_result(tmp_path):
    source = tmp_path / "source.bin"
    source.write_bytes(b"original")
    with patch.object(contracts.hashlib, "sha256", wraps=hashlib.sha256) as hashing:
        with contracts.fingerprint_stage():
            first = contracts.file_fingerprint(source)
            first["sha256"] = "tampered-result"
            second = contracts.file_fingerprint(source)
    assert hashing.call_count == 1
    assert second["sha256"] == hashlib.sha256(b"original").hexdigest()


def test_fresh_stage_rehashes_even_when_size_and_mtime_are_preserved(tmp_path):
    source = tmp_path / "source.bin"
    source.write_bytes(b"original")
    stat = source.stat()
    with contracts.fingerprint_stage():
        before = contracts.file_fingerprint(source)
        source.write_bytes(b"replaced")
        os.utime(source, ns=(stat.st_atime_ns, stat.st_mtime_ns))
        with contracts.fingerprint_stage():
            after = contracts.file_fingerprint(source)
    assert after["sha256"] != before["sha256"]
    assert after["sha256"] == hashlib.sha256(b"replaced").hexdigest()


def test_exception_does_not_leak_stage_cache(tmp_path):
    source = tmp_path / "source.bin"
    source.write_bytes(b"original")
    try:
        with contracts.fingerprint_stage():
            contracts.file_fingerprint(source)
            raise RuntimeError("stop stage")
    except RuntimeError:
        pass
    source.write_bytes(b"replaced")
    assert (
        contracts.file_fingerprint(source)["sha256"]
        == hashlib.sha256(b"replaced").hexdigest()
    )


def test_proof_publication_rehashes_source_after_render(tmp_path):
    import pytest

    from avo.adapters.media.proof_executor import _revalidate_inputs

    source = tmp_path / "source.bin"
    source.write_bytes(b"original")
    stat = source.stat()
    with contracts.fingerprint_stage():
        expected = contracts.file_fingerprint(source)
        execution = {
            "videoGraph": {"operations": [{"parameters": {"source": expected}}]},
            "audioGraph": {"operations": []},
        }
        source.write_bytes(b"replaced")
        os.utime(source, ns=(stat.st_atime_ns, stat.st_mtime_ns))
        with pytest.raises(RuntimeError, match="changed during render"):
            _revalidate_inputs(execution, {}, None)
