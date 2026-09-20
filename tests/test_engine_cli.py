"""In-process engine CLI verb map (FR-3 / FR-11).

Contract for ``avo.engine_cli.main`` — not a frozen zip, not ``~/.avo/bin/avo``.
Tests stay red until aeb-012 lands the dispatcher.
"""

from __future__ import annotations

import re

import pytest

PUBLIC_VERBS = ("transcribe", "render", "shorts", "cli", "mcp")
SEMVER_MARK = re.compile(r"\b\d+\.\d+\.\d+\b")


def _run(argv: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, str, str]:
    from avo.engine_cli import main

    try:
        raw = main(argv)
    except SystemExit as exc:
        raw = exc.code
    captured = capsys.readouterr()
    if raw is None:
        code = 0
    elif isinstance(raw, int):
        code = raw
    else:
        code = 1
    return code, captured.out, captured.err


def _combined(out: str, err: str) -> str:
    return f"{out}{err}"


def test_version_succeeds(capsys: pytest.CaptureFixture[str]) -> None:
    code, out, err = _run(["version"], capsys)
    text = _combined(out, err)
    assert code == 0
    assert text.strip()
    assert SEMVER_MARK.search(text)
    assert "Traceback" not in text


def test_help_succeeds_and_lists_verbs(capsys: pytest.CaptureFixture[str]) -> None:
    code, out, err = _run(["--help"], capsys)
    text = _combined(out, err)
    assert code == 0
    assert "Traceback" not in text
    lower = text.lower()
    for verb in (*PUBLIC_VERBS, "version"):
        assert verb in lower


@pytest.mark.parametrize("verb", PUBLIC_VERBS)
def test_public_verb_help_succeeds(
    verb: str, capsys: pytest.CaptureFixture[str]
) -> None:
    code, out, err = _run([verb, "--help"], capsys)
    text = _combined(out, err)
    assert code == 0
    assert "Traceback" not in text
    assert verb in text.lower()


def test_transcribe_help_contract(capsys: pytest.CaptureFixture[str]) -> None:
    code, out, err = _run(["transcribe", "--help"], capsys)
    text = _combined(out, err)
    lower = text.lower()
    assert code == 0
    assert "Traceback" not in text
    assert "usage" in lower
    assert "transcribe" in lower
    assert "video" in lower
    assert "--edit-dir" in lower
    assert "--model" in lower
    assert "pt-br" in lower


def test_unknown_verb_lists_commands_without_traceback(
    capsys: pytest.CaptureFixture[str],
) -> None:
    code, out, err = _run(["__unknown_verb__"], capsys)
    text = _combined(out, err)
    assert code != 0
    assert "Traceback" not in text
    lower = text.lower()
    for verb in (*PUBLIC_VERBS, "version"):
        assert verb in lower
