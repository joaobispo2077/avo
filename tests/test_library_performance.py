"""Cheap benchmark evidence checks; real baselines are explicitly opt-in."""

import json
import os
from copy import deepcopy

import pytest

from library_benchmarks import (
    baseline_report,
    measure,
    nearest_rank,
    save_report,
    space_observation,
    validate_report,
)


def test_measure_excludes_exactly_five_warmups_and_uses_nearest_rank():
    now = 0.0
    calls = 0

    def operation():
        nonlocal now, calls
        calls += 1
        now += 1000 if calls <= 5 else calls - 5

    measured = measure(operation, clock=lambda: now)
    assert calls == 35
    assert measured["warmupCount"] == 5
    assert measured["sampleCount"] == 30
    assert measured["samplesSeconds"] == list(range(1, 31))
    assert measured["p95Seconds"] == 29
    assert measured["maximumSeconds"] == 30
    assert nearest_rank([4, 1, 3, 2], 0.95) == 4


@pytest.mark.parametrize(
    "options", [{"warmups": 4}, {"samples": 29}, {"samples": True}]
)
def test_incomplete_measurement_protocol_is_rejected(options):
    with pytest.raises(ValueError):
        measure(lambda: None, **options)


def report_fixture():
    samples = [0.1] * 30
    measurement = {
        "warmupCount": 5,
        "sampleCount": 30,
        "samplesSeconds": samples,
        "p95Seconds": 0.1,
        "maximumSeconds": 0.1,
        "budgetSeconds": 2.0,
        "cacheState": "prepared-warm",
        "budgetPassed": True,
    }
    return baseline_report(
        "unit-evidence",
        {"seed": 10, "mediaKind": "byte-stub"},
        {"os": "Windows", "allocatedLogicalCpus": 16},
        {"search": measurement},
        source_revision={"commit": "fixture", "dirty": True},
    )


def test_unknown_or_different_hardware_cannot_claim_reference_acceptance():
    report = report_fixture()
    assert report["hostBudgetPassed"] is True
    assert report["referenceAccepted"] is False
    assert report["referenceProfile"] == "R1"
    assert report["referenceDeviations"]
    assert report["fixture"]["mediaKind"] == "byte-stub"
    assert report["activeLoad"] == "idle"
    assert report["asrCertified"] is False
    validate_report(report)


def test_cpu_allocation_uses_only_existing_process_cpus():
    from library_benchmarks import _cpu_mask

    assert _cpu_mask(0b101010, 2) == 0b001010
    for count in (0, True, 4):
        with pytest.raises(ValueError):
            _cpu_mask(0b101010, count)


def test_native_cli_boundary_uses_explicit_context_and_parses_final_json(
    tmp_path, monkeypatch, repo_root
):
    from types import SimpleNamespace

    import library_benchmarks

    captured = {}
    monkeypatch.setenv("AVO_ROOT", str(tmp_path / "install"))

    def run(arguments, **kwargs):
        captured.update(arguments=arguments, **kwargs)
        return SimpleNamespace(
            returncode=0, stdout='{"status":"ok","results":[]}', stderr=""
        )

    monkeypatch.setattr(library_benchmarks.subprocess, "run", run)
    service = SimpleNamespace(root=tmp_path / "footage", provider="example")
    assert (
        library_benchmarks.native_cli(service, "search", query="ação xpto")["results"]
        == []
    )
    assert captured["arguments"][1:5] == ["-m", "avo.cli", "organize", "search"]
    assert (
        captured["arguments"][captured["arguments"].index("--query") + 1] == "ação xpto"
    )
    assert captured["env"]["PYTHONPATH"] == str(repo_root / "src")
    assert captured["env"]["AVO_ROOT"] == str(tmp_path / "install")
    assert captured["cwd"] == repo_root


