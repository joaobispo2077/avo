from __future__ import annotations

import io
import json
import shutil
import subprocess
import sys
from fractions import Fraction
from pathlib import Path
from types import SimpleNamespace

import pytest

from avo.adapters.media import video_clock
from avo.adapters.media.ffprobe import FfprobeMediaAdapter
from avo.timeline.contracts import ContractError, file_fingerprint

NATIVE = pytest.mark.skipif(
    not shutil.which("ffmpeg") or not shutil.which("ffprobe"),
    reason="Native FFmpeg/FFprobe required",
)


class PacketProcess:
    def __init__(self, data, *, result=0, on_wait=None):
        self.stdout = io.BytesIO(data)
        self.result = result
        self.returncode = None
        self.on_wait = on_wait
        self.killed = False

    def wait(self, timeout=None):
        if self.on_wait is not None:
            self.on_wait()
            self.on_wait = None
        self.returncode = self.result
        return self.returncode

    def poll(self):
        return self.returncode

    def kill(self):
        self.killed = True
        self.returncode = -9


def _fake(
    tmp_path, monkeypatch, data=b"0,K__\n1,___\n2,___\n", *, result=0, on_wait=None
):
    path = tmp_path / "original.mov"
    path.write_bytes(b"synthetic original bytes")
    calls = []

    def popen(args, **kwargs):
        calls.append((args, kwargs))
        return PacketProcess(data, result=result, on_wait=on_wait)

    monkeypatch.setattr(video_clock.subprocess, "Popen", popen)
    return path, calls


def _verify(path, *, base="1/24", fps=Fraction(24), **kwargs):
    return video_clock.verify_video_clock(
        path,
        0,
        fps,
        time_base=base,
        expected_sha256=file_fingerprint(path)["sha256"],
        **kwargs,
    )


def test_inventory_cannot_publish_stale_properties_with_new_fingerprint(
    tmp_path, monkeypatch
):
    path = tmp_path / "original.mkv"
    path.write_bytes(b"before metadata probe")

    def mutate(*_, **__):
        path.write_bytes(b"changed during metadata probe")
        return SimpleNamespace(
            stdout=json.dumps({"streams": [], "format": {"duration": "3"}})
        )

    monkeypatch.setattr(subprocess, "run", mutate)
    with pytest.raises(ContractError, match="changed"):
        FfprobeMediaAdapter().inventory([path])


def test_inventory_does_not_implicitly_scan_whole_packet_clock(tmp_path, monkeypatch):
    path = tmp_path / "original.mkv"
    path.write_bytes(b"metadata-only original")
    monkeypatch.setattr(
        subprocess, "run", lambda *_, **__: SimpleNamespace(stdout='{"streams":[]}')
    )
    monkeypatch.setattr(
        subprocess,
        "Popen",
        lambda *_, **__: pytest.fail("ordinary inventory cannot trigger packet scan"),
    )
    assert (
        "clockVerification" not in FfprobeMediaAdapter().inventory([path])["sources"][0]
    )


def test_adapter_exposes_explicit_bound_clock_verifier(monkeypatch):
    calls = []
    expected = {"status": "verified"}

    def verify(*args, **kwargs):
        calls.append((args, kwargs))
        return expected

    monkeypatch.setattr(video_clock, "verify_video_clock", verify)
    path = Path("original.mov")
    assert (
        FfprobeMediaAdapter().verify_video_clock(
            path, 2, Fraction(24), time_base="1/24", expected_sha256="a" * 64
        )
        == expected
    )
    assert calls[0][0] == (path, 2, Fraction(24))
    assert calls[0][1]["time_base"] == "1/24"


def test_sorted_presentation_grid_accepts_packet_reordering_and_binds_evidence(
    tmp_path, monkeypatch
):
    path, calls = _fake(tmp_path, monkeypatch, b"2,___\n0,K__\n1,___\n")
    result = _verify(path, expected_frames=3, start_ticks=0)
    assert result == {
        "status": "verified",
        "sourceSha256": file_fingerprint(path)["sha256"],
        "streamIndex": 0,
        "frameRate": {"num": 24, "den": 1},
        "method": "packet-pts-grid-v1",
        "packetCount": 3,
        "timeBase": {"num": 1, "den": 24},
        "originTicks": 0,
        "timingSha256": result["timingSha256"],
    }
    assert len(result["timingSha256"]) == 64
    args, kwargs = calls[0]
    assert args[args.index("-select_streams") + 1] == "0"
    assert "packet_side_data=" in args[args.index("-show_entries") + 1]
    assert args[args.index("-protocol_whitelist") + 1] == "file"
    assert kwargs["stdout"] == subprocess.PIPE
    assert kwargs["stderr"] == subprocess.DEVNULL


