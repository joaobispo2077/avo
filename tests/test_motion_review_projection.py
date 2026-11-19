"""Metadata-only motion maps share identity with truthful storyboard cards."""

import json
from copy import deepcopy
from pathlib import Path

import pytest

from avo.timeline.contracts import content_hash, dependency_lock_hash, validate_document
from avo.timeline.motion_review import MotionReviewService, render_html, render_text
from avo.timeline.store import atomic_write_json
from avo.timeline.workspace import ARTIFACTS, TimelineWorkspace


@pytest.fixture
def workspace(tmp_path):
    project = {"provider": "example", "videoId": "craft", "rawDir": str(tmp_path)}
    path = tmp_path / "avo.project.json"
    path.write_text(json.dumps(project), encoding="utf-8")
    return TimelineWorkspace(
        project_path=path, project=project, raw_dir=tmp_path, video_id="craft"
    )


def install(workspace, monkeypatch, snapshots, *, states=None):
    stores = {}
    for name, snapshot in snapshots.items():
        store = workspace.store(name)
        store.initialize(
            artifact_type=name,
            artifact_id=f"craft:{name}",
            video_id="craft",
            provider="example",
            timeline_domain=ARTIFACTS[name],
        )
        store.append_revision(
            snapshot=snapshot, actor="fixture", reason="Synthetic projection metadata"
        )
        if name in (states or {}):
            index = store.load_index()
            index["activeState"] = states[name]
            atomic_write_json(store.path, index)
        stores[name] = store
    return stores


def advance(store):
    index = store.load_index()
    revision = store.revision(index["headRevisionId"])
    snapshot = revision["snapshot"]
    snapshot["fixtureChange"] = True
    store.append_revision(
        snapshot=snapshot,
        actor="fixture",
        reason="Changed synthetic metadata",
        expected_head_hash=revision["contentHash"],
    )


def cue(identifier="mo04", ticks=12, **fields):
    time = {"timebase": {"num": 1, "den": 24}, "domain": "cmap-output"}
    return {
        "cueId": identifier,
        "start": {"ticks": ticks, **time},
        "end": {"ticks": ticks + 12, **time},
        "kind": "animation",
        "targetLayerId": "presenter",
        "contentRef": {"sectionId": "opening", "concept": "Show the mechanism"},
        "intent": "Clarify the mechanism",
        "reason": "Supports spoken explanation",
        "reviewState": "pending",
        **fields,
    }


