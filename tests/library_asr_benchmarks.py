"""Opt-in real CPU inference contention, never simulated worker-load evidence."""

from __future__ import annotations

import math
import sys
import threading
import time
import wave
from array import array
from copy import deepcopy
from itertools import pairwise
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from avo.library.progress import Progress
from avo.transcribe import LocalTranscriber, source_fingerprint
from library_benchmarks import _metric, baseline_report, native_cli, save_report

NATIVE_METHODS = {"encode", "generate", "align", "detect_language"}


def native_overlap(sample, intervals):
    covered = 0.0
    ending = sample["start"]
    for interval in sorted(intervals, key=lambda item: item["start"]):
        if interval.get("status") != "ok" or interval.get("kind") not in NATIVE_METHODS:
            continue
        start = max(ending, sample["start"], interval["start"])
        end = min(sample["end"], interval["end"])
        if end > start:
            covered += end - start
            ending = end
    return covered


def _resource_proof(evidence):
    checks = [
        evidence.get("workers") == 1,
        type(evidence.get("cpuThreads")) is int and 1 <= evidence["cpuThreads"] <= 4,
        str(evidence.get("nativeModelType", "")).startswith("ctranslate2."),
        evidence.get("initialActivitySeconds", float("inf")) <= 2,
        evidence.get("maximumHeartbeatGapSeconds", float("inf")) <= 5,
        evidence.get("cancellationAcknowledgedSeconds", float("inf")) <= 2,
        evidence.get("admissionsAfterAcknowledgement") == 0,
        not evidence.get("errors"),
    ]
    return all(checks)


def actual_load_verified(evidence):
    if not _resource_proof(evidence):
        return False
    samples = evidence.get("sampleIntervals", [])
    intervals = evidence.get("nativeIntervals", [])
    if len(samples) < 30 or not intervals:
        return False
    loaded = evidence.get("modelLoadedAt", float("inf"))
    return all(
        sample["start"] >= loaded
        and sample["end"] > sample["start"]
        and native_overlap(sample, intervals) > 0
        for sample in samples
    )


