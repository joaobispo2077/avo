"""Decode actual placed proofs across every picture and PCM boundary."""

from __future__ import annotations

import shutil
import subprocess
from copy import deepcopy
from fractions import Fraction
from types import SimpleNamespace

import numpy as np
import pytest
from PIL import Image
from tests.test_timeline_import_layout import placed_snapshot, program_time, raw_time

from avo.adapters.media import proof_executor, proof_placed
from avo.capabilities import default_proof_capability_registry
from avo.timeline.contracts import file_fingerprint
from avo.timeline.initial_cut_placed import placed_cut_proof_request

pytestmark = pytest.mark.skipif(
    not shutil.which("ffmpeg") or not shutil.which("ffprobe"),
    reason="Actual ffmpeg/ffprobe required",
)


def _encode(path, values, *, audio=False, fps="24", offset=None, sar=None):
    input_args = (
        ["-f", "f32le", "-ar", "48000", "-ac", "2"]
        if audio
        else [
            "-f",
            "rawvideo",
            "-pixel_format",
            "rgb24",
            "-video_size",
            "64x48",
            "-framerate",
            fps,
        ]
    )
    output_args = (
        ["-c:a", "pcm_f32le"] if audio else ["-c:v", "ffv1", "-pix_fmt", "bgra"]
    )
    if path.suffix == ".png":
        output_args = ["-frames:v", "1", "-c:v", "png", "-update", "1"]
    elif path.suffix == ".mov":
        output_args = ["-c:v", "png", "-pix_fmt", "rgb24"]
    if offset is not None:
        output_args.extend(["-output_ts_offset", str(offset)])
    if sar is not None:
        output_args.extend(["-vf", f"setsar={sar}"])
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-nostdin",
            *input_args,
            "-i",
            "pipe:0",
            *output_args,
            str(path),
        ],
        input=values.tobytes(),
        capture_output=True,
        check=True,
    )


def _picture_values(channel, count=24):
    values = np.zeros((count, 48, 64, 3), dtype=np.uint8)
    values[:, :, :, channel] = (40 + np.arange(count, dtype=np.uint8) * 4)[
        :, None, None
    ]
    return values


def _source(source_id, path):
    return {
        "sourceId": source_id,
        "kind": "raw",
        "locator": str(path),
        "fingerprint": file_fingerprint(path),
    }


def _audio_placement(placement_id, track_id, source_id, start, end):
    return {
        "placementId": placement_id,
        "elementId": f"/audio/{placement_id}",
        "trackId": track_id,
        "sourceId": source_id,
        "mediaKind": "audio",
        "in": raw_time(0, source_id, den=48000),
        "out": raw_time(48000, source_id, den=48000),
        "start": program_time(start),
        "end": program_time(end),
        "enabled": True,
        "routing": {
            "audioSelection": {
                "streamIndex": 0,
                "channels": [0, 1],
                "sourceLayout": "stereo",
                "outputLayout": "stereo",
                "sourceSampleRate": 48000,
            }
        },
        "evidenceOrigin": "export",
    }


def _execution(tmp_path):
    paths = {
        key: tmp_path / name
        for key, name in {
            "camera": "camera.mkv",
            "upper": "upper.mkv",
            "still": "literal-%04d.png",
            "audio-a": "audio-a.wav",
            "audio-b": "audio-b.wav",
        }.items()
    }
    _encode(paths["camera"], _picture_values(0))
    _encode(paths["upper"], _picture_values(2))
    green = np.zeros((1, 48, 64, 3), dtype=np.uint8)
    green[:, :, :, 1] = 180
    _encode(paths["still"], green)
    for source_id, levels in (("audio-a", (0.1, 0.2)), ("audio-b", (0.03, 0.04))):
        _encode(
            paths[source_id],
            np.tile(np.array(levels, dtype=np.float32), (48000, 1)),
            audio=True,
        )
    snapshot = placed_snapshot()
    snapshot["sources"] = [_source(key, path) for key, path in paths.items()]
    layout = snapshot["layout"]
    upper = layout["placements"][2]
    upper.update(
        sourceId="upper", **{"in": raw_time(6, "upper"), "out": raw_time(18, "upper")}
    )
    still = deepcopy(upper)
    still.update(
        placementId="still",
        elementId="/still",
        sourceId="still",
        mediaKind="still",
        **{
            "in": raw_time(0, "still"),
            "out": raw_time(1, "still"),
            "start": program_time(54),
            "end": program_time(66),
        },
    )
    disabled = deepcopy(upper)
    disabled.update(
        placementId="disabled",
        elementId="/disabled",
        trackId="v3",
        enabled=False,
        start=program_time(0),
        end=program_time(12),
    )
    layout["placements"].extend([still, disabled])
    for track_id, kind, order in (
        ("v3", "video", 2),
        ("a1", "audio", 0),
        ("a2", "audio", 1),
    ):
        layout["tracks"].append(
            {
                "trackId": track_id,
                "kind": kind,
                "order": order,
                "enabled": True,
                "muted": False,
                "evidenceOrigin": "export",
            }
        )
    first = _audio_placement("audio-first", "a1", "audio-a", 24, 48)
    second = _audio_placement("audio-second", "a2", "audio-b", 36, 60)
    second["gainDb"] = -6.020599913279624
    layout["placements"].extend([first, second])
    request = placed_cut_proof_request(
        SimpleNamespace(raw_dir=tmp_path),
        snapshot,
        iteration_id="placed",
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
        canonicalInputLock={
            f"source:{source_id}": file_fingerprint(path)["sha256"]
            for source_id, path in paths.items()
        },
    )
    request["output"].update(
        videoCodec="ffv1", audioCodec="pcm_s32le", conformance=True
    )
    return request, paths