@pytest.mark.parametrize(
    "stale",
    [None, "review", "bmap", "tracks", "watch", "watch-lock", "watch-duplicate"],
)
def test_linked_storyboard_uses_only_selected_current_sampled_review(
    workspace, monkeypatch, stale
):
    from avo.timeline.pipeline import TimelinePipeline

    stores = install(
        workspace, monkeypatch, {"bmap": {"cues": [cue(), cue("mo05", 32)]}}
    )
    bmap = stores["bmap"].head_hash()
    candidate_sha, candidate_identity, materialization = "a" * 64, "b" * 64, "c" * 64
    report = {
        "candidateSha256": candidate_sha,
        "candidateIdentityHash": candidate_identity,
        "materializationHash": materialization,
        "bmapRevisionHash": bmap,
        "canonicalRevisionHashes": {"bmap": bmap, "tracks": None},
        "cues": [
            {
                "cueId": "mo04",
                "observedFrames": [14, 17],
                "frameFindings": [{"findingId": "layout-issue"}],
            },
            {"cueId": "mo05", "observedFrames": [], "frameFindings": []},
        ],
    }
    dependencies = {"materialization": materialization, "bmap": bmap}
    lock = dependency_lock_hash(dependencies)
    watch = {
        "kind": "watch",
        "status": "stale" if stale == "watch" else "fail",
        "candidateHash": candidate_sha,
        "candidateIdentityHash": candidate_identity,
        "dependencyHashes": dependencies,
        "dependencyLockSha256": "f" * 64 if stale == "watch-lock" else lock,
        "reviewContext": {"craftChecks": report},
    }
    review = {
        "candidate": {
            "sha256": candidate_sha,
            "identityHash": candidate_identity,
            "dependencies": dependencies,
        },
        "dependencyLockSha256": lock,
        "evidence": [watch, watch] if stale == "watch-duplicate" else [watch],
    }
    path = workspace.review_dir / "motion-proof" / candidate_sha[:12] / "review.json"
    atomic_write_json(path, review)
    workspace.pipeline_run_path.touch()
    reference = {
        "candidate": {"sha256": candidate_sha},
        "materialization": {"sha256": materialization},
        "review": {"artifactId": "motion-proof-review", "sha256": content_hash(review)},
    }
    monkeypatch.setattr(
        TimelinePipeline, "active_candidate_snapshot", lambda _: reference
    )
    if stale == "bmap":
        advance(stores["bmap"])
    elif stale == "tracks":
        # The record is exact for the prior absent Tracks state.
        install(workspace, monkeypatch, {"tracks": {"video": {}, "audio": {}}})
    elif stale == "review":
        review["evidence"][0]["reviewContext"]["craftChecks"]["cues"][0][
            "observedFrames"
        ] = [23]
        atomic_write_json(path, review)

    service = MotionReviewService(workspace)
    plan = service.project()
    if stale:
        assert "encodedReview" not in plan
        return
    assert (
        plan["encodedReview"]["reviewPath"]
        == path.relative_to(workspace.raw_dir).as_posix()
    )
    assert plan["encodedReview"]["links"] == [
        {
            "itemId": "mo04",
            "cueIds": ["mo04"],
            "observedFrames": [14, 17],
            "findingIds": ["layout-issue"],
        }
    ]
    for displayed in (render_text(plan), render_html(plan)):
        assert "layout-issue" in displayed
        assert "14, 17" in displayed
        assert "listen before accepting" in displayed
    before = workspace.active_dependency_snapshot()
    original_review = path.read_bytes()
    candidate_reference = deepcopy(reference)
    published = service.publish(plan)
    assert published["freshness"] == "current"
    assert workspace.active_dependency_snapshot() == before
    assert path.read_bytes() == original_review
    assert reference == candidate_reference
    assert service.project()["encodedReview"] == plan["encodedReview"]


def test_empty_projection_is_read_only_with_explicit_absence(workspace, monkeypatch):
    def prohibited(*args, **kwargs):
        raise AssertionError("Projection initialized or fingerprinted an input")

    monkeypatch.setattr(workspace, "initialize", prohibited)
    monkeypatch.setattr(workspace, "require_active", prohibited)
    monkeypatch.setattr("avo.timeline.contracts.file_fingerprint", prohibited)
    before = set(workspace.raw_dir.rglob("*"))
    snapshot = MotionReviewService(workspace).project()
    assert snapshot["basisHeads"] == dict.fromkeys(ARTIFACTS)
    assert snapshot["items"] == snapshot["storyboardCards"] == []
    assert snapshot["readiness"] == "conceptual"
    assert snapshot["applicability"] == "applicable"
    assert set(workspace.raw_dir.rglob("*")) == before
    validate_document(snapshot, "avo.motion-review.schema.json")


@pytest.mark.parametrize("basis", [[], "invalid", {"bmap": {"sha256": "a" * 64}}])
def test_invalid_proposal_basis_stays_stale_without_breaking_inspection(
    workspace, basis
):
    snapshot = MotionReviewService(workspace).project(
        {"proposal": {"basisHeads": basis, "items": [{"itemId": "mo04"}]}}
    )
    assert snapshot["readiness"] == "stale"
    assert snapshot["items"][0]["disposition"] == "stale"


def test_selected_staleness_survives_unchanged_canonical_heads(workspace):
    service = MotionReviewService(workspace)
    snapshot = service.project(
        {
            "proposal": {
                "basisHeads": service.project()["basisHeads"],
                "items": [{"itemId": "mo04", "disposition": "selected"}],
            },
            "proposalStale": True,
        }
    )
    assert snapshot["readiness"] == "stale"
    assert snapshot["items"][0]["disposition"] == "stale"


