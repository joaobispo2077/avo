"""Edits, opt-out and retries preserve project authorship and immutable history."""

import json
from copy import deepcopy

import pytest

from avo.direction.brief import BriefService
from avo.direction.rules import DirectionError
from avo.timeline.contracts import document_hash_excluding
from tests.test_briefstart import prepared, proposal_request
from tests.test_briefstart_modes import selected


@pytest.fixture
def service(tmp_path):
    raw = tmp_path / "next-video"
    raw.mkdir()
    project = raw / "avo.project.json"
    project.write_text(
        json.dumps(
            {
                "schemaVersion": "1.0.0",
                "provider": "neutral-channel",
                "videoId": "next-video",
                "rawDir": str(raw),
            }
        ),
        encoding="utf-8",
    )
    return BriefService(project)


def decision(target, expected, *, action="select", request_id="decision-2"):
    return {
        "requestId": request_id,
        "targetRef": target,
        "expectedIndexHash": expected,
        "action": action,
        "scope": "project",
        "actor": {"type": "human", "id": "fixture-creator"},
        "reason": "A project-specific creator decision.",
        "humanInstruction": {
            "source": "test:human-decision",
            "text": "Apply this exact disposition to this project only.",
        },
    }


def next_proposal(service):
    request = proposal_request(prepared(service))
    request["requestId"] = "proposal-2"
    request["shortView"] = "A second explicitly requested treatment proposal."
    return service.propose(request)


def test_opt_out_requires_the_prepared_exact_decision_and_keeps_old_history(service):
    selected(service)
    before = service.store.load_index()
    proposal = service.prepare("none")
    request = decision(proposal["refs"]["proposal"], proposal["expectedIndexHash"])
    assert service.store.load_index() == before
    result = service.decide(request)
    assert result["status"] == "selected"
    after = service.store.load_index()
    assert after["mode"] == "none"
    assert after["selectedBriefRef"] is None
    assert before["selectedBriefRef"] in after["proposedRefs"]
    assert before["selectedSelectionRef"] in after["selectionRefs"]
    assert service.stage_context("motion")["status"] == "bypassed"


@pytest.mark.parametrize("action", ["edit", "qualify"])
def test_changed_content_gets_a_new_proposal_and_requires_exact_selection(
    service, action
):
    selected(service)
    before = service.store.load_index()
    proposal = next_proposal(service)
    request = decision(
        proposal["refs"]["proposal"], proposal["expectedIndexHash"], action=action
    )
    request["edits"] = {
        "shortView": "Use a quieter explanation for this project.",
        "creatorChanges": ["Keep this particular explanation quiet."],
    }
    result = service.decide(request)
    assert result["status"] == "needs-review"
    assert result["refs"]["proposal"] != proposal["refs"]["proposal"]
    assert service.store.load_index()["selectedBriefRef"] == before["selectedBriefRef"]
    select_request = decision(
        result["refs"]["proposal"],
        result["expectedIndexHash"],
        request_id="select-edited-exact",
    )
    select_request["optionId"] = "restrained"
    assert service.decide(select_request)["status"] == "selected"
    assert (
        "Keep this particular explanation quiet."
        in service.stage_context("sound")["context"]["overrides"]
    )


@pytest.mark.parametrize("action", ["reject", "defer"])
def test_rejected_or_deferred_new_candidate_does_not_replace_selected_work(
    service, action
):
    selected(service)
    before = service.store.load_index()["selectedBriefRef"]
    proposal = next_proposal(service)
    request = decision(
        proposal["refs"]["proposal"], proposal["expectedIndexHash"], action=action
    )
    result = service.decide(request)
    assert result["disposition"] == action
    assert service.store.load_index()["selectedBriefRef"] == before


def test_decision_retry_is_idempotent_and_changed_authority_cannot_reuse_its_id(
    service,
):
    proposal = service.propose(proposal_request(prepared(service)))
    request = decision(proposal["refs"]["proposal"], proposal["expectedIndexHash"])
    request["optionId"] = "restrained"
    service.decide(request)
    before = (service.root / "index.json").read_bytes()
    service.decide(request)
    assert (service.root / "index.json").read_bytes() == before
    changed = deepcopy(request)
    changed["optionId"] = "progressive"
    with pytest.raises(DirectionError):
        service.decide(changed)


def test_stale_decision_cannot_select_a_new_candidate_over_another_decision(service):
    selected(service)
    proposal = next_proposal(service)
    request = decision(proposal["refs"]["proposal"], "a" * 64)
    request["optionId"] = "restrained"
    with pytest.raises(DirectionError) as error:
        service.decide(request)
    assert error.value.status == "conflict"


