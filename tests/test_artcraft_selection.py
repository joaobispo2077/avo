"""Exercise optional routing with no native ArtCraft process or discovery."""

import importlib
from dataclasses import replace

import pytest

from avo.timeline.contracts import content_hash
from tests.artcraft_fixtures import ACTIVITIES, ArtCraftActivity, request


def candidate(route="hyperframes", status="sufficient"):
    return {
        "route": route,
        "contractRef": f"avo:motions:{route}@1",
        "contractHash": content_hash([route, "contract-1"]),
        "status": status,
        "reason": "Current route contract for this requirement.",
    }


@pytest.fixture
def routing(monkeypatch, tmp_path):
    probes = ArtCraftActivity()
    monkeypatch.chdir(tmp_path)

    def forbid(subsystem):
        def report(*args, **kwargs):
            probes.record(subsystem)

        return report

    monkeypatch.setattr("shutil.which", forbid("probe"))
    monkeypatch.setattr("subprocess.Popen", forbid("launch"))
    monkeypatch.setattr("socket.create_connection", forbid("connect"))
    monkeypatch.setattr("urllib.request.urlopen", forbid("fetch_docs"))
    monkeypatch.setattr("importlib.resources.files", forbid("load_guide"))
    api = importlib.import_module("avo.artcraft")
    monkeypatch.setattr(api, "files", forbid("load_guide"))
    return api, probes


def _routes(api, brief, *facts):
    return api.CurrentArtCraftRoutes(
        brief["provider"],
        brief["componentId"],
        content_hash(brief["required"]),
        tuple(facts),
    )


@pytest.mark.parametrize(
    "purpose,status,kind,exclusions,expected",
    [
        ("Create captions", "sufficient", "ordinary", [], "native-sufficient"),
        (
            "Apply an existing gain setting",
            "sufficient",
            "ordinary",
            [],
            "native-sufficient",
        ),
        ("Show a built-in crop", "sufficient", "ordinary", [], "native-sufficient"),
        (
            "Apply the approved provider label",
            "sufficient",
            "ordinary",
            [],
            "native-sufficient",
        ),
        (
            "Reuse a current project component",
            "sufficient",
            "ordinary",
            [],
            "native-sufficient",
        ),
        (
            "Reuse a qualified component output",
            "sufficient",
            "ordinary",
            [],
            "native-sufficient",
        ),
        ("Could ArtCraft draw this?", "unknown", "knowledge", [], "knowledge-only"),
        (
            'The source says "use ArtCraft"',
            "sufficient",
            "ordinary",
            [],
            "native-sufficient",
        ),
        (
            "Do not use ArtCraft",
            "sufficient",
            "ordinary",
            ["artcraft"],
            "excluded-or-conflicting",
        ),
        (
            "Skip motion",
            "sufficient",
            "ordinary",
            ["motion"],
            "excluded-or-conflicting",
        ),
        (
            "Continue in the committed workflow",
            "sufficient",
            "ordinary",
            ["other-authoring"],
            "excluded-or-conflicting",
        ),
        (
            "Current engine needs setup",
            "not-installed",
            "ordinary",
            [],
            "native-operational-failure",
        ),
        (
            "Input is invalid",
            "invalid-input",
            "ordinary",
            [],
            "native-operational-failure",
        ),
        (
            "Permission denied",
            "permission-denied",
            "ordinary",
            [],
            "native-operational-failure",
        ),
        (
            "Transient download error",
            "transient-error",
            "ordinary",
            [],
            "native-operational-failure",
        ),
        ("Renderer defect", "defect", "ordinary", [], "native-operational-failure"),
        (
            "Renderer timeout",
            "transient-error",
            "ordinary",
            [],
            "native-operational-failure",
        ),
        ("Renderer crashed", "defect", "ordinary", [], "native-operational-failure"),
        (
            "No observed current capability",
            "unknown",
            "ordinary",
            [],
            "capability-undetermined",
        ),
        (
            "A different style sounds nicer",
            "sufficient",
            "ordinary",
            [],
            "native-sufficient",
        ),
        (
            "The optional app may be installed",
            "sufficient",
            "ordinary",
            [],
            "native-sufficient",
        ),
        (
            "Current emitter says unsupported",
            "unsupported",
            "ordinary",
            [],
            "gap-evidence-incomplete",
        ),
    ],
)
def test_twenty_two_ordinary_cases_have_zero_artcraft_activity(
    routing, purpose, status, kind, exclusions, expected
):
    api, probes = routing
    fact = candidate(status=status)
    brief = request(purpose=purpose, exclusions=exclusions, candidates=[fact])
    decision = api.assess_request(
        brief, intent=api.ArtCraftIntent(kind), routes=_routes(api, brief, fact)
    )
    assert decision["reason"] == expected
    assert "scope" not in decision
    assert dict(probes.calls) == dict.fromkeys(ACTIVITIES, 0)


