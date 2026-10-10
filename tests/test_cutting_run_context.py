import pytest

from avo.timeline.lifecycle import LifecycleError, PipelineRunStore


def run_store(tmp_path):
    store = PipelineRunStore(tmp_path / "pipeline-run.json")
    store.initialize(
        run_id="cutting-run",
        video_id="fixture",
        provider="bishop",
        project_path="fixture.json",
    )
    return store


def test_cutting_refs_do_not_advance_approval_or_state(tmp_path):
    store = run_store(tmp_path)
    before = store.load()
    references = {"proposal": {"locator": "cutting/proposal.json", "sha256": "a" * 64}}
    result = store.bind_cutting_context(references)
    assert result["activeRefs"]["cutting"] == references
    assert result["mainState"] == before["mainState"]
    assert result["sideState"] == before["sideState"]
    assert result["transitionHistory"] == before["transitionHistory"]


def test_bad_cutting_refs_are_rejected_without_a_write(tmp_path):
    store = run_store(tmp_path)
    before = store.path.read_bytes()
    with pytest.raises(LifecycleError, match="cutting"):
        store.bind_cutting_context({"proposal": {"locator": "x", "sha256": "bad"}})
    assert store.path.read_bytes() == before


def test_stale_cutting_context_cannot_overwrite_run(tmp_path):
    store = run_store(tmp_path)
    with pytest.raises(LifecycleError, match="compare-and-swap"):
        store.bind_cutting_context({}, expected_updated_at="obsolete")


def test_adding_verification_keeps_existing_proposal_binding(tmp_path):
    store = run_store(tmp_path)
    proposal = {"locator": "proposal.json", "sha256": "a" * 64}
    store.bind_cutting_context({"proposal": proposal})
    result = store.bind_cutting_context(
        {"verification": {"locator": "check.json", "sha256": "b" * 64}}
    )
    assert result["activeRefs"]["cutting"]["proposal"] == proposal
