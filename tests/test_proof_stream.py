"""Bounded proof I/O and resource arithmetic without native media execution."""

import io
import subprocess
from types import SimpleNamespace

import pytest

from avo.adapters.media import proof_stream
from avo.adapters.media.proof_stream import (
    ManagedProcess,
    StorageBudget,
    StreamError,
    copy_frames,
    pump_file,
    read_exact,
)


class ShortReader(io.BytesIO):
    def read(self, size=-1):
        return super().read(min(size, 2))


class ShortWriter(io.BytesIO):
    def write(self, data):
        return super().write(data[:2])


class Process:
    def __init__(self, *, waits=None, data=b""):
        self.stdin = io.BytesIO()
        self.stdout = io.BytesIO(data)
        self.returncode = None
        self.waits = list(waits or [0])
        self.calls = []

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        self.calls.append(("wait", timeout))
        outcome = self.waits.pop(0) if self.waits else self.returncode
        if isinstance(outcome, Exception):
            raise outcome
        self.returncode = outcome
        return outcome

    def terminate(self):
        self.calls.append(("terminate",))

    def kill(self):
        self.calls.append(("kill",))


def install_process(monkeypatch, process, *, error=b""):
    launches = []

    def launch(argv, **kwargs):
        launches.append((argv, kwargs))
        kwargs["stderr"].write(error)
        return process

    monkeypatch.setattr(proof_stream.subprocess, "Popen", launch)
    return launches


def disk_free(monkeypatch, free):
    monkeypatch.setattr(
        proof_stream.shutil, "disk_usage", lambda path: SimpleNamespace(free=free)
    )


def budget(tmp_path, monkeypatch, *, free=1000, **kwargs):
    disk_free(monkeypatch, free)
    return StorageBudget(
        tmp_path,
        candidate_reserve=kwargs.pop("candidate_reserve", 400),
        headroom=kwargs.pop("headroom", 100),
        scratch_limit=kwargs.pop("scratch_limit", 300),
        max_frames=kwargs.pop("max_frames", 60),
        **kwargs,
    )


def test_exact_reader_accumulates_short_reads():
    stream = ShortReader(b"abcdefghmore")
    assert read_exact(stream, 8) == b"abcdefgh"
    assert stream.read(2) == b"mo"
    assert read_exact(stream, 0) == b""


def test_exact_reader_rejects_truncated_frame():
    with pytest.raises(StreamError, match="truncated"):
        read_exact(ShortReader(b"abc"), 4)


@pytest.mark.parametrize("size", [-1, True, 1.2])
def test_exact_reader_rejects_invalid_allocation(size):
    with pytest.raises((StreamError, ValueError)):
        read_exact(io.BytesIO(b"abc"), size)


def test_frame_copy_preserves_decoder_for_later_chunks(tmp_path):
    stream = ShortReader(b"111122223333")
    first, last = tmp_path / "first.bgra", tmp_path / "last.bgra"
    assert copy_frames(stream, first, bytes_per_frame=4, frame_count=2) == 8
    assert first.read_bytes() == b"11112222"
    assert (
        copy_frames(stream, last, bytes_per_frame=4, frame_count=1, verify_eof=True)
        == 4
    )
    assert last.read_bytes() == b"3333"
    assert not stream.closed


def test_frame_copy_extra_bytes_fail_only_when_eof_requested(tmp_path):
    path = tmp_path / "chunk.bgra"
    with pytest.raises(StreamError, match="extra"):
        copy_frames(
            io.BytesIO(b"12345"),
            path,
            bytes_per_frame=4,
            frame_count=1,
            verify_eof=True,
        )
    assert not path.exists()


def test_frame_copy_truncation_removes_only_new_partial_chunk(tmp_path):
    path = tmp_path / "chunk.bgra"
    with pytest.raises(StreamError, match="truncated"):
        copy_frames(ShortReader(b"123456"), path, bytes_per_frame=4, frame_count=2)
    assert not path.exists()
    path.write_bytes(b"retained")
    with pytest.raises((StreamError, OSError)):
        copy_frames(io.BytesIO(b"1234"), path, bytes_per_frame=4, frame_count=1)
    assert path.read_bytes() == b"retained"


def test_frame_copy_resource_monitor_can_stop_before_more_disk_writes(tmp_path):
    path = tmp_path / "chunk.bgra"
    calls = []

    def monitor():
        calls.append(True)
        raise StreamError("scratch limit")

    with pytest.raises(StreamError, match="scratch"):
        copy_frames(
            io.BytesIO(b"12345678"),
            path,
            bytes_per_frame=4,
            frame_count=2,
            monitor=monitor,
        )
    assert len(calls) == 1 and not path.exists()


