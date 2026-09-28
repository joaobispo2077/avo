from __future__ import annotations

import importlib.util
import json
import shutil
from pathlib import Path

import pytest

from avo.adapters.media.still_extract import StillExtractAdapter
from avo.timeline.contracts import file_fingerprint, validate_document
from avo.timeline.stills import StillExtractionService


def _builder(path: Path):
    spec = importlib.util.spec_from_file_location("iteration_fixture_builder", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg and ffprobe are required",
)
def test_source_program_current_and_approved_candidate_extraction(
    tmp_path: Path,
    footage_project_factory,
    iteration_proofing_fixture_dir: Path,
):
    staging = tmp_path / "synthetic"
    _builder(iteration_proofing_fixture_dir / "build_fixtures.py").build_fixture_set(
        staging, only={"proof-ancestry"}
    )
    workspace = footage_project_factory(video_id="still-runtime")
    source = workspace.raw_dir / "raw" / "camera.mp4"
    source.parent.mkdir(parents=True)
    source.write_bytes((staging / "original-source.mp4").read_bytes())
    fingerprint = file_fingerprint(source)
    workspace.store("cmap").append_revision(
        snapshot={
            "sources": [
                {
                    "sourceId": "camera",
                    "kind": "raw",
                    "locator": str(source),
                    "fingerprint": fingerprint,
                }
            ],
            "segments": [
                {
                    "segmentId": "segment-one",
                    "sourceId": "camera",
                    "in": {
                        "ticks": 0,
                        "timebase": {"num": 1, "den": 12},
                        "domain": "raw-source",
                        "sourceId": "camera",
                    },
                    "out": {
                        "ticks": 24,
                        "timebase": {"num": 1, "den": 12},
                        "domain": "raw-source",
                        "sourceId": "camera",
                    },
                    "reason": "synthetic source",
                }
            ],
        },
        actor="agent",
        reason="still fixture",
    )
    service = StillExtractionService(workspace, adapter=StillExtractAdapter())
    raw_record = service.extract(
        purpose="reference",
        source_id="camera",
        source_time_num=1,
        source_time_den=2,
    )
    program_record = service.extract(
        purpose="review",
        program_frame=6,
        frame_rate={"num": 12, "den": 1},
    )
    current_record = service.extract(
        purpose="reference",
        candidate=source,
        candidate_frame=7,
        candidate_state="current",
        candidate_sha256=fingerprint["sha256"],
    )
    approved_record = service.extract(
        purpose="thumbnail",
        candidate=source,
        candidate_frame=8,
        candidate_state="approved",
        candidate_sha256=fingerprint["sha256"],
        width=64,
    )
    assert [
        raw_record["inputKind"],
        program_record["inputKind"],
        current_record["inputKind"],
        approved_record["inputKind"],
    ] == [
        "raw-source",
        "program",
        "current-candidate",
        "approved-candidate",
    ]
    for record in (
        raw_record,
        program_record,
        current_record,
        approved_record,
    ):
        validate_document(record, "avo.still-extraction.schema.json")
        assert Path(record["output"]["locator"]).is_file()
        record_path = (
            Path(record["output"]["locator"]).parent
            / "records"
            / (record["extractionId"] + ".json")
        )
        assert json.loads(record_path.read_text(encoding="utf-8")) == record

    approved_probe = StillExtractAdapter().probe(
        Path(approved_record["output"]["locator"])
    )
    assert approved_probe["stream"]["width"] == 64
    assert approved_record["colorPolicy"]["conversionParameters"]["outputWidth"] == 64

    again = service.extract(
        purpose="thumbnail",
        candidate=source,
        candidate_frame=8,
        candidate_state="approved",
        candidate_sha256=fingerprint["sha256"],
    )
    assert approved_record["extractionId"].endswith("v001")
    assert again["extractionId"].endswith("v002")

    Path(approved_record["output"]["locator"]).unlink()
    Path(again["output"]["locator"]).unlink()
    after_cleanup = service.extract(
        purpose="thumbnail",
        candidate=source,
        candidate_frame=8,
        candidate_state="approved",
        candidate_sha256=fingerprint["sha256"],
    )
    assert after_cleanup["extractionId"].endswith("v003")
