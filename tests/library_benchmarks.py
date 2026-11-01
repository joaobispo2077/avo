"""Explicit external benchmark utilities, with no work at import time."""

from __future__ import annotations

import ctypes
import hashlib
import json
import math
import os
import platform
import shutil
import sqlite3
import subprocess
import sys
import time
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from avo.library.rules import observation
from avo.library.search import _supports_fts, search_library
from avo.timeline.contracts import content_hash
from avo.timeline.store import now_iso
from avo.transcribe import build_transcript_payload, resolve_language
from library_fixtures import _external_root, large_library_data, manifest_hash


def nearest_rank(samples, percentile=0.95):
    values = sorted(samples)
    if not values or not 0 < percentile <= 1:
        raise ValueError("A percentile needs samples and a rank in (0, 1]")
    if any(
        type(value) not in (int, float) or not math.isfinite(value) or value < 0
        for value in values
    ):
        raise ValueError("Durations must be finite nonnegative numbers")
    return values[math.ceil(len(values) * percentile) - 1]


def measure(operation, *, warmups=5, samples=30, clock=time.perf_counter, ready=None):
    if (
        type(warmups) is not int
        or warmups != 5
        or type(samples) is not int
        or samples < 30
    ):
        raise ValueError(
            "Protocol requires exactly five warmups and at least thirty samples"
        )
    for _ in range(warmups):
        if ready:
            ready()
        operation()
    values = []
    for _ in range(samples):
        if ready:
            ready()
        started = clock()
        operation()
        values.append(clock() - started)
    return {
        "warmupCount": warmups,
        "sampleCount": samples,
        "samplesSeconds": values,
        "p95Seconds": nearest_rank(values),
        "maximumSeconds": max(values),
    }


def _command_version(arguments):
    try:
        result = subprocess.run(
            arguments, capture_output=True, text=True, timeout=3, check=False
        )
        return (
            result.stdout.strip().splitlines()[0]
            if result.returncode == 0 and result.stdout.strip()
            else None
        )
    except (OSError, subprocess.SubprocessError):
        return None


def _windows_memory():
    class MemoryStatus(ctypes.Structure):
        _fields_ = [
            ("length", ctypes.c_ulong),
            ("load", ctypes.c_ulong),
            *[
                (name, ctypes.c_ulonglong)
                for name in (
                    "total",
                    "available",
                    "pageTotal",
                    "pageAvailable",
                    "virtualTotal",
                    "virtualAvailable",
                    "extended",
                )
            ],
        ]

    value = MemoryStatus()
    value.length = ctypes.sizeof(value)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GlobalMemoryStatusEx.argtypes = [ctypes.POINTER(MemoryStatus)]
    kernel.GlobalMemoryStatusEx.restype = ctypes.c_int
    try:
        available = kernel.GlobalMemoryStatusEx(ctypes.byref(value))
    except OSError:
        return None, None
    if not available:
        return None, None
    return value.total, value.available


def _cpu_environment():
    model = platform.processor() or None
    allocated = os.cpu_count()
    if os.name == "nt":
        import winreg

        try:
            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"HARDWARE\DESCRIPTION\System\CentralProcessor\0",
            ) as key:
                model = winreg.QueryValueEx(key, "ProcessorNameString")[0].strip()
        except OSError:
            pass
        allocated = _windows_allocated_cpus()
    elif hasattr(os, "sched_getaffinity"):
        allocated = len(os.sched_getaffinity(0))
    return model, allocated


def _affinity_api():
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetCurrentProcess.argtypes = []
    kernel.GetCurrentProcess.restype = ctypes.c_void_p
    kernel.GetProcessAffinityMask.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_size_t),
        ctypes.POINTER(ctypes.c_size_t),
    ]
    kernel.GetProcessAffinityMask.restype = ctypes.c_int
    kernel.SetProcessAffinityMask.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
    kernel.SetProcessAffinityMask.restype = ctypes.c_int
    return kernel


def _windows_allocated_cpus():
    current, system = ctypes.c_size_t(), ctypes.c_size_t()
    kernel = _affinity_api()
    try:
        valid = kernel.GetProcessAffinityMask(
            kernel.GetCurrentProcess(), ctypes.byref(current), ctypes.byref(system)
        )
    except OSError:
        return None
    return current.value.bit_count() if valid else None


