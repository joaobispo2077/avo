from __future__ import annotations

from avo.timeline.command_handlers import CommandHandlers


class _Pipeline:
    pass


def test_watch_handler_renders_human_package_from_structured_evidence() -> None:
    package = {
        "candidateSha256": "a" * 64,
        "proofPlanHash": "b" * 64,
        "transcriptHash": "c" * 64,
        "modelIdentity": "qwen3.5-4b",
        "reviewContractHash": "d" * 64,
        "status": "pass",
        "coverage": {"samplingMode": "sparse-by-section+dense-risk"},
        "findings": [],
    }
    result = CommandHandlers(
        _Pipeline(), evidence_runner=lambda **_options: {"reviewPackage": package}
    ).execute("watch", "evidence")
    assert result["evidence"]["reviewPackage"] == package
    assert result["reviewPackageMarkdown"].startswith("# Vision review package")
    assert "qwen3.5-4b" in result["reviewPackageMarkdown"]
