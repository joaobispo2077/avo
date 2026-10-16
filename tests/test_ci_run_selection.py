"""Feature pushes defer to eligible PRs without weakening actual CI evidence."""

from __future__ import annotations

import copy
import json
import subprocess
from pathlib import Path

import pytest
from scripts.ci import select_ci_run as selector

REPOSITORY = "owner/avo"
BRANCH = "feature/avo-example"
SHA = "a" * 40
BASE_SHA = "b" * 40


def pull_request(*, base="develop", draft=False):
    return {
        "number": 96,
        "state": "open",
        "draft": draft,
        "head": {
            "ref": BRANCH,
            "sha": SHA,
            "repo": {"full_name": REPOSITORY},
        },
        "base": {
            "ref": base,
            "sha": BASE_SHA,
            "repo": {"full_name": REPOSITORY},
        },
    }


def selected(pulls, *, workflow="ci", event="push", branch=BRANCH):
    run, reason = selector.select_run(workflow, event, REPOSITORY, branch, SHA, pulls)
    assert isinstance(reason, str) and reason
    return run


@pytest.mark.parametrize("workflow", ["ci", "engine-binary"])
def test_feature_push_runs_before_a_pr_exists(workflow):
    assert selected([], workflow=workflow) is True


@pytest.mark.parametrize("draft", [False, True])
@pytest.mark.parametrize("base", ["develop", "release", "main"])
def test_matching_open_pr_owns_feature_validation_including_drafts(base, draft):
    assert selected([pull_request(base=base, draft=draft)]) is False


@pytest.mark.parametrize(
    "section,field,value",
    [
        (None, "state", "closed"),
        (None, "number", None),
        ("head", "ref", "feature/another"),
        ("head", "sha", "c" * 40),
        ("head", "repo", {"full_name": "fork/avo"}),
        ("base", "repo", {"full_name": "other/avo"}),
    ],
)
def test_foreign_or_stale_pr_cannot_suppress_push_validation(section, field, value):
    pull = pull_request()
    target = pull if section is None else pull[section]
    target[field] = value
    assert selected([pull]) is True


def test_ci_only_defers_to_its_supported_pr_targets_but_engine_accepts_any_target():
    pull = pull_request(base="experiment")
    assert selected([pull], workflow="ci") is True
    assert selected([pull], workflow="engine-binary") is False


@pytest.mark.parametrize("event", ["pull_request", "workflow_dispatch", "release"])
def test_non_push_events_always_execute_their_own_validation(event):
    assert selected([pull_request()], event=event) is True


@pytest.mark.parametrize("branch", ["release", "main", "develop", "featureish"])
def test_non_feature_pushes_remain_full_when_explicitly_evaluated(branch):
    assert selected([pull_request()], branch=branch) is True


def test_matching_pr_is_found_after_unrelated_requests():
    unrelated = pull_request()
    unrelated["head"]["sha"] = "c" * 40
    assert selected([unrelated, pull_request()]) is False


@pytest.fixture
def environment(tmp_path, monkeypatch):
    output = tmp_path / "output"
    summary = tmp_path / "summary.md"
    event_path = tmp_path / "event.json"
    event_path.write_text(
        json.dumps({"number": 96, "pull_request": pull_request()}),
        encoding="utf-8",
    )
    for name, value in {
        "GITHUB_EVENT_NAME": "push",
        "GITHUB_REPOSITORY": REPOSITORY,
        "GITHUB_REF_NAME": BRANCH,
        "GITHUB_SHA": SHA,
        "GITHUB_OUTPUT": str(output),
        "GITHUB_STEP_SUMMARY": str(summary),
        "GITHUB_EVENT_PATH": str(event_path),
    }.items():
        monkeypatch.setenv(name, value)

    def forbidden(*args, **kwargs):
        pytest.fail("Test must explicitly mock every GitHub lookup")

    monkeypatch.setattr(subprocess, "run", forbidden)
    return output, summary, event_path