def allocate_benchmark_cpus(count=8):
    """Constrain only this disposable benchmark process, never system settings."""
    if os.name != "nt":
        raise ValueError("Native Windows benchmark CPU allocation is unavailable")
    kernel = _affinity_api()
    current, system = ctypes.c_size_t(), ctypes.c_size_t()
    if not kernel.GetProcessAffinityMask(
        kernel.GetCurrentProcess(), ctypes.byref(current), ctypes.byref(system)
    ):
        raise OSError("Cannot inspect benchmark process affinity")
    mask = _cpu_mask(current.value, count)
    if (
        not kernel.SetProcessAffinityMask(kernel.GetCurrentProcess(), mask)
        or _windows_allocated_cpus() != count
    ):
        raise OSError("Cannot enforce benchmark CPU allocation")
    return {
        "previousMask": current.value,
        "appliedMask": mask,
        "allocatedLogicalCpus": count,
    }


def _cpu_mask(current, count):
    if type(count) is not int or count < 1:
        raise ValueError("Requested allocation must be a positive integer")
    bits = [
        index
        for index in range(ctypes.sizeof(ctypes.c_size_t) * 8)
        if current & (1 << index)
    ]
    if len(bits) < count:
        raise ValueError("Requested allocation exceeds available process CPUs")
    return sum(1 << index for index in bits[:count])


def _disk_environment(root):
    disk = {
        "filesystem": None,
        "storageType": None,
        "model": None,
        "interface": None,
        "freeBytes": shutil.disk_usage(root).free,
        "volume": Path(root).anchor,
    }
    if os.name == "nt":
        disk.update(_windows_volume(root))
    return disk


def _windows_volume(root):
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetVolumeInformationW.argtypes = [
        ctypes.c_wchar_p,
        ctypes.c_wchar_p,
        ctypes.c_uint32,
        ctypes.POINTER(ctypes.c_uint32),
        ctypes.POINTER(ctypes.c_uint32),
        ctypes.POINTER(ctypes.c_uint32),
        ctypes.c_wchar_p,
        ctypes.c_uint32,
    ]
    kernel.GetVolumeInformationW.restype = ctypes.c_int
    kernel.GetDriveTypeW.argtypes = [ctypes.c_wchar_p]
    kernel.GetDriveTypeW.restype = ctypes.c_uint32
    filesystem = ctypes.create_unicode_buffer(64)
    try:
        valid = kernel.GetVolumeInformationW(
            str(Path(root).anchor),
            None,
            0,
            None,
            None,
            None,
            filesystem,
            len(filesystem),
        )
        drive_type = kernel.GetDriveTypeW(str(Path(root).anchor))
    except OSError:
        return {"filesystem": None, "driveType": None}
    return {"filesystem": filesystem.value if valid else None, "driveType": drive_type}


def environment_snapshot(root):
    model, allocated = _cpu_environment()
    total, available = _windows_memory() if os.name == "nt" else (None, None)
    with sqlite3.connect(":memory:") as connection:
        fts = _supports_fts(connection)
    environment = {
        "os": platform.system(),
        "osRelease": platform.release(),
        "osVersion": platform.version(),
        "machine": platform.machine(),
        "cpuModel": model,
        "logicalCpus": os.cpu_count(),
        "allocatedLogicalCpus": allocated,
        "totalMemoryBytes": total,
        "availableMemoryBytes": available,
        "disk": _disk_environment(root),
        "python": platform.python_version(),
        "sqlite": sqlite3.sqlite_version,
        "fts5": fts,
        "ffprobe": _command_version(["ffprobe", "-version"]),
        "browser": None,
        "powerMode": _command_version(["powercfg", "/getactivescheme"])
        if os.name == "nt"
        else None,
        "observedAt": now_iso(),
    }
    native = _native_volume_evidence(root)
    environment["nativeHardwareEvidence"] = native
    if native["coverage"] == "observed":
        data = native["data"]
        environment["osCaption"] = data["osCaption"]
        if "Windows 11" in data["osCaption"]:
            environment["osRelease"] = "11"
        environment["disk"].update(
            model=data["diskModel"],
            interface=data["busType"],
            storageType=data["mediaType"],
            diskNumber=data["diskNumber"],
        )
    return environment