@pytest.mark.parametrize(
    "data",
    [
        b"",
        b"0,K__\nN/A,___\n",
        b"0,K__\n0,___\n",
        b"0,XYZ\n",
        b"0,__C\n",
        b"0,K__,extra\n",
        b"0,K__",
    ],
)
def test_missing_duplicate_unrecognized_or_incomplete_packet_records_are_unverified(
    tmp_path, monkeypatch, data
):
    path, _ = _fake(tmp_path, monkeypatch, data)
    with pytest.raises(video_clock.VideoClockError):
        _verify(path)


@pytest.mark.parametrize(
    "data,fps,base",
    [
        (b"0,K__\n3,___\n", Fraction(24), "1/48"),
        (b"0,K__\n2,___\n4,___\n", Fraction(2), "1/3"),
    ],
)
def test_integral_grid_has_zero_tolerance_and_quantized_grid_error_is_strictly_less_than_one_tick(
    tmp_path, monkeypatch, data, fps, base
):
    path, _ = _fake(tmp_path, monkeypatch, data)
    with pytest.raises(video_clock.VideoClockError):
        _verify(path, fps=fps, base=base)


def test_half_tick_quantization_is_exact_fraction_math_not_uniform_delta_check(
    tmp_path, monkeypatch
):
    path, _ = _fake(tmp_path, monkeypatch, b"0,K__\n2,___\n3,___\n5,___\n")
    assert _verify(path, fps=Fraction(2), base="1/3")["packetCount"] == 4


@pytest.mark.parametrize("options", [{"expected_frames": 2}, {"start_ticks": 1}])
def test_header_count_and_first_presented_origin_must_match(
    tmp_path, monkeypatch, options
):
    path, _ = _fake(tmp_path, monkeypatch)
    with pytest.raises(video_clock.VideoClockError):
        _verify(path, **options)


def test_discard_packets_require_consistent_known_header_count_and_origin(
    tmp_path, monkeypatch
):
    path, _ = _fake(tmp_path, monkeypatch, b"-1,_D_\n0,K__\n1,___\n")
    result = _verify(path, expected_frames=2, start_ticks=0)
    assert result["packetCount"] == 2 and result["originTicks"] == 0
    for options in (
        {},
        {"expected_frames": 3, "start_ticks": 0},
        {"expected_frames": 2},
    ):
        with pytest.raises(video_clock.VideoClockError):
            _verify(path, **options)


@pytest.mark.parametrize(
    "limit,value,data",
    [
        ("MAX_PACKETS", 2, b"0,K__\n1,___\n2,___\n"),
        ("MAX_OUTPUT_BYTES", 10, b"0,K__\n1,___\n"),
        ("MAX_LINE_BYTES", 8, b"123456789,K__\n"),
    ],
)
def test_packet_output_and_line_overflow_never_accept_a_valid_prefix(
    tmp_path, monkeypatch, limit, value, data
):
    path, _ = _fake(tmp_path, monkeypatch, data)
    monkeypatch.setattr(video_clock, limit, value)
    with pytest.raises(video_clock.VideoClockError, match="limit|long"):
        _verify(path)


def test_nonzero_probe_exit_is_not_successful_prefix(tmp_path, monkeypatch):
    path, _ = _fake(tmp_path, monkeypatch, result=2)
    with pytest.raises(video_clock.VideoClockError):
        _verify(path)


def test_cache_reuses_only_exact_bounds_and_fresh_original_bytes(tmp_path, monkeypatch):
    path, calls = _fake(tmp_path, monkeypatch)
    cache = {}
    first = _verify(path, expected_frames=3, start_ticks=0, cache=cache)
    assert _verify(path, expected_frames=3, start_ticks=0, cache=cache) == first
    assert len(calls) == 1
    with pytest.raises(video_clock.VideoClockError):
        _verify(path, expected_frames=2, start_ticks=0, cache=cache)
    assert len(calls) == 2
    old_hash = file_fingerprint(path)["sha256"]
    path.write_bytes(b"different current bytes")
    with pytest.raises(video_clock.VideoClockError, match="changed|fingerprint"):
        video_clock.verify_video_clock(
            path,
            0,
            Fraction(24),
            time_base="1/24",
            expected_sha256=old_hash,
            expected_frames=3,
            start_ticks=0,
            cache=cache,
        )


def test_scan_cannot_cache_evidence_until_closing_fingerprint_guard_passes(
    tmp_path, monkeypatch
):
    path = tmp_path / "original.mov"
    path, _ = _fake(
        tmp_path,
        monkeypatch,
        on_wait=lambda: path.write_bytes(b"changed after packet stdout"),
    )
    cache = {}
    with pytest.raises(video_clock.VideoClockError, match="changed"):
        _verify(path, cache=cache)
    assert cache == {}


