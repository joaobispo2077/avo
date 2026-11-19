"""Pending authoring references survive request changes without granting approval."""

from copy import deepcopy

import pytest

from avo.timeline.lifecycle import LifecycleError, PipelineRunStore
from tests.test_editing_craft_run_selection import bind
from tests.test_editing_craft_run_selection import store as run_store

store = pytest.fixture(name="store")(run_store.__wrapped__)


def work(kind="sound", operation="sound-first", request_id="request-one"):
    namespace = "sound/" if kind == "sound" else ""
    return {
        "kind": kind,
        "operationId": operation,
        "requestId": request_id,
        "proposalRef": {
            "path": f"edit/motion/{namespace}proposals/{'a' * 64}.json",
            "sha256": "a" * 64,
        },
        "scope": {
            "itemIds": ["mo04"],
            "eventIds": ["sound-mo04"] if kind == "sound" else [],
        },
    }


def test_pending_references_are_idempotent_and_keep_original_requests_after_restart(
    store,
):
    bind(store, request_id="request-one")
    original = work()
    store.bind_editing_craft_work(original)
    before = store.path.read_bytes()
    store.bind_editing_craft_work(original)
    assert store.path.read_bytes() == before
    original["proposalRef"]["sha256"] = "b" * 64
    bind(store, request_id="request-two", new_request=True)
    second = work("motion", "motion-next", "request-two")
    store.bind_editing_craft_work(second)
    fresh = PipelineRunStore(store.path).load()
    assert fresh["extensions"]["editingCraftWork"] == [work(), second]
    assert fresh["activeRefs"] == {}
    assert fresh["mainState"] == "intake"


@pytest.mark.parametrize(
    "problem", ["unknown-request", "wrong-path", "conflict", "unknown-field", "scope"]
)
def test_invalid_pending_work_cannot_replace_saved_references(store, problem):
    bind(store, request_id="request-one")
    original = work()
    store.bind_editing_craft_work(original)
    changed = deepcopy(original)
    if problem == "unknown-request":
        changed["requestId"] = "not-frozen"
    elif problem == "wrong-path":
        changed["proposalRef"]["path"] = "edit/motion/proposals/" + "a" * 64 + ".json"
    elif problem == "unknown-field":
        changed["approved"] = True
    elif problem == "scope":
        changed["scope"]["itemIds"] = ["another-item"]
    else:
        changed["proposalRef"] = {
            "path": "edit/motion/sound/proposals/" + "b" * 64 + ".json",
            "sha256": "b" * 64,
        }
    before = store.path.read_bytes()
    with pytest.raises(LifecycleError):
        store.bind_editing_craft_work(changed)
    assert store.path.read_bytes() == before


def test_requested_work_budget_fails_before_replacing_the_run(store):
    bind(store, request_id="request-one")
    document = store.load()
    document.setdefault("extensions", {})["editingCraftWork"] = [
        work(operation=f"sound-{index}") for index in range(500)
    ]
    store._write(document)
    before = store.path.read_bytes()
    with pytest.raises(LifecycleError, match="invalid pipeline run"):
        store.bind_editing_craft_work(work(operation="over-budget"))
    assert store.path.read_bytes() == before