def _host_deviations(environment):
    checks = [
        (environment.get("os") == "Windows", "Windows is required"),
        (str(environment.get("osRelease")) == "11", "Windows 11 was not verified"),
        (
            environment.get("allocatedLogicalCpus") == 8,
            "Exactly eight allocated logical CPUs were not verified",
        ),
        (
            (environment.get("availableMemoryBytes") or 0) >= 16 * 1024**3,
            "16 GiB available RAM was not verified",
        ),
        (bool(environment.get("cpuModel")), "CPU model is unavailable"),
        (bool(environment.get("powerMode")), "Power mode is unavailable"),
    ]
    return [reason for passed, reason in checks if not passed]


def _storage_deviations(environment):
    disk = environment.get("disk", {})
    checks = [
        (disk.get("filesystem") == "NTFS", "NTFS was not verified"),
        (
            disk.get("storageType") == "SSD",
            "Local solid-state storage was not verified",
        ),
        (bool(disk.get("model")), "Disk model is unavailable"),
        (bool(disk.get("interface")), "Disk interface is unavailable"),
    ]
    return [reason for passed, reason in checks if not passed]


def _tool_deviations(environment):
    browser = environment.get("browser") or {}
    checks = [
        (
            _supported_python(environment.get("python", "")),
            "Supported Python version was not verified",
        ),
        (environment.get("fts5") is True, "FTS5 was not verified"),
        (bool(environment.get("sqlite")), "SQLite version is unavailable"),
        (bool(browser.get("version")), "Browser version is unavailable"),
        (bool(environment.get("ffprobe")), "FFprobe version is unavailable"),
    ]
    return [reason for passed, reason in checks if not passed]


def _supported_python(version):
    try:
        return tuple(int(value) for value in version.split(".")[:2]) >= (3, 11)
    except (ValueError, AttributeError):
        return False


def _reference_deviations(environment):
    return (
        _host_deviations(environment)
        + _storage_deviations(environment)
        + _tool_deviations(environment)
    )


def capture_source_revision():
    root = Path(__file__).resolve().parents[1]
    files = [
        *sorted((root / "src/avo/library").glob("*.py")),
        root / "src/avo/cli.py",
        root / "src/avo/library_cli.py",
        root / "src/avo/engine_cli.py",
        root / "src/avo/telemetry.py",
        root / "src/avo/timeline/command_registry.py",
        root / "schemas/avo.library.schema.json",
        root / "src/avo/transcribe.py",
        root / "src/avo/timeline/contracts.py",
        root / "src/avo/timeline/store.py",
        root / "tests/library_fixtures.py",
        Path(__file__).resolve(),
        root / "tests/test_library_performance.py",
    ]
    files.extend(sorted((root / "src/avo/templates/library_review").glob("*.html")))
    files.extend(sorted((root / "src/avo/templates/library_review").glob("*.css")))
    files.extend(sorted((root / "src/avo/templates/library_review").glob("*.js")))
    asr_helper = root / "tests/library_asr_benchmarks.py"
    if asr_helper.exists():
        files.append(asr_helper)
    fingerprints = {
        file.relative_to(root).as_posix(): content_hash(
            file.read_text(encoding="utf-8")
        )
        for file in files
    }
    commit = _command_version(["git", "-C", str(root), "rev-parse", "HEAD"])
    dirty = _command_version(["git", "-C", str(root), "status", "--porcelain"])
    return {
        "commit": commit,
        "dirty": bool(dirty),
        "sourceFiles": fingerprints,
        "sourceFilesHash": content_hash(fingerprints),
    }


def _sealed(report):
    body = {key: value for key, value in report.items() if key != "reportHash"}
    return {**body, "reportHash": content_hash(body)}


