"""Native observation policy compares pixels that the real check already captures."""

import pytest

from avo.motion import MotionError
from avo.proof_composition import observe_code_drawn_environment


@pytest.mark.parametrize("changed", ["frames", "rgbaSha256"])
def test_current_observer_rejects_changed_pixels_even_when_environment_matches(
    tmp_path, monkeypatch, changed
):
    recorded = {
        "frames": [0, 1],
        "rgbaSha256": ["a" * 64, "b" * 64],
        "environment": {"platform": "same-environment"},
    }
    fresh = {
        **recorded,
        changed: [2, 3] if changed == "frames" else ["c" * 64, "d" * 64],
    }
    monkeypatch.setattr(
        "avo.adapters.motion.code_drawn.CodeDrawnAdapter.check",
        lambda *args, **kwargs: {"checks": [{"evidence": fresh}]},
    )
    with pytest.raises(MotionError, match="pixels|RGBA|capture"):
        observe_code_drawn_environment(
            tmp_path / "composition.json", expected_evidence=recorded
        )


def test_current_observer_returns_only_matched_observed_environment(
    tmp_path, monkeypatch
):
    evidence = {
        "frames": [0],
        "rgbaSha256": ["a" * 64],
        "environment": {"platform": "observed"},
    }
    monkeypatch.setattr(
        "avo.adapters.motion.code_drawn.CodeDrawnAdapter.check",
        lambda *args, **kwargs: {"checks": [{"evidence": evidence}]},
    )
    assert (
        observe_code_drawn_environment(
            tmp_path / "composition.json", expected_evidence=evidence
        )
        == evidence["environment"]
    )
