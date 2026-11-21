"""Selected reference audio keeps its actual original stream clock."""

import shutil
import subprocess

import pytest

from avo.adapters.media.reference_audio import _packet_clock, measure_reference_audio
from avo.adapters.understand.visual_motion import _decode_log, _source_stream


def test_clock_with_discontinuous_pcm_abstains():
    log = "\n".join(
        f"[Parsed_ashowinfo] pts:{pts} rate:48000 nb_samples:480"
        for pts in (48_000, 48_840)
    )
    with pytest.raises(ValueError, match="discontinuous"):
        _packet_clock(log, 48_000, (48_000, 50_000), 48)


@pytest.mark.skipif(
    not shutil.which("ffmpeg") or not shutil.which("ffprobe"),
    reason="local FFmpeg and FFprobe required",
)
def test_decode_audio_on_original_shifted_clock(tmp_path):
    source = tmp_path / "original.mka"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            r"aevalsrc=0|if(between(t\,0.24\,0.31)\,0.8*sin(2*PI*1000*t)\,0):s=48000:d=0.8",
            "-c:a",
            "pcm_f32le",
            "-output_ts_offset",
            "2",
            str(source),
        ],
        check=True,
        timeout=30,
    )
    stream = _source_stream(source, 0, [], "audio")
    scope = {"startTicks": 2110, "endTicks": 2400, "timebase": {"num": 1, "den": 1000}}
    selection = {"streamIndex": 0, "channelIndex": 1, "energyThreshold": 0.05}
    result = measure_reference_audio(
        source, tmp_path / "selected.f32", scope, selection, stream, _decode_log
    )
    assert result["status"] == "observed"
    assert result["sampleRate"] == 48_000
    assert result["clockUncertaintySamples"] == 48
    assert result["startSample"] == 2110 * 48
    assert result["endSampleExclusive"] == 2400 * 48
    assert result["onsetSamples"] == [pytest.approx(2240 * 48, abs=96)]
    assert result["selection"] == selection
    other = {**selection, "channelIndex": 0}
    silent = measure_reference_audio(
        source, tmp_path / "silent.f32", scope, other, stream, _decode_log
    )
    assert silent["status"] == "observed"
    assert silent["onsetSamples"] == []
