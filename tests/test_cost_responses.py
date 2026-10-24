"""User-visible closure summaries must be automatic and before the footer."""

from pathlib import Path

from avo.costs import render_summary


def test_both_closing_references_require_automatic_costs():
    root = Path(__file__).resolve().parents[1]
    for name in ("learndown", "cleanup"):
        text = (root / f"agent-skills/avo-pipeline/references/{name}.md").read_text(
            "utf-8"
        )
        assert "automatically display" in text
        assert "before the existing step-status footer" in text
        assert "pending turn" in text


def test_missing_accounting_failure_is_not_a_fabricated_total():
    output = render_summary(
        {
            "coverage": "unavailable",
            "persistence": "failed",
            "message": "Cost snapshot unavailable; retry accounting/export without repeating cleanup",
        }
    )
    assert "unavailable" in output
    assert "0" not in output


def test_estimate_and_unknown_report_are_clear():
    text = render_summary(
        {
            "amounts": [],
            "tokens": {"total": None},
            "coverage": "partial",
            "cutoff": None,
        }
    )
    assert "unknown cost" in text
    assert "partial" in text
    assert "pending" in text
    assert "not an invoice" in text