def _decoded(path, *, audio=False):
    args = (
        ["-map", "0:a:0", "-f", "f32le"]
        if audio
        else ["-map", "0:v:0", "-pix_fmt", "rgb24", "-f", "rawvideo"]
    )
    data = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), *args, "pipe:1"],
        capture_output=True,
        check=True,
    ).stdout
    return np.frombuffer(data, dtype=np.float32 if audio else np.uint8).reshape(
        (-1, 2) if audio else (-1, 48, 64, 3)
    )


def _expected_picture():
    frames = np.zeros((96, 48, 64, 3), dtype=np.uint8)
    frames[24:48], frames[72:96] = _picture_values(0), _picture_values(0)
    frames[30:42] = _picture_values(2)[6:18]
    frames[54:66, :, :, 1] = 180
    return frames


def _expected_audio():
    samples = np.zeros((192000, 2), dtype=np.float32)
    samples[48000:96000] += (0.1, 0.2)
    samples[72000:120000] += (0.015, 0.02)
    return samples


def test_lossless_placed_proof_preserves_every_frame_and_independent_pcm_join(tmp_path):
    execution, _ = _execution(tmp_path)
    output = tmp_path / "full.mkv"
    result = proof_executor.execute_ffmpeg_proof(execution, output)
    np.testing.assert_allclose(_decoded(output), _expected_picture(), atol=1)
    np.testing.assert_allclose(
        _decoded(output, audio=True), _expected_audio(), atol=2e-7
    )
    assert result["audioEncodeCount"] == 1
    assert result["audioMix"]["ephemeralLeadNodeIds"] == []
    assert result["audioMix"]["sampleCount"] == 192000


def test_placed_microproof_is_exact_window_of_same_picture_and_pcm_graph(tmp_path):
    execution, _ = _execution(tmp_path)
    execution["window"] = {"startFrame": 29, "endFrameExclusive": 73}
    output = tmp_path / "micro.mkv"
    proof_executor.execute_ffmpeg_proof(execution, output)
    np.testing.assert_allclose(_decoded(output), _expected_picture()[29:73], atol=1)
    np.testing.assert_allclose(
        _decoded(output, audio=True), _expected_audio()[58000:146000], atol=2e-7
    )


@pytest.mark.parametrize(
    "fault",
    [
        "changed-source",
        "stale-implementation",
        "unknown-parameter",
        "forbidden-disabled-ancestor",
    ],
)
def test_placed_executor_blocks_untrusted_graph_before_public_output(tmp_path, fault):
    execution, paths = _execution(tmp_path)
    operation = execution["videoGraph"]["operations"][0]
    if fault == "changed-source":
        paths["camera"].write_bytes(paths["camera"].read_bytes() + b"changed")
    elif fault == "stale-implementation":
        execution["implementationRefs"][0]["sha256"] = "0" * 64
    elif fault == "unknown-parameter":
        operation["parameters"]["hiddenTransform"] = True
    else:
        operation["parameters"]["placements"][-1]["source"]["mediaClass"] = "proof"
    output = tmp_path / "blocked.mkv"
    with pytest.raises(RuntimeError):
        proof_executor.execute_ffmpeg_proof(execution, output)
    assert not output.exists()


def test_placed_inputs_are_rehashed_before_candidate_publication(tmp_path, monkeypatch):
    execution, paths = _execution(tmp_path)
    original = proof_executor._render_final

    def change_source(*args, **kwargs):
        result = original(*args, **kwargs)
        paths["camera"].write_bytes(
            paths["camera"].read_bytes() + b"changed-during-render"
        )
        return result

    monkeypatch.setattr(proof_executor, "_render_final", change_source)
    output = tmp_path / "blocked.mkv"
    with pytest.raises(RuntimeError, match="changed"):
        proof_executor.execute_ffmpeg_proof(execution, output)
    assert not output.exists()


