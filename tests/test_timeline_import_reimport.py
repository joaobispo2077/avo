"""M3 replacement/return contracts with explicit fixture-only media and Sync."""

from __future__ import annotations

import json
import shutil
from copy import deepcopy

import pytest

from avo.timeline.cmap_service import CMapService
from avo.timeline.contracts import content_hash
from avo.timeline.import_evidence import verify_import_origin
from avo.timeline.lifecycle import PipelineRunStore, PipelineState, TransitionFacts
from avo.timeline.otio_import import ImportError
from tests.test_timeline_import_evidence import _activate, _prepare_evidence
from tests.test_timeline_import_service import _approve_fixture_sync, _trial


def _commit(service, ready, expected_head):
    return service.activate(
        ready["importId"],
        validation_hash=ready["validationHash"],
        expected_head=expected_head,
        actor="fixture-editor",
        reason="Explicitly select the reviewed replacement fixture",
    )


def _scoped_edit(service, revision):
    snapshot = deepcopy(revision["snapshot"])
    snapshot["segments"][0]["out"]["ticks"] -= 1
    return CMapService(service.workspace).author(
        snapshot,
        expected_head_hash=revision["contentHash"],
        actor="fixture-editor",
        reason="Preserve this requested AVO-only trim",
    )


def _replacement(tmp_path, *, scoped=True):
    service, first_ready = _prepare_evidence(tmp_path)
    initial = _activate(service, first_ready)
    before = _scoped_edit(service, initial) if scoped else initial
    document = json.loads(
        (service.root / first_ready["importId"] / "source.otio").read_text()
    )
    clip = document["tracks"]["children"][0]["children"][0]
    clip["source_range"]["start_time"]["value"] += 2
    clip["source_range"]["duration"]["value"] = 36
    changed = tmp_path / "revised-export.otio"
    changed.write_text(json.dumps(document), encoding="utf-8")
    original = before["snapshot"]["sources"][0]["locator"]
    prepared = _trial(service, original, export=changed)
    ready = service.validate(prepared["importId"])
    if ready["status"] == "awaiting-sync":
        _approve_fixture_sync(service, ready["proposal"])
        ready = service.validate(prepared["importId"])
    return service, first_ready, before, ready


def test_revised_export_stages_hash_bound_diff_against_scoped_avo_head(tmp_path):
    service, first, before, ready = _replacement(tmp_path)
    assert ready["importId"] != first["importId"]
    assert service.head_hash() == before["contentHash"]
    assert ready["status"] == "ready-to-activate"
    diff = ready["activeEditDiff"]
    assert diff and ready["proposal"]["activeEditDiff"] == diff
    assert diff == CMapService._diff(
        before["snapshot"], ready["proposal"]["snapshot"], diff[0]["reason"]
    )
    assert ready["validation"]["locks"]["activeEditDiffHash"] == content_hash(diff)
    assert ready["validation"]["locks"]["expectedHeadHash"] == before["contentHash"]


def test_native_service_status_names_the_current_scoped_canonical_revision(tmp_path):
    service, ready = _prepare_evidence(tmp_path)
    first = _activate(service, ready)
    current = _scoped_edit(service, first)
    shown = service.status()
    assert shown["currentCanonical"] == {
        "revisionId": current["revisionId"],
        "sha256": current["contentHash"],
    }
    assert (
        shown["currentOrigin"]["activationId"]
        == first["snapshot"]["originRef"]["activationId"]
    )
    assert shown["nextAction"]


def test_explicit_nonempty_activation_appends_one_draft_and_preserves_prior_content(
    tmp_path,
):
    service, _, before, ready = _replacement(tmp_path)
    store = service.workspace.store("cmap")
    previous_count = len(store.load_index()["revisionRefs"])
    result = _commit(service, ready, before["contentHash"])
    revision = result["revision"]
    assert revision["parentRevisionId"] == before["revisionId"]
    assert revision["snapshot"]["segments"] == ready["proposal"]["snapshot"]["segments"]
    assert store.revision(before["revisionId"])["snapshot"] == before["snapshot"]
    assert len(store.load_index()["revisionRefs"]) == previous_count + 1
    assert store.effective_approval() is None
    assert verify_import_origin(service.workspace, revision)


def test_intervening_avo_edit_refuses_stale_replacement_without_overwriting_it(
    tmp_path,
):
    service, _, before, ready = _replacement(tmp_path)
    intervening = _scoped_edit(service, before)
    with pytest.raises(ImportError):
        _commit(service, ready, before["contentHash"])
    assert service.head_hash() == intervening["contentHash"]
    assert (
        service.workspace.store("cmap").revision(intervening["revisionId"])["snapshot"]
        == intervening["snapshot"]
    )


def test_changed_mapping_requires_new_fixture_sync_without_inheriting_old_decision(
    tmp_path,
):
    service, first_ready = _prepare_evidence(tmp_path)
    before = _activate(service, first_ready)
    original = before["snapshot"]["sources"][0]["locator"]
    moved = service.workspace.raw_dir / "relocated-original.mov"
    shutil.copyfile(original, moved)
    export = service.root / first_ready["importId"] / "source.otio"
    prepared = _trial(service, moved, export=export)
    waiting = service.validate(prepared["importId"])
    assert waiting["status"] == "awaiting-sync"
    assert service.head_hash() == before["contentHash"]
    assert not waiting["readiness"]["activationAllowed"]
    _approve_fixture_sync(service, waiting["proposal"])
    assert service.validate(prepared["importId"])["status"] == "ready-to-activate"