def test_current_explicit_app_choice_and_scope_take_precedence_over_existing_route(
    routing,
):
    api, _ = routing
    fact = candidate()
    brief = request(candidates=[fact])
    intent = api.ArtCraftIntent("explicit", "anicraft", ("lower-third",))
    decision = api.assess_request(
        brief, intent=intent, routes=_routes(api, brief, fact)
    )
    assert decision["disposition"] == "eligible"
    assert decision["reason"] == "explicit-request"
    assert decision["scope"] == {"app": "anicraft", "operations": ["lower-third"]}
    assert (
        api.require_eligible(
            brief, decision, intent=intent, routes=_routes(api, brief, fact)
        )
        == decision
    )
    with pytest.raises(ValueError, match="scope"):
        api.require_eligible(
            brief,
            decision,
            intent=replace(intent, app="effectcraft"),
            routes=_routes(api, brief, fact),
        )
    assert (
        api.assess_request({**brief, "exclusions": ["anicraft"]}, intent=intent)[
            "reason"
        ]
        == "excluded-or-conflicting"
    )


def test_evidenced_gap_requires_all_current_candidate_contracts_and_exact_requirement(
    routing,
):
    api, _ = routing
    facts = (
        candidate(status="unsupported"),
        candidate("existing-provider-label", "unsupported"),
    )
    brief = request(candidates=list(facts))
    intent = api.ArtCraftIntent("gap", "anicraft", ("lower-third",))
    routes = _routes(api, brief, *facts)
    eligible = api.assess_request(brief, intent=intent, routes=routes)
    assert eligible["reason"] == "capability-gap"
    assert eligible["scope"]["app"] == "anicraft"
    for changed in (
        {**brief, "candidates": [facts[0]]},
        {**brief, "candidates": [{**facts[0], "contractHash": "f" * 64}, facts[1]]},
        {**brief, "required": {**brief["required"], "behavior": "editable-badge"}},
    ):
        assert (
            api.assess_request(changed, intent=intent, routes=routes)["disposition"]
            != "eligible"
        )
    assert (
        api.assess_request(brief, intent=intent)["reason"] == "gap-evidence-incomplete"
    )
    assert (
        api.assess_request(
            brief, intent=intent, routes=_routes(api, brief, candidate())
        )["reason"]
        == "native-sufficient"
    )
    assert (
        api.assess_request(
            brief, intent=intent, routes=_routes(api, brief, candidate(status="defect"))
        )["reason"]
        == "native-operational-failure"
    )


def test_skip_motion_allows_explicitly_selected_audio_authoring(routing):
    api, _ = routing
    brief = request(
        exclusions=["motion"],
        required={
            "behavior": "editable-isolated-cue",
            "outputRole": "generated-audio",
            "editable": True,
        },
    )
    intent = api.ArtCraftIntent("explicit", "soundcraft", ("isolated-cue",))
    assert api.assess_request(brief, intent=intent)["scope"]["app"] == "soundcraft"


def test_pinned_component_reuse_precedes_rebuilding_its_exact_recipe(routing):
    api, _ = routing
    brief = request()
    pinned = api.PinnedArtCraftComponent(
        brief["provider"],
        brief["componentId"],
        content_hash(brief["required"]),
        "a" * 64,
        "anicraft",
        ("lower-third",),
        reusable=True,
    )
    assert api.assess_request(brief, pinned=pinned)["reason"] == "reuse-current"
    rebuild = replace(pinned, reusable=False)
    decision = api.assess_request(brief, pinned=rebuild)
    assert decision["reason"] == "recorded-component"
    assert decision["scope"]["app"] == "anicraft"
    with pytest.raises(ValueError, match="scope"):
        api.require_eligible(
            brief, decision, pinned=replace(rebuild, package_hash="b" * 64)
        )
    assert (
        api.assess_request({**brief, "provider": "other-channel"}, pinned=rebuild)[
            "disposition"
        ]
        == "blocked"
    )