def test_pump_handles_partial_writes_without_closing_persistent_encoder(tmp_path):
    path = tmp_path / "chunk.bgra"
    path.write_bytes(b"abcdefghijkl")
    destination = ShortWriter()
    assert pump_file(path, destination, block_size=5) == 12
    assert destination.getvalue() == path.read_bytes()
    assert not destination.closed


def test_pump_broken_pipe_is_scoped_and_does_not_close_caller_stream(tmp_path):
    path = tmp_path / "chunk.bgra"
    path.write_bytes(b"1234")

    class ClosedEncoder:
        def write(self, data):
            raise BrokenPipeError("encoder stopped")

    with pytest.raises(StreamError, match="encoder|pipe"):
        pump_file(path, ClosedEncoder())


def test_pump_rejects_nonprogressing_sink(tmp_path):
    path = tmp_path / "chunk.bgra"
    path.write_bytes(b"1234")
    with pytest.raises(StreamError, match="progress|write"):
        pump_file(path, SimpleNamespace(write=lambda data: 0))


def test_managed_process_closes_encoder_input_before_wait(monkeypatch, tmp_path):
    process = Process()
    original = process.wait

    def wait(timeout=None):
        assert process.stdin.closed
        assert not process.stdout.closed
        return original(timeout)

    process.wait = wait
    launches = install_process(monkeypatch, process)
    path = tmp_path / "encoder.stderr"
    with ManagedProcess(
        ["ffmpeg", "args"], stderr_path=path, stdin=True, cwd=tmp_path
    ) as child:
        assert child is process
        child.stdin.write(b"frame")
    assert launches[0][0] == ["ffmpeg", "args"]
    assert launches[0][1]["stdin"] == subprocess.PIPE
    assert launches[0][1]["stdout"] == subprocess.DEVNULL
    assert launches[0][1]["shell"] is False
    assert launches[0][1]["cwd"] == tmp_path
    assert process.stdout.closed and launches[0][1]["stderr"].closed
    assert not any(call[0] in {"terminate", "kill"} for call in process.calls)


def test_managed_decoder_exits_after_consumed_eof(monkeypatch, tmp_path):
    process = Process(data=b"abcd")
    launches = install_process(monkeypatch, process)
    with ManagedProcess(
        ["ffmpeg"], stderr_path=tmp_path / "decoder.stderr", stdout=True
    ) as child:
        assert read_exact(child.stdout, 4) == b"abcd"
        assert child.stdout.read(1) == b""
    assert launches[0][1]["stdout"] == subprocess.PIPE
    assert process.stdout.closed


def test_nonzero_process_diagnostic_contains_stderr_and_is_reaped(
    monkeypatch, tmp_path
):
    process = Process(waits=[23])
    launches = install_process(monkeypatch, process, error=b"specific native failure")
    with pytest.raises(StreamError, match="23.*specific native failure"):
        with ManagedProcess(["ffmpeg"], stderr_path=tmp_path / "failed.stderr"):
            pass
    assert process.returncode == 23
    assert process.stdin.closed and process.stdout.closed
    assert launches[0][1]["stderr"].closed


def test_exception_terminates_then_kills_and_reaps_stubborn_process(
    monkeypatch, tmp_path
):
    process = Process(waits=[subprocess.TimeoutExpired("child", 5), -9])
    launches = install_process(monkeypatch, process)
    with pytest.raises(ValueError, match="original failure"):
        with ManagedProcess(["ffmpeg"], stderr_path=tmp_path / "failed.stderr"):
            raise ValueError("original failure")
    assert [call[0] for call in process.calls] == ["terminate", "wait", "kill", "wait"]
    assert process.returncode == -9 and process.stdout.closed and process.stdin.closed
    assert launches[0][1]["stderr"].closed


def test_normal_wait_timeout_also_terminates_kills_and_reaps(monkeypatch, tmp_path):
    process = Process(
        waits=[
            subprocess.TimeoutExpired("child", 0.1),
            subprocess.TimeoutExpired("child", 5),
            -9,
        ]
    )
    install_process(monkeypatch, process)
    with pytest.raises(StreamError, match="timed out"):
        with ManagedProcess(
            ["ffmpeg"], stderr_path=tmp_path / "timeout.stderr", wait_timeout=0.1
        ):
            pass
    assert [call[0] for call in process.calls] == [
        "wait",
        "terminate",
        "wait",
        "kill",
        "wait",
    ]
    assert process.stdout.closed and process.stdin.closed


def test_process_launch_failure_closes_job_stderr(monkeypatch, tmp_path):
    streams = []

    def fail(argv, **kwargs):
        streams.append(kwargs["stderr"])
        raise OSError("missing native binary")

    monkeypatch.setattr(proof_stream.subprocess, "Popen", fail)
    with pytest.raises(StreamError, match="launch|missing"):
        with ManagedProcess(["missing"], stderr_path=tmp_path / "launch.stderr"):
            pass
    assert streams[0].closed