def actual_load_fixture():
    return {
        "nativeModelType": "ctranslate2._ext.Whisper",
        "cpuThreads": 4,
        "workers": 1,
        "modelLoadedAt": 1.0,
        "nativeIntervals": [
            {"kind": "encode", "start": 2.0, "end": 40.0, "status": "ok"}
        ],
        "sampleIntervals": [
            {"start": 3.0 + index, "end": 3.5 + index} for index in range(30)
        ],
        "initialActivitySeconds": 0.1,
        "maximumHeartbeatGapSeconds": 0.5,
        "cancellationAcknowledgedSeconds": 0.2,
        "admissionsAfterAcknowledgement": 0,
    }


def test_actual_load_proof_requires_native_inference_overlap_not_worker_status():
    from library_asr_benchmarks import actual_load_verified

    assert actual_load_verified(actual_load_fixture())
    without_inference = actual_load_fixture()
    without_inference["nativeIntervals"] = []
    without_inference["workerRunning"] = True
    assert not actual_load_verified(without_inference)


@pytest.mark.parametrize(
    "field,value",
    [
        ("cpuThreads", 5),
        ("workers", 2),
        ("modelLoadedAt", 100.0),
        ("initialActivitySeconds", 2.1),
        ("maximumHeartbeatGapSeconds", 5.1),
        ("cancellationAcknowledgedSeconds", 2.1),
        ("admissionsAfterAcknowledgement", 1),
        ("nativeModelType", "fixture.FakeRuntime"),
    ],
)
def test_actual_load_proof_rejects_unqualified_resources_or_timing(field, value):
    from library_asr_benchmarks import actual_load_verified

    evidence = actual_load_fixture()
    evidence[field] = value
    assert not actual_load_verified(evidence)


@pytest.mark.parametrize(
    "damage", ["fixture", "environment", "samples", "reference-claim"]
)
def test_saved_report_rejects_identity_or_measurement_tampering(damage):
    report = deepcopy(report_fixture())
    if damage == "fixture":
        report["fixture"]["seed"] = 11
    elif damage == "environment":
        report["environment"]["allocatedLogicalCpus"] = 8
    elif damage == "samples":
        report["measurements"]["search"]["samplesSeconds"][0] = 99
    else:
        report["referenceAccepted"] = True
    with pytest.raises(ValueError):
        validate_report(report)


def test_report_and_byte_observations_are_external_and_do_not_conflate_moves(tmp_path):
    report = report_fixture()
    path = save_report(tmp_path, report)
    assert path.parent == tmp_path / "edit/library/reports"
    assert json.loads(path.read_text(encoding="utf-8")) == report
    assert save_report(tmp_path, report) == path
    observed = space_observation(tmp_path, created_bytes=12, moved_bytes=100)
    assert observed["createdBytes"] == 12
    assert observed["movedBytes"] == 100
    assert observed["freeDiskBytes"] > 0
    assert observed["libraryFootprintBytes"] >= path.stat().st_size


def test_large_fixture_builder_publishes_real_canonical_transcript_references(
    tmp_path, monkeypatch
):
    from avo.library.search import search_library
    from avo.library.service import LibraryService
    from library_benchmarks import prepare_large_library
    from library_fixtures import install_provider

    install_provider(tmp_path / "install")
    monkeypatch.setenv("AVO_ROOT", str(tmp_path / "install"))
    root = tmp_path / "footage"
    root.mkdir()
    service = LibraryService(root, "example")
    manifest = prepare_large_library(service, recordings=6, segments=18, groups=3)
    inventory = service.store.get(service.store.head()["inventoryRef"])
    assert len(inventory["recordings"]) == 6
    assert manifest["mediaKind"] == "byte-stub"
    assert manifest["transcriptKind"] == "synthetic-time-aligned"
    result = search_library(service, "xpto", mode="speech")
    assert len(result["results"]) == 15
    assert result["coverage"]["speechSearchable"] == 5
    assert all(0 <= item["start"] < item["end"] for item in result["results"])