def test_static_provisional_items_have_linked_cards_without_fake_timing(workspace):
    context = {
        "proposal": {
            "items": [
                {
                    "itemId": "mo04",
                    "label": "mo04",
                    "sectionId": "opening",
                    "concept": "Hold presenter",
                    "purpose": "Give the explanation space",
                    "treatment": "static",
                }
            ]
        },
        "pendingRevisions": [{"requestId": "change-mo04", "status": "pending"}],
    }
    service = MotionReviewService(workspace)
    snapshot = service.project(context)
    item, card = snapshot["items"][0], snapshot["storyboardCards"][0]
    assert item["itemId"] == card["itemId"] == "mo04"
    assert item["timing"] is None and item["timingState"] == "provisional"
    assert card["evidence"]["type"] == "concept"
    assert card["evidence"]["status"] == "unverified"
    assert "entrance" in card["unresolvedFields"]
    assert snapshot["pendingRevisions"] == context["pendingRevisions"]
    assert service.project(context)["snapshotHash"] == snapshot["snapshotHash"]
    assert context["proposal"]["items"][0].get("timing") is None


def test_persisted_concept_explanation_reaches_map_cards_text_and_html(
    workspace, monkeypatch
):
    metadata = {
        "density": 0,
        "dominantFocus": "Keep the evidence dominant",
        "supportingMotion": "Reveal the pointer only when needed",
        "ambientMotion": "Hold the background still",
        "readingIntent": "Hold the full comparison until both values are read",
        "depthIntent": "Keep <plane> behind evidence & preserve focus",
        "continuityIntent": "Carry the selected line into the conclusion",
        "cameraIntent": "Keep the original presenter framing",
        "soundIntent": "Choose silence during this explanation",
        "layout": {"mode": "lateral-overlay", "placement": "left of evidence"},
    }
    proposal = {
        "items": [
            {
                "itemId": "mo04",
                "label": "mo04",
                "sectionId": "opening",
                "purpose": "Explain the actual comparison",
                "concept": "One continuous comparison",
                "treatment": "static",
                **metadata,
            }
        ]
    }
    install(
        workspace, monkeypatch, {"bmap": {"cues": [cue(contentRef={"itemId": "mo04"})]}}
    )
    before = {
        path: path.read_bytes()
        for path in workspace.raw_dir.rglob("*")
        if path.is_file()
    }

    def prohibited(*args, **kwargs):
        raise AssertionError(
            "Concept explanation attempted source work or initialization"
        )

    monkeypatch.setattr(workspace, "initialize", prohibited)
    monkeypatch.setattr(workspace, "require_active", prohibited)
    monkeypatch.setattr("avo.timeline.contracts.file_fingerprint", prohibited)
    snapshot = MotionReviewService(workspace).project({"proposal": proposal})
    item, card = snapshot["items"][0], snapshot["storyboardCards"][0]
    for field, value in metadata.items():
        assert item[field] == value
        assert card[field] == value
    assert item["timing"]["start"]["ticks"] == 12
    assert card["evidence"]["status"] == "unverified"
    text, visual = render_text(snapshot), render_html(snapshot)
    storyboard = visual.split('aria-label="Linked storyboard"', 1)[1].split(
        "Equivalent text", 1
    )[0]
    motion_map = visual.split('aria-label="Chronological motion map"', 1)[1].split(
        'aria-label="Linked storyboard"', 1
    )[0]
    for field in (
        "dominantFocus",
        "supportingMotion",
        "ambientMotion",
        "readingIntent",
        "continuityIntent",
        "cameraIntent",
        "soundIntent",
    ):
        assert metadata[field] in text
        assert metadata[field] in storyboard
    assert "Density: 0" in text
    assert metadata["dominantFocus"] in motion_map
    assert "&lt;plane&gt;" in storyboard and "&amp; preserve focus" in storyboard
    assert "<plane>" not in visual
    assert {
        path: path.read_bytes()
        for path in workspace.raw_dir.rglob("*")
        if path.is_file()
    } == before
    validate_document(snapshot, "avo.motion-review.schema.json")


