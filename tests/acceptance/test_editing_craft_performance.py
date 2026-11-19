"""Opt-in synthetic metadata benchmarks; no model/render/human qualification."""

from __future__ import annotations

import builtins
import json
import math
import os
import platform
import shutil
import subprocess
import time
import wave
from copy import deepcopy
from pathlib import Path

import pytest

from avo.adapters.registry import build_sfx_catalog
from avo.sfx_catalog import SfxCatalogService, _entry_id, _revision
from avo.timeline.contracts import content_hash
from avo.timeline.motion_review import MotionReviewService
from avo.timeline.workspace import ARTIFACTS, TimelineWorkspace
from test_sfx_catalog import Facts

pytestmark = pytest.mark.skipif(
    os.environ.get("AVO_RUN_EDITING_CRAFT_PERFORMANCE") != "1",
    reason="Requires explicit metadata-performance exercise on a declared machine",
)
ATTEMPTS = 20


def _workspace(directory):
    directory.mkdir()
    project = {
        "provider": "example",
        "videoId": "performance",
        "rawDir": str(directory),
    }
    path = directory / "avo.project.json"
    path.write_text(json.dumps(project), encoding="utf-8")
    return TimelineWorkspace(
        project_path=path, project=project, raw_dir=directory, video_id="performance"
    )


def _motion_corpus(tmp_path):
    workspace = _workspace(tmp_path / "motion")
    cues, proposals = [], []
    clock = {"timebase": {"num": 1, "den": 24}, "domain": "cmap-output"}
    for index in range(150):
        identifier, section = f"mo{index:04d}", f"section-{index // 25}"
        cues.append(
            {
                "cueId": identifier,
                "kind": "animation",
                "start": {"ticks": index * 192, **clock},
                "end": {"ticks": (index + 1) * 192, **clock},
                "targetLayerId": "presenter",
                "contentRef": {
                    "itemId": identifier,
                    "sectionId": section,
                    "concept": "Explain the current mechanism",
                },
                "intent": "Clarify the explanation",
                "reason": "Synthetic benchmark",
                "reviewState": "pending",
            }
        )
        proposals.append(
            {
                "itemId": identifier,
                "label": identifier,
                "sectionId": section,
                "concept": "Explain the current mechanism",
                "purpose": "Synthetic benchmark",
                "treatment": "static",
            }
        )
    snapshots = {
        "cmap": {"durationSeconds": 1200, "segments": []},
        "bmap": {"cues": cues},
        "tracks": {
            "audioTracks": {
                "layers": [
                    {
                        "layerId": "dialogue",
                        "order": 0,
                        "role": "dialogue",
                        "regions": [],
                    }
                ]
            },
            "videoTracks": {
                "layers": [
                    {
                        "layerId": "presenter",
                        "order": 0,
                        "role": "primary",
                        "regions": [],
                    }
                ]
            },
        },
    }
    for name, snapshot in snapshots.items():
        store = workspace.store(name)
        store.initialize(
            artifact_type=name,
            artifact_id=f"performance:{name}",
            video_id=workspace.video_id,
            provider="example",
            timeline_domain=ARTIFACTS[name],
        )
        store.append_revision(
            snapshot=snapshot,
            actor="benchmark",
            reason="Synthetic saved metadata, no media proof",
        )
    context = {"proposal": {"items": proposals}}
    service = MotionReviewService(workspace)
    return service, context, content_hash({"snapshots": snapshots, "context": context})


def _sfx_corpus(tmp_path):
    workspace = _workspace(tmp_path / "sound-project")
    root = tmp_path / "sounds"
    root.mkdir()
    source = root / "seed.wav"
    with wave.open(str(source), "wb") as stream:
        stream.setparams((2, 2, 48000, 0, "NONE", "not compressed"))
        stream.writeframes(b"\x00\x08\x00\x08" * 48000)
    service = SfxCatalogService(workspace, roots={"synthetic": root}, analyzer=Facts())
    initial = service.scan(
        expected_generation=None, actor="benchmark", reason="Synthetic metadata fixture"
    )
    entries, base = [], initial["entries"][0]
    link_source = source
    for index in range(5000):
        entry = deepcopy(base)
        relative = f"{index:04d}-whoosh.wav"
        # Windows limits hard links per inode; bounded groups keep setup portable.
        if index % 1000 == 0:
            link_source = root / f"seed-part-{index // 1000}.wav"
            shutil.copyfile(source, link_source)
        os.link(link_source, root / relative)
        entry.update(relativePath=relative, entryId=_entry_id("synthetic", relative))
        entry["entryRevision"] = _revision(entry)
        entry["curation"].update(material="metal", tags=["whoosh", f"metal{index % 5}"])
        entry["rights"] = {
            "status": "licensed",
            "license": "synthetic-test-only",
            "evidenceRef": "generated fixture, no third-party asset",
            "sourceSha256": base["source"]["sha256"],
        }
        entries.append(entry)
    document = {
        **initial,
        "entries": entries,
        "operation": {
            "kind": "scan",
            "actor": "benchmark",
            "reason": "Synthetic 5000-entry saved catalogue; fixture measurements",
        },
        "coverage": {
            "complete": True,
            "processed": 5000,
            "discovered": 5000,
            "skipped": 0,
            "reason": "complete",
        },
    }
    published = service._publish(document, initial["generationId"])
    return service, root, published["generationId"]


