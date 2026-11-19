"""Private bounded process, frame I/O and scratch accounting for native proofs."""

import shutil
import subprocess
from math import isfinite
from pathlib import Path

GIB = 1024**3


class StreamError(RuntimeError):
    pass


def _integer(value, label, minimum=0):
    if type(value) is not int or value < minimum:
        raise StreamError(f"{label} must be an integer of at least {minimum}")
    return value


def _close(stream):
    if stream is None:
        return None
    try:
        stream.close()
    except OSError as error:
        return error
    return None


class ManagedProcess:
    """Own a child and job-local stderr; callers consume stdout before normal exit."""

    def __init__(
        self, argv, *, stderr_path, stdin=False, stdout=False, wait_timeout=60, cwd=None
    ):
        if not isinstance(argv, (list, tuple)) or not argv:
            raise StreamError("process argv must be a nonempty sequence")
        if (
            type(wait_timeout) not in (int, float)
            or not isfinite(wait_timeout)
            or wait_timeout <= 0
        ):
            raise StreamError("process wait timeout must be finite and positive")
        self.argv = list(argv)
        self.stderr_path = Path(stderr_path)
        self.stdin, self.stdout = stdin, stdout
        self.wait_timeout, self.cwd = wait_timeout, cwd
        self.process = self.errors = None

    def __enter__(self):
        try:
            self.stderr_path.parent.mkdir(parents=True, exist_ok=True)
            self.errors = self.stderr_path.open("xb")
            self.process = subprocess.Popen(
                self.argv,
                stdin=subprocess.PIPE if self.stdin else subprocess.DEVNULL,
                stdout=subprocess.PIPE if self.stdout else subprocess.DEVNULL,
                stderr=self.errors,
                shell=False,
                cwd=self.cwd,
            )
        except BaseException as error:
            _close(self.errors)
            if isinstance(error, OSError):
                raise StreamError(f"cannot launch native process: {error}") from error
            raise
        return self.process

    def _stop(self):
        if self.process.poll() is None:
            try:
                self.process.terminate()
            except OSError:
                pass  # A child may have exited between poll and terminate.
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                try:
                    self.process.kill()
                except OSError:
                    pass
                self.process.wait()
        else:
            self.process.wait()

    def _diagnostic(self, reason):
        try:
            with self.stderr_path.open("rb") as stream:
                stream.seek(0, 2)
                stream.seek(max(0, stream.tell() - 8192))
                tail = stream.read(8192).decode("utf-8", errors="replace").strip()
        except OSError:
            tail = "stderr unavailable"
        return f"{reason}: {self.argv[0]}: {tail or 'no stderr output'}"

    def __exit__(self, kind, error, traceback):
        reason = None
        try:
            input_error = _close(self.process.stdin)
            if error is not None:
                self._stop()
            else:
                reason = self._finish(input_error)
        except BaseException:
            self._stop()
            raise
        finally:
            output_error = _close(self.process.stdout)
            log_error = _close(self.errors)
        if error is not None:
            if self.process.returncode not in (None, 0):
                error.add_note(
                    self._diagnostic(f"native process exited {self.process.returncode}")
                )
            return False
        if reason is None and (output_error or log_error):
            reason = "cannot close native process output"
        if reason:
            raise StreamError(self._diagnostic(reason))
        return False

    def _finish(self, input_error):
        try:
            code = self.process.wait(timeout=self.wait_timeout)
        except subprocess.TimeoutExpired:
            self._stop()
            return "native process timed out"
        if code != 0:
            return f"native process exited {code}"
        return "cannot close native encoder input" if input_error else None


def read_exact(stream, size):
    """Read one bounded unit; partial pipe reads never imply a complete frame."""
    _integer(size, "read size")
    data = bytearray()
    while len(data) < size:
        try:
            part = stream.read(size - len(data))
        except OSError as error:
            raise StreamError(f"cannot read native frame stream: {error}") from error
        if not part:
            raise StreamError(
                f"truncated frame stream: expected {size} bytes, received {len(data)}"
            )
        if not isinstance(part, (bytes, bytearray)) or len(part) > size - len(data):
            raise StreamError("native frame read exceeded its bounded byte contract")
        data.extend(part)
    return bytes(data)


