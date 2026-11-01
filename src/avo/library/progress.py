"""Independent lightweight library heartbeats and explicit immutable outcomes."""

from __future__ import annotations

import json
import math
import os
import shutil
import stat
import sys
import threading
import time
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

from avo.timeline.store import now_iso


def _directory_observation(directory):
    total = 0
    errors = 0
    folders = []
    try:
        with os.scandir(directory) as entries:
            for entry in entries:
                try:
                    info = entry.stat(follow_symlinks=False)
                    linked = stat.S_ISLNK(info.st_mode)
                    if linked or getattr(info, "st_file_attributes", 0) & 0x400:
                        continue
                    if stat.S_ISDIR(info.st_mode):
                        folders.append(Path(entry.path))
                    elif stat.S_ISREG(info.st_mode):
                        total += info.st_size
                except OSError:
                    errors += 1
    except OSError:
        errors += 1
    return total, folders, errors


def _observe_resources(root):
    """Metadata-only boundary observation; never follow links/reparse folders."""
    root = Path(root)
    total = 0
    errors = 0
    pending = [root]
    while pending:
        size, folders, unreadable = _directory_observation(pending.pop())
        total += size
        errors += unreadable
        pending.extend(folders)
    try:
        free = shutil.disk_usage(root).free
    except OSError:
        free = None
    return {
        "freeDiskBytes": free,
        "libraryFootprintBytes": total if not errors else None,
        "readableFootprintBytes": total,
        "coverage": "partial" if errors or free is None else "observed",
        "unreadableEntries": errors,
        "observedAt": now_iso(),
    }


def _count(value, name):
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{name} must be a nonnegative integer")
    return value