def baseline_report(
    name,
    fixture,
    environment,
    measurements,
    *,
    source_revision=None,
    observations=None,
    active_load="idle",
):
    if fixture.get("sha256") and fixture["sha256"] != manifest_hash(fixture):
        raise ValueError("Fixture manifest hash differs from frozen contents")
    deviations = _reference_deviations(environment)
    passed = bool(measurements) and all(
        item["budgetPassed"] for item in measurements.values()
    )
    asr_verified = _asr_verified(active_load, observations or {})
    report = {
        "schemaVersion": 1,
        "kind": "library-performance-baseline",
        "name": name,
        "fixture": deepcopy(fixture),
        "fixtureHash": manifest_hash(fixture),
        "environment": deepcopy(environment),
        "environmentHash": content_hash(environment),
        "sourceRevision": source_revision
        if source_revision is not None
        else capture_source_revision(),
        "measurements": deepcopy(measurements),
        "observations": deepcopy(observations or {}),
        "activeLoad": active_load,
        "asrCertified": asr_verified,
        "asrAccuracyCertified": False,
        "referenceProfile": "R1",
        "referenceDeviations": deviations,
        "referenceAccepted": _reference_accepted(
            passed, deviations, active_load, asr_verified
        ),
        "hostBudgetPassed": passed,
        "createdAt": now_iso(),
    }
    return _sealed(report)


def _asr_verified(active_load, observations):
    if active_load == "idle":
        return False
    if active_load != "actual-local-asr":
        raise ValueError("Unknown benchmark load")
    from library_asr_benchmarks import actual_load_verified

    return actual_load_verified(observations.get("actualASR", {}))


def _reference_accepted(passed, deviations, active_load, asr_verified):
    return passed and not deviations and (active_load == "idle" or asr_verified)


def _validate_measurement(measurement):
    samples = measurement["samplesSeconds"]
    if (
        measurement["warmupCount"] != 5
        or measurement["sampleCount"] < 30
        or len(samples) != measurement["sampleCount"]
    ):
        raise ValueError("Incomplete measurement protocol")
    if measurement["p95Seconds"] != nearest_rank(samples) or measurement[
        "maximumSeconds"
    ] != max(samples):
        raise ValueError("Stored sample statistics disagree")
    if not measurement["cacheState"] or measurement["budgetPassed"] != (
        measurement["p95Seconds"] <= measurement["budgetSeconds"]
    ):
        raise ValueError("Stored budget or cache evidence disagrees")


def validate_report(report):
    if (
        _sealed(report) != report
        or manifest_hash(report["fixture"]) != report["fixtureHash"]
    ):
        raise ValueError("Report or fixture identity differs")
    if content_hash(report["environment"]) != report["environmentHash"]:
        raise ValueError("Environment identity differs")
    for measurement in report["measurements"].values():
        _validate_measurement(measurement)
    _validate_claims(report)


def _validate_claims(report):
    if report["referenceDeviations"] != _reference_deviations(report["environment"]):
        raise ValueError("Reference-profile coverage differs from captured hardware")
    passed = bool(report["measurements"]) and all(
        item["budgetPassed"] for item in report["measurements"].values()
    )
    asr_verified = _asr_verified(report["activeLoad"], report["observations"])
    expected = _reference_accepted(
        passed, report["referenceDeviations"], report["activeLoad"], asr_verified
    )
    if (
        report["hostBudgetPassed"] != passed
        or report["referenceAccepted"] != expected
        or report["asrCertified"] != asr_verified
    ):
        raise ValueError("Unsupported benchmark acceptance claim")


def save_report(root, report):
    validate_report(report)
    root = _external_root(root)
    folder = root / "edit/library/reports"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"benchmark-{report['reportHash']}.json"
    text = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if path.exists():
        if path.read_text(encoding="utf-8") != text:
            raise ValueError("Existing benchmark report differs")
    else:
        with path.open("x", encoding="utf-8") as output:
            output.write(text)
    return path


def space_observation(root, *, created_bytes, moved_bytes):
    if any(
        type(value) is not int or value < 0 for value in (created_bytes, moved_bytes)
    ):
        raise ValueError(
            "Created and logically moved bytes need separate nonnegative counters"
        )
    footprint = sum(
        path.stat().st_size
        for path in Path(root).rglob("*")
        if path.is_file() and not path.is_symlink()
    )
    return {
        "createdBytes": created_bytes,
        "movedBytes": moved_bytes,
        "libraryFootprintBytes": footprint,
        "freeDiskBytes": shutil.disk_usage(root).free,
        "observedAt": now_iso(),
    }


