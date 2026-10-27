"""Durable per-request motion choices without changing editorial authority."""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from itertools import count

import pytest

from avo.motion import MotionError, resolve_motion_selection
from avo.timeline.contracts import ContractError, validate_document
from avo.timeline.lifecycle import LifecycleError, PipelineRunStore, TransitionFacts
from avo.timeline.pipeline import TimelinePipeline
from avo.timeline.workspace import TimelineWorkspace

RUN_FIELDS = {"runId", "requestId", "engine", "source", "resolutionHash"}


def _selection(engine="code-drawn", source="invocation"):
    if source == "default":
        return resolve_motion_selection()
    return resolve_motion_selection(
        **{
            source + "_settings" if source != "invocation" else source: {
                "engine": engine
            }
        }
    )


def _clock():
    ticks = count()
    start = datetime(2026, 10, 26, tzinfo=UTC)
    return lambda: (
        (start + timedelta(seconds=next(ticks))).isoformat().replace("+00:00", "Z")
    )


@pytest.fixture
def run_store(tmp_path):
    store = PipelineRunStore(tmp_path / "pipeline-run.json", clock=_clock())
    store.initialize(
        run_id="video-run-0001",
        video_id="video",
        provider="sample",
        project_path=str(tmp_path / "avo.project.json"),
    )
    return store


def _nested_values(value):
    yield value
    if isinstance(value, dict):
        for child in value.values():
            yield from _nested_values(child)
    elif isinstance(value, list):
        for child in value:
            yield from _nested_values(child)


def _pipeline(tmp_path, name="video"):
    raw = tmp_path / name
    raw.mkdir()
    path = raw / "avo.project.json"
    path.write_text(
        json.dumps(
            {
                "schemaVersion": "1.0.0",
                "provider": "bishop",
                "videoId": name,
                "rawDir": str(raw),
            }
        ),
        encoding="utf-8",
    )
    return TimelinePipeline(TimelineWorkspace.from_project(path))


def _canonical_bytes(pipeline):
    return {
        path.relative_to(pipeline.workspace.timeline_dir).as_posix(): path.read_bytes()
        for path in pipeline.workspace.timeline_dir.rglob("*")
        if path.is_file() and path != pipeline.workspace.pipeline_run_path
    }


def test_legacy_run_without_execution_choices_remains_valid_and_unchanged(run_store):
    before = run_store.path.read_bytes()
    document = run_store.load()
    assert "executionChoices" not in document
    assert validate_document(document, "avo.pipeline-run.schema.json") == document
    assert run_store.path.read_bytes() == before


def test_first_choice_pins_only_typed_identity_fields_and_defensively_copies(run_store):
    selection = _selection()
    document = run_store.bind_motion_selection(selection, request_id="request-one")
    pinned = document["executionChoices"]["motion"]
    assert set(pinned) == RUN_FIELDS
    assert pinned == {
        "runId": document["runId"],
        "requestId": "request-one",
        "engine": "code-drawn",
        "source": "invocation",
        "resolutionHash": selection["resolutionHash"],
    }
    assert validate_document(document, "avo.pipeline-run.schema.json") == document
    selection["engine"] = "remotion"
    document["executionChoices"]["motion"]["engine"] = "hyperframes"
    assert run_store.load()["executionChoices"]["motion"]["engine"] == "code-drawn"


def test_automatic_request_identity_is_stable_across_repeated_initialization(run_store):
    first = run_store.bind_motion_selection(_selection())
    pinned = first["executionChoices"]["motion"]
    assert pinned["requestId"]
    before = run_store.path.read_bytes()
    second = run_store.bind_motion_selection(_selection())
    assert second["executionChoices"]["motion"] == pinned
    assert run_store.path.read_bytes() == before


