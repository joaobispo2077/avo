from fractions import Fraction
from types import SimpleNamespace

import pytest

from avo.adapters.understand import watch_skill as watch
from avo.timeline.vision_review import compile_review_coverage


@pytest.mark.parametrize("scope", ["windows", "full"])
def test_native_review_only_adds_program_overview_for_full_scope(
    monkeypatch, tmp_path, scope
):
    class CoverageChecked(Exception):
        pass

    def inspect_coverage(**kwargs):
        coverage = compile_review_coverage(**kwargs)
        sampled = {
            frame for item in coverage["passes"] for frame in item["sampleFrames"]
        }
        assert (83758 in sampled) is (scope == "full")
        assert {3600, 7799} <= sampled
        assert not coverage["coverageHoles"]
        raise CoverageChecked

    monkeypatch.setattr(
        watch, "_native_endpoint", lambda pin: ("http://local", "qwen3.5-4b")
    )
    monkeypatch.setattr(watch, "probe_vision_capabilities", lambda **kwargs: {})
    monkeypatch.setattr(
        watch, "_video_geometry", lambda path: (Fraction(60), 83759, 1395.967)
    )
    monkeypatch.setattr(watch, "compile_review_coverage", inspect_coverage)
    review = SimpleNamespace(
        candidate=tmp_path / "original.mkv",
        scope=scope,
        windows=[{"start": 60, "end": 130, "reason": "pause context"}],
        effective={
            "operatorManagedLifecycle": True,
            "concurrency": 1,
            "vramCeilingBytes": 7 * 1024**3,
            "contextLimit": 8192,
            "maxImagesPerPass": 4,
        },
    )
    with pytest.raises(CoverageChecked):
        watch._native_review(review, {})