def test_daemon_deadline_kills_probe_and_never_returns_prefix_evidence(
    tmp_path, monkeypatch
):
    path = tmp_path / "original.mov"
    path.write_bytes(b"original bytes")
    native_popen = subprocess.Popen

    def sleepy(*_, **kwargs):
        return native_popen(
            [
                sys.executable,
                "-c",
                "import sys,time;sys.stdout.write('0,K__\\n');sys.stdout.flush();time.sleep(10)",
            ],
            **kwargs,
        )

    monkeypatch.setattr(video_clock.subprocess, "Popen", sleepy)
    monkeypatch.setattr(video_clock, "TIMEOUT_SECONDS", 0.1)
    with pytest.raises(video_clock.VideoClockError, match="timed|limit"):
        _verify(path)


def _recording(path, *, fps="24", container="mkv", irregular=False, bframes=False):
    shifted = path.with_name("intermediate-" + path.name)
    args = [
        "ffmpeg",
        "-v",
        "error",
        "-nostdin",
        "-f",
        "lavfi",
        "-i",
        f"testsrc2=s=64x48:r={fps}",
    ]
    if bframes:
        args.extend(
            [
                "-f",
                "lavfi",
                "-i",
                "sine=frequency=997:sample_rate=48000:duration=1",
                "-map",
                "1:a",
                "-map",
                "0:v",
                "-frames:v",
                "24",
                "-c:a",
                "pcm_s16le",
                "-c:v",
                "libx264",
                "-x264-params",
                "bframes=2:b-adapt=0",
            ]
        )
    else:
        args.extend(
            [
                "-frames:v",
                "12" if fps == "24" else "30",
                "-c:v",
                "png" if container == "mov" else "ffv1",
            ]
        )
    if irregular:
        shift = 1900 if container == "mov" else 1000
        args.extend(
            [
                "-vf",
                f"settb=1/48000,setpts=PTS+if(eq(N\\,6)\\,{shift}\\,0)",
                "-fps_mode",
                "passthrough",
                "-enc_time_base",
                "1:48000",
            ]
        )
    subprocess.run(
        [*args, str(shifted if irregular else path)], check=True, capture_output=True
    )
    if irregular:
        finish = (
            ["-bsf:v", "setts=duration=2000:time_base=1/48000"]
            if container == "mov"
            else ["-r", "24"]
        )
        subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-nostdin",
                "-i",
                str(shifted),
                "-map",
                "0:v",
                "-c",
                "copy",
                *finish,
                str(path),
            ],
            check=True,
            capture_output=True,
        )


@NATIVE
@pytest.mark.parametrize(
    "fps,container,bframes,count",
    [
        ("24", "mkv", False, 12),
        ("30000/1001", "mkv", False, 30),
        ("24", "mov", True, 24),
    ],
)
def test_native_regular_and_bframe_clocks_are_verified_without_picture_decode(
    tmp_path, fps, container, bframes, count
):
    path = tmp_path / ("original." + container)
    _recording(path, fps=fps, container=container, bframes=bframes)
    stream = FfprobeMediaAdapter().inventory([path])["sources"][0]["streams"]["video"][
        0
    ]
    result = video_clock.verify_video_clock(
        path,
        stream["index"],
        Fraction(fps),
        time_base=stream["timeBase"],
        expected_sha256=file_fingerprint(path)["sha256"],
        expected_frames=stream["frameCount"],
        start_ticks=stream["startTicks"],
    )
    assert result["status"] == "verified"
    assert result["packetCount"] == count
    assert result["frameRate"] == {
        "num": Fraction(fps).numerator,
        "den": Fraction(fps).denominator,
    }
    if bframes:
        assert stream["index"] == 1
        data = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "1",
                "-show_packets",
                "-show_entries",
                "packet=pts",
                "-of",
                "csv=p=0",
                str(path),
            ],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        values = [int(line) for line in data.splitlines() if line]
        assert values != sorted(values)


@NATIVE
@pytest.mark.parametrize("container", ["mov", "mkv"])
def test_native_irregular_clock_with_equal_nominal_and_average_rate_is_rejected(
    tmp_path, container
):
    path = tmp_path / ("irregular." + container)
    _recording(path, container=container, irregular=True)
    stream = FfprobeMediaAdapter().inventory([path])["sources"][0]["streams"]["video"][
        0
    ]
    assert stream["frameRate"] == stream["averageFrameRate"] == "24/1"
    with pytest.raises(video_clock.VideoClockError, match="grid|irregular"):
        video_clock.verify_video_clock(
            path,
            stream["index"],
            Fraction(24),
            time_base=stream["timeBase"],
            expected_sha256=file_fingerprint(path)["sha256"],
            expected_frames=stream["frameCount"],
            start_ticks=stream["startTicks"],
        )
