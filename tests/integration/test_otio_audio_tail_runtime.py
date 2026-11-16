"""Continuous audio graph preserves original samples and explicit silent tails."""

import shutil
import subprocess
from fractions import Fraction
from types import SimpleNamespace

import numpy as np
import pytest
from tests.integration.test_otio_placed_render_runtime import _decoded, _encode
from tests.test_import_audio_tail import tail_snapshot

from avo.adapters.media.audio_clock import verify_audio_sample_count
from avo.adapters.media.proof_placed import execute_placed_proof
from avo.capabilities import default_proof_capability_registry
from avo.timeline.contracts import file_fingerprint
from avo.timeline.initial_cut_placed import placed_cut_proof_request

pytestmark = pytest.mark.skipif(
    not shutil.which("ffmpeg") or not shutil.which("ffprobe"),
    reason="Native FFmpeg required",
)


@pytest.mark.parametrize("tail", [5504, 4288, 2304])
def test_declared_tail_is_exact_silence_and_microproof_matches_full(tmp_path, tail):
    snapshot = tail_snapshot(tail)
    original = tmp_path / "dialogue.wav"
    values = np.tile(np.array([0.1, 0.2], dtype=np.float32), (48000 - tail, 1))
    _encode(original, values, audio=True)
    snapshot["sources"][0].update(
        locator=str(original), fingerprint=file_fingerprint(original)
    )
    request = placed_cut_proof_request(
        SimpleNamespace(raw_dir=tmp_path),
        snapshot,
        iteration_id="tail",
        output=tmp_path / "full.mkv",
        frame_rate={"num": 24, "den": 1},
        width=64,
        height=48,
        sample_rate=48000,
        sample_rate_probe=None,
    )
    implementation = default_proof_capability_registry().resolve("source-layout")
    request["videoGraph"]["operations"][0]["implementationId"] = (
        implementation.implementation_id
    )
    request.update(
        window=None,
        sourceAssemblyPolicy="preserve-import",
        implementationRefs=[implementation.proof_reference()],
        canonicalInputLock={"source:camera": file_fingerprint(original)["sha256"]},
    )
    request["output"].update(
        videoCodec="ffv1", audioCodec="pcm_s32le", conformance=True
    )
    full = tmp_path / "full.mkv"
    execute_placed_proof(request, full, request["output"], Fraction(24), 48000)
    decoded = _decoded(full, audio=True)
    assert len(decoded) == 192000
    assert np.array_equal(decoded[48000 : 96000 - tail], values)
    assert np.count_nonzero(decoded[:48000]) == 0
    assert np.count_nonzero(decoded[96000 - tail :]) == 0
    request["window"] = {"startFrame": 24, "endFrameExclusive": 49}
    micro = tmp_path / "micro.mkv"
    execute_placed_proof(request, micro, request["output"], Fraction(24), 48000)
    assert np.array_equal(_decoded(micro, audio=True), decoded[48000:98000])


def test_aac_decoded_sample_evidence_matches_actual_pcm(tmp_path):
    wav = tmp_path / "input.wav"
    _encode(wav, np.zeros((48123, 2), dtype=np.float32), audio=True)
    encoded = tmp_path / "source.m4a"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(wav), "-c:a", "aac", str(encoded)],
        check=True,
    )
    digest = file_fingerprint(encoded)["sha256"]
    evidence = verify_audio_sample_count(encoded, 0, expected_sha256=digest)
    actual = _decoded(encoded, audio=True)
    assert evidence["sampleCount"] == len(actual)
    with pytest.raises(ValueError, match="changed"):
        verify_audio_sample_count(encoded, 0, expected_sha256="0" * 64)
