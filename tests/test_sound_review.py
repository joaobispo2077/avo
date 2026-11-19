"""Sound choices join the built-in map without becoming visual timing authority."""

import json
from copy import deepcopy
from pathlib import Path

import pytest

from avo.timeline.contracts import (
    content_hash,
    document_hash_excluding,
    validate_document,
)
from avo.timeline.motion_review import MotionReviewService, render_html, render_text
from tests.test_sound_application import application


@pytest.fixture(scope="module")
def sound_program(tmp_path_factory):
    return application(tmp_path_factory.mktemp("sound-review"))


def report(result):
    assert result["reviewReady"] is True
    return json.loads(
        Path(result["review"]["refs"]["snapshot"]).read_text(encoding="utf-8")
    )


def test_propose_automatically_links_its_current_opportunity_to_the_storyboard(
    sound_program,
):
    _, _, _, _, _, shown = sound_program
    snapshot = report(shown)
    item = next(item for item in snapshot["items"] if item["itemId"] == "mo04")
    card = next(
        card for card in snapshot["storyboardCards"] if card["itemId"] == "mo04"
    )
    assert item["sound"] == card["sound"]
    opportunity = card["sound"]["opportunities"][0]
    assert opportunity["eventId"] == shown["proposal"]["opportunities"][0]["eventId"]
    assert opportunity["proposalRef"] == shown["proposalRef"]
    assert opportunity["recommendation"] == "audition"
    assert opportunity["silenceAllowed"] is True


def test_selected_sound_is_linked_in_pure_default_views_without_extending_picture(
    sound_program, monkeypatch
):
    workspace, _, service, probe, request, _ = sound_program
    applied = service.apply(request)
    snapshot = report(applied)
    item = next(item for item in snapshot["items"] if item["itemId"] == "mo04")
    selection = item["sound"]["selections"][0]
    assert selection["eventId"] == request["choices"][0]["eventId"]
    assert selection["applicationRef"] == applied["receipt"]["requestRef"]
    assert selection["acceptance"] == "pending-listening"
    assert selection["evidenceType"] == "authored-metadata"
    assert item["timing"]["start"]["ticks"] == 100
    assert item["timing"]["end"]["ticks"] == 400
    calls = len(probe.calls)

    def forbidden(*args, **kwargs):
        pytest.fail("Motion inspection hashed or inspected source media")

    monkeypatch.setattr("avo.timeline.contracts.file_fingerprint", forbidden)
    before = {p: p.read_bytes() for p in workspace.raw_dir.rglob("*") if p.is_file()}
    current = MotionReviewService(workspace).project()
    current_item = next(item for item in current["items"] if item["itemId"] == "mo04")
    assert current_item["sound"]["selections"] == item["sound"]["selections"]
    assert len(probe.calls) == calls
    assert selection["eventId"] in render_text(current)
    assert selection["eventId"] in render_html(current)
    assert {
        p: p.read_bytes() for p in workspace.raw_dir.rglob("*") if p.is_file()
    } == before


def test_presentation_failure_preserves_committed_sound_and_reports_the_gap(
    sound_program, monkeypatch
):
    workspace, _, service, _, request, _ = sound_program
    service.apply(request)
    original = {name: workspace.store(name).head_hash() for name in ("bmap", "tracks")}

    def unavailable(*args, **kwargs):
        raise OSError("fixture presentation unavailable")

    monkeypatch.setattr(MotionReviewService, "publish", unavailable)
    result = service.apply(request)
    assert result["status"] == "applied"
    assert result["reviewReady"] is False
    assert "fixture presentation unavailable" in result["warnings"][0]
    assert {name: workspace.store(name).head_hash() for name in original} == original


@pytest.mark.parametrize("problem", ["malformed", "foreign", "stale"])
def test_provided_sound_opportunities_cannot_claim_current_foreign_or_invalid_evidence(
    sound_program, problem
):
    workspace, _, _, _, _, shown = sound_program
    context = {
        "proposal": deepcopy(shown["proposal"]),
        "proposalRef": shown["proposalRef"],
    }
    if problem == "malformed":
        context = {"proposal": "invalid"}
    elif problem == "foreign":
        context["proposal"]["videoId"] = "another-video"
        context["proposal"]["proposalHash"] = content_hash(
            {
                key: value
                for key, value in context["proposal"].items()
                if key != "proposalHash"
            }
        )
    else:
        context["proposal"]["basisHeads"]["bmap"]["sha256"] = "f" * 64
        context["proposal"]["proposalHash"] = content_hash(
            {
                key: value
                for key, value in context["proposal"].items()
                if key != "proposalHash"
            }
        )
    snapshot = MotionReviewService(workspace).project({"soundProposal": context})
    if problem == "stale":
        item = next(item for item in snapshot["items"] if item["itemId"] == "mo04")
        opportunity = item["sound"]["opportunities"][0]
        assert opportunity["basisCurrent"] is False
        assert opportunity["recommendation"] == "unresolved"
    else:
        assert any(
            isinstance(gap, dict) and gap["kind"].startswith("sound-proposal-")
            for gap in snapshot["gaps"]
        )
        assert not any(
            (item.get("sound") or {}).get("opportunities") for item in snapshot["items"]
        )


@pytest.mark.parametrize("version", ["1.1.0", "1.2.0", "1.3.0"])
def test_older_motion_report_generators_remain_readable(sound_program, version):
    workspace, _, _, _, _, _ = sound_program
    snapshot = MotionReviewService(workspace).project()
    snapshot["generator"]["version"] = version
    snapshot["snapshotHash"] = document_hash_excluding(snapshot, "snapshotHash")
    validate_document(snapshot, "avo.motion-review.schema.json")


def test_unresolved_sound_target_has_a_card_without_invented_visual_timing(
    sound_program,
):
    workspace, _, _, _, _, shown = sound_program
    proposal = deepcopy(shown["proposal"])
    record = proposal["opportunities"][0]
    record.update(
        itemId="missing-item",
        opportunity=None,
        origin=None,
        recommendation="unresolved",
        search=None,
        issues=["item-unavailable"],
    )
    record["intent"]["itemId"] = "missing-item"
    proposal["proposalHash"] = content_hash(
        {key: value for key, value in proposal.items() if key != "proposalHash"}
    )
    snapshot = MotionReviewService(workspace).project(
        {"soundProposal": {"proposal": proposal, "proposalRef": shown["proposalRef"]}}
    )
    item = next(item for item in snapshot["items"] if item["itemId"] == "missing-item")
    assert item["timing"] is None
    opportunity = item["sound"]["opportunities"][0]
    assert opportunity["recommendation"] == "unresolved"
    assert opportunity["issues"] == ["item-unavailable"]
