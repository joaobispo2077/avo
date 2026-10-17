"""New-video options stay scoped proposals until an exact creator selection."""

import json
from copy import deepcopy
from pathlib import Path

import pytest

from avo.direction.brief import BriefService
from avo.direction.rules import DirectionError

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "briefstart"


@pytest.fixture
def project(tmp_path):
    raw = tmp_path / "next-video"
    raw.mkdir()
    path = raw / "avo.project.json"
    path.write_text(
        json.dumps(
            {
                "schemaVersion": "1.0.0",
                "provider": "neutral-channel",
                "videoId": "next-analysis",
                "rawDir": str(raw),
            }
        ),
        encoding="utf-8",
    )
    return path


def context():
    return json.loads((FIXTURE_ROOT / "context.json").read_text(encoding="utf-8"))


def reference():
    return {
        "schemaVersion": "1.0.0",
        "referenceId": "natural-delivery",
        "label": "Earlier delivery",
        "locator": None,
        "selectedAspects": ["Natural cadence"],
        "description": "Preserve a natural conversational delivery.",
        "observationKind": "user-described",
        "applicability": ["analysis-review"],
        "exclusions": ["Do not copy audio gains"],
        "knownUsageLimits": "No rights or approval transfer.",
    }


def options():
    def option(identifier, rhythm, visual):
        return {
            "id": identifier,
            "approach": f"A {identifier} comparison.",
            "treatment": {
                "rhythm": rhythm,
                "visual": visual,
                "motion": "Selective informative arrivals",
                "sound": "Voice above music and purposeful SFX",
            },
            "fit": "A qualified answer to whether longer is better.",
            "tradeoffs": ["Changes the emphasis, not the factual claim."],
            "sourceContribution": [
                {"sourceId": "natural-delivery", "aspects": ["Natural cadence"]}
            ],
            "statementIds": [],
            "exclusions": ["No copied timings or restoration settings"],
        }

    return [
        option("restrained", "Conversational", "Presenter and documentary evidence"),
        option(
            "progressive", "Stepwise contrast", "Progressive side-by-side comparison"
        ),
    ]


def prepared(service):
    return service.prepare("references", context(), [reference()])


def proposal_request(result):
    return {
        "requestId": "proposal-1",
        "packetRef": result["refs"]["packet"],
        "expectedIndexHash": result["expectedIndexHash"],
        "options": options(),
        "shortView": "Compare restrained conversation with progressive visual contrast.",
        "synthesisProvenance": {
            "executionKind": "driving-agent",
            "agentId": "fixture-agent",
            "modelId": None,
            "packetHash": result["refs"]["packet"]["documentHash"],
            "promptHash": None,
        },
    }


def read_packet(project_path, result):
    return json.loads(
        (
            project_path.parent
            / "edit"
            / "briefstart"
            / result["refs"]["packet"]["path"]
        ).read_text(encoding="utf-8")
    )


def test_prepare_reuses_known_context_and_writes_no_selection_index(project):
    result = prepared(BriefService(project))
    packet = read_packet(project, result)
    assert result["status"] == "needs-authoring"
    assert result["expectedIndexHash"] == "absent"
    assert packet["questions"] == []
    assert packet["context"]["promise"] == context()["promise"]
    assert not (project.parent / "edit" / "briefstart" / "index.json").exists()


def test_prepare_asks_at_most_three_material_questions_without_repeating_known_answers(
    project,
):
    result = BriefService(project).prepare(
        "references",
        {"schemaVersion": "1.0.0", "idea": "Compare long and short games."},
        [reference()],
    )
    packet = read_packet(project, result)
    assert result["status"] == "needs-context"
    assert 1 <= len(packet["questions"]) <= 3
    assert all("idea" not in question.lower() for question in packet["questions"])


def test_two_options_create_only_a_reviewable_project_proposal(project):
    service = BriefService(project)
    result = service.propose(proposal_request(prepared(service)))
    assert result["status"] == "needs-review"
    assert result["refs"]["proposal"]["documentHash"]
    index = json.loads(
        (project.parent / "edit" / "briefstart" / "index.json").read_text(
            encoding="utf-8"
        )
    )
    assert index.get("selectedBriefRef") is None
    assert index.get("selectedSelectionRef") is None


def test_proposal_cannot_hide_oversize_options_behind_a_short_summary(project):
    service = BriefService(project)
    request = proposal_request(prepared(service))
    request["options"][0]["treatment"]["visual"] = "visible " * 601
    with pytest.raises(DirectionError) as error:
        service.propose(request)
    assert error.value.code == "BRIEF_WORD_LIMIT"


def test_single_option_needs_an_explicit_constraint_explanation(project):
    service = BriefService(project)
    request = proposal_request(prepared(service))
    request["options"] = request["options"][:1]
    with pytest.raises(DirectionError):
        service.propose(request)
    request["singletonReason"] = (
        "Only one format is feasible with the source constraints."
    )
    assert service.propose(request)["status"] == "needs-review"


def test_option_names_alone_do_not_establish_distinct_directions(project):
    service = BriefService(project)
    request = proposal_request(prepared(service))
    request["options"][1] = {**deepcopy(request["options"][0]), "id": "another-name"}
    with pytest.raises(DirectionError):
        service.propose(request)


def test_option_cannot_cite_a_source_missing_from_the_exact_packet(project):
    service = BriefService(project)
    request = proposal_request(prepared(service))
    request["options"][0]["sourceContribution"][0]["sourceId"] = "invented-source"
    with pytest.raises(DirectionError):
        service.propose(request)


