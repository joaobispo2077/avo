import pytest

from avo.timeline.cutting_policy import pause_retention, resolve_cutting_policy
from avo.timeline.cutting_profiles import FAMILIES, INTENSITIES, get_profile


@pytest.mark.parametrize("language", ["pt-BR", "en"])
@pytest.mark.parametrize("family", FAMILIES)
@pytest.mark.parametrize("intensity", INTENSITIES)
def test_all_profiles_preserve_micro_pauses_and_protection(language, family, intensity):
    policy = resolve_cutting_policy(
        project_settings={
            "enabled": True,
            "family": family,
            "intensity": intensity,
            "language": language,
        }
    )
    assert policy.profile.calibration_status == "unvalidated-seed"
    assert pause_retention(100, policy, confirmed_dispensable=True)["action"] == "keep"
    assert (
        pause_retention(5000, policy, confirmed_dispensable=True, protected=True)[
            "retainedMs"
        ]
        == 5000
    )
    assert policy.effective["guards"] == {"beforeMs": 120, "afterMs": 180}


def test_disabled_policy_does_not_invent_a_pacing_band():
    report = pause_retention(300, resolve_cutting_policy(), confirmed_dispensable=True)
    assert report["band"] is None
    assert report["retainedMs"] == 300


def test_half_open_bands():
    profile = get_profile("analysis-review", "balanced")
    assert [
        profile.pause_band(value) for value in [0, 249, 250, 699, 700, 1799, 1800]
    ] == ["micro", "micro", "quick", "quick", "medium", "medium", "long"]


def test_retention_requires_evidence_and_never_extends_a_gap():
    policy = resolve_cutting_policy(
        project_settings={"enabled": True, "family": "analysis-review"}
    )
    assert pause_retention(2000, policy)["retainedMs"] == 2000
    assert pause_retention(300, policy, confirmed_dispensable=True)["retainedMs"] == 300
    assert (
        pause_retention(2000, policy, confirmed_dispensable=True)["retainedMs"] == 550
    )


def test_infeasible_dynamic_target_reports_guard_floor():
    policy = resolve_cutting_policy(
        project_settings={
            "enabled": True,
            "family": "spoken-short",
            "intensity": "dynamic",
        }
    )
    report = pause_retention(
        500, policy, confirmed_dispensable=True, rounding_allowance_ms=17
    )
    assert report["requestedTargetMs"] == 250
    assert report["retainedMs"] == 317
    assert report["guardLimited"] is True


def test_conservative_keeps_quick_gap():
    policy = resolve_cutting_policy(
        project_settings={
            "enabled": True,
            "family": "analysis-review",
            "intensity": "conservative",
        }
    )
    assert pause_retention(600, policy, confirmed_dispensable=True)["action"] == "keep"


@pytest.mark.parametrize(
    "family,bands,targets",
    [
        (
            "analysis-review",
            (250, 700, 1800),
            ((None, 650, 750), (450, 450, 550), (300, 300, 400)),
        ),
        (
            "tutorial",
            (300, 900, 2200),
            ((None, 800, 1000), (550, 650, 800), (400, 450, 600)),
        ),
        (
            "interview-podcast",
            (350, 1000, 2500),
            ((None, 1000, 1200), (700, 800, 1000), (550, 600, 800)),
        ),
        (
            "narration-essay",
            (250, 650, 1600),
            ((None, 650, 800), (400, 500, 650), (300, 350, 450)),
        ),
        (
            "spoken-short",
            (200, 500, 1200),
            ((None, 450, 550), (300, 350, 450), (200, 250, 350)),
        ),
        (
            "react-gameplay",
            (300, 800, 2000),
            ((None, 750, 1000), (500, 600, 800), (350, 450, 650)),
        ),
    ],
)
def test_exact_plan_seeds(family, bands, targets):
    for intensity, expected in zip(INTENSITIES, targets):
        profile = get_profile(family, intensity)
        assert profile.upper_bounds_ms == bands
        assert profile.targets_ms == expected
