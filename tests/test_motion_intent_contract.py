"""Typed selection tests plus review fixtures, never an arbitrary-prose parser.

The prose cases document expected driving-agent decisions. T037 records actual
walkthrough observations separately; a passing fixture check is not that proof.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from avo.cli import build_parser
from avo.mcp.bridge import run_cli
from avo.timeline.animation import AnimationService
from tests import test_motion_cli as motion_cli_contract
from tests.test_timeline_animation_service import strategy

motion_cli_sandbox = motion_cli_contract.motion_cli_sandbox

ROOT = Path(__file__).resolve().parents[1]
MATRIX = json.loads(
    (ROOT / "tests/fixtures/motion/intent-cases.json").read_text(encoding="utf-8")
)


def test_review_matrix_retains_nonexecution_and_conflicting_authority_cases():
    cases = {case["id"]: case for case in MATRIX["cases"]}
    assert {
        "no-frameworks",
        "without-framework",
        "framework-free",
        "avoid-hyperframes",
        "do-not-use-hyperframes",
        "named-remotion",
        "canvas-no-framework",
        "svg-no-framework",
        "contradiction-remotion",
        "contradiction-hyperframes",
        "contrary-flag",
        "contrary-field",
        "skip-animation",
        "skip-motion",
        "capability-question",
        "negated-exclusion",
        "quoted-article",
        "reference-example",
        "scope-unclear",
        "one-run",
    } == cases.keys()
    assert "not" in MATRIX["description"] and "parser" in MATRIX["description"]
    for case in cases.values():
        expected = case["expected"]
        assert expected["persistPreference"] is False
        normalized = expected["normalizedRequest"]
        if expected["action"] != "execute":
            assert normalized["motionEngine"] is None
            assert expected["mutateEngineWork"] is False
        if expected["action"] == "skip":
            assert normalized["skipMotion"] is True
        if case["instructionAuthority"] in {
            "question",
            "source-material",
            "negated-exclusion",
        }:
            assert expected["action"] in {"answer", "inherit"}
    assert (
        cases["named-remotion"]["expected"]["normalizedRequest"]["motionEngine"]
        == "remotion"
    )
    assert cases["contradiction-remotion"]["expected"]["action"] == "clarify"


@pytest.mark.parametrize(
    "case",
    [case for case in MATRIX["cases"] if case["expected"]["action"] == "execute"],
    ids=lambda case: case["id"],
)
def test_normalized_invocation_uses_real_scoped_selection_without_saving(
    motion_cli_sandbox, case
):
    box = motion_cli_sandbox
    project = json.loads(box["project"].read_text(encoding="utf-8"))
    project["motion"] = {"engine": "hyperframes"}
    box["project"].write_text(json.dumps(project), encoding="utf-8")
    before = {name: box[name].read_bytes() for name in ("project", "provider")}
    normalized = case["expected"]["normalizedRequest"]
    selected = run_cli(
        [
            "animation",
            "engine-show",
            "--project",
            str(box["project"]),
            "--motion-engine",
            normalized["motionEngine"],
            "--json",
        ]
    )
    assert selected.exit_code == 0, selected.stderr
    assert selected.parsed_json["selection"]["engine"] == normalized["motionEngine"]
    assert selected.parsed_json["selection"]["source"] == "invocation"
    assert selected.parsed_json["selection"]["advanced"] is (
        normalized["motionEngine"] == "code-drawn"
    )
    inherited = run_cli(
        ["animation", "engine-show", "--project", str(box["project"]), "--json"]
    )
    assert inherited.exit_code == 0, inherited.stderr
    assert inherited.parsed_json["selection"]["engine"] == "hyperframes"
    assert inherited.parsed_json["selection"]["source"] == "project"
    assert {name: box[name].read_bytes() for name in before} == before
    assert not box["global"].exists()
    assert not (box["raw"] / "edit").exists()


def author_args(project, strategy_path):
    return [
        "animation",
        "author",
        "--project",
        str(project),
        "--strategy",
        str(strategy_path),
        "--actor",
        "intent-contract",
        "--reason",
        "explicit current instruction",
    ]


@pytest.mark.parametrize("engine", ["hyperframes", "remotion", "code-drawn"])
@pytest.mark.parametrize("entry", ["pipeline", "author"])
def test_native_authoring_entries_accept_only_canonical_engine_ids(
    tmp_path, engine, entry
):
    project = tmp_path / "avo.project.json"
    args = (
        ["pipeline", "run", "--project", str(project)]
        if entry == "pipeline"
        else author_args(project, tmp_path / "strategy.json")
    )
    parsed = build_parser().parse_args([*args, "--motion-engine", engine])
    assert parsed.motion_engine == engine


@pytest.mark.parametrize("engine", ["canvas", "none", "no frameworks", "HyperFrames"])
@pytest.mark.parametrize("entry", ["pipeline", "author"])
def test_native_authoring_entries_reject_prose_route_and_malformed_ids(
    tmp_path, capsys, engine, entry
):
    project = tmp_path / "avo.project.json"
    args = (
        ["pipeline", "run", "--project", str(project)]
        if entry == "pipeline"
        else author_args(project, tmp_path / "strategy.json")
    )
    with pytest.raises(SystemExit) as caught:
        build_parser().parse_args([*args, "--motion-engine", engine])
    assert caught.value.code == 2
    assert "invalid choice" in capsys.readouterr().err


@pytest.mark.parametrize(
    "field_engine,flag_engine",
    [("hyperframes", "code-drawn"), ("code-drawn", "remotion")],
)
def test_contrary_explicit_strategy_field_is_rejected_before_authoring(
    motion_cli_sandbox, monkeypatch, field_engine, flag_engine
):
    box = motion_cli_sandbox
    value = strategy()
    value["framework"] = field_engine
    path = box["raw"] / "strategy.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    before = box["project"].read_bytes()
    monkeypatch.setattr(
        AnimationService,
        "author",
        lambda *args, **kwargs: pytest.fail(
            "Contrary explicit choices reached authoring"
        ),
    )
    result = run_cli(
        [*author_args(box["project"], path), "--motion-engine", flag_engine, "--json"]
    )
    assert result.exit_code in {2, 3}
    error = json.loads(result.stderr)
    assert re.search(
        r"conflict|contradict|mismatch",
        error["code"] + " " + error["message"],
        re.IGNORECASE,
    )
    assert result.stdout == ""
    assert box["project"].read_bytes() == before
    assert not (box["raw"] / "edit").exists()


@pytest.mark.parametrize(
    "path,boundary",
    [
        ("agent-skills/avo/SKILL.md", "## Session start"),
        ("agent-skills/avo-pipeline/SKILL.md", "## Command router"),
        ("agent-skills/avo-pipeline/references/arguments.md", "## Required context"),
    ],
)
def test_leading_agent_branch_inspects_selection_before_workflow_loading(
    path, boundary
):
    text = (ROOT / path).read_text(encoding="utf-8")
    leading = text.split(boundary, 1)[0]
    assert "engine-show" in leading, f"{path} must resolve the engine before {boundary}"
    assert re.search(r"code-drawn(?:/selection)?\.md", leading)
    assert "HyperFrames" in leading


def test_canonical_policy_places_code_drawn_exception_before_hyperframes_load():
    text = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    motion_policy = text.split("## Animation And Motion Design System", 1)[1].split(
        "\n## ", 1
    )[0]
    assert "engine-show" in motion_policy
    assert "code-drawn" in motion_policy
    assert re.search(
        r"no frameworks|without a framework|avoid HyperFrames",
        motion_policy,
        re.IGNORECASE,
    )
    required_load = motion_policy.find("`/hyperframes`")
    assert required_load == -1 or motion_policy.index("engine-show") < required_load


def test_shared_arguments_cover_nonexecution_and_conflicting_intent():
    text = (ROOT / "agent-skills/avo-pipeline/references/arguments.md").read_text(
        encoding="utf-8"
    )
    for phrase in (
        "--motion-engine",
        "Motion engine:",
        "code-drawn",
        "Remotion",
        "Do not avoid HyperFrames",
    ):
        assert phrase in text
    for meaning in (
        r"no frameworks|without a framework",
        r"no animation|skip motion",
        r"quot",
        r"question",
        r"conflict|contradict",
    ):
        assert re.search(meaning, text, re.IGNORECASE), meaning


def test_portable_selection_entry_discloses_advanced_invocation_and_default():
    entry = ROOT / "agent-skills/avo-pipeline/references/code-drawn.md"
    selection = ROOT / "agent-skills/avo-pipeline/references/code-drawn/selection.md"
    assert entry.is_file(), (
        "Advanced motion requires its installed portable entry guide"
    )
    assert selection.is_file(), "Selection policy needs its single portable guide owner"
    text = entry.read_text(encoding="utf-8") + selection.read_text(encoding="utf-8")
    for term in (
        "advanced",
        "engine-show",
        "engine-set",
        "engine-reset",
        "--motion-engine",
        "HyperFrames",
    ):
        assert term.casefold() in text.casefold()
    assert not re.search(
        r"^\s*/avo\.motion\.(?:hyperframes|remotion|code-drawn)\b", text, re.MULTILINE
    )