def _native_volume_evidence(root):
    drive = Path(root).drive.rstrip(":")
    unavailable = {
        "coverage": "unavailable",
        "reason": "Native selected-volume and OS inventory is unavailable",
    }
    if os.name != "nt" or len(drive) != 1 or not drive.isalpha():
        return unavailable
    script = """$ErrorActionPreference = 'Stop'
$system = Get-CimInstance Win32_OperatingSystem
$disks = @(Get-Partition -DriveLetter '{DRIVE}' | Get-Disk)
if ($disks.Count -ne 1) { throw 'Selected volume is ambiguous' }
$disk = $disks[0]
$physical = @(Get-PhysicalDisk | Where-Object { $_.FriendlyName.Trim() -eq $disk.FriendlyName.Trim() })
$media = $null
if ($physical.Count -eq 1) { $media = [string]$physical[0].MediaType }
[pscustomobject]@{osCaption=$system.Caption;diskModel=$disk.FriendlyName;diskNumber=[int]$disk.Number;busType=[string]$disk.BusType;mediaType=$media} | ConvertTo-Json -Compress
""".replace("{DRIVE}", drive)
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True,
            text=True,
            timeout=12,
            check=False,
        )
        if result.returncode:
            return unavailable
        data = json.loads(result.stdout)
    except (OSError, ValueError, subprocess.SubprocessError):
        return unavailable
    return {
        "coverage": "observed",
        "selectedDrive": drive,
        "source": "Get-Partition/Get-Disk/Get-PhysicalDisk/CIM Win32_OperatingSystem",
        "observedAt": now_iso(),
        "data": data,
    }


def _metric(operation, budget, cache_state, *, ready=None):
    measured = measure(operation, ready=ready)
    return {
        **measured,
        "budgetSeconds": budget,
        "budgetPassed": measured["p95Seconds"] <= budget,
        "cacheState": cache_state,
    }


def native_cli(service, operation, *, query=None, mode="all", recursive=False):
    """Measure callers include process startup through usable parsed final JSON."""
    if operation not in {"scan", "search"}:
        raise ValueError("Benchmark CLI supports scan/search only")
    repository = Path(__file__).resolve().parents[1]
    environment = {
        **os.environ,
        "PYTHONPATH": str(repository / "src"),
        "PYTHONUTF8": "1",
    }
    environment["AVO_ROOT"] = os.environ.get("AVO_ROOT", str(repository))
    arguments = [
        sys.executable,
        "-m",
        "avo.cli",
        "organize",
        operation,
        "--root",
        str(service.root),
        "--provider",
        service.provider,
        "--json",
    ]
    if query is not None:
        arguments.extend(["--query", query, "--mode", mode])
    if recursive:
        arguments.append("--recursive")
    result = subprocess.run(
        arguments,
        cwd=repository,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
        check=False,
    )
    if result.returncode:
        raise RuntimeError(f"Native benchmark command failed: {result.stderr[-2000:]}")
    payload = json.loads(result.stdout)
    if payload.get("status") != "ok":
        raise ValueError("Native benchmark command did not return usable success")
    return payload