def test_replacement_returns_later_pipeline_state_to_current_draft_and_clears_candidate_refs(
    tmp_path,
):
    service, _, before, ready = _replacement(tmp_path)
    run = PipelineRunStore(service.workspace.pipeline_run_path)
    current = run.load()
    refs = {
        **current["activeRefs"],
        "candidateSha256": "c" * 64,
        "review": {"path": "old-review.json"},
    }
    run.advance(
        PipelineState.CUT_AI_REVIEW,
        TransitionFacts(),
        actor="fixture-editor",
        reason="Fixture-only later cut review state",
        active_refs=refs,
    )
    revision = _commit(service, ready, before["contentHash"])["revision"]
    current = run.load()
    assert current["mainState"] == "cmap-draft"
    assert current["sideState"] is None
    assert current["activeRefs"]["cmapRevisionId"] == revision["revisionId"]
    assert "candidateSha256" not in current["activeRefs"]
    assert "review" not in current["activeRefs"]


def test_return_prior_content_creates_new_revision_with_current_sync_and_no_old_approval(
    tmp_path,
):
    service, _, before, ready = _replacement(tmp_path)
    store = service.workspace.store("cmap")
    # Explicit fixture-only approval, not production creator review.
    store.approve(
        before["revisionId"],
        revision_hash=before["contentHash"],
        candidate_hash="f" * 64,
    )
    assert store.effective_approval() is not None
    replacement = _commit(service, ready, before["contentHash"])["revision"]
    returned = service.rollback(
        replacement["snapshot"]["originRef"]["activationId"],
        expected_head=replacement["contentHash"],
        actor="fixture-editor",
        reason="Return to recorded pre-replacement content",
    )["revision"]
    assert returned["revisionId"] not in {
        before["revisionId"],
        replacement["revisionId"],
    }
    assert returned["parentRevisionId"] == replacement["revisionId"]
    assert returned["snapshot"] == before["snapshot"]
    assert store.effective_approval() is None
    assert verify_import_origin(service.workspace, returned)


def test_return_refuses_stale_expected_head_and_preserves_requested_later_edit(
    tmp_path,
):
    service, _, before, ready = _replacement(tmp_path)
    replacement = _commit(service, ready, before["contentHash"])["revision"]
    later = _scoped_edit(service, replacement)
    with pytest.raises(ImportError):
        service.rollback(
            replacement["snapshot"]["originRef"]["activationId"],
            expected_head=replacement["contentHash"],
            actor="fixture-editor",
            reason="Stale return",
        )
    assert service.head_hash() == later["contentHash"]


def test_return_revalidates_prior_originals_against_current_sync_instead_of_old_approval(
    tmp_path,
):
    service, first_ready = _prepare_evidence(tmp_path)
    before = _activate(service, first_ready)
    original = before["snapshot"]["sources"][0]["locator"]
    moved = service.workspace.raw_dir / "replacement-original.mov"
    shutil.copyfile(original, moved)
    export = service.root / first_ready["importId"] / "source.otio"
    prepared = _trial(service, moved, export=export)
    waiting = service.validate(prepared["importId"])
    assert waiting["status"] == "awaiting-sync"
    _approve_fixture_sync(service, waiting["proposal"])
    ready = service.validate(prepared["importId"])
    replacement = _commit(service, ready, before["contentHash"])["revision"]
    activation_id = replacement["snapshot"]["originRef"]["activationId"]
    with pytest.raises(ImportError):
        service.rollback(
            activation_id,
            expected_head=replacement["contentHash"],
            actor="fixture-editor",
            reason="Prior source needs fresh current Sync",
        )
    assert service.head_hash() == replacement["contentHash"]
    _approve_fixture_sync(service, {"snapshot": before["snapshot"]})
    returned = service.rollback(
        activation_id,
        expected_head=replacement["contentHash"],
        actor="fixture-editor",
        reason="Select prior content with current fixture Sync",
    )["revision"]
    assert returned["snapshot"]["sources"] == before["snapshot"]["sources"]
    assert returned["snapshot"]["syncRef"] != before["snapshot"]["syncRef"]
    assert service.workspace.store("cmap").effective_approval() is None
    assert verify_import_origin(service.workspace, returned)


@pytest.mark.parametrize("field", ["actor", "reason"])
def test_return_requires_named_actor_and_reason(tmp_path, field):
    service, _, before, ready = _replacement(tmp_path)
    replacement = _commit(service, ready, before["contentHash"])["revision"]
    options = {
        "expected_head": replacement["contentHash"],
        "actor": "fixture-editor",
        "reason": "Return",
    }
    options[field] = " "
    with pytest.raises(ImportError):
        service.rollback(
            replacement["snapshot"]["originRef"]["activationId"], **options
        )
    assert service.head_hash() == replacement["contentHash"]