class Progress:
    """A busy worker owns admissions; this reporter never grants completion."""

    def __init__(
        self,
        store,
        operation_name,
        *,
        emit=True,
        interval=1.0,
        clock=time.monotonic,
        observe_resources=True,
    ):
        if (
            not isinstance(interval, (int, float))
            or not math.isfinite(interval)
            or interval <= 0
        ):
            raise ValueError("Heartbeat interval must be finite and positive")
        self.store = store
        self.operation_id = uuid4().hex
        self.phase = operation_name
        self._emit = emit
        self._observe_resources = observe_resources
        self._interval = interval
        self._clock = clock
        self._started = clock()
        self._phase_started = self._started
        self._completed = 0
        self._total = None
        self._current = None
        self._reused = 0
        self._failed = 0
        self._sequence = 0
        self._status = "running"
        self._resources = {
            "coverage": "not-observed",
            "freeDiskBytes": None,
            "libraryFootprintBytes": None,
        }
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._heartbeat, daemon=True)
        self._entered = False
        self._closed = False
        self._report = None
        self._report_ref = None

    @property
    def cancelled(self):
        """Read the native control record; failures propagate to admission owners."""
        return self.store.cancelled(self.operation_id)

    def __enter__(self):
        if self._entered:
            raise RuntimeError("A progress context cannot be entered twice")
        self._entered = True
        self._tick()
        if self._emit:
            self._thread.start()
        try:
            resources = (
                _observe_resources(self.store.root)
                if self._observe_resources
                else self._resources
            )
        except BaseException:
            self.__exit__(*sys.exc_info())
            raise
        with self._lock:
            self._resources = resources
        return self

    def __exit__(self, _exc_type, _exc_value, _traceback):
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join(timeout=2.0)
        self._closed = True
        return False

    def _heartbeat(self):
        while not self._stop.wait(self._interval):
            self._tick()

    def _estimate(self, elapsed):
        if self._total is None:
            return None, None, "Total is still unknown"
        if self._completed > self._total:
            return (
                None,
                None,
                "Discovery changed; completed count exceeds the current total",
            )
        if not self._total:
            return None, None, "No work has been discovered"
        percent = round(self._completed / self._total * 100, 1)
        if not self._completed or elapsed <= 0:
            return (
                percent,
                None,
                "Not enough measured progress to estimate remaining time",
            )
        remaining = elapsed / self._completed * (self._total - self._completed)
        return percent, {"lower": remaining * 0.5, "upper": remaining * 1.5}, None

    def _tick(self, cancelled=None):
        if cancelled is None:
            try:
                cancelled = self.cancelled
            except (OSError, ValueError):
                cancelled = None
        with self._lock:
            self._sequence += 1
            event = self._event(cancelled)
            if self._emit and not self._closed:
                self._write_event(event)
            return event

    def _event(self, cancelled):
        elapsed = max(0.0, self._clock() - self._started)
        phase_elapsed = max(0.0, self._clock() - self._phase_started)
        percent, eta, reason = self._estimate(phase_elapsed)
        status = (
            "cancelling" if cancelled and self._status == "running" else self._status
        )
        return {
            "operationId": self.operation_id,
            "libraryId": getattr(self, "library_id", None),
            "sequence": self._sequence,
            "phase": self.phase,
            "status": status,
            "current": self._current,
            "completed": self._completed,
            "total": self._total,
            "elapsedSeconds": elapsed,
            "percent": percent,
            "etaSeconds": eta,
            "estimateBasis": "Approximate range from observed phase progress"
            if eta is not None
            else None,
            "estimateReason": reason,
            "reused": self._reused,
            "failed": self._failed,
            "cancelled": cancelled,
            "cancellationCoverage": "observed"
            if cancelled is not None
            else "unavailable",
            "resources": deepcopy(self._resources),
            "timestamp": now_iso(),
        }

    def _write_event(self, event):
        total = "unknown" if event["total"] is None else str(event["total"])
        human = f"{event['phase']}: {event['completed']}/{total} | {event['elapsedSeconds']:.1f}s elapsed | {event['status']}"
        if event["current"] is not None:
            human += f" | current {event['current']}"
        eta = event["etaSeconds"]
        if eta is None:
            human += " | remaining time unknown"
        else:
            human += f" | estimated remaining {eta['lower']:.1f}-{eta['upper']:.1f}s"
        try:
            print(human, file=sys.stderr, flush=True)
            print(
                "AVO_JSON " + json.dumps(event, ensure_ascii=False, allow_nan=False),
                file=sys.stderr,
                flush=True,
            )
        except OSError:
            # A closed output pipe must not replace the worker's outcome.
            self._emit = False

    def update(
        self,
        completed=None,
        total=None,
        current=None,
        reused=0,
        failed=0,
        phase=None,
        cancelled=None,
    ):
        """Set absolute completion/total; add reuse/failure deltas to cumulative counts.

        None keeps existing values. A new phase resets its completed/total/current
        observations before applying this update, and refreshes boundary resources.
        """
        resources = None
        if phase is not None and phase != self.phase:
            resources = (
                _observe_resources(self.store.root)
                if self._observe_resources
                else self._resources
            )
        with self._lock:
            if self._report is not None or self._closed:
                raise RuntimeError("Finished progress cannot be updated")
            if resources is not None:
                self.phase = phase
                self._phase_started = self._clock()
                self._completed, self._total, self._current = 0, None, None
                self._resources = resources
            if completed is not None:
                self._completed = _count(completed, "completed")
            if total is not None:
                self._total = _count(total, "total")
            if current is not None:
                self._current = current
            self._reused += _count(reused, "reused")
            self._failed += _count(failed, "failed")
        return self._tick(cancelled)

    def finish(
        self, status="ok", estimates=None, counts=None, usage=None, remaining=None
    ):
        if self._report_ref is not None:
            return deepcopy(self._report_ref)
        resources = (
            _observe_resources(self.store.root)
            if self._observe_resources
            else self._resources
        )
        with self._lock:
            if self._report is None:
                outcomes = {
                    "completed": self._completed,
                    "total": self._total,
                    "reused": self._reused,
                    "failed": self._failed,
                    **(counts or {}),
                }
                resources.update(
                    {
                        "createdBytes": outcomes.get("createdBytes"),
                        "movedBytes": outcomes.get("movedBytes"),
                        "byteAccountingReason": "Only caller-observed created/moved bytes are counted",
                    }
                )
                self._report = {
                    "operationId": self.operation_id,
                    "phase": self.phase,
                    "status": status,
                    "elapsedSeconds": max(0.0, self._clock() - self._started),
                    "estimates": deepcopy(estimates or {}),
                    "counts": deepcopy(outcomes),
                    "resources": resources,
                    "usage": deepcopy(usage)
                    if usage is not None
                    else {
                        "tokens": None,
                        "amount": None,
                        "currency": None,
                        "coverage": "unavailable",
                        "reason": "No attributable usage supplied",
                    },
                    "remaining": deepcopy(remaining or []),
                }
            report = deepcopy(self._report)
        ref = self.store.put("report", report)
        with self._lock:
            self._report_ref = ref
            self._resources = report["resources"]
            self._status = report["status"]
            self._stop.set()
        self._tick()
        return deepcopy(ref)