def inventory_baseline(service, fixture, environment):
    if len(fixture.files) != 1000 or fixture.manifest["mediaKind"] != "playable-tone":
        raise ValueError("F1 requires 1,000 actual playable non-sparse media files")
    started = time.perf_counter()
    service.scan(recursive=True)
    preparation = time.perf_counter() - started
    fixture.probe.calls.clear()
    with (
        patch(
            "avo.library.rules.source_lock",
            side_effect=AssertionError("Warm inventory hashed media"),
        ),
        patch(
            "avo.transcribe.source_fingerprint",
            side_effect=AssertionError("Warm inventory hashed media"),
        ),
        patch(
            "avo.transcribe.LocalTranscriber",
            side_effect=AssertionError("Warm inventory loaded ASR"),
        ),
        patch(
            "avo.transcribe.transcribe_one",
            side_effect=AssertionError("Warm inventory dispatched ASR"),
        ),
    ):
        instrumented = service.scan(recursive=True)
    if fixture.probe.calls or instrumented["summary"]["reused"] != 1000:
        raise AssertionError("Unchanged inventory repeated media preparation")
    backend = _metric(lambda: service.scan(recursive=True), 10.0, "warm-saved-probes")
    measured = _metric(
        lambda: native_cli(service, "scan", recursive=True),
        10.0,
        "warm-saved-probes-native-cli",
    )
    if fixture.probe.calls:
        raise AssertionError("Measured warm inventory reprobed media")
    report = baseline_report(
        "F1-idle-warm-refresh",
        fixture.manifest,
        environment,
        {"refresh": measured},
        observations={
            "initialPreparationSeconds": preparation,
            "reusedRecordings": 1000,
            "instrumentationSeparateFromTiming": True,
            "repeatedProbeCalls": 0,
            "mediaHashCallsDuringInstrumentedRefresh": 0,
            "modelLoadsDuringInstrumentedRefresh": 0,
            "backendRefreshDiagnostic": backend,
            "measurementBoundary": "native-cli-startup-through-parsed-final-json",
        },
    )
    return report, save_report(service.root, report)


def _large_transcript(
    service, source, recording_id, words, source_observation, source_hash
):
    _, language_code, engine_language = resolve_language("en")
    payload = build_transcript_payload(
        [{"words": words}],
        {
            "path": str(source),
            "sha256": source_hash,
            "size_bytes": source_observation["sizeBytes"],
            "mtime_ns": source_observation["mtimeNs"],
        },
        "fixture-local",
        "fixture",
        language_code=language_code,
        engine_language=engine_language,
    )
    target = service.root / "edit/library/transcripts" / f"{recording_id}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    with target.open("xb") as output:
        output.write(raw)
    return {
        "path": target.relative_to(service.root).as_posix(),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "sourceSha256": source_hash,
        "model": "fixture-local",
        "requestedLanguage": "en",
        "observation": source_observation,
    }


def _large_record(service, row, words):
    source = service.root / row["path"]
    source.parent.mkdir(parents=True, exist_ok=True)
    raw = f"synthetic-library-source:{row['recordingId']}".encode()
    with source.open("xb") as output:
        output.write(raw)
    observed = observation(source)
    digest = hashlib.sha256(raw).hexdigest()
    ref = _large_transcript(
        service, source, row["recordingId"], words, observed, digest
    )
    recording = {
        "id": row["recordingId"],
        "version": "fixture-v1",
        "path": row["path"],
        "originalPath": row["path"],
        "observation": observed,
        "metadata": {"durationSeconds": row["duration"] * 2 + 1, "audio": True},
        "availability": row["availability"],
        "transcript": ref,
        "restrictions": [],
    }
    if row["availability"] == "missing":
        source.unlink()
    elif row["transcriptStatus"] == "stale":
        with source.open("ab") as output:
            output.write(b":changed")
    return recording


def prepare_large_library(
    service, *, recordings=10_000, segments=100_000, groups=100, seed=10
):
    _external_root(service.root)
    if service.store.head_path.exists():
        raise ValueError("Build F2 only in a fresh disposable library")
    data = large_library_data(
        recordings=recordings, segments=segments, groups=groups, seed=seed
    )
    by_recording = {row["recordingId"]: [] for row in data["recordings"]}
    for segment in data["segments"]:
        by_recording[segment["recordingId"]].append(
            {
                "word": segment["text"],
                "start": segment["start"] * 2,
                "end": segment["start"] * 2 + 0.8,
            }
        )
    rows = [
        _large_record(service, row, by_recording[row["recordingId"]])
        for row in data["recordings"]
    ]
    inventory = {
        "recordings": rows,
        "summary": {"total": len(rows)},
        "scope": {"recursive": True},
    }
    with service.store.exclusive():
        head = service.store.initialize()
        inv_ref = service.store.put("inventory", inventory)
        proposal = _large_proposal(data, rows, inv_ref, groups, seed)
        prop_ref = service.store.put("proposal", proposal)
        service.store.publish(
            {**head, "inventoryRef": inv_ref, "proposalRef": prop_ref}, head["headHash"]
        )
    manifest = {
        **data["manifest"],
        "mediaKind": "byte-stub",
        "transcriptKind": "synthetic-time-aligned",
        "timingScale": 2,
        "preparation": "canonical-records-projection-not-built",
    }
    manifest["sha256"] = manifest_hash(manifest)
    return manifest