def test_recorded_repetition_advisories_are_preserved_without_new_judgment(workspace):
    advisory = {
        "code": "motion-repetition",
        "itemIds": ["mo01", "mo02", "mo03"],
        "message": "Repeated treatments may be intentional; review variation and reading time.",
    }
    context = {
        "proposal": {
            "items": [
                {"itemId": f"mo0{index}", "treatment": "reveal"}
                for index in range(1, 4)
            ]
        },
        "advisories": [advisory],
    }
    snapshot = MotionReviewService(workspace).project(context)
    assert snapshot["advisories"] == [advisory]
    assert advisory["message"] in render_text(snapshot)
    assert advisory["message"] in render_html(snapshot)
    assert all(item["disposition"] == "proposed" for item in snapshot["items"])
    assert (
        MotionReviewService(workspace).project({"proposal": context["proposal"]})[
            "advisories"
        ]
        == []
    )


def test_invalid_optional_concept_details_remain_explicit_partial_metadata(workspace):
    snapshot = MotionReviewService(workspace).project(
        {
            "proposal": {
                "items": [
                    {
                        "itemId": "mo04",
                        "readingIntent": {"unexpected": "object"},
                        "density": True,
                    }
                ]
            },
            "advisories": [{"message": "missing required identity"}],
        }
    )
    assert snapshot["items"][0]["readingIntent"] is None
    assert snapshot["items"][0]["density"] is None
    assert snapshot["advisories"] == []
    assert any("readingIntent" in str(gap) for gap in snapshot["gaps"])
    assert any("advisories" in str(gap) for gap in snapshot["gaps"])


def test_cues_sort_by_time_without_renumbering_and_preserve_anchor_types(
    workspace, monkeypatch
):
    install(workspace, monkeypatch, {"bmap": {"cues": [cue("mo08", 24), cue()]}})
    snapshot = MotionReviewService(workspace).project()
    assert [item["label"] for item in snapshot["items"]] == ["mo04", "mo08"]
    assert [card["itemId"] for card in snapshot["storyboardCards"]] == ["mo04", "mo08"]
    assert snapshot["items"][0]["timing"]["start"]["ticks"] == 12
    assert snapshot["items"][0]["anchor"]["type"] == "cut"
    assert snapshot["readiness"] == "timed-unresolved"


@pytest.mark.parametrize(
    "rebase_state", ["shifted", "split", "removed", "ambiguous", "unsupported"]
)
def test_rebase_disposition_remains_visible(workspace, monkeypatch, rebase_state):
    install(workspace, monkeypatch, {"bmap": {"cues": [cue(rebaseState=rebase_state)]}})
    snapshot = MotionReviewService(workspace).project()
    assert snapshot["items"][0]["rebaseState"] == rebase_state
    if rebase_state in {"ambiguous", "unsupported"}:
        assert snapshot["items"][0]["disposition"] == "needs-judgment"


def test_changed_cut_basis_marks_items_stale_without_changing_decisions(
    workspace, monkeypatch
):
    install(
        workspace,
        monkeypatch,
        {
            "cmap": {"segments": []},
            "bmap": {
                "basis": {"sha256": "a" * 64},
                "cues": [cue(reviewState="approved")],
            },
        },
    )
    snapshot = MotionReviewService(workspace).project()
    assert snapshot["readiness"] == "stale"
    assert snapshot["items"][0]["disposition"] == "stale"
    assert snapshot["items"][0]["recordedDisposition"] == "approved"


def test_sketch_is_never_render_verification(workspace):
    snapshot = MotionReviewService(workspace).project(
        {
            "proposal": {
                "items": [
                    {
                        "itemId": "mo04",
                        "evidence": {"type": "sketch", "inspected": True},
                    }
                ]
            }
        }
    )
    assert snapshot["storyboardCards"][0]["evidence"] == {
        "type": "sketch",
        "status": "unverified",
    }


