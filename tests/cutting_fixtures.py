"""Original, generated media and canonical workspaces for cutting tests."""

from __future__ import annotations

import json
import math
import struct
import wave
from pathlib import Path

from avo.timeline.contracts import file_fingerprint
from avo.timeline.sync_service import SyncService
from avo.timeline.workspace import TimelineWorkspace


def write_dialogue_wav(path: Path, *, sample_rate: int = 48000) -> Path:
    """Generate a tone with quiet guards, not fabricated speech ground truth."""
    samples = [
        int(8000 * math.sin(2 * math.pi * 220 * i / sample_rate))
        if sample_rate // 4 <= i < sample_rate * 3 // 4
        else 0
        for i in range(sample_rate)
    ]
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        output.writeframes(struct.pack(f"<{len(samples)}h", *samples))
    return path


def cutting_workspace(tmp_path: Path, *, enabled: bool = False):
    raw = tmp_path / "footage"
    raw.mkdir()
    project = raw / "avo.project.json"
    declaration = {"provider": "bishop", "rawDir": str(raw)}
    if enabled:
        declaration["cutting"] = {"enabled": True}
    project.write_text(json.dumps(declaration), encoding="utf-8")
    workspace = TimelineWorkspace.from_project(project, video_id="cutting-fixture")
    workspace.initialize()
    source = write_dialogue_wav(raw / "original.wav")
    sync = SyncService(workspace)
    revision = sync.author_not_applicable(
        raw_fingerprints={"dialogue": file_fingerprint(source)["sha256"]},
        actor="fixture",
        reason="generated muxed source has one clock",
    )
    evidence = sync.validate_current()
    sync.decide(
        decision="approved",
        candidate_hash=revision["contentHash"],
        evidence_bundle_hash=evidence["sha256"],
        actor="fixture-reviewer",
        reason="explicit N/A for generated source",
    )
    return workspace, source


def source_snapshot(source: Path) -> dict:
    return {
        "sources": [
            {
                "sourceId": "dialogue",
                "kind": "raw",
                "locator": str(source),
                "fingerprint": file_fingerprint(source),
                "streamMetadata": {
                    "videoStreamIndex": 0,
                    "audioSelection": {
                        "streamIndex": 0,
                        "channels": [0],
                        "sourceLayout": "mono",
                        "sourceSampleRate": 48000,
                        "outputLayout": "dual-mono",
                    },
                },
            }
        ],
        "segments": [
            {
                "segmentId": "unit-one",
                "sourceId": "dialogue",
                "in": {
                    "domain": "raw-source",
                    "sourceId": "dialogue",
                    "ticks": 0,
                    "timebase": {"num": 1, "den": 48000},
                },
                "out": {
                    "domain": "raw-source",
                    "sourceId": "dialogue",
                    "ticks": 48000,
                    "timebase": {"num": 1, "den": 48000},
                },
                "reason": "retain generated original",
            }
        ],
    }