def outputs(path):
    return dict(line.split("=", 1) for line in path.read_text().splitlines())


def mock_api(monkeypatch, payload, *following):
    calls = []
    responses = iter((payload, *following))

    def run(command, **options):
        calls.append((command, options))
        response = next(responses)
        if isinstance(response, BaseException):
            raise response
        return subprocess.CompletedProcess(command, 0, json.dumps(response), "")

    monkeypatch.setattr(subprocess, "run", run)
    return calls


def test_cli_selects_full_validation_before_pr_creation(environment, monkeypatch):
    output, summary, _ = environment
    mock_api(monkeypatch, [])
    assert selector.main(["--workflow", "ci"]) == 0
    result = outputs(output)
    assert result["run_full_ci"] == "true" and result["reason"]
    assert result["reason"] in summary.read_text(encoding="utf-8")


def test_cli_lists_requests_then_rechecks_identity_without_mutating_github(
    environment, monkeypatch
):
    output, summary, _ = environment
    calls = mock_api(
        monkeypatch,
        [pull_request()],
        {**pull_request(), "mergeable": True},
    )
    assert selector.main(["--workflow", "ci"]) == 0
    assert outputs(output)["run_full_ci"] == "false"
    assert "skipped" in summary.read_text(encoding="utf-8").lower()
    assert len(calls) == 2
    command, options = calls[0]
    assert command[:2] == ["gh", "api"]
    assert command[command.index("--method") + 1] == "GET"
    assert "per_page=100" in command
    assert "--paginate" not in command and "--slurp" not in command
    assert f"head=owner:{BRANCH}" in command
    assert options["timeout"] == 20
    detail_command, detail_options = calls[1]
    assert f"repos/{REPOSITORY}/pulls/96" in detail_command
    assert detail_command[detail_command.index("--method") + 1] == "GET"
    assert detail_options["timeout"] == 20


@pytest.mark.parametrize("mergeable", [False, None, "missing", "true", 1])
def test_conflicted_unknown_or_malformed_mergeability_keeps_push_validation(
    environment, monkeypatch, mergeable
):
    output, _, _ = environment
    current = pull_request()
    if mergeable != "missing":
        current["mergeable"] = mergeable
    calls = mock_api(monkeypatch, [pull_request()], current)
    assert selector.main(["--workflow", "ci"]) == 0
    assert outputs(output)["run_full_ci"] == "true"
    assert len(calls) == 2  # Unknown mergeability does not cause polling or retries.


@pytest.mark.parametrize("change", ["head", "closed", "retargeted"])
def test_identity_changes_between_pr_list_and_detail_do_not_skip_validation(
    environment, monkeypatch, change
):
    output, _, _ = environment
    current = {**pull_request(), "mergeable": True}
    if change == "head":
        current["head"]["sha"] = "c" * 40
    elif change == "closed":
        current["state"] = "closed"
    else:
        current["base"]["ref"] = "unsupported-target"
    calls = mock_api(monkeypatch, [pull_request()], current)
    assert selector.main(["--workflow", "ci"]) == 0
    assert outputs(output)["run_full_ci"] == "true"
    assert len(calls) == 2


@pytest.mark.parametrize("current", [None, [], "not a PR"])
def test_malformed_pr_detail_keeps_push_validation(environment, monkeypatch, current):
    output, _, _ = environment
    mock_api(monkeypatch, [pull_request()], current)
    assert selector.main(["--workflow", "ci"]) == 0
    assert outputs(output)["run_full_ci"] == "true"


@pytest.mark.parametrize("failure", ["denied", "timeout"])
def test_pr_detail_lookup_failure_keeps_push_validation(
    environment, monkeypatch, failure
):
    output, _, _ = environment
    error = (
        subprocess.TimeoutExpired(["gh", "api"], 20)
        if failure == "timeout"
        else subprocess.CalledProcessError(1, ["gh", "api"], stderr="denied")
    )
    calls = mock_api(monkeypatch, [pull_request()], error)
    assert selector.main(["--workflow", "ci"]) == 0
    assert outputs(output)["run_full_ci"] == "true"
    assert len(calls) == 2