def test_tracks_show_actual_order_role_level_and_cue_links(workspace, monkeypatch):
    region = {
        "regionId": "region-one",
        "startTicks": 0,
        "endTicks": 24,
        "cueIds": ["mo04"],
    }
    install(
        workspace,
        monkeypatch,
        {
            "tracks": {
                "audioTracks": {
                    "layers": [
                        {
                            "layerId": "speech",
                            "order": 0,
                            "role": "dialogue",
                            "mute": False,
                            "gainDb": -3,
                            "regions": [region],
                        }
                    ]
                },
                "videoTracks": {
                    "layers": [
                        {
                            "layerId": "graphics",
                            "order": 2,
                            "zOrder": 7,
                            "role": "overlay",
                            "regions": [region],
                        }
                    ]
                },
            }
        },
    )
    snapshot = MotionReviewService(workspace).project()
    assert snapshot["lanes"]["audio"][0]["gainDb"] == -3
    assert snapshot["lanes"]["video"][0]["zOrder"] == 7
    assert snapshot["lanes"]["video"][0]["regions"][0]["cueIds"] == ["mo04"]
    assert "dialogue" in render_text(snapshot)


def test_publication_is_idempotent_contained_and_does_not_mutate_canonical_state(
    workspace,
):
    service = MotionReviewService(workspace)
    context = {
        "proposal": {"items": [{"itemId": "mo04", "concept": "<script>bad()</script>"}]}
    }
    snapshot = service.project(context)
    result = service.publish(snapshot)
    assert result["freshness"] == "current"
    target = workspace.review_dir / "motion-plan" / snapshot["snapshotHash"]
    assert (
        json.loads((target / "snapshot.json").read_text(encoding="utf-8")) == snapshot
    )
    assert (target / "review.md").read_text(encoding="utf-8") == render_text(snapshot)
    html = (target / "review.html").read_text(encoding="utf-8")
    assert "<script>bad()" not in html and "&lt;script&gt;" in html
    assert "https://" not in html
    assert not workspace.timeline_dir.exists()
    before = {p: p.stat().st_mtime_ns for p in target.iterdir()}
    service.publish(snapshot)
    assert before == {p: p.stat().st_mtime_ns for p in target.iterdir()}


def test_changed_heads_leave_published_snapshot_historical(workspace, monkeypatch):
    stores = install(workspace, monkeypatch, {"bmap": {"cues": [cue()]}})
    service = MotionReviewService(workspace)
    snapshot = service.project()
    advance(stores["bmap"])
    result = service.publish(snapshot, expected_basis=snapshot["basisHeads"])
    assert result["freshness"] == "historical"
    assert result["status"] == "stale"
    assert result["snapshot"] == snapshot


def test_context_order_and_display_timestamps_do_not_reidentify_snapshot(workspace):
    service = MotionReviewService(workspace)
    first = service.project(
        {"direction": {"purpose": "Explain"}, "displayTimestamp": "old"}
    )
    second = service.project(
        {"displayTimestamp": "new", "direction": {"purpose": "Explain"}}
    )
    assert first["snapshotHash"] == second["snapshotHash"]
    skipped = service.project({"applicability": "explicitly-skipped"})
    assert skipped["applicability"] == "explicitly-skipped"


def test_publication_rejects_forged_hash_before_selecting_a_path(workspace):
    service = MotionReviewService(workspace)
    snapshot = service.project()
    snapshot["snapshotHash"] = "../escape"
    with pytest.raises(ValueError, match="hash"):
        service.publish(snapshot)
    assert not workspace.review_dir.exists()


def test_publication_never_overwrites_mismatching_immutable_snapshot(workspace):
    service = MotionReviewService(workspace)
    snapshot = service.project()
    service.publish(snapshot)
    path = (
        workspace.review_dir
        / "motion-plan"
        / snapshot["snapshotHash"]
        / "snapshot.json"
    )
    path.write_text('{"tampered": true}', encoding="utf-8")
    with pytest.raises(ValueError, match="immutable"):
        service.publish(snapshot)
    assert path.read_text(encoding="utf-8") == '{"tampered": true}'
    assert service.report_status(snapshot)["freshness"] == "invalid"


def test_publication_rejects_review_root_outside_project(workspace):
    service = MotionReviewService(workspace)
    snapshot = service.project()
    workspace.review_dir = workspace.raw_dir.parent / "outside-review"
    with pytest.raises(ValueError, match="contain"):
        service.publish(snapshot)