def test_same_content_retry_is_idempotent_but_changed_content_same_request_is_rejected(
    project,
):
    service = BriefService(project)
    request = proposal_request(prepared(service))
    first = service.propose(request)
    assert service.propose(request)["refs"]["proposal"] == first["refs"]["proposal"]
    request["shortView"] = "Changed content under the old request identity."
    with pytest.raises(DirectionError):
        service.propose(request)


def test_a_packet_cannot_be_silently_rebound_after_another_proposal_changes_the_index(
    project,
):
    service = BriefService(project)
    request = proposal_request(prepared(service))
    service.propose(request)
    request["requestId"] = "different-proposal"
    with pytest.raises(DirectionError) as error:
        service.propose(request)
    assert error.value.status in {"stale", "conflict"}


def test_changed_packet_target_hash_cannot_be_submitted(project):
    service = BriefService(project)
    request = proposal_request(prepared(service))
    request["packetRef"]["documentHash"] = "f" * 64
    with pytest.raises(DirectionError):
        service.propose(request)


def test_exact_project_selection_freezes_only_authorial_sources_and_overrides(project):
    service = BriefService(project)
    selected_context = context()
    selected_context["currentInstructions"] = ["Keep this video conversational."]
    preparation = service.prepare("references", selected_context, [reference()])
    proposal = service.propose(proposal_request(preparation))
    request = {
        "requestId": "choose-1",
        "targetRef": proposal["refs"]["proposal"],
        "expectedIndexHash": proposal["expectedIndexHash"],
        "action": "select",
        "scope": "project",
        "actor": {"type": "human", "id": "fixture-creator"},
        "reason": "Choose the restrained direction for this project.",
        "humanInstruction": {
            "source": "test:explicit-human-selection",
            "text": "Select restrained for this video.",
        },
        "optionId": "restrained",
    }
    assert service.decide(request)["status"] == "selected"
    shown = service.show()
    assert (
        shown["brief"]["context"]["currentInstructions"]
        == selected_context["currentInstructions"]
    )
    assert shown["selection"]["scope"] == "project"
    frozen = list((service.root / "frozen").glob("*.json"))
    assert len(frozen) == 1
    assert (
        json.loads(frozen[0].read_text(encoding="utf-8"))["source"]["document"]
        == reference()
    )
    assert not (project.parent / "edit" / "timeline").exists()
    stage = service.stage_context("motion")["context"]
    assert stage["constraints"] == selected_context["constraints"]


def test_reference_only_option_cannot_invent_provider_statement_ids(project):
    service = BriefService(project)
    request = proposal_request(prepared(service))
    request["options"][0]["statementIds"] = ["fictional-preference"]
    with pytest.raises(DirectionError):
        service.propose(request)


def test_brief_root_cannot_escape_raw_directory_through_a_symlink(project, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    try:
        (project.parent / "edit").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("This host does not permit directory symlinks.")
    with pytest.raises(DirectionError):
        BriefService(project).prepare("references", context(), [reference()])
    assert list(outside.iterdir()) == []


def test_derived_view_cannot_escape_through_a_nested_directory_symlink(
    project, tmp_path
):
    service = BriefService(project)
    preparation = prepared(service)
    outside = tmp_path / "outside-view"
    outside.mkdir()
    try:
        (service.root / "views").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("This host does not permit directory symlinks.")
    result = service.propose(proposal_request(preparation))
    assert list(outside.iterdir()) == []
    assert result["warnings"]


def test_actual_provider_statement_text_and_scope_reach_the_selected_stage(tmp_path):
    from tests.test_briefstart_context import selected_project

    _, service, _, _ = selected_project(tmp_path, provider_mode=True)
    new_context = context()
    new_context["primaryFormat"] = "step-by-step"
    preparation = service.prepare("provider:editorial@r0001", new_context)
    packet = service.store.load_document(preparation["refs"]["packet"]["path"])
    source = packet["sources"][0]
    source_statement = source["document"]["statements"][0]
    request = proposal_request(preparation)
    for option in request["options"]:
        option["sourceContribution"] = [
            {"sourceId": source["id"], "aspects": ["Speech priority"]}
        ]
        option["statementIds"] = [source_statement["statementId"]]
    proposal = service.propose(request)
    service.decide(
        {
            "requestId": "select-provider-statement",
            "targetRef": proposal["refs"]["proposal"],
            "expectedIndexHash": proposal["expectedIndexHash"],
            "action": "select",
            "scope": "project",
            "actor": {"type": "human", "id": "fixture-creator"},
            "reason": "Use this applicable sound direction in this tutorial.",
            "humanInstruction": {
                "source": "test:human-selection",
                "text": "Select restrained for this tutorial.",
            },
            "optionId": "restrained",
        }
    )
    stage = service.stage_context("sound")["context"]
    assert stage["statements"][0]["text"] == source_statement["text"]
    assert stage["statements"][0]["applicability"] == source_statement["applicability"]
    assert stage["constraints"] == new_context["constraints"]


def test_changed_provider_support_is_visible_before_a_new_brief_is_authored(tmp_path):
    from tests.test_briefstart_context import selected_project

    _, service, _, _ = selected_project(tmp_path, provider_mode=True)
    learner = next((tmp_path / "neutral" / "learndowns").glob("*/learndown.json"))
    learner.write_bytes(learner.read_bytes() + b"\n")
    result = service.prepare("provider:editorial@r0001", context())
    packet = service.store.load_document(result["refs"]["packet"]["path"])
    assert result["warnings"]
    assert any("changed" in disposition for disposition in packet["sourceDispositions"])


def test_reference_packet_cannot_exceed_the_authoring_word_budget(project):
    descriptor = reference()
    descriptor["description"] = "reference " * 24001
    with pytest.raises(DirectionError) as error:
        BriefService(project).prepare("references", context(), [descriptor])
    assert error.value.code == "DIR_PACKET_LIMIT"
