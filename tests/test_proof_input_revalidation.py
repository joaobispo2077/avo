"""Post-render checks hash every distinct input afresh without repeated reads."""

from unittest.mock import patch

import pytest

from avo.adapters.media.cutting_audio import _source_fingerprint_batch
from avo.adapters.media.proof_executor import _revalidate_inputs
from avo.timeline.contracts import file_fingerprint
from avo.timeline.ports import ToolError


def execution_with_sources(video, audio=()):
    def operations(sources):
        return [{"parameters": {"source": source}} for source in sources]

    return {
        "videoGraph": {"operations": operations(video)},
        "audioGraph": {"operations": operations(audio)},
    }


def test_repeated_picture_and_audio_share_one_fresh_hash(tmp_path):
    path = tmp_path / "raw.mkv"
    path.write_bytes(b"original picture and sound")
    source = file_fingerprint(path)
    execution = execution_with_sources([source, source], [source, source])

    with patch(
        "avo.adapters.media.proof_executor.file_fingerprint", wraps=file_fingerprint
    ) as fingerprint:
        _revalidate_inputs(execution, {}, None)

    assert fingerprint.call_count == 1


def test_conflicting_claim_for_same_input_still_fails(tmp_path):
    path = tmp_path / "raw.mkv"
    path.write_bytes(b"original")
    source = file_fingerprint(path)
    conflicting = {**source, "sha256": "0" * 64}

    with pytest.raises(RuntimeError, match="source changed during render"):
        _revalidate_inputs(execution_with_sources([source], [conflicting]), {}, None)


def test_each_distinct_input_is_checked(tmp_path):
    sources = []
    for name in ("camera.mkv", "recorder.wav"):
        path = tmp_path / name
        path.write_bytes(name.encode())
        sources.append(file_fingerprint(path))

    with patch(
        "avo.adapters.media.proof_executor.file_fingerprint", wraps=file_fingerprint
    ) as fingerprint:
        _revalidate_inputs(execution_with_sources(sources), {}, None)

    assert fingerprint.call_count == 2


def test_revalidation_does_not_cache_across_calls(tmp_path):
    path = tmp_path / "raw.mkv"
    path.write_bytes(b"original")
    execution = execution_with_sources([file_fingerprint(path)])
    _revalidate_inputs(execution, {}, None)
    path.write_bytes(b"modified during another render")

    with pytest.raises(RuntimeError, match="source changed during render"):
        _revalidate_inputs(execution, {}, None)


def test_preview_batch_reuses_source_observation_and_rechecks_before_return(tmp_path):
    path = tmp_path / "raw.mkv"
    path.write_bytes(b"original")
    execution = execution_with_sources([file_fingerprint(path)])
    with patch(
        "avo.adapters.media.proof_executor.file_fingerprint", wraps=file_fingerprint
    ) as fingerprint:
        with _source_fingerprint_batch():
            _revalidate_inputs(execution, {}, None)
            _revalidate_inputs(execution, {}, None)
        assert fingerprint.call_count == 1


def test_preview_batch_cannot_return_after_source_changes(tmp_path):
    path = tmp_path / "raw.mkv"
    path.write_bytes(b"original")
    execution = execution_with_sources([file_fingerprint(path)])
    with pytest.raises(ToolError, match="changed"):
        with _source_fingerprint_batch():
            _revalidate_inputs(execution, {}, None)
            path.write_bytes(b"changed while rendering")
