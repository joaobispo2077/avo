"""Decode every repeated output frame and compare the same micro/full graph."""

import shutil
import subprocess
from copy import deepcopy
from fractions import Fraction

import numpy as np
import pytest
from tests.integration.test_otio_placed_render_runtime import (
    _decoded,
    _encode,
    _execution,
    _picture_values,
)

from avo.adapters.media.proof_placed import (
    _admit_picture,
    _stage_picture,
    execute_placed_proof,
)
from avo.timeline.contracts import file_fingerprint

pytestmark = pytest.mark.skipif(
    not shutil.which("ffmpeg") or not shutil.which("ffprobe"),
    reason="Actual FFmpeg/FFprobe required",
)


def test_bounded_end_gap_holds_only_missing_positions_before_final_frame(tmp_path):
    original = tmp_path / "complete.mkv"
    source = tmp_path / "end-gap.mkv"
    values = _picture_values(0)[:10]
    _encode(original, values, fps="30")
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            str(original),
            "-map",
            "0:v:0",
            "-c:v",
            "copy",
            "-bsf:v",
            "setts=pts=PTS+67*gte(N\\,9):dts=DTS+67*gte(N\\,9)",
            str(source),
        ],
        check=True,
    )
    digest = file_fingerprint(source)["sha256"]
    item = {
        "placementId": "end-gap",
        "trackId": "video",
        "sourceId": "raw",
        "mediaKind": "video",
        "pictureSampling": "repeat-2x",
        "pictureEndGapFrames": 2,
        "source": {
            "locator": str(source),
            "sha256": digest,
            "mediaClass": "source",
            "streamIndex": 0,
        },
        "sourceRange": {
            "startTicks": 0,
            "endTicks": 12,
            "timebase": {"num": 1, "den": 30},
        },
        "outputRange": {"startFrame": 0, "endFrameExclusive": 24},
        "zOrder": 0,
        "enabled": True,
    }
    execution = {"canonicalInputLock": {"source:raw": digest}}
    admitted = _admit_picture(execution, [item], 24, Fraction(60), {})
    staged = tmp_path / "held.mkv"
    _stage_picture(admitted[0], staged, {"width": 64, "height": 48}, Fraction(60))
    expected = np.concatenate(
        [values[:9], np.repeat(values[8:9], 2, axis=0), values[9:]]
    )
    assert np.array_equal(_decoded(staged), np.repeat(expected, 2, axis=0))
    tail = tmp_path / "held-tail.mkv"
    _stage_picture(
        admitted[0],
        tail,
        {"width": 64, "height": 48},
        Fraction(60),
        start_frame=20,
        stop_frame=24,
    )
    assert np.array_equal(_decoded(tail), np.repeat(expected, 2, axis=0)[20:24])
    undeclared = deepcopy(item)
    undeclared.pop("pictureEndGapFrames")
    with pytest.raises(RuntimeError, match="clock|grid"):
        _admit_picture(execution, [undeclared], 24, Fraction(60), {})


def test_actual_30_to_60_repeats_trimmed_source_frames_exactly(tmp_path):
    source = tmp_path / "source30.mkv"
    values = _picture_values(0)
    _encode(source, values, fps="30")
    digest = file_fingerprint(source)["sha256"]
    item = {
        "placementId": "trimmed",
        "trackId": "video",
        "sourceId": "raw",
        "mediaKind": "video",
        "pictureSampling": "repeat-2x",
        "source": {
            "locator": str(source),
            "sha256": digest,
            "mediaClass": "source",
            "streamIndex": 0,
        },
        "sourceRange": {
            "startTicks": 3,
            "endTicks": 17,
            "timebase": {"num": 1, "den": 30},
        },
        "outputRange": {"startFrame": 0, "endFrameExclusive": 28},
        "zOrder": 0,
        "enabled": True,
    }
    admitted = _admit_picture(
        {"canonicalInputLock": {"source:raw": digest}}, [item], 28, Fraction(60), {}
    )
    staged = tmp_path / "stage60.mkv"
    _stage_picture(admitted[0], staged, {"width": 64, "height": 48}, Fraction(60))
    assert np.array_equal(_decoded(staged), np.repeat(values[3:17], 2, axis=0))


def test_repetition_preserves_every_frame_pcm_and_microproof_window(tmp_path):
    original, _ = _execution(tmp_path)
    base = tmp_path / "base.mkv"
    execute_placed_proof(original, base, original["output"], Fraction(24), 48000)
    repeated = deepcopy(original)
    repeated["output"]["frameRate"] = {"num": 48, "den": 1}
    operation = repeated["videoGraph"]["operations"][0]
    operation["outputRange"]["endFrameExclusive"] *= 2
    for item in operation["parameters"]["placements"]:
        for key in ("startFrame", "endFrameExclusive"):
            item["outputRange"][key] *= 2
        if item["mediaKind"] == "video":
            item["pictureSampling"] = "repeat-2x"
    full = tmp_path / "repeated.mkv"
    execute_placed_proof(repeated, full, repeated["output"], Fraction(48), 48000)
    assert np.array_equal(_decoded(full), np.repeat(_decoded(base), 2, axis=0))
    assert np.array_equal(_decoded(full, audio=True), _decoded(base, audio=True))
    repeated["window"] = {"startFrame": 47, "endFrameExclusive": 113}
    micro = tmp_path / "micro-repeated.mkv"
    execute_placed_proof(repeated, micro, repeated["output"], Fraction(48), 48000)
    assert np.array_equal(_decoded(micro), _decoded(full)[47:113])
    assert np.array_equal(
        _decoded(micro, audio=True), _decoded(full, audio=True)[47000:113000]
    )


def test_undeclared_doubling_is_rejected_before_publication(tmp_path):
    execution, _ = _execution(tmp_path)
    execution["output"]["frameRate"] = {"num": 48, "den": 1}
    operation = execution["videoGraph"]["operations"][0]
    operation["outputRange"]["endFrameExclusive"] *= 2
    for item in operation["parameters"]["placements"]:
        for key in ("startFrame", "endFrameExclusive"):
            item["outputRange"][key] *= 2
    output = tmp_path / "undeclared.mkv"
    with pytest.raises(RuntimeError, match="differs from program clock"):
        execute_placed_proof(
            execution, output, execution["output"], Fraction(48), 48000
        )
    assert not output.exists()
