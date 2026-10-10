import pytest

from avo.timeline.cutting_policy import CuttingPolicyError, resolve_cutting_policy
from avo.timeline.cutting_profiles import get_profile


def test_absent_policy_is_disabled_and_has_no_invented_format():
    policy = resolve_cutting_policy()
    assert policy.enabled is False
    assert policy.profile is None
    assert policy.effective["family"] is None


def test_scopes_merge_with_provenance_and_section_wins():
    policy = resolve_cutting_policy(
        global_settings={
            "enabled": True,
            "family": "analysis-review",
            "intensity": "conservative",
        },
        provider_settings={"intensity": "balanced", "notes": ["provider"]},
        project_settings={"guards": {"beforeMs": 150}, "notes": ["project"]},
        run_settings={"intensity": "dynamic"},
        section_settings={
            "intensity": "conservative",
            "purpose": "introduce the question",
        },
    )
    assert policy.effective["intensity"] == "conservative"
    assert policy.sources["intensity"] == "section"
    assert policy.sources["family"] == "global"
    assert policy.effective["notes"] == ["project"]
    assert policy.effective["guards"] == {"beforeMs": 150, "afterMs": 180}
    assert len(policy.policy_hash) == 64


def test_protection_cannot_be_removed_by_stronger_settings():
    policy = resolve_cutting_policy(
        project_settings={"enabled": True, "family": "spoken-short"},
        run_settings={
            "protectedEvents": [
                {
                    "eventId": "quiz",
                    "sourceId": "s",
                    "startMs": 100,
                    "endMs": 5100,
                    "kind": "quiz",
                    "minimumDurationMs": 5000,
                }
            ]
        },
        section_settings={"protectedEvents": []},
        manual_locks=[
            {"eventId": "manual", "sourceId": "s", "startMs": 7000, "endMs": 8000}
        ],
    )
    assert {event["eventId"] for event in policy.protections} == {"quiz", "manual"}
    assert (
        next(event for event in policy.protections if event["eventId"] == "manual")[
            "kind"
        ]
        == "manual-lock"
    )


@pytest.mark.parametrize(
    "settings",
    [{"guards": {"beforeMs": 119}}, {"guards": {"afterMs": 179}}, {"enabled": True}],
)
def test_unsafe_guards_or_missing_format_fail(settings):
    with pytest.raises(CuttingPolicyError):
        resolve_cutting_policy(project_settings=settings)


def test_profile_catalog_is_immutable():
    profile = get_profile("analysis-review", "balanced")
    with pytest.raises((AttributeError, TypeError)):
        profile.intensity = "dynamic"


def test_conflicting_protection_definition_is_not_silently_overridden():
    event = {"eventId": "hold", "sourceId": "s", "startMs": 10, "endMs": 510}
    with pytest.raises(CuttingPolicyError, match="conflicting protected event"):
        resolve_cutting_policy(
            project_settings={"protectedEvents": [event]},
            run_settings={"protectedEvents": [{**event, "endMs": 100}]},
        )


def test_protection_normalizes_millisecond_clock():
    policy = resolve_cutting_policy(
        protected_events=[
            {"eventId": "hold", "sourceId": "s", "startMs": 10, "endMs": 510}
        ]
    )
    assert policy.protections[0]["sourceRange"] == {
        "sourceId": "s",
        "startTicks": 10,
        "endTicksExclusive": 510,
        "timebase": {"num": 1, "den": 1000},
    }


def test_payload_is_detached_and_protection_changes_hash():
    policy = resolve_cutting_policy()
    payload = policy.payload()
    payload["effective"]["guards"]["beforeMs"] = 0
    assert policy.effective["guards"]["beforeMs"] == 120
    protected = resolve_cutting_policy(
        protected_events=[
            {"eventId": "hold", "sourceId": "s", "startMs": 10, "endMs": 510}
        ]
    )
    assert policy.policy_hash != protected.policy_hash


def test_runtime_bindings_are_preserved_and_affect_policy_hash():
    original = resolve_cutting_policy()
    resolved = resolve_cutting_policy(
        project_settings={
            "runtimeRefs": {
                "alignmentInterpreter": "local-python",
                "modelHash": "a" * 64,
            }
        }
    )
    assert resolved.effective["runtimeRefs"]["modelHash"] == "a" * 64
    assert resolved.sources["runtimeRefs"] == "project"
    assert resolved.policy_hash != original.policy_hash


def test_section_overrides_preserve_larger_guards_and_hard_protection():
    from avo.timeline.cutting_policy import resolve_section_policy

    base = resolve_cutting_policy(
        project_settings={
            "enabled": True,
            "family": "analysis-review",
            "guards": {"beforeMs": 220, "afterMs": 280},
            "sections": {
                "intro": {
                    "intensity": "dynamic",
                    "guards": {"beforeMs": 120, "afterMs": 180},
                    "protectedEvents": [],
                }
            },
        },
        protected_events=[
            {"eventId": "hold", "sourceId": "s", "startMs": 10, "endMs": 510}
        ],
    )
    section = resolve_section_policy(base, "intro")
    assert section.effective["intensity"] == "dynamic"
    assert section.sources["intensity"] == "section"
    assert section.effective["guards"] == base.effective["guards"]
    assert section.protections == base.protections
    assert section.sources["family"] == "project"
    assert resolve_section_policy(base, "missing") == base


def test_section_only_source_hold_is_global_for_every_removal_path():
    event = {"eventId": "quiz", "sourceId": "s", "startMs": 100, "endMs": 500}
    policy = resolve_cutting_policy(
        project_settings={
            "enabled": True,
            "family": "analysis-review",
            "sections": {"quiz": {"protectedEvents": [event]}},
        }
    )
    assert [item["eventId"] for item in policy.protections] == ["quiz"]
    assert policy.effective["protectedEvents"] == list(policy.protections)


def test_stronger_empty_section_and_top_level_lists_cannot_erase_lower_hold():
    event = {"eventId": "hold", "sourceId": "s", "startMs": 100, "endMs": 500}
    policy = resolve_cutting_policy(
        provider_settings={"sections": {"intro": {"protectedEvents": [event]}}},
        project_settings={
            "sections": {"intro": {"protectedEvents": []}},
            "protectedEvents": [],
        },
        run_settings={"sections": {"intro": {"protectedEvents": []}}},
        section_settings={"protectedEvents": []},
    )
    assert [item["eventId"] for item in policy.protections] == ["hold"]


def test_section_protection_declaration_requires_list_even_if_overridden():
    with pytest.raises(CuttingPolicyError, match="protectedEvents must be a list"):
        resolve_cutting_policy(
            provider_settings={
                "sections": {"intro": {"protectedEvents": {"eventId": "not-a-list"}}}
            },
            run_settings={"sections": {"intro": {"protectedEvents": []}}},
        )
