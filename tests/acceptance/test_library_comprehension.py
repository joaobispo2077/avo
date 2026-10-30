"""Validate supplied real participant evidence; never manufacture a study."""

import json
import os
from pathlib import Path

import pytest


@pytest.mark.skipif(
    not os.environ.get("AVO_LIBRARY_STUDY_FILE"),
    reason="Requires actual five-person comprehension study results",
)
def test_five_creators_can_read_the_folder_proposal():
    result = json.loads(
        Path(os.environ["AVO_LIBRARY_STUDY_FILE"]).read_text(encoding="utf-8")
    )
    assert result["fixtureRecordingCount"] == 100
    assert result["fixtureSha256"] and result["proposalHash"]
    people = result["participants"]
    assert len(people) >= 5
    assert len({p["participantId"] for p in people}) == len(people)
    passed = [
        p
        for p in people
        if p["destinationCorrect"]
        and p["groupingExplained"]
        and p["conflictFound"]
        and 0 < p["elapsedSeconds"] <= 120
        and p["assistance"] is False
    ]
    assert len(passed) / len(people) >= 0.8