def copy_frames(
    stream, destination, *, bytes_per_frame, frame_count, verify_eof=False, monitor=None
):
    """Copy exactly one raw chunk, retaining a persistent decoder unless EOF is final."""
    _integer(bytes_per_frame, "frame size", 1)
    _integer(frame_count, "frame count")
    destination = Path(destination)
    created = False
    try:
        with destination.open("xb") as output:
            created = True
            for _ in range(frame_count):
                if monitor:
                    monitor()
                frame = read_exact(stream, bytes_per_frame)
                if output.write(frame) != bytes_per_frame:
                    raise StreamError("incomplete raw frame file write")
            if verify_eof and stream.read(1) != b"":
                raise StreamError(
                    "native decoder produced unexpected extra frame bytes"
                )
        if monitor:
            monitor()
    except BaseException:
        if created:
            destination.unlink(missing_ok=True)
        raise
    return bytes_per_frame * frame_count


def _write_all(stream, data):
    remaining = memoryview(data)
    while remaining:
        count = stream.write(remaining)
        if type(count) is not int or not 0 < count <= len(remaining):
            raise StreamError("native encoder write made no valid progress")
        remaining = remaining[count:]


def pump_file(path, stream, *, block_size=1024**2):
    """Feed a raw chunk without closing the persistent final encoder input."""
    _integer(block_size, "pump block size", 1)
    count = 0
    try:
        with Path(path).open("rb") as source:
            for block in iter(lambda: source.read(block_size), b""):
                _write_all(stream, block)
                count += len(block)
        stream.flush()
    except OSError as error:
        raise StreamError(f"native encoder pipe/file write failed: {error}") from error
    return count


class StorageBudget:
    """Image-scratch budget; mixed PCM lives outside this measured directory."""

    def __init__(
        self,
        directory,
        *,
        candidate_reserve=12 * GIB,
        headroom=2 * GIB,
        scratch_limit=6 * GIB,
        max_frames=60,
    ):
        self.directory = Path(directory)
        self.candidate_reserve = _integer(candidate_reserve, "candidate reserve")
        self.headroom = _integer(headroom, "disk headroom")
        self.scratch_limit = _integer(scratch_limit, "scratch limit", 1)
        self.max_frames = _integer(max_frames, "maximum chunk frames", 1)
        self.directory.mkdir(parents=True, exist_ok=True)

    def _scratch_bytes(self):
        total = 0
        for path in self.directory.rglob("*"):
            if path.is_symlink():
                raise StreamError("image scratch must not contain symlinks")
            if path.is_file():
                total += path.stat().st_size
        return total

    def check(
        self, scratch_bytes=None, *, mixed_size=0, candidate_size=0, additional_bytes=0
    ):
        _integer(mixed_size, "existing mixed PCM size")
        _integer(candidate_size, "current candidate size")
        _integer(additional_bytes, "additional scratch bytes")
        if candidate_size > self.candidate_reserve:
            raise StreamError("candidate exceeds its hard allocation cap")
        used = (
            self._scratch_bytes()
            if scratch_bytes is None
            else _integer(scratch_bytes, "current scratch bytes")
        )
        if used > self.scratch_limit:
            raise StreamError("image scratch exceeds its hard limit")
        # disk_usage.free already accounts for PCM, current scratch and candidate.
        # Reserve only candidate bytes that have not yet been allocated.
        free = shutil.disk_usage(self.directory).free
        capacity = free - self.headroom - (self.candidate_reserve - candidate_size)
        if capacity < 0:
            raise StreamError(
                "insufficient free space for candidate reserve and headroom"
            )
        capacity = min(capacity, self.scratch_limit - used)
        if additional_bytes > capacity:
            raise StreamError("insufficient scratch space for the pending write")
        return capacity

    def chunk_frames(
        self, bytes_per_frame, remaining, mixed_size=0, *, candidate_size=0
    ):
        _integer(bytes_per_frame, "combined scratch bytes per frame", 1)
        _integer(remaining, "remaining frames")
        capacity = self.check(mixed_size=mixed_size, candidate_size=candidate_size)
        frames = min(self.max_frames, remaining, capacity // bytes_per_frame)
        if remaining and frames < 1:
            raise StreamError("insufficient space to allocate even one raw frame")
        return frames