@pytest.mark.integration
@pytest.mark.skipif(
    os.environ.get("AVO_LIBRARY_BENCHMARK") != "1",
    reason="Opt-in actual external F1/F2 benchmark",
)
def test_actual_f1_unchanged_playable_inventory_baseline(tmp_path, monkeypatch):
    from avo.library.service import LibraryService
    from library_benchmarks import environment_snapshot, inventory_baseline
    from library_fixtures import install_provider, make_library

    install_provider(tmp_path / "install")
    monkeypatch.setenv("AVO_ROOT", str(tmp_path / "install"))
    fixture = make_library(tmp_path / "footage", count=1000, playable=True)
    fixture.probe.results = {
        path: {"durationSeconds": 1.0, "audio": True} for path in fixture.files
    }
    service = LibraryService(fixture.root, "example", probe=fixture.probe)
    report, path = inventory_baseline(
        service, fixture, environment_snapshot(fixture.root)
    )
    print(
        f"F1 baseline report: {path}; p95={report['measurements']['refresh']['p95Seconds']:.3f}s; R1={report['referenceAccepted']}"
    )
    assert report["hostBudgetPassed"], f"F1 inventory budget failed; evidence: {path}"


@pytest.mark.integration
@pytest.mark.skipif(
    os.environ.get("AVO_LIBRARY_BENCHMARK") != "1",
    reason="Opt-in actual external F1/F2 benchmark",
)
def test_actual_f2_prepared_search_and_optional_edge_baseline(tmp_path, monkeypatch):
    from avo.library.service import LibraryService
    from library_benchmarks import (
        environment_snapshot,
        prepare_large_library,
        search_baseline,
    )
    from library_fixtures import install_provider

    install_provider(tmp_path / "install")
    monkeypatch.setenv("AVO_ROOT", str(tmp_path / "install"))
    root = tmp_path / "footage"
    root.mkdir()
    service = LibraryService(root, "example")
    manifest = prepare_large_library(service)
    report, path = search_baseline(
        service,
        manifest,
        environment_snapshot(root),
        browser=os.environ.get("AVO_LIBRARY_BROWSER_BENCHMARK") == "1",
    )
    print(
        f"F2 baseline report: {path}; p95={report['measurements']['search']['p95Seconds']:.3f}s; R1={report['referenceAccepted']}"
    )
    assert report["hostBudgetPassed"], (
        f"F2 search/review budget failed; evidence: {path}"
    )


@pytest.mark.integration
@pytest.mark.skipif(
    os.environ.get("AVO_LIBRARY_ASR_BENCHMARK") != "1",
    reason="Opt-in actual prepared-model ASR contention",
)
def test_actual_asr_search_overlap_and_cancellation_baseline(tmp_path, monkeypatch):
    from pathlib import Path

    from avo.library.service import LibraryService
    from avo.transcribe import default_model_root
    from library_asr_benchmarks import actual_asr_baseline
    from library_benchmarks import (
        allocate_benchmark_cpus,
        environment_snapshot,
        prepare_large_library,
    )
    from library_fixtures import install_provider

    allocate_benchmark_cpus(8)
    install_provider(tmp_path / "install")
    monkeypatch.setenv("AVO_ROOT", str(tmp_path / "install"))
    root = tmp_path / "footage"
    root.mkdir()
    service = LibraryService(root, "example")
    manifest = prepare_large_library(service)
    model_dir = Path(
        os.environ.get(
            "AVO_LIBRARY_BENCHMARK_MODEL_DIR", str(default_model_root() / "small")
        )
    )
    report, path = actual_asr_baseline(
        service, manifest, environment_snapshot(root), model_dir=model_dir
    )
    print(
        f"Actual ASR report: {path}; p95={report['measurements']['searchUnderActualASR']['p95Seconds']:.3f}s; overlap={report['asrCertified']}"
    )
    assert report["asrCertified"], (
        f"Actual inference overlap or cancellation evidence failed: {path}"
    )
    assert report["hostBudgetPassed"], f"Search under actual ASR exceeds budget: {path}"
