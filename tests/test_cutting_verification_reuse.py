from copy import deepcopy

import pytest

from avo.timeline.ports import ToolError


def test_source_observations_are_scoped_and_rechecked(tmp_path, monkeypatch):
    from avo.adapters.media import cutting_audio as audio

    path = tmp_path / "source.bin"
    path.write_bytes(b"original")
    calls = []
    original = audio.source_fingerprint

    def observed(value):
        calls.append(value)
        return original(value)

    monkeypatch.setattr(audio, "source_fingerprint", observed)
    with audio._source_fingerprint_batch():
        first = audio._observed_source_fingerprint(path)
        with audio._source_fingerprint_batch():
            assert audio._observed_source_fingerprint(path) == first
    assert len(calls) == 2
    with audio._source_fingerprint_batch():
        assert audio._observed_source_fingerprint(path) == first
    assert len(calls) == 4


def test_source_change_blocks_batch_and_does_not_leak_cache(tmp_path):
    from avo.adapters.media import cutting_audio as audio

    path = tmp_path / "source.bin"
    path.write_bytes(b"original")
    with pytest.raises(ToolError, match="changed"):
        with audio._source_fingerprint_batch():
            before = audio._observed_source_fingerprint(path)
            path.write_bytes(b"modified")
    assert audio._observed_source_fingerprint(path)["sha256"] != before["sha256"]


def test_batch_checks_each_distinct_source(tmp_path):
    from avo.adapters.media import cutting_audio as audio

    first, second = tmp_path / "first.bin", tmp_path / "second.bin"
    first.write_bytes(b"first")
    second.write_bytes(b"second")
    with audio._source_fingerprint_batch():
        assert (
            audio._observed_source_fingerprint(first)["sha256"]
            != audio._observed_source_fingerprint(second)["sha256"]
        )


def test_conflicting_source_claim_still_fails_before_decode(tmp_path):
    from avo.adapters.media import cutting_audio as audio

    path = tmp_path / "source.bin"
    path.write_bytes(b"original")
    with audio._source_fingerprint_batch():
        audio._observed_source_fingerprint(path)
        with pytest.raises(ToolError, match="fingerprint"):
            audio.extract_dialogue_pcm(
                path,
                selection={},
                source_range={},
                fingerprint={"sha256": "0" * 64},
                sync_ref={},
                output_dir=tmp_path / "out",
            )


@pytest.mark.parametrize("different_window", [False, True])
def test_identical_verification_windows_reuse_signal_check_only_within_call(
    tmp_path, monkeypatch, different_window
):
    from avo.adapters.qc import cutting_boundary as boundary

    candidate = tmp_path / "candidate.bin"
    candidate.write_bytes(b"candidate")
    calls = []

    def verify(*args):
        calls.append(args)
        return {"status": "pass", "checks": []}

    monkeypatch.setattr(boundary, "_verify_window", verify)
    first = {
        "occurrenceId": "join-1",
        "localStartSeconds": 0,
        "localEndSeconds": 1,
        "expectedAudio": {"source": "original"},
        "retainedWordEdges": [{"text": "word", "start": 0.1, "end": 0.9}],
        "fadeRanges": [],
    }
    second = {**deepcopy(first), "occurrenceId": "join-2"}
    if different_window:
        second["fadeRanges"] = [{"start": 0, "end": 0.03}]
    request = {
        "proposal_ref": {"locator": "proposal", "sha256": "a" * 64},
        "proof_plan_ref": {"locator": "plan", "sha256": "b" * 64},
        "graph_hash": "c" * 64,
        "required_occurrences": ["join-1", "join-2"],
        "candidate_selection": {"streamIndex": 0, "channels": [0]},
        "windows": [first, second],
    }
    verifier = boundary.CuttingBoundaryVerifier(tmp_path / "qc")
    result = verifier.verify(candidate, **request)
    assert result["status"] == "pass"
    assert result["occurrenceCoverage"] == ["join-1", "join-2"]
    assert len(calls) == (2 if different_window else 1)
    verifier.verify(candidate, **request)
    assert len(calls) == (4 if different_window else 2)


def test_verifier_cannot_return_pass_after_source_changes(tmp_path, monkeypatch):
    from avo.adapters.media import cutting_audio as audio
    from avo.adapters.qc import cutting_boundary as boundary

    candidate, source = tmp_path / "candidate.bin", tmp_path / "source.bin"
    candidate.write_bytes(b"candidate")
    source.write_bytes(b"original")

    def verify(*args):
        audio._observed_source_fingerprint(source)
        source.write_bytes(b"modified")
        return {"status": "pass", "checks": []}

    monkeypatch.setattr(boundary, "_verify_window", verify)
    with pytest.raises(ToolError, match="changed"):
        boundary.CuttingBoundaryVerifier(tmp_path / "qc").verify(
            candidate,
            proposal_ref={"locator": "proposal", "sha256": "a" * 64},
            proof_plan_ref={"locator": "plan", "sha256": "b" * 64},
            graph_hash="c" * 64,
            required_occurrences=["join-1"],
            candidate_selection={"streamIndex": 0, "channels": [0]},
            windows=[{"occurrenceId": "join-1"}],
        )