def test_during_publication_head_race_is_historical(workspace, monkeypatch):
    from avo.timeline import motion_review

    stores = install(workspace, monkeypatch, {"bmap": {"cues": [cue()]}})
    service = MotionReviewService(workspace)
    snapshot = service.project()
    original_write = motion_review.atomic_write_json

    def race(path, value):
        original_write(path, value)
        advance(stores["bmap"])

    monkeypatch.setattr(motion_review, "atomic_write_json", race)
    result = service.publish(snapshot)
    assert result["freshness"] == "historical" and result["status"] == "stale"
    assert result["warnings"]


def test_invalid_optional_context_stays_a_partial_projection(workspace):
    snapshot = MotionReviewService(workspace).project(
        {"direction": "invalid", "options": [], "proposal": {"items": "invalid"}}
    )
    assert snapshot["readiness"] == "conceptual"
    assert "context:direction:invalid" in snapshot["gaps"]
    assert "context:proposal-items:invalid" in snapshot["gaps"]


def test_cached_report_rejects_altered_text_and_missing_styles(workspace):
    service = MotionReviewService(workspace)
    snapshot = service.project()
    service.publish(snapshot)
    target = workspace.review_dir / "motion-plan" / snapshot["snapshotHash"]
    (target / "review.md").write_text("different plan", encoding="utf-8")
    assert service.report_status(snapshot)["freshness"] == "invalid"
    (target / "review.md").write_text(render_text(snapshot), encoding="utf-8")
    (target / "review.css").unlink()
    assert service.report_status(snapshot)["freshness"] == "missing"


def test_parent_context_gaps_and_bounded_coverage_remain_truthful(workspace):
    gap = {"kind": "options-unavailable", "detail": "Provider is absent"}
    snapshot = MotionReviewService(workspace).project(
        {
            "gaps": [gap],
            "proposal": {"items": [{"itemId": f"mo{n:04d}"} for n in range(503)]},
        }
    )
    assert gap in snapshot["gaps"]
    assert snapshot["coverage"]["shown"] == 500
    assert snapshot["coverage"]["total"] == 503
    assert len(snapshot["storyboardCards"]) == 500


def test_derived_html_has_stable_links_to_every_storyboard_card(workspace):
    service = MotionReviewService(workspace)
    snapshot = service.project(
        {"proposal": {"items": [{"itemId": "mo04", "concept": "Static explanation"}]}}
    )
    result = service.publish(snapshot)
    html = Path(result["refs"]["visual"]).read_text(encoding="utf-8")
    assert '<article id="' in html
    assert '<a href="#' in html
    assert "Static explanation" in html
    assert "Lifecycle" in html and "Camera" in html


def test_existing_animation_components_enrich_linked_cards(workspace, monkeypatch):
    install(
        workspace,
        monkeypatch,
        {
            "bmap": {"cues": [cue(componentRef="explanation")]},
            "animation": {
                "components": [
                    {
                        "componentId": "explanation",
                        "lifecycle": {
                            "preEntry": "hidden",
                            "entrance": "reveal",
                            "hold": "read",
                            "exit": "fade",
                        },
                        "audioRelationship": {"intent": "silence"},
                    }
                ]
            },
        },
    )
    card = MotionReviewService(workspace).project()["storyboardCards"][0]
    assert card["lifecycle"]["entrance"] == "reveal"
    assert card["sound"] == {"intent": "silence"}


def test_provisional_sections_follow_authorial_order_not_alphabetical(workspace):
    snapshot = MotionReviewService(workspace).project(
        {
            "proposal": {
                "items": [
                    {"itemId": "mo04", "sectionId": "opening"},
                    {"itemId": "mo08", "sectionId": "conclusion"},
                ]
            }
        }
    )
    assert [item["label"] for item in snapshot["items"]] == ["mo04", "mo08"]


