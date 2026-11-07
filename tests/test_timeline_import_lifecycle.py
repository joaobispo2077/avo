"""An explicitly committed import reselects a draft without retaining approvals."""

from copy import deepcopy

import pytest

from avo.timeline.contracts import content_hash
from avo.timeline.lifecycle import LifecycleError, PipelineRunStore


def _references(activation="a" * 64):
    return {
        "rawInventory": {"sources": [{"sourceId": "original-new", "sha256": "d" * 64}]},
        "syncRevisionId": "sync-current",
        "syncRevisionHash": "b" * 64,
        "cmapRevisionId": "cmap-import-" + activation[:24],
        "cmapRevisionHash": "c" * 64,
    }


def _select(store, *, activation="a" * 64, references=None, **overrides):
    references = _references(activation) if references is None else references
    arguments = {
        "activation_id": activation,
        "cmap_revision_id": references.get("cmapRevisionId", "cmap-current"),
        "cmap_revision_hash": references.get("cmapRevisionHash", "c" * 64),
        "active_refs": references,
        "actor": "fixture-editor",
        "reason": "Reconcile explicitly committed imported draft",
        **overrides,
    }
    return store.reconcile_import_draft(**arguments)


@pytest.fixture
def run_store(tmp_path):
    store = PipelineRunStore(tmp_path / "timeline" / "pipeline-run.json")
    store.initialize(
        run_id="run-fixture",
        video_id="video",
        provider="channel",
        project_path=tmp_path / "avo.project.json",
    )
    store.bind_motion_selection(
        {
            "engine": "code-drawn",
            "source": "invocation",
            "advanced": True,
            "resolutionHash": "e" * 64,
            "maskedChoices": [],
        }
    )
    return store


@pytest.mark.parametrize(
    "state", ["cut-ai-review", "cmap-approved", "delivered", "archived"]
)
def test_committed_import_returns_later_pipeline_to_unapproved_draft(run_store, state):
    # Lifecycle fixtures model existing state; they create no creator approval.
    old = run_store.load()
    old.update(mainState=state, sideState="blocked", blockers=[{"code": "OLD_REVIEW"}])
    old["activeRefs"] = {
        "candidateSha256": "f" * 64,
        "approval": {"old": True},
        "review": {"old": True},
        "transcript": {"old": True},
        "activeCandidateSnapshot": {"snapshotId": "candidate-old", "sha256": "f" * 64},
        "bmapRevisionId": "old-bmap",
        "masterSha256": "f" * 64,
    }
    old["extensions"] = {
        "costContext": {"contextId": "cost-existing"},
        "unrelated": {"keep": True},
    }
    run_store._write(old)
    references = _references()
    before_references = deepcopy(references)
    selected = _select(run_store, references=references)
    assert selected["mainState"] == "cmap-draft"
    assert selected["sideState"] is None
    assert selected["blockers"] == []
    assert selected["activeRefs"] == references
    assert references == before_references
    assert selected["executionChoices"] == old["executionChoices"]
    assert selected["extensions"]["costContext"] == old["extensions"]["costContext"]
    assert selected["extensions"]["unrelated"] == old["extensions"]["unrelated"]
    identity = selected["extensions"]["importDraftSelection"]
    assert identity == {
        "activationId": "a" * 64,
        "cmapRevisionId": references["cmapRevisionId"],
        "cmapRevisionHash": "c" * 64,
        "activeRefsHash": content_hash(references),
    }
    event = selected["transitionHistory"][-1]
    assert event["fromMainState"] == state
    assert event["toMainState"] == "cmap-draft"
    assert event["fromSideState"] == "blocked"
    assert event["toSideState"] is None


def test_exact_reconciliation_retry_is_a_noop_even_after_ordinary_progress(run_store):
    _select(run_store)
    later = run_store.load()
    later["mainState"] = "cut-ai-review"
    later["activeRefs"]["candidateSha256"] = "f" * 64
    run_store._write(later)
    before = run_store.path.read_bytes()
    retried = _select(run_store)
    assert retried == later
    assert run_store.path.read_bytes() == before


def test_reusing_an_activation_for_different_revision_or_refs_is_rejected(run_store):
    _select(run_store)
    references = _references()
    references["cmapRevisionHash"] = "d" * 64
    before = run_store.path.read_bytes()
    with pytest.raises(LifecycleError, match="identity"):
        _select(run_store, references=references)
    assert run_store.path.read_bytes() == before


def test_historical_activation_identity_cannot_be_rebound_after_a_new_import(run_store):
    _select(run_store)
    _select(run_store, activation="f" * 64)
    references = _references()
    references["syncRevisionHash"] = "d" * 64
    before = run_store.path.read_bytes()
    with pytest.raises(LifecycleError, match="identity"):
        _select(run_store, references=references)
    assert run_store.path.read_bytes() == before
    assert (
        _select(run_store)["extensions"]["importDraftSelection"]["activationId"]
        == "f" * 64
    )


@pytest.mark.parametrize(
    "overrides",
    [
        {"activation_id": "bad"},
        {"activation_id": True},
        {"cmap_revision_hash": "bad"},
        {"cmap_revision_id": ""},
        {"cmap_revision_id": "different-cmap"},
        {"cmap_revision_hash": "d" * 64},
        {"actor": "  "},
        {"reason": ""},
        {"actor": None},
    ],
)
def test_invalid_or_mismatched_selection_is_rejected_before_write(run_store, overrides):
    before = run_store.path.read_bytes()
    with pytest.raises(LifecycleError):
        _select(run_store, **overrides)
    assert run_store.path.read_bytes() == before


@pytest.mark.parametrize(
    "defect", ["stale-approval", "missing-source", "bad-sync-hash", "missing-cmap"]
)
def test_only_current_source_sync_and_cmap_refs_can_replace_active_refs(
    run_store, defect
):
    references = _references()
    if defect == "stale-approval":
        references["approval"] = {"old": True}
    elif defect == "missing-source":
        del references["rawInventory"]
    elif defect == "bad-sync-hash":
        references["syncRevisionHash"] = "not-a-hash"
    else:
        del references["cmapRevisionId"]
    before = run_store.path.read_bytes()
    with pytest.raises(LifecycleError):
        _select(run_store, references=references)
    assert run_store.path.read_bytes() == before