def test_changed_future_default_cannot_reinterpret_an_existing_request(run_store):
    initial = run_store.bind_motion_selection(
        _selection("code-drawn"), request_id="initial"
    )
    before = run_store.path.read_bytes()
    current = run_store.bind_motion_selection(
        _selection("hyperframes", source="global")
    )
    assert (
        current["executionChoices"]["motion"] == initial["executionChoices"]["motion"]
    )
    assert run_store.path.read_bytes() == before


def test_same_explicit_request_retry_is_idempotent_even_when_new_request_is_requested(
    run_store,
):
    selection = _selection()
    first = run_store.bind_motion_selection(
        selection, request_id="repeatable", new_request=True
    )
    before = run_store.path.read_bytes()
    retry = run_store.bind_motion_selection(
        selection, request_id="repeatable", new_request=True
    )
    assert retry == first
    assert run_store.path.read_bytes() == before


def test_reusing_request_identity_for_a_different_choice_conflicts_without_mutation(
    run_store,
):
    run_store.bind_motion_selection(_selection(), request_id="repeatable")
    before = run_store.path.read_bytes()
    with pytest.raises((LifecycleError, MotionError)):
        run_store.bind_motion_selection(
            _selection("hyperframes"), request_id="repeatable", new_request=True
        )
    assert run_store.path.read_bytes() == before


def test_new_request_records_previous_choice_without_resetting_lifecycle(run_store):
    first = run_store.bind_motion_selection(_selection(), request_id="original")
    previous = deepcopy(first["executionChoices"]["motion"])
    run_store.advance(
        "sources-ready",
        TransitionFacts(),
        actor="agent",
        reason="inventory",
        active_refs={"sourceInventory": {"sha256": "a" * 64}},
    )
    blocked = run_store.enter_side_state(
        "blocked",
        actor="agent",
        reason="Review tool unavailable",
        blockers=[{"code": "WATCH_UNAVAILABLE"}],
    )
    updated = run_store.bind_motion_selection(
        _selection("hyperframes", source="global"),
        request_id="replacement",
        new_request=True,
    )
    assert updated["executionChoices"]["motion"]["engine"] == "hyperframes"
    assert updated["executionChoices"]["motion"]["requestId"] == "replacement"
    for field in (
        "runId",
        "mainState",
        "sideState",
        "activeRefs",
        "blockers",
        "createdAt",
    ):
        assert updated[field] == blocked[field]
    assert (
        updated["transitionHistory"][: len(blocked["transitionHistory"])]
        == blocked["transitionHistory"]
    )
    assert previous in list(_nested_values(updated.get("extensions", {})))


def test_pause_and_resume_keep_the_exact_original_choice(run_store):
    chosen = run_store.bind_motion_selection(_selection(), request_id="original")[
        "executionChoices"
    ]["motion"]
    blocked = run_store.enter_side_state(
        "blocked",
        actor="agent",
        reason="Wait for review",
        blockers=[{"code": "WATCH_UNAVAILABLE"}],
    )
    assert blocked["executionChoices"]["motion"] == chosen
    resumed = run_store.resume(
        actor="creator", reason="Review restored", recovery_event="watch-ready"
    )
    assert resumed["sideState"] is None
    assert resumed["executionChoices"]["motion"] == chosen
    assert len(resumed["transitionHistory"]) == len(blocked["transitionHistory"]) + 1


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("engine", "canvas"),
        ("source", "machine"),
        ("resolutionHash", "invalid"),
    ],
)
def test_invalid_choice_never_changes_the_run(run_store, field, value):
    selection = _selection()
    selection[field] = value
    before = run_store.path.read_bytes()
    with pytest.raises((LifecycleError, MotionError, ContractError)):
        run_store.bind_motion_selection(selection)
    assert run_store.path.read_bytes() == before