@pytest.mark.parametrize("payload", [None, {}, [None], ["not a PR"], [[{}]]])
def test_malformed_lookup_falls_back_to_full_validation(
    environment, monkeypatch, payload
):
    output, _, _ = environment
    mock_api(monkeypatch, payload)
    assert selector.main(["--workflow", "ci"]) == 0
    assert outputs(output)["run_full_ci"] == "true"


@pytest.mark.parametrize("failure", ["denied", "timeout", "missing-gh", "invalid-json"])
def test_lookup_failure_never_removes_validation(environment, monkeypatch, failure):
    output, _, _ = environment

    def run(command, **kwargs):
        if failure == "denied":
            raise subprocess.CalledProcessError(1, command, stderr="private detail")
        if failure == "timeout":
            raise subprocess.TimeoutExpired(command, 20)
        if failure == "missing-gh":
            raise FileNotFoundError("gh unavailable")
        return subprocess.CompletedProcess(command, 0, "invalid JSON", "")

    monkeypatch.setattr(subprocess, "run", run)
    assert selector.main(["--workflow", "ci"]) == 0
    assert outputs(output)["run_full_ci"] == "true"


@pytest.mark.parametrize(
    "event,branch",
    [("push", "release"), ("pull_request", BRANCH), ("workflow_dispatch", BRANCH)],
)
def test_required_events_do_not_need_a_pr_lookup(
    environment, monkeypatch, event, branch
):
    output, _, _ = environment
    monkeypatch.setenv("GITHUB_EVENT_NAME", event)
    monkeypatch.setenv("GITHUB_REF_NAME", branch)
    assert selector.main(["--workflow", "ci"]) == 0
    assert outputs(output)["run_full_ci"] == "true"


def test_fresh_pr_allows_publication_and_fork_identity_must_stay_exact():
    current = pull_request()
    current["head"]["repo"]["full_name"] = "fork/avo"
    event = {"number": 96, "pull_request": copy.deepcopy(current)}
    assert selector.is_current_pr(event, current, REPOSITORY) is True
    current["head"]["repo"]["full_name"] = REPOSITORY
    assert selector.is_current_pr(event, current, REPOSITORY) is False


@pytest.mark.parametrize(
    "section,field,value",
    [
        (None, "state", "closed"),
        (None, "number", 97),
        ("head", "sha", "c" * 40),
        ("base", "sha", "c" * 40),
        ("head", "ref", "feature/replaced"),
        ("base", "ref", "main"),
        ("head", "repo", {"full_name": "fork/avo"}),
        ("base", "repo", {"full_name": "other/avo"}),
    ],
)
def test_stale_or_retargeted_pr_cannot_authorize_publication(section, field, value):
    current = pull_request()
    event = {"number": 96, "pull_request": copy.deepcopy(current)}
    target = current if section is None else current[section]
    target[field] = value
    assert selector.is_current_pr(event, current, REPOSITORY) is False


@pytest.mark.parametrize("current", [None, [], {}, {"state": "open"}])
def test_missing_current_pr_evidence_denies_publication(current):
    event = {"number": 96, "pull_request": pull_request()}
    assert selector.is_current_pr(event, current, REPOSITORY) is False


def test_current_pr_must_target_this_repository():
    current = pull_request()
    event = {"number": 96, "pull_request": copy.deepcopy(current)}
    assert selector.is_current_pr(event, current, "other/avo") is False


@pytest.mark.parametrize("fresh", [True, False])
def test_cli_emits_pr_number_only_when_its_original_identity_is_current(
    environment, monkeypatch, fresh
):
    output, _, _ = environment
    monkeypatch.setenv("GITHUB_EVENT_NAME", "pull_request")
    current = pull_request()
    if not fresh:
        current["head"]["sha"] = "c" * 40
    calls = mock_api(monkeypatch, current)
    assert selector.main(["--workflow", "ci", "--check-pr-current"]) == 0
    assert outputs(output)["number"] == ("96" if fresh else "")
    assert calls[0][0][calls[0][0].index("--method") + 1] == "GET"
    assert calls[0][1]["timeout"] == 20


