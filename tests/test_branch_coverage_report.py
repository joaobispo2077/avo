"""Safety branch reports use measured branch counts, never aggregate line scores."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "report_branch_coverage", ROOT / "scripts/ci/report_branch_coverage.py"
)
assert SPEC and SPEC.loader
REPORT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(REPORT)


def _file(total: int, covered: int, arcs: list[list[int]]) -> dict:
    return {
        "summary": {
            "num_branches": total,
            "covered_branches": covered,
            "missing_branches": total - covered,
            "percent_covered": 99.9,
        },
        "missing_branches": arcs,
    }


def _profile() -> dict:
    return {
        "meta": {"branch_coverage": True, "timestamp": "2026-10-14T12:00:00"},
        "files": {
            path: _file(0, 0, []) for _label, paths in REPORT.SCOPES for path in paths
        },
    }


def _report(profile: dict, **overrides) -> dict:
    return REPORT.build_report(
        profile,
        sha="a" * 40,
        run_id="12345",
        recorded_at="2026-10-14T12:30:00Z",
        test_outcome=overrides.get("test_outcome", "success"),
        suite="fixture safety tests",
    )


def test_branch_totals_are_weighted_and_expose_exact_missing_arcs() -> None:
    profile = _profile()
    profile["files"]["src/avo/timeline/lineage.py"] = _file(2, 1, [[81, 82]])
    profile["files"]["src/avo/timeline/picture_lineage.py"] = _file(8, 8, [])
    result = _report(profile)
    ancestry = result["groups"][0]
    assert ancestry["covered_branches"] == 9
    assert ancestry["num_branches"] == 10
    assert ancestry["percent"] == 90.0
    assert result["totals"]["percent"] == 90.0
    missing = ancestry["files"][0]["missing_branches"]
    assert missing == [[81, 82]]
    markdown = REPORT.render_markdown(result)
    assert "90.00%" in markdown
    assert "src/avo/timeline/lineage.py:81" in markdown
    assert "to line 82" in markdown
    assert "99.90%" not in markdown


def test_missing_scopes_and_zero_branch_files_never_become_full_coverage() -> None:
    profile = _profile()
    del profile["files"]["src/avo/project_inventory.py"]
    result = _report(profile)
    cleanup = next(
        group for group in result["groups"] if group["name"] == "Cleanup preservation"
    )
    assert cleanup["complete"] is False
    assert cleanup["percent"] is None
    assert cleanup["files"][0]["measured"] is False
    assert result["totals"]["percent"] is None
    markdown = REPORT.render_markdown(result)
    assert "not measured" in markdown
    assert "no measured branches" in markdown
    assert "100.00%" not in markdown


def test_windows_and_absolute_paths_resolve_to_the_same_source_scope() -> None:
    profile = _profile()
    measured = profile["files"].pop("src/avo/timeline/mapping.py")
    profile["files"][str(ROOT / "src/avo/timeline/mapping.py")] = measured
    measured = profile["files"].pop("src/avo/mcp/request_state.py")
    profile["files"]["src\\avo\\mcp\\request_state.py"] = measured
    result = _report(profile)
    assert all(group["complete"] for group in result["groups"])


@pytest.mark.parametrize("branch_enabled", [False, None])
def test_line_only_profile_is_rejected(branch_enabled) -> None:
    profile = _profile()
    profile["meta"]["branch_coverage"] = branch_enabled
    with pytest.raises(ValueError, match="branch instrumentation"):
        _report(profile)


@pytest.mark.parametrize(
    "summary",
    [
        {"num_branches": 1, "covered_branches": 2, "missing_branches": 0},
        {"num_branches": True, "covered_branches": 0, "missing_branches": 1},
        {"num_branches": 2, "covered_branches": 1, "missing_branches": 0},
    ],
)
def test_inconsistent_or_invalid_branch_counts_are_rejected(summary: dict) -> None:
    profile = _profile()
    profile["files"]["src/avo/timeline/mapping.py"]["summary"] = summary
    with pytest.raises(ValueError, match="src/avo/timeline/mapping.py"):
        _report(profile)


def test_failing_suite_is_visible_and_exit_arc_is_not_a_negative_line() -> None:
    profile = _profile()
    profile["files"]["src/avo/mcp/request_state.py"] = _file(2, 1, [[253, -242]])
    result = _report(profile, test_outcome="failure")
    assert result["test_outcome"] == "failure"
    markdown = REPORT.render_markdown(result)
    assert "failure" in markdown
    assert "src/avo/mcp/request_state.py:253" in markdown
    assert "to exit" in markdown
    assert ":-242" not in markdown
    assert "a" * 40 in markdown and "12345" in markdown


def test_cli_rejects_missing_provenance_before_overwriting_outputs(
    tmp_path: Path,
) -> None:
    source = tmp_path / "coverage.json"
    source.write_text(json.dumps(_profile()), encoding="utf-8")
    output = tmp_path / "report.json"
    markdown = tmp_path / "report.md"
    output.write_text("preserve me", encoding="utf-8")
    assert (
        REPORT.main(
            [
                "--coverage",
                str(source),
                "--out",
                str(output),
                "--markdown",
                str(markdown),
                "--sha",
                "",
                "--run-id",
                "",
            ]
        )
        == 1
    )
    assert output.read_text(encoding="utf-8") == "preserve me"
    assert not markdown.exists()


def test_optional_lane_preserves_suite_scope_and_has_no_quality_floor() -> None:
    workflow = (ROOT / ".github/workflows/mutation-full.yml").read_text(
        encoding="utf-8"
    )
    branch_job = workflow.split("  branch-risk:", 1)[1]
    assert "timeout-minutes: 20" in branch_job
    assert "--cov-branch" in branch_job and "--cov-fail-under=0" in branch_job
    assert (
        "--ignore=tests/projects" in branch_job
        and "--ignore=tests/integration" in branch_job
    )
    assert "not project and not integration" in branch_job
    assert "report_branch_coverage.py" in branch_job
    assert "steps.branch-tests.outcome" in branch_job
    assert "branch-risk-reports" in branch_job
    assert "branch-risk" not in (ROOT / ".github/workflows/ci.yml").read_text(
        encoding="utf-8"
    )
