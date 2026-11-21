"""Explicit source points retain occurrence identity before sound is scheduled."""

from copy import deepcopy
from fractions import Fraction

import pytest

from avo.timeline import sound_anchors
from avo.timeline.sound_fitting import SoundPlanningError
from avo.timeline.sound_planning import derive_sound_opportunities
from tests.test_sound_opportunities import intent, plan
from tests.test_sound_opportunities import workspace as opportunity_workspace
from tests.test_timeline_import_layout import placed_snapshot
from tests.test_timeline_mapping import SNAPSHOT

workspace = pytest.fixture(name="workspace")(opportunity_workspace.__wrapped__)


def source_intent():
    value = intent(
        kind="click",
        sourceAnchor={
            "sourceId": "camera",
            "sourceSha256": "a" * 64,
            "placementId": "first",
            "trackId": "v1",
            "sourceTime": {"ticks": 6, "timebase": {"num": 1, "den": 24}},
        },
    )
    value.pop("phase")
    return value


def test_source_opportunity_uses_current_cmap_without_a_second_phase_clock(
    workspace, monkeypatch
):
    snapshot = plan(workspace, monkeypatch)
    selected = source_intent()
    (record,) = derive_sound_opportunities(
        snapshot,
        [selected],
        frame_rate=Fraction(24),
        program_end_frame=96,
        cmap=placed_snapshot(),
    )
    assert record["opportunity"]["programFrame"] == 30
    assert record["opportunity"]["sourceAnchor"] == selected["sourceAnchor"]
    assert record["recommendation"] == "audition"


def test_missing_source_map_stays_unresolved_instead_of_using_cue_start(
    workspace, monkeypatch
):
    snapshot = plan(workspace, monkeypatch)
    (record,) = derive_sound_opportunities(
        snapshot,
        [source_intent()],
        frame_rate=Fraction(24),
        program_end_frame=96,
    )
    assert record["opportunity"] is None
    assert record["recommendation"] == "unresolved"
    assert any("source map" in issue for issue in record["issues"])


def test_source_point_cannot_also_claim_an_independent_phase(workspace, monkeypatch):
    selected = source_intent()
    selected["phase"] = 0.5
    with pytest.raises(SoundPlanningError):
        derive_sound_opportunities(
            plan(workspace, monkeypatch),
            [selected],
            frame_rate=Fraction(24),
            program_end_frame=96,
            cmap=placed_snapshot(),
        )


def test_source_point_at_cue_end_stays_unresolved(workspace, monkeypatch):
    selected = source_intent()
    selected["sourceAnchor"]["sourceTime"]["ticks"] = 12
    (record,) = derive_sound_opportunities(
        plan(workspace, monkeypatch),
        [selected],
        frame_rate=Fraction(24),
        program_end_frame=96,
        cmap=placed_snapshot(),
    )
    assert record["recommendation"] == "unresolved"
    assert record["opportunity"] is None
    assert any("visible program range" in issue for issue in record["issues"])


def test_ordinary_intents_do_not_load_additional_source_metadata(monkeypatch):
    from avo.timeline.motion_review import MotionReviewService
    from avo.timeline.sound_planning import SoundPlanningService

    def forbidden(*args, **kwargs):
        pytest.fail("Ordinary sound intents requested additional source metadata")

    monkeypatch.setattr(MotionReviewService, "_metadata", forbidden)
    service = object.__new__(SoundPlanningService)
    assert service._source_cmap([intent()]) is None


def test_source_mapping_changes_invalidate_native_producer_identity(monkeypatch):
    from pathlib import Path

    from avo import capabilities

    path = Path(capabilities.__file__).parent / "timeline/mapping.py"
    original = Path.read_bytes
    before = capabilities._implementation_digest("mix", "ffmpeg.mix")

    def changed(file):
        result = original(file)
        return result + b"\n# changed source mapping\n" if file == path else result

    monkeypatch.setattr(Path, "read_bytes", changed)
    assert capabilities._implementation_digest("mix", "ffmpeg.mix") != before


def contiguous_context():
    cmap = deepcopy(SNAPSHOT)
    cmap["sources"] = [
        {"sourceId": "cam1", "kind": "raw", "fingerprint": {"sha256": "a" * 64}}
    ]
    repeat = deepcopy(cmap["segments"][0])
    repeat["segmentId"] = "repeat-a"
    cmap["segments"].append(repeat)
    anchor = {
        "sourceId": "cam1",
        "sourceSha256": "a" * 64,
        "segmentId": "repeat-a",
        "sourceTime": {"ticks": 2000, "timebase": {"num": 1, "den": 1000}},
    }
    return cmap, anchor


def test_contiguous_source_point_uses_the_selected_repeat_without_changing_inputs():
    cmap, anchor = contiguous_context()
    before = deepcopy((cmap, anchor))
    assert sound_anchors.source_anchor_time(anchor, cmap) == {
        "ticks": 5000,
        "timebase": {"num": 1, "den": 1000},
        "domain": "cmap-output",
    }
    assert (cmap, anchor) == before


def test_placed_source_point_uses_its_exact_active_placement_and_track():
    cmap = placed_snapshot()
    anchor = {
        "sourceId": "camera",
        "sourceSha256": "a" * 64,
        "placementId": "repeat",
        "trackId": "v1",
        "sourceTime": {"ticks": 12, "timebase": {"num": 1, "den": 24}},
    }
    assert sound_anchors.source_anchor_time(anchor, cmap) == {
        "ticks": 84,
        "timebase": {"num": 1, "den": 24},
        "domain": "cmap-output",
    }


@pytest.mark.parametrize(
    "changed",
    ["source", "fingerprint", "occurrence", "proof", "outside", "end", "duplicate"],
)
def test_wrong_or_ambiguous_source_context_never_falls_back_to_the_first_take(changed):
    cmap, anchor = contiguous_context()
    if changed == "source":
        anchor["sourceId"] = "absent"
    elif changed == "fingerprint":
        anchor["sourceSha256"] = "b" * 64
    elif changed == "occurrence":
        anchor["segmentId"] = "absent"
    elif changed == "proof":
        cmap["sources"][0]["kind"] = "derived"
    elif changed == "outside":
        anchor["sourceTime"]["ticks"] = 5000
    elif changed == "end":
        anchor["sourceTime"]["ticks"] = 3000
    else:
        cmap["segments"].append(deepcopy(cmap["segments"][-1]))
    with pytest.raises(SoundPlanningError):
        sound_anchors.source_anchor_time(anchor, cmap)


@pytest.mark.parametrize("changed", ["disabled", "wrong-track", "sampled", "still"])
def test_unavailable_or_unsupported_placed_source_time_is_explicit(changed):
    cmap = placed_snapshot()
    anchor = {
        "sourceId": "camera",
        "sourceSha256": "a" * 64,
        "placementId": "repeat",
        "trackId": "v1",
        "sourceTime": {"ticks": 12, "timebase": {"num": 1, "den": 24}},
    }
    target = cmap["layout"]["placements"][1]
    if changed == "disabled":
        target["enabled"] = False
    elif changed == "wrong-track":
        anchor["trackId"] = "v2"
    elif changed == "sampled":
        target["pictureSampling"] = "repeat-2x"
    else:
        target["mediaKind"] = "still"
    with pytest.raises(SoundPlanningError):
        sound_anchors.source_anchor_time(anchor, cmap)