def test_qualification_only_preserves_summary_and_displays_creator_changes_once(
    service,
):
    selected(service)
    proposal = next_proposal(service)
    request = decision(
        proposal["refs"]["proposal"], proposal["expectedIndexHash"], action="qualify"
    )
    request["edits"] = {"creatorChanges": ["Use one quiet visual comparison."]}
    result = service.decide(request)
    document = service.store.load_document(result["refs"]["proposal"]["path"])
    assert (
        document["summaryText"] == "A second explicitly requested treatment proposal."
    )
    assert document["shortView"].count("### restrained") == 1
    assert "Use one quiet visual comparison." in document["shortView"]


def fail_index_publication(monkeypatch):
    import avo.direction.store as store_module

    original = store_module.atomic_write_json

    def fail(path, document):
        if path.name == "index.json":
            raise RuntimeError("Injected index publication failure")
        return original(path, document)

    monkeypatch.setattr(store_module, "atomic_write_json", fail)


def test_proposal_retry_reuses_only_its_exact_orphan_when_the_clock_changes(
    service, monkeypatch
):
    request = proposal_request(prepared(service))
    service.clock = lambda: "2026-01-01T00:00:00Z"
    fail_index_publication(monkeypatch)
    with pytest.raises(RuntimeError, match="publication failure"):
        service.propose(request)
    orphan = next((service.root / "briefs").glob("*.json"))
    before = orphan.read_bytes()
    assert service.store.load_index() is None
    monkeypatch.undo()
    service.clock = lambda: "2026-01-02T00:00:00Z"
    result = service.propose(request)
    assert result["status"] == "needs-review"
    assert orphan.read_bytes() == before


def test_selection_retry_reuses_exact_events_and_selection_after_index_crash(
    service, monkeypatch
):
    proposal = service.propose(proposal_request(prepared(service)))
    request = decision(proposal["refs"]["proposal"], proposal["expectedIndexHash"])
    request["optionId"] = "restrained"
    service.clock = lambda: "2026-01-01T00:00:00Z"
    before_index = (service.root / "index.json").read_bytes()
    fail_index_publication(monkeypatch)
    with pytest.raises(RuntimeError, match="publication failure"):
        service.decide(request)
    originals = {
        path: path.read_bytes() for path in (service.root / "decisions").glob("*.json")
    }
    assert (service.root / "index.json").read_bytes() == before_index
    monkeypatch.undo()
    service.clock = lambda: "2026-01-02T00:00:00Z"
    assert service.decide(request)["status"] == "selected"
    assert all(path.read_bytes() == encoded for path, encoded in originals.items())


def test_foreign_validly_rehashed_orphan_cannot_be_activated_as_the_requested_proposal(
    service, monkeypatch
):
    request = proposal_request(prepared(service))
    fail_index_publication(monkeypatch)
    with pytest.raises(RuntimeError, match="publication failure"):
        service.propose(request)
    orphan = next((service.root / "briefs").glob("*.json"))
    document = json.loads(orphan.read_text(encoding="utf-8"))
    document["context"]["promise"] = "A different promise injected into the orphan."
    document["documentHash"] = document_hash_excluding(document, "documentHash")
    orphan.write_text(json.dumps(document), encoding="utf-8")
    before = orphan.read_bytes()
    monkeypatch.undo()
    with pytest.raises(DirectionError) as error:
        service.propose(request)
    assert error.value.status == "conflict"
    assert orphan.read_bytes() == before
    assert service.store.load_index() is None


def test_proposal_retry_returns_its_original_snapshot_after_a_later_selection(service):
    request = proposal_request(prepared(service))
    original = service.propose(request)
    choose = decision(
        original["refs"]["proposal"],
        original["expectedIndexHash"],
        request_id="first-select",
    )
    choose["optionId"] = "restrained"
    service.decide(choose)
    before = (service.root / "index.json").read_bytes()
    replayed = service.propose(request)
    assert replayed["expectedIndexHash"] == original["expectedIndexHash"]
    assert replayed["refs"]["proposal"] == original["refs"]["proposal"]
    assert (service.root / "index.json").read_bytes() == before


def test_selection_retry_returns_original_snapshot_without_reversing_later_opt_out(
    service,
):
    proposal = service.propose(proposal_request(prepared(service)))
    choose = decision(
        proposal["refs"]["proposal"],
        proposal["expectedIndexHash"],
        request_id="first-select",
    )
    choose["optionId"] = "restrained"
    original = service.decide(choose)
    opt_out = service.prepare("none")
    service.decide(
        decision(
            opt_out["refs"]["proposal"],
            opt_out["expectedIndexHash"],
            request_id="later-opt-out",
        )
    )
    before = (service.root / "index.json").read_bytes()
    replayed = service.decide(choose)
    assert replayed["expectedIndexHash"] == original["expectedIndexHash"]
    assert replayed["refs"]["brief"] == original["refs"]["brief"]
    assert replayed["refs"] == original["refs"]
    assert (service.root / "index.json").read_bytes() == before
    assert service.show()["mode"] == "none"