def test_proposal_cue_link_never_becomes_an_output_timing_authority(workspace):
    planned = {
        "itemId": "mo04",
        "cueId": "planned-cue",
        "start": cue()["start"],
        "end": cue()["end"],
    }
    snapshot = MotionReviewService(workspace).project(
        {"proposal": {"items": [planned]}}
    )
    assert snapshot["items"][0]["timing"] is None
    assert snapshot["items"][0]["timingState"] == "provisional"


@pytest.mark.parametrize("tamper", ["deep", "boolean"])
def test_cached_json_never_crashes_or_accepts_bool_integer_coercion(workspace, tamper):
    service = MotionReviewService(workspace)
    snapshot = service.project()
    service.publish(snapshot)
    path = (
        workspace.review_dir
        / "motion-plan"
        / snapshot["snapshotHash"]
        / "snapshot.json"
    )
    payload = "[" * 1050 + "0" + "]" * 1050
    if tamper == "boolean":
        altered = deepcopy(snapshot)
        altered["coverage"]["shown"] = False
        payload = (
            json.dumps(altered, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
        )
    path.write_text(payload, encoding="utf-8", newline="\n")
    result = service.report_status(snapshot)
    assert result["freshness"] == "invalid" and result["refs"] == {}


def test_duplicate_proposal_definitions_are_preserved_as_unresolved(workspace):
    definitions = [
        {"itemId": "mo04", "concept": "First choice"},
        {
            "itemId": "mo04",
            "concept": "Other choice",
            "cueId": "fake-cue",
            "start": cue()["start"],
            "end": cue()["end"],
        },
    ]
    snapshot = MotionReviewService(workspace).project(
        {"proposal": {"items": definitions}}
    )
    item = snapshot["items"][0]
    assert item["itemId"] == "mo04" and item["disposition"] == "needs-judgment"
    assert item["identityConflicts"] == definitions
    assert item["parts"] == [] and item["timing"] is None
    assert snapshot["coverage"]["proposalDefinitionCount"] == 2
    assert "First choice" in render_text(snapshot) and "Other choice" in render_text(
        snapshot
    )


def test_split_canonical_parts_keep_one_identity_and_every_exact_range(
    workspace, monkeypatch
):
    cues = [
        cue("cue-first", 12, contentRef={"itemId": "mo04"}),
        cue("cue-second", 48, contentRef={"itemId": "mo04"}),
    ]
    install(workspace, monkeypatch, {"bmap": {"cues": cues}})
    snapshot = MotionReviewService(workspace).project()
    assert len(snapshot["items"]) == len(snapshot["storyboardCards"]) == 1
    item = snapshot["items"][0]
    assert item["itemId"] == snapshot["storyboardCards"][0]["itemId"] == "mo04"
    assert item["timing"] is None and item["timingState"] == "split"
    assert item["disposition"] == "needs-judgment"
    assert [part["cueId"] for part in item["parts"]] == ["cue-first", "cue-second"]
    assert [part["timing"]["start"]["ticks"] for part in item["parts"]] == [12, 48]
    assert [part["cue"] for part in item["parts"]] == cues
    assert snapshot["coverage"]["canonicalPartCount"] == 2
    assert "cue-first" in render_text(snapshot) and "cue-second" in render_text(
        snapshot
    )


@pytest.mark.parametrize("oversized", ["depth", "text"])
def test_context_budget_fails_as_visible_unknown_coverage(workspace, oversized):
    value = "x" * 10000
    if oversized == "depth":
        value = {}
        for _ in range(200):
            value = {"nested": value}
    snapshot = MotionReviewService(workspace).project({"direction": {"value": value}})
    assert any(
        isinstance(gap, dict) and gap.get("kind") == "context-unavailable"
        for gap in snapshot["gaps"]
    )
    assert snapshot["coverage"]["total"] is None
    assert snapshot["coverage"]["complete"] is False


def test_card_materialization_is_limited_before_work(workspace, monkeypatch):
    from avo.timeline import motion_review

    original = motion_review._card
    calls = []

    def counted(*args):
        calls.append(1)
        return original(*args)

    monkeypatch.setattr(motion_review, "_card", counted)
    snapshot = MotionReviewService(workspace).project(
        {"proposal": {"items": [{"itemId": f"mo{n:04d}"} for n in range(1000)]}}
    )
    assert len(calls) == snapshot["coverage"]["shown"] == 500
    assert snapshot["coverage"]["total"] == 1000


def test_bounded_reader_keeps_known_identity_when_selected_body_is_oversize(
    workspace, monkeypatch
):
    from avo.timeline import motion_review

    stores = install(
        workspace, monkeypatch, {"bmap": {"cues": [cue()], "padding": "x" * 4000}}
    )
    index = stores["bmap"].load_index()
    monkeypatch.setattr(motion_review, "MAX_DOCUMENT_BYTES", 2048, raising=False)
    snapshot = MotionReviewService(workspace).project()
    assert snapshot["basisHeads"]["bmap"]["revisionId"] == index["headRevisionId"]
    assert snapshot["basisHeads"]["bmap"]["availability"] == "unavailable"
    assert (
        snapshot["readiness"] == "unavailable" and snapshot["coverage"]["total"] is None
    )


def test_bounded_reader_verifies_selected_head_without_reading_unrelated_history(
    workspace, monkeypatch
):
    stores = install(workspace, monkeypatch, {"bmap": {"cues": [cue()]}})
    store = stores["bmap"]
    previous = store.load_index()["revisionRefs"][0]
    advance(store)
    index = store.load_index()
    (workspace.timeline_dir / previous["path"]).write_text(
        "corrupt unrelated history", encoding="utf-8"
    )
    snapshot = MotionReviewService(workspace).project()
    assert snapshot["basisHeads"]["bmap"]["revisionId"] == index["headRevisionId"]
    assert snapshot["items"][0]["itemId"] == "mo04"


def test_bounded_reader_exposes_changed_selected_bytes_as_unavailable(
    workspace, monkeypatch
):
    stores = install(workspace, monkeypatch, {"bmap": {"cues": [cue()]}})
    reference = stores["bmap"].load_index()["revisionRefs"][0]
    path = workspace.timeline_dir / reference["path"]
    body = json.loads(path.read_text(encoding="utf-8"))
    body["snapshot"]["cues"][0]["intent"] = "Changed without a revision"
    path.write_text(json.dumps(body), encoding="utf-8")
    snapshot = MotionReviewService(workspace).project()
    assert snapshot["basisHeads"]["bmap"]["availability"] == "unavailable"
    assert snapshot["items"] == [] and snapshot["coverage"]["complete"] is False


@pytest.mark.parametrize("cached", [False, True])
def test_missing_report_never_requires_template_access(workspace, monkeypatch, cached):
    from avo.timeline import motion_review

    service = MotionReviewService(workspace)
    snapshot = service.project()
    if cached:
        service.publish(snapshot)

    def absent(*args):
        raise FileNotFoundError("Templates unavailable")

    monkeypatch.setattr(motion_review, "files", absent)
    result = service.report_status(snapshot)
    assert result["freshness"] == ("invalid" if cached else "missing")
    assert result["refs"] == {}


@pytest.mark.parametrize("claim", ["sha-only", "nonexistent", "stale"])
def test_self_supplied_render_inspection_claims_never_become_verified(workspace, claim):
    service = MotionReviewService(workspace)
    heads = service.project()["basisHeads"]
    reference = {"sha256": "0" * 64}
    if claim == "nonexistent":
        reference["locator"] = "edit/review/does-not-exist.json"
    if claim == "stale":
        heads = {**heads, "cmap": {"revisionId": "old", "sha256": "a" * 64}}
    snapshot = service.project(
        {
            "proposal": {
                "items": [
                    {
                        "itemId": "mo04",
                        "evidence": {
                            "type": "rendered-frame",
                            "inspectionRef": reference,
                            "basisHeads": heads,
                        },
                    }
                ]
            }
        }
    )
    evidence = snapshot["storyboardCards"][0]["evidence"]
    assert evidence["status"] == "unverified"
    assert evidence["inspectionRef"] == reference
    assert evidence["basisStatus"] == ("stale" if claim == "stale" else "matches")
