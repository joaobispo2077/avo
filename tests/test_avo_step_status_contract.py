"""Static contract tests for guided AVO responses."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "agent-skills" / "avo-pipeline" / "references" / "step-status.md"

ALLOWED_STATUSES = {
    "not started",
    "in progress",
    "awaiting user",
    "blocked",
    "completed",
}
FOOTER_FIELDS = (
    "**Workflow:**",
    "**Current step:**",
    "**Next step:**",
    "**Next expected update:**",
)


def _example_sections(text: str) -> dict[str, str]:
    sections: dict[str, str] = {}
    matches = list(
        re.finditer(
            r"^### (Start|Progress|Approval|Blocked|Completion)$", text, re.MULTILINE
        )
    )
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        sections[match.group(1).lower()] = text[match.end() : end].strip()
    return sections


def test_contract_defines_only_the_allowed_statuses() -> None:
    text = CONTRACT.read_text(encoding="utf-8")
    declaration = re.search(r"\*\*Allowed statuses:\*\* (.+)", text)
    assert declaration is not None
    declared = {value.strip(" `") for value in declaration.group(1).split("|")}
    assert declared == ALLOWED_STATUSES


def test_durable_state_is_authoritative_over_conversation_memory() -> None:
    text = CONTRACT.read_text(encoding="utf-8")
    ordered_sources = (
        "pipeline-run.json",
        "review.json",
        "shorts.status.json",
        "delivery-manifest.json",
        "observed invocation result",
    )
    positions = [text.index(source) for source in ordered_sources]
    assert positions == sorted(positions)
    assert "conversation memory cannot override it" in text
    assert "Read durable state again when a workflow resumes" in text


def test_examples_cover_every_response_state_and_end_with_one_footer() -> None:
    text = CONTRACT.read_text(encoding="utf-8")
    examples = _example_sections(text)
    assert set(examples) == {"start", "progress", "approval", "blocked", "completion"}

    statuses: set[str] = set()
    for name, example in examples.items():
        assert example.count("**Workflow:**") == 1, name
        assert all(example.count(field) == 1 for field in FOOTER_FIELDS), name
        footer_start = example.index("**Workflow:**")
        footer = example[footer_start:].strip().strip("`").strip()
        assert footer.splitlines()[0].startswith("**Workflow:**"), name
        assert footer.splitlines()[-1].startswith("**Next expected update:**"), name
        assert not example[footer_start:].rstrip().endswith(
            "```"
        ) or example.rstrip().endswith("```"), name

        current = re.search(r"\*\*Current step:\*\* .+ — (.+)$", footer, re.MULTILINE)
        assert current is not None, name
        statuses.add(current.group(1).strip())

    assert statuses == ALLOWED_STATUSES


def test_approval_example_explains_the_decision_and_exact_reply() -> None:
    approval = _example_sections(CONTRACT.read_text(encoding="utf-8"))["approval"]
    for phrase in (
        "Why this is needed:",
        "Controls:",
        "Reply with exactly:",
        "Tradeoff or safety consequence:",
    ):
        assert phrase in approval
    assert "awaiting user" in approval


def test_blocked_and_completion_examples_do_not_overclaim() -> None:
    examples = _example_sections(CONTRACT.read_text(encoding="utf-8"))
    blocked = examples["blocked"]
    assert "Failed prerequisite:" in blocked
    assert "Evidence:" in blocked
    assert "Minimum unblocking action:" in blocked
    assert "Later gates have not been evaluated" in blocked

    completion = examples["completion"]
    assert "Verified outputs:" in completion
    assert "Valid next command:" in completion
    assert "Workflow complete" in completion
