from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from avo import shorts_plan

REQUEST = (
    Path(__file__).parents[1]
    / "fixtures"
    / "shorts"
    / "switch-comparison"
    / "shorts.request.json"
)


def load_mounted_request() -> tuple[dict, list[dict]]:
    project_value = os.environ.get("AVO_SWITCH_COMPARISON_PROJECT", "").strip()
    if not project_value:
        pytest.skip(
            "set AVO_SWITCH_COMPARISON_PROJECT to run the private Switch regression"
        )
    project_root = Path(project_value).expanduser().resolve()
    request = json.loads(REQUEST.read_text(encoding="utf-8"))
    master_name = Path(request["source"]["masterPath"]).name
    transcript_name = Path(request["source"]["transcriptPath"]).name
    request["source"]["masterPath"] = str(
        project_root / "edit" / "masters" / master_name
    )
    request["source"]["transcriptPath"] = str(
        project_root / "edit" / "transcripts" / transcript_name
    )
    insertion_value = os.environ.get("AVO_SWITCH_COMPARISON_INSERT", "").strip()
    if insertion_value:
        request["insertions"][0]["sourcePath"] = str(
            Path(insertion_value).expanduser().resolve()
        )
    transcript_path = Path(request["source"]["transcriptPath"])
    if not transcript_path.is_file():
        pytest.skip(f"approved Switch transcript is not mounted under {project_root}")
    return request, json.loads(transcript_path.read_text(encoding="utf-8"))


@pytest.mark.project
def test_switch_batch_resolves_ten_owned_outputs_and_safe_insertions() -> None:
    request, transcript = load_mounted_request()
    first = shorts_plan.resolve_batch(
        request,
        transcript,
        request_path=REQUEST,
        source_fingerprint=request["source"]["expectedFingerprint"],
    )
    second = shorts_plan.resolve_batch(
        request,
        transcript,
        request_path=REQUEST,
        source_fingerprint=request["source"]["expectedFingerprint"],
    )
    assert first["resolvedCount"] == 10
    assert [item["id"] for item in first["items"]] == [
        f"{index:02d}" for index in range(1, 11)
    ]
    assert [row["candidateId"] for row in first["insertionAllocation"]] == [
        "02",
        "04",
        "06",
    ]
    assert first["planHash"] == second["planHash"]
    for item in first["items"]:
        assert item["captions"]
        for phrase in item["captions"]:
            assert all(
                word["highlightExitSec"] <= phrase["endSec"] for word in phrase["words"]
            )
        if item["id"] in {"02", "04", "06"}:
            insertion = item["insertion"]
            assert insertion["audioStreamIndex"] == "0:a:0"
            assert item["layout"]["captionAnchor"] == "seam"
            assert all(
                5 <= segment["sourceStartSec"] < segment["sourceEndSec"] <= 46.5
                for segment in insertion["sourceTimeMap"]
            )
            assert any(
                segment["outputStartSec"] <= 42 < segment["outputEndSec"]
                for segment in insertion["sourceTimeMap"]
            )


@pytest.mark.project
def test_shared_and_per_short_fingerprints_invalidate_expected_scope() -> None:
    request, transcript = load_mounted_request()
    base = shorts_plan.resolve_batch(
        request,
        transcript,
        request_path=REQUEST,
        source_fingerprint=request["source"]["expectedFingerprint"],
    )
    request["candidates"][3]["requestedSpeed"] = 1.15
    changed = shorts_plan.resolve_batch(
        request,
        transcript,
        request_path=REQUEST,
        source_fingerprint=request["source"]["expectedFingerprint"],
    )
    changed_ids = [
        a["id"]
        for a, b in zip(base["items"], changed["items"])
        if a["inputFingerprint"] != b["inputFingerprint"]
    ]
    assert changed_ids == ["04"]
