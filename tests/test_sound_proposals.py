"""Explicit sound proposals freeze current heads, direction, options and catalogue."""

from copy import deepcopy

import pytest

from avo.editing_craft import resolve_editing_craft_selection
from avo.sfx_catalog import SfxCatalogService
from avo.timeline.bmap_service import BMapService
from avo.timeline.motion_review import MotionReviewService
from avo.timeline.sound_planning import SoundPlanningError, SoundPlanningService
from tests.test_sfx_catalog import Facts, annotate, scan
from tests.test_sound_opportunities import intent
from tests.test_timeline_bmap_service import approved_workspace, cue


def prepared(tmp_path):
    workspace, _, _ = approved_workspace(tmp_path)
    visual = cue()
    visual["contentRef"]["itemId"] = "mo04"
    BMapService(workspace).author(
        {"cues": [visual]}, actor="fixture", reason="Current visible comparison"
    )
    library = tmp_path / "sound-library"
    library.mkdir()
    (library / "whoosh.wav").write_bytes(b"synthetic metadata fixture")
    catalogue = SfxCatalogService(workspace, roots={"test": library}, analyzer=Facts())
    generation = scan(catalogue)
    entry = generation["entries"][0]
    generation = annotate(
        catalogue,
        generation["generationId"],
        entry["entryId"],
        {
            "curation": {"material": "metallic", "tags": ["short", "bright", "whoosh"]},
            "rights": {
                "status": "licensed",
                "license": "fixture",
                "evidenceRef": "rights-fixture",
            },
        },
    )
    request = {
        "contractVersion": "1.0.0",
        "operation": "propose",
        "operationId": "sound-first",
        "actor": "creator",
        "reason": "Audition one purposeful accent",
        "expectedBasis": MotionReviewService(workspace).project()["basisHeads"],
        "selection": resolve_editing_craft_selection(
            invocation={"soundMatching": {"enabled": True}}
        ),
        "expectedGeneration": generation["generationId"],
        "clock": {
            "frameRate": {"num": 24, "den": 1},
            "sampleRate": 48000,
            "programEndFrame": 24,
        },
        "intents": [intent()],
    }
    return workspace, catalogue, request


def test_proposal_freezes_audition_results_and_replays_without_new_work(
    tmp_path, monkeypatch
):
    workspace, catalogue, request = prepared(tmp_path)
    before = deepcopy(request["expectedBasis"])
    service = SoundPlanningService(workspace, catalogue=catalogue)
    result = service.propose(request)
    proposal = result["proposal"]
    assert proposal["basisHeads"] == before
    assert proposal["generationId"] == request["expectedGeneration"]
    assert proposal["options"]["effective"]["soundMatching"]["enabled"] is True
    assert proposal["opportunities"][0]["search"]["mode"] == "descriptor"
    assert len(proposal["opportunities"][0]["search"]["results"]) == 1
    assert proposal["opportunities"][0]["silenceAllowed"] is True
    assert MotionReviewService(workspace).project()["basisHeads"] == before

    def forbidden(*args, **kwargs):
        pytest.fail("An identical proposal replay repeated matching")

    monkeypatch.setattr(catalogue, "search", forbidden)
    assert (
        SoundPlanningService(workspace, catalogue=catalogue).propose(request)[
            "proposalRef"
        ]
        == result["proposalRef"]
    )


@pytest.mark.parametrize(
    "problem", ["disabled", "stale-head", "stale-generation", "clock"]
)
def test_invalid_proposals_do_not_freeze_or_publish_any_new_state(
    tmp_path, monkeypatch, problem
):
    workspace, catalogue, request = prepared(tmp_path)
    if problem == "disabled":
        request["selection"] = resolve_editing_craft_selection()
    elif problem == "stale-head":
        request["expectedBasis"]["bmap"]["sha256"] = "f" * 64
    elif problem == "stale-generation":
        request["expectedGeneration"] = "f" * 64
    else:
        request["clock"]["programEndFrame"] = 13
    before = {p: p.read_bytes() for p in workspace.raw_dir.rglob("*") if p.is_file()}

    def forbidden(*args, **kwargs):
        pytest.fail("Invalid proposal searched before validating its basis")

    monkeypatch.setattr(catalogue, "search", forbidden)
    with pytest.raises(SoundPlanningError):
        SoundPlanningService(workspace, catalogue=catalogue).propose(request)
    assert {
        p: p.read_bytes() for p in workspace.raw_dir.rglob("*") if p.is_file()
    } == before


def test_active_options_survive_future_preferences_and_budget_is_explicit(tmp_path):
    workspace, catalogue, request = prepared(tmp_path)
    service = SoundPlanningService(workspace, catalogue=catalogue)
    first = service.propose(request)
    revised = deepcopy(request)
    revised.update(
        operationId="sound-second",
        selection=resolve_editing_craft_selection(),
        maxCandidates=1,
    )
    revised["intents"].append(intent(eventId="another-event"))
    result = service.propose(revised)["proposal"]
    assert result["options"] == first["proposal"]["options"]
    assert result["coverage"]["candidates"] == 1
    assert result["opportunities"][1]["search"] is None
    assert "candidate-budget-exhausted" in result["opportunities"][1]["issues"]


def test_selected_semantic_mode_never_silently_falls_back_to_descriptors(tmp_path):
    workspace, catalogue, request = prepared(tmp_path)
    request["selection"] = resolve_editing_craft_selection(
        invocation={"soundMatching": {"enabled": True, "mode": "semantic"}}
    )
    result = SoundPlanningService(workspace, catalogue=catalogue).propose(request)[
        "proposal"
    ]
    search = result["opportunities"][0]["search"]
    assert search["mode"] == "semantic"
    assert search["status"] == "unavailable"
    assert not search["results"]


def test_invalid_matcher_output_cannot_freeze_a_new_request(tmp_path, monkeypatch):
    workspace, catalogue, request = prepared(tmp_path)
    monkeypatch.setattr(catalogue, "search", lambda *a, **k: {"results": []})
    before = {p: p.read_bytes() for p in workspace.raw_dir.rglob("*") if p.is_file()}
    with pytest.raises(SoundPlanningError):
        SoundPlanningService(workspace, catalogue=catalogue).propose(request)
    assert {
        p: p.read_bytes() for p in workspace.raw_dir.rglob("*") if p.is_file()
    } == before


def test_operation_identity_cannot_be_reused_for_revised_inputs(tmp_path):
    workspace, catalogue, request = prepared(tmp_path)
    service = SoundPlanningService(workspace, catalogue=catalogue)
    first = service.propose(request)
    changed = deepcopy(request)
    changed["intents"][0]["purpose"] = "A different creative choice"
    with pytest.raises(SoundPlanningError, match="different inputs"):
        service.propose(changed)
    assert service.propose(request)["proposalRef"] == first["proposalRef"]
