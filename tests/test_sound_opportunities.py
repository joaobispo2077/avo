"""Sound opportunities derive from current cue parts, never a second timeline."""

from copy import deepcopy
from fractions import Fraction

import pytest

from avo.timeline.motion_review import MotionReviewService
from avo.timeline.sound_planning import SoundPlanningError, derive_sound_opportunities
from tests.test_motion_review_projection import cue, install
from tests.test_motion_review_projection import workspace as review_workspace

workspace = pytest.fixture(name="workspace")(review_workspace.__wrapped__)


def intent(**changes):
    return {
        "eventId": "sound-mo04",
        "itemId": "mo04",
        "kind": "reveal",
        "purpose": "Support the visible comparison",
        "role": "main",
        "visibility": "visible",
        "motionCharacter": "accent",
        "phase": 0.5,
        "material": "metallic",
        "strength": "subtle",
        "query": "short bright metallic whoosh",
        **changes,
    }


def plan(workspace, monkeypatch, *, split=False, context=None):
    first = cue("cue-first", ticks=24)
    first["contentRef"].update(itemId="mo04", componentId="comparison-card")
    cues = [first]
    if split:
        last = cue("cue-last", ticks=48)
        last["contentRef"].update(itemId="mo04", componentId="comparison-card")
        cues.append(last)
    install(workspace, monkeypatch, {"bmap": {"cues": cues}})
    return MotionReviewService(workspace).project(context)


def test_opportunity_keeps_canonical_frame_interval_and_source_context(
    workspace, monkeypatch
):
    snapshot = plan(
        workspace,
        monkeypatch,
        context={
            "proposal": {
                "items": [
                    {
                        "itemId": "mo04",
                        "spokenTrigger": {
                            "wordId": "word-one",
                            "sourceId": "raw-camera",
                        },
                    }
                ]
            }
        },
    )
    before = deepcopy(snapshot)
    (record,) = derive_sound_opportunities(
        snapshot, [intent()], frame_rate=Fraction(24), program_end_frame=72
    )
    event = record["opportunity"]
    assert event["visibleRange"] == {"startFrame": 24, "endFrameExclusive": 36}
    assert event["programFrame"] == 30
    assert event["cueId"] == "cue-first"
    assert event["material"] == "metallic" and event["strength"] == "subtle"
    assert record["recommendation"] == "audition"
    assert record["origin"]["componentRef"] == "comparison-card"
    assert record["origin"]["anchor"]["spokenTrigger"]["wordId"] == "word-one"
    assert record["silenceAllowed"] is True
    assert snapshot == before


@pytest.mark.parametrize(
    "changes",
    [
        {"visibility": "hidden"},
        {"visibility": "unknown"},
        {"motionCharacter": "slow"},
        {"motionCharacter": "background"},
        {"motionCharacter": "static"},
        {"choice": "silence"},
    ],
)
def test_non_accent_motion_does_not_force_a_sound(workspace, monkeypatch, changes):
    snapshot = plan(workspace, monkeypatch)
    (record,) = derive_sound_opportunities(
        snapshot, [intent(**changes)], frame_rate=Fraction(24), program_end_frame=72
    )
    assert record["recommendation"] == "silence"
    assert record["silenceAllowed"] is True


def test_split_item_needs_an_explicit_canonical_part(workspace, monkeypatch):
    snapshot = plan(workspace, monkeypatch, split=True)
    (unresolved,) = derive_sound_opportunities(
        snapshot, [intent()], frame_rate=Fraction(24), program_end_frame=72
    )
    assert unresolved["opportunity"] is None
    assert unresolved["recommendation"] == "unresolved"
    assert "ambiguous-cue" in unresolved["issues"]
    (selected,) = derive_sound_opportunities(
        snapshot,
        [intent(cueId="cue-last")],
        frame_rate=Fraction(24),
        program_end_frame=72,
    )
    assert selected["opportunity"]["visibleRange"] == {
        "startFrame": 48,
        "endFrameExclusive": 60,
    }


def test_missing_removed_and_out_of_program_items_stay_unresolved(
    workspace, monkeypatch
):
    snapshot = plan(workspace, monkeypatch)
    (missing,) = derive_sound_opportunities(
        snapshot,
        [intent(itemId="missing")],
        frame_rate=Fraction(24),
        program_end_frame=72,
    )
    (outside,) = derive_sound_opportunities(
        snapshot, [intent()], frame_rate=Fraction(24), program_end_frame=30
    )
    assert missing["recommendation"] == outside["recommendation"] == "unresolved"
    assert missing["opportunity"] is outside["opportunity"] is None


def test_no_selected_intents_add_no_effects_or_media_work(workspace, monkeypatch):
    snapshot = plan(workspace, monkeypatch)

    def forbidden(*args, **kwargs):
        pytest.fail("Opportunity planning inspected a source or runtime")

    monkeypatch.setattr("avo.timeline.contracts.file_fingerprint", forbidden)
    before = {p: p.read_bytes() for p in workspace.raw_dir.rglob("*") if p.is_file()}
    assert (
        derive_sound_opportunities(
            snapshot, [], frame_rate=Fraction(24), program_end_frame=72
        )
        == []
    )
    assert {
        p: p.read_bytes() for p in workspace.raw_dir.rglob("*") if p.is_file()
    } == before


@pytest.mark.parametrize(
    "bad", ["duplicates", "unknown", "boolean-phase", "unsafe-query"]
)
def test_invalid_intent_sets_fail_before_derivation(workspace, monkeypatch, bad):
    snapshot = plan(workspace, monkeypatch)
    selected = [intent()]
    if bad == "duplicates":
        selected.append(intent())
    elif bad == "unknown":
        selected[0]["extraClock"] = 0
    elif bad == "boolean-phase":
        selected[0]["phase"] = True
    else:
        selected[0]["query"] = "x" * 513
    with pytest.raises(SoundPlanningError):
        derive_sound_opportunities(
            snapshot, selected, frame_rate=Fraction(24), program_end_frame=72
        )
