from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_watch_optional_controls_are_completely_documented() -> None:
    text = (ROOT / "docs" / "optional-capabilities.md").read_text(encoding="utf-8")
    for heading in (
        "Purpose",
        "Applicability",
        "Default",
        "Accepted values",
        "Scope and precedence",
        "Failure behavior",
        "Examples",
        "Artifact effects",
        "Valid next workflow action",
    ):
        assert f"## {heading}" in text
    for flag in (
        "--watch-whisper-model",
        "--watch-device",
        "--watch-max-frames",
        "--watch-repair-max-frames",
        "--watch-analysis-attempts",
        "--watch-tool-attempts",
        "--watch-working-directory",
        "--watch-format",
        "--watch-language",
        "--watch-acceptance-criterion",
        "--watch-risk-note",
    ):
        assert flag in text


def test_arguments_reference_explains_invocation_vs_persistence() -> None:
    text = (
        ROOT / "agent-skills" / "avo-pipeline" / "references" / "arguments.md"
    ).read_text(encoding="utf-8")
    assert "Invocation versus persistent settings" in text
    assert "global → provider → registry → project → invocation" in text