def test_non_square_source_pixels_are_rejected_before_lossy_fitting(tmp_path):
    execution, _ = _execution(tmp_path)
    path = tmp_path / "anamorphic.mkv"
    _encode(path, _picture_values(0), sar="2")
    digest = file_fingerprint(path)["sha256"]
    for item in execution["videoGraph"]["operations"][0]["parameters"]["placements"]:
        if item["sourceId"] == "camera":
            item["source"].update(locator=str(path), sha256=digest)
    execution["canonicalInputLock"]["source:camera"] = digest
    output = tmp_path / "blocked.mkv"
    with pytest.raises(RuntimeError, match="aspect|SAR"):
        proof_executor.execute_ffmpeg_proof(execution, output)
    assert not output.exists()


def test_literal_alpha_still_composites_over_moving_original_layers(tmp_path):
    execution, paths = _execution(tmp_path)
    Image.new("RGBA", (64, 48), (0, 180, 0, 128)).save(paths["still"])
    still = next(
        item
        for item in execution["videoGraph"]["operations"][0]["parameters"]["placements"]
        if item["mediaKind"] == "still"
    )
    still.update(
        trackId="v3", zOrder=2, outputRange={"startFrame": 36, "endFrameExclusive": 48}
    )
    still["source"]["sha256"] = file_fingerprint(paths["still"])["sha256"]
    execution["canonicalInputLock"]["source:still"] = still["source"]["sha256"]
    expected = _expected_picture()
    expected[54:66] = 0
    expected[36:48] = np.rint(
        expected[36:48] * (127 / 255) + np.array((0, 180, 0)) * (128 / 255)
    ).astype(np.uint8)
    output = tmp_path / "alpha.mkv"
    proof_executor.execute_ffmpeg_proof(execution, output)
    np.testing.assert_allclose(_decoded(output), expected, atol=1)


def _fractional_execution(tmp_path):
    fps = Fraction(30000, 1001)
    path = tmp_path / "offset-clock.mov"
    _encode(path, _picture_values(0, 36), fps=str(fps), offset=4)
    snapshot = placed_snapshot()
    snapshot["sources"] = [_source("camera", path)]
    rate = {"num": fps.numerator, "den": fps.denominator}
    base = {"num": fps.denominator, "den": fps.numerator}
    snapshot["importOutput"]["frameRate"] = rate
    layout = snapshot["layout"]
    layout["programClock"].update(frameRate=rate, timebase=base)
    layout["duration"] = {"ticks": 30, "timebase": base, "domain": "cmap-output"}
    layout["tracks"] = layout["tracks"][:1]
    picture = layout["placements"][0]
    for key, ticks in (("in", 6), ("out", 36)):
        picture[key] = {
            "ticks": ticks,
            "timebase": base,
            "domain": "raw-source",
            "sourceId": "camera",
        }
    for key, ticks in (("start", 0), ("end", 30)):
        picture[key] = {"ticks": ticks, "timebase": base, "domain": "cmap-output"}
    layout["placements"], layout["gaps"] = [picture], []
    request = placed_cut_proof_request(
        SimpleNamespace(raw_dir=tmp_path),
        snapshot,
        iteration_id="fractional",
        output=tmp_path / "fractional.mkv",
        frame_rate=rate,
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
        canonicalInputLock={"source:camera": file_fingerprint(path)["sha256"]},
    )
    request["output"].update(
        videoCodec="ffv1", audioCodec="pcm_s32le", conformance=True
    )
    return request


@pytest.mark.parametrize(
    "window,first,last,samples",
    [(None, 0, 30, 48048), ({"startFrame": 1, "endFrameExclusive": 3}, 1, 3, 3203)],
)
def test_fractional_clock_and_nonzero_source_pts_use_exact_frame_and_half_up_sample_boundaries(
    tmp_path, window, first, last, samples
):
    execution = _fractional_execution(tmp_path)
    execution["window"] = window
    output = tmp_path / "fractional.mkv"
    result = proof_executor.execute_ffmpeg_proof(execution, output)
    np.testing.assert_allclose(
        _decoded(output), _picture_values(0, 36)[6 + first : 6 + last], atol=1
    )
    np.testing.assert_array_equal(
        _decoded(output, audio=True), np.zeros((samples, 2), dtype=np.float32)
    )
    assert result["audioMix"]["sampleCount"] == samples
    if window is not None:
        assert result["audioMix"]["window"] == {
            "startSample": 1602,
            "endSampleExclusive": 4805,
        }


def test_placed_exact_half_sample_ties_use_compiler_half_up_policy():
    fps = Fraction(96000, 1001)
    assert proof_placed._sample_boundary(1, fps) == 501
    assert proof_placed._sample_boundary(3, fps) == 1502
    extent = {"startSample": 0, "endSampleExclusive": 2002}
    execution = {
        "window": {"startFrame": 1, "endFrameExclusive": 3},
        "audioGraph": {
            "operations": [{"kind": "encode", "parameters": {}, "range": extent}]
        },
    }
    assert proof_placed._window(execution, 4, fps) == (1, 3)