@pytest.mark.parametrize("request_id", ["", "   "])
def test_empty_explicit_request_identity_is_rejected(run_store, request_id):
    before = run_store.path.read_bytes()
    with pytest.raises((LifecycleError, MotionError)):
        run_store.bind_motion_selection(_selection(), request_id=request_id)
    assert run_store.path.read_bytes() == before


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("runId", "different-run"),
        ("requestId", ""),
        ("engine", "canvas"),
        ("source", "machine"),
        ("resolutionHash", "invalid"),
    ],
)
def test_loading_malformed_or_foreign_run_choice_fails_closed(run_store, field, value):
    document = run_store.load()
    pinned = {
        "runId": document["runId"],
        "requestId": "request-one",
        "engine": "code-drawn",
        "source": "invocation",
        "resolutionHash": "a" * 64,
    }
    pinned[field] = value
    document["executionChoices"] = {"motion": pinned}
    run_store.path.write_text(json.dumps(document), encoding="utf-8")
    before = run_store.path.read_bytes()
    with pytest.raises(LifecycleError):
        run_store.load()
    assert run_store.path.read_bytes() == before


def test_pipeline_initialization_binds_legacy_canonical_workspace_and_preserves_it(
    tmp_path,
):
    pipeline = _pipeline(tmp_path)
    pipeline.initialize()
    assert pipeline.workspace.authority == "canonical"
    canonical = _canonical_bytes(pipeline)
    pipeline.initialize(motion_selection=_selection(), request_id="first")
    first = pipeline.run_store.load()["executionChoices"]["motion"]
    pipeline.initialize(motion_selection=_selection("hyperframes", source="global"))
    assert pipeline.run_store.load()["executionChoices"]["motion"] == first
    assert _canonical_bytes(pipeline) == canonical
    pipeline.initialize(
        motion_selection=_selection("hyperframes", source="global"),
        request_id="second",
        new_request=True,
    )
    assert (
        pipeline.run_store.load()["executionChoices"]["motion"]["requestId"] == "second"
    )
    assert _canonical_bytes(pipeline) == canonical


def test_fresh_pipeline_resolves_the_new_selection_without_reusing_another_run(
    tmp_path,
):
    first, second = _pipeline(tmp_path, "first"), _pipeline(tmp_path, "second")
    first.initialize(motion_selection=_selection(), request_id="first-request")
    second.initialize(
        motion_selection=_selection("hyperframes", source="global"),
        request_id="second-request",
    )
    assert (
        first.run_store.load()["executionChoices"]["motion"]["engine"] == "code-drawn"
    )
    assert (
        second.run_store.load()["executionChoices"]["motion"]["engine"] == "hyperframes"
    )


def test_pipeline_status_does_not_backfill_a_legacy_run_choice(tmp_path):
    pipeline = _pipeline(tmp_path)
    pipeline.initialize()
    before = {
        path: path.read_bytes()
        for path in pipeline.workspace.timeline_dir.rglob("*")
        if path.is_file()
    }
    pipeline.status()
    assert {path: path.read_bytes() for path in before} == before
    assert "executionChoices" not in pipeline.run_store.load()


def test_retrying_a_historical_request_keeps_the_current_request_without_mutation(
    run_store,
):
    original = _selection()
    run_store.bind_motion_selection(original, request_id="original")
    current = run_store.bind_motion_selection(
        _selection("hyperframes"), request_id="current", new_request=True
    )
    before = run_store.path.read_bytes()
    retried = run_store.bind_motion_selection(
        original, request_id="original", new_request=True
    )
    assert retried == current
    assert run_store.path.read_bytes() == before


def test_historical_request_identity_cannot_be_reused_for_different_intent(run_store):
    run_store.bind_motion_selection(_selection(), request_id="original")
    run_store.bind_motion_selection(
        _selection("hyperframes"), request_id="current", new_request=True
    )
    before = run_store.path.read_bytes()
    with pytest.raises((LifecycleError, MotionError)):
        run_store.bind_motion_selection(
            _selection("remotion"), request_id="original", new_request=True
        )
    assert run_store.path.read_bytes() == before
