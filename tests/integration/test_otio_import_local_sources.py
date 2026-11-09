"""Raw source admission and decode cannot follow untracked playlist ancestors."""

import shutil
import subprocess

import pytest
from tests.test_local_source import _playlist, _recording

from avo.adapters.media import proof_executor, proof_placed
from avo.adapters.media.audio_tracks import AudioGraphError
from avo.adapters.media.proof_audio_mix import _stage_source
from avo.timeline.contracts import file_fingerprint

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not shutil.which("ffmpeg") or not shutil.which("ffprobe"),
        reason="Native media tools required",
    ),
]


@pytest.fixture
def playlist(tmp_path):
    outside = tmp_path / "private" / "untracked.ts"
    _recording(outside, container="mpegts")
    path = tmp_path / "declared" / "original.m3u8"
    _playlist(path, "../private/untracked.ts")
    return path


def test_canonical_source_probe_rejects_playlist_even_with_matching_byte_lock(playlist):
    fingerprint = file_fingerprint(playlist)
    parameters = {
        "sourceId": "original",
        "source": {
            "locator": str(playlist),
            "sha256": fingerprint["sha256"],
            "mediaClass": "source",
            "ancestry": [],
            "streamIndex": 0,
        },
    }
    with pytest.raises(subprocess.CalledProcessError) as error:
        proof_executor._source(
            parameters, {"source:original": fingerprint["sha256"]}, {}
        )
    assert "not on whitelist" in error.value.stderr.lower()
    assert "untracked.ts" not in error.value.stderr


def test_placed_picture_decode_rejects_playlist_before_external_media(
    playlist, tmp_path
):
    source = {
        "path": playlist,
        "stream": 0,
        "first": 0,
        "last": 24,
        "item": {
            "mediaKind": "video",
            "outputRange": {"startFrame": 0, "endFrameExclusive": 24},
        },
    }
    from fractions import Fraction

    output = tmp_path / "picture.mkv"
    with pytest.raises(RuntimeError) as error:
        proof_placed._stage_picture(
            source, output, {"width": 32, "height": 32}, Fraction(24)
        )
    assert "not on whitelist" in str(error.value).lower()
    assert "untracked.ts" not in str(error.value)
    assert not output.exists()


def test_audio_decode_rejects_playlist_before_external_media(playlist, tmp_path):
    node = {
        "sourceRange": {"startSample": 0, "endSampleExclusive": 48000},
        "outputRange": {"startSample": 0, "endSampleExclusive": 48000},
        "channelMap": [0, 1],
    }
    output = tmp_path / "audio.wav"
    with pytest.raises(AudioGraphError) as error:
        _stage_source(node, (playlist, 1), output)
    assert "not on whitelist" in str(error.value).lower()
    assert "untracked.ts" not in str(error.value)
    assert not output.exists()
