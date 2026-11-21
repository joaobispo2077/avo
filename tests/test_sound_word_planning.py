"""A claimed word point cannot substitute for current retained word evidence."""

from copy import deepcopy
from fractions import Fraction

import pytest

from avo.timeline.contracts import content_hash
from avo.timeline.sound_planning import derive_sound_opportunities
from tests.test_sound_opportunities import plan
from tests.test_sound_opportunities import workspace as opportunity_workspace
from tests.test_sound_source_anchors import source_intent
from tests.test_timeline_import_layout import placed_snapshot

workspace = pytest.fixture(name="workspace")(opportunity_workspace.__wrapped__)


def spoken_intent():
    selected = source_intent()
    selected["sourceAnchor"]["spokenEvidence"] = {
        "analysisRef": {
            "locator": "documents/pinned-analysis.json",
            "sha256": "b" * 64,
        },
        "wordIndex": 0,
        "wordHash": "c" * 64,
        "selectionHash": "d" * 64,
    }
    return selected


def test_claimed_word_time_stays_unresolved_without_current_word_evidence(
    workspace, monkeypatch
):
    (record,) = derive_sound_opportunities(
        plan(workspace, monkeypatch),
        [spoken_intent()],
        frame_rate=Fraction(24),
        program_end_frame=96,
        cmap=placed_snapshot(),
    )
    assert record["opportunity"] is None
    assert record["recommendation"] == "unresolved"
    assert any("word" in issue for issue in record["issues"])


def test_resolved_word_time_is_frozen_and_requires_no_manual_cue_phase(
    workspace, monkeypatch
):
    selected = spoken_intent()
    selected["sourceAnchor"].pop("sourceTime")
    resolved = deepcopy(selected["sourceAnchor"])
    resolved["sourceTime"] = {"ticks": 6, "timebase": {"num": 1, "den": 24}}
    (record,) = derive_sound_opportunities(
        plan(workspace, monkeypatch),
        [selected],
        frame_rate=Fraction(24),
        program_end_frame=96,
        cmap=placed_snapshot(),
        spoken={content_hash(selected["sourceAnchor"]): {"anchor": resolved}},
    )
    assert record["opportunity"]["programFrame"] == 30
    assert record["opportunity"]["sourceAnchor"] == resolved


def test_unresolved_word_request_does_not_require_an_invented_missing_file(
    tmp_path, monkeypatch
):
    from avo.timeline import sound_word_evidence
    from avo.timeline.motion_retention import retained_motion_files
    from avo.timeline.sound_planning import SoundPlanningService
    from tests.test_sound_proposals import prepared

    workspace, catalogue, request = prepared(tmp_path)
    cmap = workspace.store("cmap").load()["revisions"][-1]["snapshot"]
    request["intents"][0].pop("phase")
    request["intents"][0]["sourceAnchor"] = {
        "sourceId": cmap["sources"][0]["sourceId"],
        "sourceSha256": cmap["sources"][0]["fingerprint"]["sha256"],
        "segmentId": cmap["segments"][0]["segmentId"],
        "spokenEvidence": {
            "analysisRef": {
                "locator": "documents/source-analysis/missing.json",
                "sha256": "b" * 64,
            },
            "wordIndex": 0,
        },
    }
    monkeypatch.setattr(
        sound_word_evidence, "workspace_speech_dependencies", lambda ws: {}
    )
    shown = SoundPlanningService(workspace, catalogue=catalogue).propose(request)
    record = shown["proposal"]["opportunities"][0]
    assert record["opportunity"] is None and record["recommendation"] == "unresolved"
    assert retained_motion_files(workspace)
