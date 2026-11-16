"""Batch caching must finish with fresh byte verification before publication."""

import hashlib
import os
from fractions import Fraction
from pathlib import Path
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


def test_sequential_render_keeps_deleted_segments_out_of_batch_guard(
    tmp_path, monkeypatch
):
    from avo.adapters.media import proof_executor

    source = tmp_path / "original.bin"
    source.write_bytes(b"original")
    output = tmp_path / "proof.mkv"
    staged = []

    def piece(_segment, _left, _right, _spec, _fps, _rate, path, **_kwargs):
        path.write_bytes(b"private segment")
        contracts.file_fingerprint(path)
        staged.append(path)

    def final(_listing, candidate, *_args):
        candidate.write_bytes(b"candidate")
        contracts.file_fingerprint(candidate)
        return {}, []

    def verify():
        assert not output.exists()
        assert contracts.file_fingerprint(source) == original

    monkeypatch.setattr(proof_executor, "_render_piece", piece)
    monkeypatch.setattr(proof_executor, "_render_final", final)
    node = {"outputRange": {"startSample": 0, "endSampleExclusive": 48000}}
    with proof_validation_batch():
        original = contracts.file_fingerprint(source)
        proof_executor._render_media(
            output,
            [(0, 1, None, None, None, node)],
            {"conformance": True},
            Fraction(1),
            48000,
            0,
            1,
            [],
            verify,
        )
        assert all(not path.exists() for path in staged)
    assert output.read_bytes() == b"candidate"


@pytest.mark.parametrize("native_batch", [False, True])
@pytest.mark.parametrize(
    "window",
    [None, {"startFrame": 0, "endFrameExclusive": 1}],
    ids=["bounded", "legacy"],
)
def test_placed_render_shares_source_reads_only_in_native_batch(
    tmp_path, monkeypatch, native_batch, window
):
    from avo.adapters.media import (
        proof_bounded,
        proof_executor,
        proof_placed,
        proof_stream,
    )

    source = tmp_path / "source.bin"
    source.write_bytes(b"original")
    original_open, reads = Path.open, []

    def opened(path, mode="r", *args, **kwargs):
        if path == source and mode == "rb":
            reads.append(path)
        return original_open(path, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", opened)
    monkeypatch.setattr(proof_placed, "_layout_operation", lambda _: {"parameters": {}})
    monkeypatch.setattr(proof_placed, "_compose_picture", lambda *args: None)

    def mix(_graph, output, **_kwargs):
        output.write_bytes(b"temporary mix")
        return {"output": contracts.file_fingerprint(output)}

    monkeypatch.setattr(proof_placed, "render_proof_audio_mix", mix)

    paths = []

    def final(_listing, output, *_args, **_kwargs):
        paths.append("legacy")
        output.write_bytes(b"candidate")
        return {}, []

    def bounded_picture(_execution, _sources, _directory, output, *_args):
        paths.append("bounded")
        output.write_bytes(b"candidate")
        return []

    def budget(directory, **kwargs):
        return proof_stream.StorageBudget(
            directory, candidate_reserve=128, headroom=128, **kwargs
        )

    monkeypatch.setattr(proof_executor, "_render_final", final)
    monkeypatch.setattr(proof_executor, "_check_encoded", lambda *_args: {})
    monkeypatch.setattr(proof_bounded, "_stream_picture", bounded_picture)
    monkeypatch.setattr(proof_bounded, "StorageBudget", budget)
    monkeypatch.setattr(
        proof_placed,
        "_revalidate_sources",
        lambda *args: contracts.file_fingerprint(source),
    )
    context = (
        proof_validation_batch() if native_batch else contracts.fingerprint_stage()
    )
    with context:
        contracts.file_fingerprint(source)
        for index in range(2):
            proof_placed._render(
                {"audioGraph": {"nodes": []}, "window": window},
                tmp_path / f"proof-{index}.mkv",
                [],
                1,
                {"width": 64, "height": 48, "conformance": True},
                Fraction(60),
                None,
                (0, 1),
                {},
                None,
            )
            assert (tmp_path / f"proof-{index}.mkv").read_bytes() == b"candidate"
        assert paths == ["bounded" if window is None else "legacy"] * 2
        assert len(reads) == (1 if native_batch else 3)
    assert len(reads) == (2 if native_batch else 3)
