"""Request choices survive preference changes without transferring approval."""

from copy import deepcopy
from datetime import UTC, datetime, timedelta
from itertools import count

import pytest

from avo.timeline.contracts import ContractError, validate_document
from avo.timeline.lifecycle import LifecycleError, PipelineRunStore


@pytest.fixture
def store(tmp_path):
    ticks = count()
    epoch = datetime(2026, 11, 16, tzinfo=UTC)
    run = PipelineRunStore(
        tmp_path / "pipeline-run.json",
        clock=lambda: (epoch + timedelta(seconds=next(ticks))).isoformat(),
    )
    run.initialize(
        run_id="craft-run",
        video_id="video",
        provider="sample",
        project_path=str(tmp_path / "avo.project.json"),
    )
    return run


def selection(enabled=False):
    from avo.editing_craft import resolve_editing_craft_selection

    return resolve_editing_craft_selection(invocation={"camera": {"enabled": enabled}})


def bind(store, choice=None, **kwargs):
    return store.bind_editing_craft_selection(
        choice if choice is not None else selection(),
        actor="creator",
        reason="Selected treatment",
        **kwargs,
    )


def test_legacy_run_read_has_no_selection_or_side_effect(store):
    before = store.path.read_bytes()
    assert "executionChoices" not in store.load()
    assert store.path.read_bytes() == before


def test_first_selection_freezes_context_and_copies_inputs(store):
    choice = selection(True)
    basis = {name: None for name in ("cmap", "bmap", "tracks", "animation", "sync-map")}
    basis["cmap"] = {"revisionId": "cmap-001", "sha256": "a" * 64}
    direction = {"path": "edit/direction/selected.json", "sha256": "b" * 64}
    result = bind(
        store,
        choice,
        request_id="request-one",
        basis_heads=basis,
        direction_ref=direction,
    )
    frozen = result["executionChoices"]["editingCraft"]
    assert frozen["selection"] == choice
    assert frozen["basisHeads"] == basis
    assert frozen["directionRef"] == direction
    assert frozen["runId"] == "craft-run"
    assert frozen["requestId"] == "request-one"
    validate_document(result, "avo.pipeline-run.schema.json")
    choice["effective"]["camera"]["enabled"] = False
    basis["cmap"]["sha256"] = "c" * 64
    frozen["selection"]["effective"]["camera"]["enabled"] = False
    assert (
        store.load()["executionChoices"]["editingCraft"]["selection"]["effective"][
            "camera"
        ]["enabled"]
        is True
    )
    assert (
        store.load()["executionChoices"]["editingCraft"]["basisHeads"]["cmap"]["sha256"]
        == "a" * 64
    )


def test_resume_ignores_changed_future_preferences(store):
    first = bind(store, request_id="original")
    before = store.path.read_bytes()
    assert bind(store, selection(True)) == first
    assert store.path.read_bytes() == before


def test_identical_retry_preserves_exact_bytes(store):
    choice = selection(True)
    first = bind(store, choice, request_id="repeatable", new_request=True)
    before = store.path.read_bytes()
    assert bind(store, choice, request_id="repeatable", new_request=True) == first
    assert store.path.read_bytes() == before


def test_request_collision_is_rejected_without_writing(store):
    bind(store, request_id="repeatable")
    before = store.path.read_bytes()
    with pytest.raises(LifecycleError, match="conflict"):
        bind(store, selection(True), request_id="repeatable", new_request=True)
    assert store.path.read_bytes() == before


def test_new_request_preserves_history_and_side_state(store):
    first = bind(store, request_id="original")
    frozen = deepcopy(first["executionChoices"]["editingCraft"])
    blocked = store.enter_side_state(
        "blocked",
        actor="creator",
        reason="Await review",
        blockers=[{"code": "REVIEW_PENDING"}],
    )
    updated = bind(store, selection(True), request_id="replacement", new_request=True)
    for key in (
        "mainState",
        "sideState",
        "activeRefs",
        "blockers",
        "transitionHistory",
        "createdAt",
    ):
        assert updated[key] == blocked[key]
    assert updated["extensions"]["editingCraftRequestHistory"] == [frozen]
    before = store.path.read_bytes()
    assert bind(store, request_id="original", new_request=True) == updated
    assert store.path.read_bytes() == before


def test_different_request_requires_explicit_new_request(store):
    bind(store, request_id="original")
    with pytest.raises(LifecycleError, match="new_request"):
        bind(store, request_id="replacement")


@pytest.mark.parametrize(
    "kwargs",
    [
        {"request_id": " "},
        {"request_id": 4},
        {"new_request": "yes"},
        {"basis_heads": {"cmap": {"sha256": "invalid"}}},
        {"direction_ref": {"path": "draft", "sha256": "invalid"}},
    ],
)
def test_invalid_request_context_cannot_mutate_run(store, kwargs):
    before = store.path.read_bytes()
    with pytest.raises(LifecycleError):
        bind(store, **kwargs)
    assert store.path.read_bytes() == before


def test_tampered_selection_hash_cannot_be_frozen(store):
    choice = selection()
    choice["selectionHash"] = "0" * 64
    before = store.path.read_bytes()
    with pytest.raises(LifecycleError):
        bind(store, choice)
    assert store.path.read_bytes() == before


def test_pause_resume_retains_choices_without_granting_approval(store):
    frozen = bind(store, request_id="pending")["executionChoices"]["editingCraft"]
    store.enter_side_state("blocked", actor="creator", reason="Await source")
    resumed = store.resume(
        actor="creator", reason="Source restored", recovery_event="source-ready"
    )
    assert resumed["executionChoices"]["editingCraft"] == frozen
    assert resumed["mainState"] == "intake"
    assert resumed["activeRefs"] == {}


def test_craft_history_cannot_contain_untyped_requests(store):
    document = store.load()
    document["extensions"] = {"editingCraftRequestHistory": [{"requestId": "fake"}]}
    with pytest.raises(ContractError):
        validate_document(document, "avo.pipeline-run.schema.json")


def test_pipeline_request_start_freezes_craft_and_resume_keeps_it(
    footage_project_factory,
):
    from avo.timeline.pipeline import TimelinePipeline

    pipeline = TimelinePipeline(footage_project_factory())
    pipeline.initialize(
        craft_request={
            "selection": selection(False),
            "actor": "creator",
            "reason": "Start request",
        }
    )
    original = pipeline.run_store.load()["executionChoices"]["editingCraft"]
    pipeline.initialize(
        craft_request={
            "selection": selection(True),
            "actor": "creator",
            "reason": "Future preference",
        }
    )
    assert pipeline.run_store.load()["executionChoices"]["editingCraft"] == original
    assert pipeline.status()["motionPlan"]["options"] == original["selection"]
