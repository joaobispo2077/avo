"""Pure selected-brief projection, distinct from installed stage integration."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from avo.direction.brief import BriefService
from avo.direction.store import DirectionStore
from tests.test_briefstart_contracts import reference

NOW = "2026-10-16T12:00:00Z"
CONTEXT = Path(__file__).parent / "fixtures" / "briefstart" / "context.json"


def project_fixture(tmp_path: Path) -> Path:
    raw = tmp_path / "new-video"
    raw.mkdir(parents=True)
    path = raw / "avo.project.json"
    path.write_text(
        json.dumps({"provider": "neutral", "videoId": "new-video", "rawDir": str(raw)}),
        encoding="utf-8",
    )
    return path


def selected_project(tmp_path: Path, *, provider_mode: bool = False):
    project = project_fixture(tmp_path)
    provider_root = tmp_path / "neutral"
    if provider_mode:
        from tests.test_direction_service import (
            decide_request,
            prepare_candidate,
            provider_fixture,
        )

        provider_root = provider_fixture(tmp_path)
        provider, _, _, request = prepare_candidate(provider_root)
        provider.decide(decide_request(provider.propose(request)))
    service = BriefService(project, provider_root=provider_root, clock=lambda: NOW)
    prepared = service.prepare(
        "provider:editorial@r0001" if provider_mode else "references",
        context=json.loads(CONTEXT.read_text(encoding="utf-8")),
        references=[] if provider_mode else [reference()],
    )
    store = DirectionStore(project.parent / "edit/briefstart")
    packet_ref = prepared["refs"]["packet"]
    packet = store.load_document(packet_ref["path"])
    source_id = packet["sources"][0]["id"]

    def option(identifier, rhythm, visual):
        return {
            "id": identifier,
            "approach": "Explain the qualified comparison without hiding its limits.",
            "treatment": {
                "rhythm": rhythm,
                "visual": visual,
                "motion": "Progressively reveal necessary comparisons; hold for reading.",
                "sound": "Speech remains intelligible above purposeful support.",
                "sectionVariants": ["Hold the conclusion without decorative movement."],
            },
            "fit": "Answers whether duration alone establishes value.",
            "tradeoffs": ["More evidence requires more reading time."],
            "sourceContribution": [
                {"sourceId": source_id, "aspects": ["Natural conversational pacing"]}
            ],
            "statementIds": [],
            "exclusions": ["Never reveal a quiz answer early", "No decorative SFX"],
        }

    proposed = service.propose(
        {
            "requestId": "brief-proposal-001",
            "packetRef": packet_ref,
            "expectedIndexHash": prepared["expectedIndexHash"],
            "options": [
                option("quiet", "Natural pauses", "Presenter plus selected evidence"),
                option("compare", "Progressive contrasts", "Side-by-side comparisons"),
            ],
            "shortView": "Choose natural delivery or progressive visual comparison.",
            "synthesisProvenance": {
                "executionKind": "driving-agent",
                "agentId": "neutral-agent",
                "modelId": None,
                "packetHash": packet_ref["documentHash"],
                "promptHash": None,
            },
        }
    )
    selection = service.decide(
        {
            "requestId": "brief-selection-001",
            "targetRef": proposed["refs"]["proposal"],
            "expectedIndexHash": proposed["expectedIndexHash"],
            "action": "select",
            "scope": "project",
            "actor": {"type": "human", "id": "neutral-creator"},
            "reason": "Use natural delivery for this specific video.",
            "humanInstruction": {
                "source": "session:neutral-selection",
                "text": "Choose quiet for this new video only.",
            },
            "optionId": "quiet",
        }
    )
    return project, service, proposed["refs"]["proposal"], selection


@pytest.mark.parametrize("stage", ["structure", "cmap", "bmap", "motion", "sound"])
def test_selected_exact_brief_is_projected_to_each_authoring_stage(tmp_path, stage):
    project, service, brief_ref, _ = selected_project(tmp_path)
    heads = {"cmap": "a" * 64, "sync": "b" * 64}
    before = (project.parent / "edit/briefstart/index.json").read_bytes()
    result = service.stage_context(stage, heads)
    assert result["status"] == "ok"
    assert result["refs"]["brief"] == brief_ref
    assert result["stage"] == stage
    assert result["context"]["briefRef"] == brief_ref
    assert result["context"]["optionId"] == "quiet"
    assert result["context"]["treatment"]["rhythm"] == "Natural pauses"
    assert "Never reveal a quiz answer early" in result["context"]["exclusions"]
    assert result["context"]["canonicalHeads"] == heads
    assert (project.parent / "edit/briefstart/index.json").read_bytes() == before
    assert not (project.parent / "edit/briefstart/context").exists()


def test_recorded_guidance_means_offered_and_never_applied_or_media_approved(tmp_path):
    project, service, brief_ref, _ = selected_project(tmp_path)
    result = service.stage_context("motion", {"animation": "c" * 64}, record=True)
    receipt = DirectionStore(project.parent / "edit/briefstart").load_document(
        result["refs"]["receipt"]["path"]
    )
    assert receipt["status"] == "offered-to-authoring"
    assert receipt["briefRef"] == brief_ref
    assert receipt["optionId"] == "quiet"
    assert receipt["canonicalHeads"] == {"animation": "c" * 64}
    assert not ({"masterApproved", "implemented", "applied"} & receipt.keys())
    assert not (project.parent / "edit/timeline").exists()


def test_selected_provider_projection_replays_from_frozen_local_inputs(tmp_path):
    project, service, brief_ref, _ = selected_project(tmp_path, provider_mode=True)
    original = service.stage_context("sound")
    shutil.rmtree(tmp_path / "neutral")
    replayed = BriefService(
        project, provider_root=tmp_path / "unavailable-provider", clock=lambda: NOW
    ).stage_context("sound")
    assert replayed["refs"]["brief"] == brief_ref
    assert replayed["context"] == original["context"]


def test_no_reference_projection_creates_no_artistic_files(tmp_path):
    project = project_fixture(tmp_path)
    service = BriefService(project, provider_root=tmp_path / "missing-provider")
    result = service.stage_context("structure")
    assert result["status"] == "bypassed"
    assert result["context"] is None
    assert not (project.parent / "edit/briefstart").exists()
