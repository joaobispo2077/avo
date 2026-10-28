"""Selected motion prerequisites preserve the historical unselected Gate 1."""

from __future__ import annotations

import json

import pytest

from avo import motion
from avo import validate_dependencies as dependencies
from avo.motion import MotionError


@pytest.fixture
def root(tmp_path):
    config = tmp_path / "config"
    config.mkdir()
    (config / "avo.config.json").write_text(
        json.dumps(
            {"jobs": {"motion": {"local": ["hyperframes", "remotion", "code-drawn"]}}}
        )
    )
    (config / "avo.dependencies.json").write_text(
        json.dumps(
            {
                "tools": {
                    "hyperframes": {
                        "required": True,
                        "job": "motion",
                        "kind": "npm-package",
                        "package": "hyperframes",
                    },
                    "remotion": {
                        "required": False,
                        "job": "motion",
                        "kind": "documentation-only",
                        "doc": "remotion.md",
                    },
                    "code-drawn": {
                        "required": False,
                        "job": "motion",
                        "kind": "managed-runtime",
                    },
                }
            }
        )
    )
    return tmp_path


def test_explicit_code_drawn_gate_checks_only_selected_runtime(root, monkeypatch):
    seen = []

    def inspect(**kwargs):
        seen.append(kwargs)
        return {"readiness": {"ready": True, "blockers": []}}

    monkeypatch.setattr(motion, "inspect_motion", inspect)
    monkeypatch.setattr(
        dependencies,
        "check_npm_package",
        lambda *a: pytest.fail("Unused HyperFrames checked."),
    )
    results = dependencies.run_checks(
        root, ci=True, optional=True, motion_engine="code-drawn"
    )
    by_id = {item.tool: item for item in results}
    assert by_id["hyperframes"].status == by_id["remotion"].status == "SKIP"
    assert by_id["code-drawn"].status == "OK"
    assert seen == [{"root": root, "invocation": "code-drawn"}]


def test_unavailable_selected_engine_fails_even_when_optional(root, monkeypatch):
    monkeypatch.setattr(
        motion,
        "inspect_motion",
        lambda **k: {
            "readiness": {"ready": False, "blockers": ["Managed Chromium absent."]}
        },
    )
    results = dependencies.run_checks(
        root, ci=False, optional=False, motion_engine="code-drawn"
    )
    selected = next(item for item in results if item.tool == "code-drawn")
    assert selected.status == "FAIL"
    assert selected.note == "Managed Chromium absent."


def test_invalid_selected_engine_is_rejected_before_prerequisite_probes(
    root, monkeypatch
):
    monkeypatch.setattr(
        dependencies,
        "check_npm_package",
        lambda *a: pytest.fail("Invalid choice reached probes."),
    )
    with pytest.raises(MotionError):
        dependencies.run_checks(root, ci=True, optional=False, motion_engine="canvas")


def test_without_selection_preserves_historical_hyperframes_requirement(
    root, monkeypatch
):
    seen = []

    def npm(root, tool, spec):
        seen.append(tool)
        return dependencies.CheckResult(tool, "FAIL", "Existing npm requirement.")

    monkeypatch.setattr(dependencies, "check_npm_package", npm)
    results = dependencies.run_checks(root, ci=True, optional=False)
    assert seen == ["hyperframes"]
    assert next(item for item in results if item.tool == "hyperframes").status == "FAIL"
    assert next(item for item in results if item.tool == "code-drawn").status == "SKIP"


def test_gate_cli_forwards_selection(root, monkeypatch):
    observed = []
    monkeypatch.setattr(
        dependencies,
        "run_checks",
        lambda target, **kwargs: observed.append((target, kwargs)) or [],
    )
    assert (
        dependencies.main(["--root", str(root), "--motion-engine", "code-drawn"]) == 0
    )
    assert observed == [
        (root, {"ci": False, "optional": False, "motion_engine": "code-drawn"})
    ]