def _tone_file(root, seconds=30):
    target = Path(root) / f"edit/library/cache/asr-load/{uuid4().hex}/tone.wav"
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        raise FileExistsError("Use a fresh ASR benchmark tone path")
    cycle = array(
        "h",
        (
            int(8000 * math.sin(2 * math.pi * 440 * index / 16000))
            for index in range(16000)
        ),
    )
    if sys.byteorder != "little":
        cycle.byteswap()
    with wave.open(str(target), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(16000)
        output.writeframes(cycle.tobytes() * seconds)
    return target


class NativeCalls:
    """Observe pass-through CTranslate2 calls, not model-load/thread status."""

    def __init__(self, model):
        self.original = model
        self.model_type = f"{type(model).__module__}.{type(model).__name__}"
        if not self.model_type.startswith("ctranslate2."):
            raise TypeError("Actual native CTranslate2 model is required")
        self.intervals = []
        self.active = threading.Event()

    def __getattr__(self, name):
        original = getattr(self.original, name)
        if name not in NATIVE_METHODS:
            return original

        def invoke(*args, **kwargs):
            started = time.perf_counter()
            status = "failed"
            self.active.set()
            try:
                result = original(*args, **kwargs)
                status = "ok"
                return result
            finally:
                self.intervals.append(
                    {
                        "kind": name,
                        "start": started,
                        "end": time.perf_counter(),
                        "status": status,
                    }
                )
                self.active.clear()

        return invoke


class ActualLoad:
    def __init__(self, runtime, audio, fingerprint, progress):
        self.runtime = runtime
        self.calls = NativeCalls(runtime.model.model)
        runtime.model.model = self.calls
        self.audio, self.fingerprint, self.progress = audio, fingerprint, progress
        self.stop = threading.Event()
        self.admission = threading.Lock()
        self.attempts, self.errors = [], []
        self.thread = threading.Thread(target=self._run, daemon=True)

    def _run(self):
        while not self.stop.is_set():
            with self.admission:
                if self.stop.is_set() or self.progress.cancelled:
                    break
                attempt = {
                    "admittedAt": time.perf_counter(),
                    "number": len(self.attempts) + 1,
                }
                self.attempts.append(attempt)
            self.progress.update(
                completed=len(self.attempts) - 1,
                current=f"native inference attempt {attempt['number']}",
            )
            try:
                self.runtime.transcribe_audio(
                    self.audio,
                    self.fingerprint,
                    source_start=0,
                    analysis_provenance={
                        "kind": "generated-tone-benchmark",
                        "vadFilter": False,
                    },
                )
                attempt["completedAt"] = time.perf_counter()
            except Exception as exc:
                self.errors.append(f"{type(exc).__name__}: {exc}")
                self.stop.set()

    def ready(self):
        deadline = time.monotonic() + 60
        while not self.calls.active.wait(0.05):
            if self.errors or not self.thread.is_alive() or time.monotonic() > deadline:
                raise RuntimeError(
                    f"Native inference did not become active: {self.errors}"
                )

    def cancel(self):
        started = time.perf_counter()
        with self.admission:
            self.progress.store.cancel(self.progress.operation_id)
            self.stop.set()
        acknowledged = time.perf_counter()
        self.thread.join(timeout=120)
        if self.thread.is_alive():
            raise RuntimeError(
                "Current native inference did not settle after cancellation"
            )
        return started, acknowledged


def _load_runtime(model_dir):
    started = time.perf_counter()
    runtime = LocalTranscriber(
        model="small",
        model_dir=Path(model_dir),
        device="cpu",
        compute_type="int8",
        num_workers=1,
        cpu_threads=4,
        language="en",
    )
    return runtime, time.perf_counter() - started, time.perf_counter()


def _evidence(
    load, events, samples, loaded, model_seconds, cancellation, operation_started
):
    cancelled, acknowledged = cancellation
    gaps = [
        right["elapsedSeconds"] - left["elapsedSeconds"]
        for left, right in pairwise(events)
    ]
    return {
        "nativeModelType": load.calls.model_type,
        "cpuThreads": 4,
        "workers": 1,
        "device": "cpu",
        "computeType": "int8",
        "model": "small",
        "modelLoadSeconds": model_seconds,
        "modelLoadedAt": loaded,
        "nativeIntervals": load.calls.intervals,
        "sampleIntervals": samples[5:],
        "initialActivitySeconds": events[0]["benchmarkMonotonic"] - operation_started,
        "maximumHeartbeatGapSeconds": max(gaps, default=0),
        "cancellationRequestedAt": cancelled,
        "cancellationAcknowledgedAt": acknowledged,
        "cancellationAcknowledgedSeconds": acknowledged - cancelled,
        "admissionsAfterAcknowledgement": sum(
            item["admittedAt"] > acknowledged for item in load.attempts
        ),
        "attempts": load.attempts,
        "errors": load.errors,
        "heartbeatEvents": events,
        "vadFilter": False,
        "sourceKind": "generated-real-PCM-tone",
        "sourceDurationSeconds": 30,
        "speechAccuracyEvaluated": False,
        "timingBoundaries": {
            "sampleIntervals": "native-cli-process-start-through-parsed-final-json",
            "initialActivitySeconds": "in-process-Progress-invocation-through-first-event",
            "cancellationAcknowledgedSeconds": "in-process-store-cancel-through-durable-return",
            "modelLoadSeconds": "LocalTranscriber-construction-through-prepared-model-loaded",
        },
    }


def actual_asr_baseline(service, manifest, environment, *, model_dir):
    operation_started = time.perf_counter()
    if any(
        service.store.path(f"edit/cleanup/{name}").exists()
        for name in ("cleanup-result.json", "preservation-result.json")
    ):
        raise ValueError("Closed roots cannot host mutable benchmarks")
    events, samples = [], []
    progress = Progress(service.store, "real-asr-contention", interval=0.5)
    with (
        patch.object(
            progress,
            "_write_event",
            side_effect=lambda event: events.append(
                {**deepcopy(event), "benchmarkMonotonic": time.perf_counter()}
            ),
        ),
        progress,
    ):
        source = _tone_file(service.root)
        fingerprint = source_fingerprint(source)
        # Model evidence/loading is visible preparation, excluded from query samples.
        model_fingerprint = source_fingerprint(Path(model_dir) / "model.bin")
        runtime, model_seconds, loaded = _load_runtime(model_dir)
        load = ActualLoad(runtime, source, fingerprint, progress)
        load.thread.start()

        def query():
            started = time.perf_counter()
            result = native_cli(service, "search", query="xpto", mode="speech")
            samples.append(
                {
                    "start": started,
                    "end": time.perf_counter(),
                    "returned": len(result["results"]),
                }
            )

        try:
            metrics = {
                "searchUnderActualASR": _metric(
                    query,
                    2.0,
                    "prepared-sqlite-projection-warm-native-cli",
                    ready=load.ready,
                )
            }
        finally:
            cancellation = load.cancel()
        progress.finish(
            status="cancelled", counts={"nativeAttempts": len(load.attempts)}
        )
    evidence = _evidence(
        load, events, samples, loaded, model_seconds, cancellation, operation_started
    )
    evidence["modelArtifact"] = model_fingerprint
    report = baseline_report(
        "F2-actual-local-ASR-contention",
        manifest,
        environment,
        metrics,
        observations={"actualASR": evidence, "audioSource": fingerprint},
        active_load="actual-local-asr",
    )
    return report, save_report(service.root, report)