def test_encoder_input_close_broken_pipe_still_reports_and_reaps_child(
    monkeypatch, tmp_path
):
    class BrokenInput(io.BytesIO):
        def close(self):
            super().close()
            raise BrokenPipeError("encoder already failed")

    process = Process(waits=[9])
    process.stdin = BrokenInput()
    launches = install_process(monkeypatch, process, error=b"actual encoder diagnostic")
    with pytest.raises(StreamError, match="9.*actual encoder diagnostic"):
        with ManagedProcess(
            ["ffmpeg"], stderr_path=tmp_path / "broken-input.stderr", stdin=True
        ):
            pass
    assert process.returncode == 9 and process.stdin.closed and process.stdout.closed
    assert launches[0][1]["stderr"].closed


def test_existing_stderr_evidence_is_not_overwritten(monkeypatch, tmp_path):
    path = tmp_path / "stderr.log"
    path.write_bytes(b"original failure evidence")
    launches = install_process(monkeypatch, Process())
    with pytest.raises(StreamError):
        with ManagedProcess(["ffmpeg"], stderr_path=path):
            pass
    assert not launches and path.read_bytes() == b"original failure evidence"


def test_pump_flush_failure_reports_closed_encoder(tmp_path):
    class FailedFlush(io.BytesIO):
        def flush(self):
            raise BrokenPipeError("encoder failed during flush")

    path = tmp_path / "chunk.bgra"
    path.write_bytes(b"frame")
    destination = FailedFlush()
    with pytest.raises(StreamError, match="encoder|pipe"):
        pump_file(path, destination)
    assert not destination.closed


def test_storage_budget_applies_scratch_limit_frame_cap_and_remaining(
    tmp_path, monkeypatch
):
    value = budget(tmp_path, monkeypatch)
    assert value.chunk_frames(10, 100) == 30
    assert value.chunk_frames(10, 7) == 7
    value = budget(tmp_path, monkeypatch, free=10000, scratch_limit=2000)
    assert value.chunk_frames(10, 1000) == 60


def test_storage_budget_reserves_only_remaining_candidate_allocation(
    tmp_path, monkeypatch
):
    value = budget(tmp_path, monkeypatch, free=650, scratch_limit=1000)
    assert value.chunk_frames(10, 100, candidate_size=0) == 15
    assert value.chunk_frames(10, 100, candidate_size=200) == 35
    assert value.chunk_frames(10, 100, candidate_size=400) == 55


def test_existing_pcm_mix_is_not_reserved_twice_against_free_space(
    tmp_path, monkeypatch
):
    value = budget(tmp_path, monkeypatch, free=650, scratch_limit=1000)
    assert value.chunk_frames(10, 100, mixed_size=500) == 15
    assert value.chunk_frames(10, 100, mixed_size=500, candidate_size=200) == 35


def test_existing_image_scratch_is_counted_for_cap_without_double_reserving_disk(
    tmp_path, monkeypatch
):
    (tmp_path / "old-layer.bgra").write_bytes(b"x" * 200)
    value = budget(tmp_path, monkeypatch, free=650)
    assert value.chunk_frames(10, 100) == 10
    assert value.check() == 100


def test_storage_budget_rejects_before_even_one_frame_if_insufficient(
    tmp_path, monkeypatch
):
    value = budget(tmp_path, monkeypatch, free=509)
    with pytest.raises(StreamError, match="frame|space|reserve"):
        value.chunk_frames(10, 1)


def test_storage_budget_never_allows_candidate_above_hard_cap(tmp_path, monkeypatch):
    value = budget(tmp_path, monkeypatch, free=10000)
    with pytest.raises(StreamError, match="candidate"):
        value.chunk_frames(1, 1, candidate_size=401)


def test_storage_budget_monitor_detects_cap_free_space_and_pending_writes(
    tmp_path, monkeypatch
):
    value = budget(tmp_path, monkeypatch)
    with pytest.raises(StreamError, match="scratch"):
        value.check(301)
    with pytest.raises(StreamError, match="scratch|space"):
        value.check(290, additional_bytes=11)
    disk_free(monkeypatch, 499)
    with pytest.raises(StreamError, match="space|reserve"):
        value.check(0)


@pytest.mark.parametrize(
    "field,value",
    [
        ("candidate_reserve", -1),
        ("headroom", True),
        ("scratch_limit", 0),
        ("max_frames", 0),
    ],
)
def test_storage_budget_rejects_invalid_limits(tmp_path, field, value):
    with pytest.raises((StreamError, ValueError)):
        StorageBudget(tmp_path, **{field: value})