def test_freshness_lookup_failure_denies_publication(environment, monkeypatch):
    output, _, _ = environment
    monkeypatch.setenv("GITHUB_EVENT_NAME", "pull_request")

    def timeout(command, **kwargs):
        raise subprocess.TimeoutExpired(command, 20)

    monkeypatch.setattr(subprocess, "run", timeout)
    assert selector.main(["--workflow", "ci", "--check-pr-current"]) == 0
    assert outputs(output)["number"] == ""


def test_push_cannot_authorize_a_pr_comment(environment):
    output, _, _ = environment
    assert selector.main(["--workflow", "ci", "--check-pr-current"]) == 0
    assert outputs(output)["number"] == ""


def test_static_ci_triggers_remove_promotion_duplicates_but_keep_release_pushes():
    root = Path(__file__).resolve().parents[1]
    workflow = (root / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    push = workflow.split("  push:\n", 1)[1].split("  pull_request:\n", 1)[0]
    branches = {
        line.strip()[2:].strip("'")
        for line in push.splitlines()
        if line.strip().startswith("- ")
    }
    assert branches == {"release", "feature/**"}
    pulls = workflow.split("  pull_request:\n", 1)[1].split("\nconcurrency:", 1)[0]
    assert {
        line.strip()[2:] for line in pulls.splitlines() if line.strip().startswith("- ")
    } == {"develop", "release", "main"}
    prerequisites = workflow.split("  prerequisites-gate:\n", 1)[1].split(
        "    steps:\n", 1
    )[0]
    assert "needs: select-run" in prerequisites
    assert "needs.select-run.outputs.run_full_ci == 'true'" in prerequisites
    concurrency = workflow.split("\nconcurrency:\n", 1)[1].split("\nenv:\n", 1)[0]
    assert "github.event_name" in concurrency
    assert "github.event.pull_request.number" in concurrency
    assert "github.run_id" in concurrency
    assert "github.ref_name == 'release'" in concurrency


def test_engine_workflow_selects_pr_and_push_without_gating_release_builds():
    root = Path(__file__).resolve().parents[1]
    workflow = (root / ".github/workflows/engine-binary.yml").read_text(
        encoding="utf-8"
    )
    push = workflow.split("  push:\n", 1)[1].split("  pull_request:\n", 1)[0]
    branches = push.split("    branches:\n", 1)[1].split("    paths:\n", 1)[0]
    assert {
        line.strip()[2:].strip("'")
        for line in branches.splitlines()
        if line.strip().startswith("- ")
    } == {"feature/**"}
    assert "  pull_request:\n    paths:" in workflow
    assert "  release:\n    types: [published]" in workflow
    assert "  workflow_dispatch:" in workflow
    assert "select_ci_run.py --workflow engine-binary" in workflow
    selection = workflow.split("  select-run:\n", 1)[1].split("    steps:\n", 1)[0]
    assert (
        "if: github.event_name != 'release' && github.event_name != 'workflow_dispatch'"
    ) in selection
    smoke = workflow.split("  zip-smoke:\n", 1)[1].split("    strategy:\n", 1)[0]
    assert "needs: select-run" in smoke
    assert "!cancelled()" in smoke
    assert (
        "(github.event_name == 'release' || github.event_name == 'workflow_dispatch') "
        "|| (needs.select-run.result == 'success' && "
        "needs.select-run.outputs.run_full_ci == 'true')"
    ) in smoke
    concurrency = workflow.split("\nconcurrency:\n", 1)[1].split("\npermissions:\n", 1)[
        0
    ]
    assert "github.event_name" in concurrency
    assert "github.event.pull_request.number" in concurrency
    assert "github.run_id" in concurrency
