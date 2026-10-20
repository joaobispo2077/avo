"""Artistic guidance is optional, explicit and pinned for an existing project."""

import json

import pytest

from avo.direction.brief import BriefService
from avo.direction.rules import DirectionError
from tests.test_briefstart import context, prepared, proposal_request


@pytest.fixture
def project(tmp_path):
    raw = tmp_path / "new-video"
    raw.mkdir()
    path = raw / "avo.project.json"
    path.write_text(
        json.dumps(
            {
                "schemaVersion": "1.0.0",
                "provider": "neutral-channel",
                "videoId": "new-video",
                "rawDir": str(raw),
            }
        ),
        encoding="utf-8",
    )
    return path


def selected(service):
    candidate = service.propose(proposal_request(prepared(service)))
    return service.decide(
        {
            "requestId": "choose-1",
            "targetRef": candidate["refs"]["proposal"],
            "expectedIndexHash": candidate["expectedIndexHash"],
            "action": "select",
            "scope": "project",
            "actor": {"type": "human", "id": "fixture-creator"},
            "reason": "Choose the restrained treatment for this video.",
            "humanInstruction": {
                "source": "test:user-message-1",
                "text": "Select the restrained option for this project.",
            },
            "optionId": "restrained",
        }
    )


@pytest.mark.parametrize("selector", [None, "none"])
def test_new_raw_entry_bypasses_all_artistic_source_resolution(
    project, monkeypatch, selector
):
    service = BriefService(project)

    def forbidden(*args, **kwargs):
        pytest.fail("No-reference startup must not resolve artistic sources.")

    monkeypatch.setattr(service, "_sources", forbidden)
    result = service.prepare(selector)
    assert result["status"] == "bypassed"
    assert not service.root.exists()


def test_none_does_not_implicitly_select_an_existing_provider_profile(
    project, tmp_path
):
    provider = tmp_path / "provider"
    direction = provider / "direction"
    direction.mkdir(parents=True)
    (direction / "index.json").write_text(
        "Not consulted for raw entry.", encoding="utf-8"
    )
    service = BriefService(project, provider_root=provider)
    assert service.prepare("none")["status"] == "bypassed"
    assert not service.root.exists()


@pytest.mark.parametrize(
    "identifier",
    ["analysis-review", "step-by-step", "narrative-conversation", "focused-short"],
)
def test_every_builtin_is_available_without_provider_learning(
    project, tmp_path, identifier
):
    service = BriefService(project, provider_root=tmp_path / "offline-provider")
    result = service.prepare(f"builtin:{identifier}@1.0.0", context())
    assert result["status"] == "needs-authoring"
    packet = service.store.load_document(result["refs"]["packet"]["path"])
    source = packet["sources"][0]
    assert source["kind"] == "builtin"
    assert source["id"] == identifier
    assert source["document"]["version"] == "1.0.0"


def test_provider_mode_requires_a_real_exact_accepted_profile(project, tmp_path):
    service = BriefService(project, provider_root=tmp_path / "no-accepted-profile")
    with pytest.raises(DirectionError) as error:
        service.prepare("provider:editorial@r0001", context())
    assert error.value.code == "BRIEF_UNACCEPTED_PROVIDER_PROFILE"
    assert not service.root.exists()


def test_omission_on_an_existing_selected_project_retains_its_exact_choice(project):
    service = BriefService(project)
    selected(service)
    before = (service.root / "index.json").read_bytes()
    result = service.prepare()
    assert result["status"] == "selected"
    assert (service.root / "index.json").read_bytes() == before


def test_explicit_none_on_a_bound_project_only_prepares_a_typed_opt_out(project):
    service = BriefService(project)
    selected(service)
    before = service.store.load_index()
    result = service.prepare("none")
    assert result["status"] == "needs-review"
    proposal = service.store.load_document(result["refs"]["proposal"]["path"])
    assert proposal["documentType"] == "BriefOptOutProposal"
    assert proposal["previousSelectionRef"] == before["selectedSelectionRef"]
    assert service.store.load_index() == before


def test_initial_declaration_is_not_silently_treated_as_none(project):
    document = json.loads(project.read_text(encoding="utf-8"))
    document["direction"] = {"selector": "builtin:analysis-review@1.0.0"}
    project.write_text(json.dumps(document), encoding="utf-8")
    result = BriefService(project).prepare(context=context())
    assert result["status"] == "needs-authoring"