def _forbid_execution(monkeypatch, media_roots):
    original_import, original_open = builtins.__import__, Path.open

    def forbidden(*_args, **_kwargs):
        raise AssertionError(
            "Warm metadata call attempted media/model execution or hashing"
        )

    def guarded_import(name, *args, **kwargs):
        if name.split(".")[0] in {"torch", "transformers", "cv2"}:
            forbidden()
        return original_import(name, *args, **kwargs)

    def guarded_open(path, *args, **kwargs):
        resolved = path.resolve()
        if any(resolved.is_relative_to(root.resolve()) for root in media_roots):
            forbidden()
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    monkeypatch.setattr(Path, "open", guarded_open)
    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr("avo.sfx_catalog.file_fingerprint", forbidden)
    monkeypatch.setattr("avo.timeline.contracts.file_fingerprint", forbidden)


def _record(tmp_path, case, corpus, first, measurements, limit, scope):
    machine = {
        "system": platform.system(),
        "release": platform.release(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "cpuCount": os.cpu_count(),
        "python": platform.python_version(),
    }
    p95 = sorted(measurements)[math.ceil(0.95 * len(measurements)) - 1]
    result = {
        "contractVersion": "1.0.0",
        "case": case,
        "machine": machine,
        "machineDigest": content_hash(machine),
        "corpusDigest": corpus,
        "scope": scope,
        "attempts": len(measurements),
        "warmSeconds": measurements,
        "firstQuerySeconds": first,
        "p95Seconds": p95,
        "p95Method": "nearest-rank",
        "limitSeconds": limit,
        "passed": p95 <= limit,
        "coldScope": "First query after synthetic publication; imports/setup excluded; OS/schema caches not flushed",
        "warmScope": "20 repeated metadata calls; source opens/hashes, processes and optional ML imports forbidden",
        "semanticRuntimeQualification": "not performed; no provisioned model",
        "humanSuitabilityQualification": "not performed; synthetic metadata only",
    }
    target = Path(
        os.environ.get("AVO_EDITING_CRAFT_PERFORMANCE_REPORT_DIR", str(tmp_path))
    )
    target.mkdir(parents=True, exist_ok=True)
    (target / f"{case}.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(result, sort_keys=True))
    assert p95 <= limit, (
        f"{case} p95 {p95:.3f}s exceeds {limit}s; inspect saved measurements"
    )


def test_20_minute_150_item_warm_motion_review(tmp_path, monkeypatch):
    service, context, corpus = _motion_corpus(tmp_path)
    with monkeypatch.context() as guard:
        _forbid_execution(guard, [])
        started = time.perf_counter()
        first = service.project(context)
        first_seconds = time.perf_counter() - started
        samples = []
        for _ in range(ATTEMPTS):
            started = time.perf_counter()
            result = service.project(context)
            samples.append(time.perf_counter() - started)
            assert result["snapshotHash"] == first["snapshotHash"]
            assert len(result["items"]) == len(result["storyboardCards"]) == 150
    _record(
        tmp_path,
        "motion-review-150",
        corpus,
        first_seconds,
        samples,
        10,
        {
            "durationSeconds": 1200,
            "cueCount": 150,
            "linkedCardCount": 150,
            "savedArtifactCount": 3,
            "mediaPresent": False,
        },
    )


def test_5000_indexed_sfx_warm_descriptor_search(tmp_path, monkeypatch):
    service, root, corpus = _sfx_corpus(tmp_path)
    with monkeypatch.context() as guard:
        _forbid_execution(guard, [root])
        started = time.perf_counter()
        first = service.search("whoosh metal0", filters={"rights": ["licensed"]})
        first_seconds = time.perf_counter() - started
        assert first["status"] == "ok"
        samples = []
        for index in range(ATTEMPTS):
            query = (
                "unrelated mythical instrument"
                if index % 5 == 0
                else f"whoosh metal{index % 5}"
            )
            started = time.perf_counter()
            composed = build_sfx_catalog(service.workspace, roots=service.roots)
            result = composed.search(query, filters={"rights": ["licensed"]})
            samples.append(time.perf_counter() - started)
            assert (
                result["status"] in {"ok", "no-match"}
                and result["mode"] == "descriptor"
            )
            assert result["generationId"] == corpus
    _record(
        tmp_path,
        "sfx-descriptor-5000",
        corpus,
        first_seconds,
        samples,
        5,
        {
            "entryCount": 5000,
            "queryCount": 20,
            "newRegistryServicePerAttempt": True,
            "limit": 20,
            "fixtureAnalysis": "synthetic saved measurements",
            "sourceBytes": "generated PCM fixture; no third-party media",
        },
    )