def _large_proposal(data, records, inv_ref, count, seed):
    groups = [
        {
            "id": f"group-{index:03d}",
            "label": f"Group {index}",
            "path": f"group-{index:03d}",
            "rationale": "Seeded fixture group",
            "evidence": ["fixture manifest"],
        }
        for index in range(count)
    ]
    actions = [
        {
            "actionId": f"action-{index:05d}",
            "recordingId": record["id"],
            "from": record["path"],
            "to": record["path"],
            "groupId": data["recordings"][index]["groupId"],
            "status": "keep",
            "reason": "Fixture mapping",
            "sizeBytes": record["observation"]["sizeBytes"],
            "durationSeconds": record["metadata"]["durationSeconds"],
        }
        for index, record in enumerate(records)
    ]
    return {
        "proposalId": f"fixture-{seed}",
        "revision": 1,
        "parent": None,
        "inventoryRef": inv_ref,
        "groups": groups,
        "actions": actions,
        "summary": {"total": len(actions), "keep": len(actions)},
    }


def _browser_measurements(service):
    from playwright.sync_api import sync_playwright

    from avo.library.review import render_review

    head = service.store.head()
    review = render_review(
        service.root,
        service.store.get(head["proposalRef"]),
        {**head, "provider": service.provider},
    )
    with sync_playwright() as runtime:
        browser = runtime.chromium.launch(channel="msedge", headless=True)
        try:
            page = browser.new_page()
            metrics = _measure_page(page, review["html"])
            version = {"name": "Edge", "version": browser.version, "headless": True}
        finally:
            browser.close()
    return metrics, version


def _measure_page(page, path):
    def visible_frame():
        page.evaluate(
            "() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))"
        )

    def open_review():
        page.goto(path.as_uri(), wait_until="load")
        page.locator("button.file").first.wait_for(state="visible")
        visible_frame()

    opening = _metric(open_review, 2.0, "prepared-offline-review-warm-browser")
    counter = 0

    def inspect_recording():
        nonlocal counter
        page.locator("button.file").nth(counter % 100).click()
        counter += 1
        page.locator("#inspector dd").first.wait_for(state="visible")
        visible_frame()

    interaction = _metric(
        inspect_recording, 1.0, "prepared-offline-review-warm-browser"
    )
    return {"reviewOpen": opening, "reviewInteraction": interaction}


def search_baseline(service, manifest, environment, *, browser=False):
    started = time.perf_counter()
    cold = search_library(service, "xpto", mode="speech")
    preparation = time.perf_counter() - started
    counter = 0

    def query():
        nonlocal counter
        number = counter
        counter += 1
        term = (
            "xpto",
            "ação",
            "Fixture phrase",
            f"xpto 10 {number}",
            f"group-{number % 100:03d}",
        )[number % 5]
        search_library(service, term)

    backend = _metric(query, 2.0, "prepared-sqlite-projection-warm")
    counter = 0

    def cli_query():
        nonlocal counter
        number = counter
        counter += 1
        term = (
            "xpto",
            "ação",
            "Fixture phrase",
            f"xpto 10 {number}",
            f"group-{number % 100:03d}",
        )[number % 5]
        native_cli(service, "search", query=term)

    metrics = {
        "search": _metric(cli_query, 2.0, "prepared-sqlite-projection-warm-native-cli")
    }
    environment = deepcopy(environment)
    if browser:
        ui_metrics, version = _browser_measurements(service)
        metrics.update(ui_metrics)
        environment["browser"] = version
    report = baseline_report(
        "F2-idle-prepared-search",
        manifest,
        environment,
        metrics,
        observations={
            "coldProjectionSeconds": preparation,
            "searchCoverage": cold["coverage"],
            "browserMeasured": browser,
            "realSourceMedia": False,
            "realASRLoad": False,
            "uiMeasuredAtVisibleFrames": browser,
            "backendSearchDiagnostic": backend,
            "measurementBoundary": "native-cli-startup-through-parsed-final-json",
        },
    )
    return report, save_report(service.root, report)
