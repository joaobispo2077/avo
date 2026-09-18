"""Consume-mode resolver contract (spec FR-5).

In-process ``avo.consume_mode`` — no freeze, no real ``~/.avo/bin/avo``.
Imports the production API inside helpers so collection succeeds while tests
stay red until aeb-010.
"""

from __future__ import annotations

from pathlib import Path

import pytest

ORCHESTRATOR_MARK = "<!-- avo:orchestrator:start -->"


def _resolve(cwd: Path, *, override: str | None = None, home: Path):
    from avo.consume_mode import resolve_consume_mode

    return resolve_consume_mode(cwd, override=override, home=home)


def _write_checkout(root: Path) -> Path:
    (root / "src" / "avo").mkdir(parents=True)
    (root / "pyproject.toml").write_text('[project]\nname = "avo"\n', encoding="utf-8")
    (root / "AGENTS.md").write_text(f"{ORCHESTRATOR_MARK}\n", encoding="utf-8")
    return root


def _write_engine(home: Path) -> Path:
    launcher = home / ".avo" / "bin" / "avo"
    launcher.parent.mkdir(parents=True)
    launcher.write_text("", encoding="utf-8")
    return launcher


def test_checkout_markers_win_over_installed_engine(tmp_path: Path) -> None:
    cwd = _write_checkout(tmp_path / "checkout")
    launcher = _write_engine(tmp_path / "home")
    resolved = _resolve(cwd, home=tmp_path / "home")
    assert resolved.mode == "checkout"
    assert resolved.command_prefix == "python -m"
    assert str(launcher) not in resolved.command_prefix


@pytest.mark.parametrize("kind", ["footage", "other"])
def test_non_checkout_workspace_selects_binary(tmp_path: Path, kind: str) -> None:
    cwd = tmp_path / kind
    cwd.mkdir()
    if kind == "other":
        (cwd / "pyproject.toml").write_text(
            '[project]\nname = "other"\n', encoding="utf-8"
        )
        (cwd / "src" / "other").mkdir(parents=True)
        (cwd / "AGENTS.md").write_text("# not avo\n", encoding="utf-8")
    home = tmp_path / "home"
    _write_engine(home)
    resolved = _resolve(cwd, home=home)
    assert resolved.mode == "binary"
    assert Path(resolved.command_prefix) == home / ".avo" / "bin" / "avo"


@pytest.mark.parametrize("omit", ["pyproject", "src_avo", "agents"])
def test_incomplete_checkout_markers_select_binary(tmp_path: Path, omit: str) -> None:
    cwd = tmp_path / "almost"
    cwd.mkdir()
    if omit != "pyproject":
        (cwd / "pyproject.toml").write_text(
            '[project]\nname = "avo"\n', encoding="utf-8"
        )
    if omit != "src_avo":
        (cwd / "src" / "avo").mkdir(parents=True)
    if omit != "agents":
        (cwd / "AGENTS.md").write_text(f"{ORCHESTRATOR_MARK}\n", encoding="utf-8")
    home = tmp_path / "home"
    resolved = _resolve(cwd, home=home)
    assert resolved.mode == "binary"
    assert Path(resolved.command_prefix) == home / ".avo" / "bin" / "avo"


@pytest.mark.parametrize("override", ["mcp", "self-build"])
def test_user_override_wins_over_checkout_and_binary(
    tmp_path: Path, override: str
) -> None:
    cwd = _write_checkout(tmp_path / "checkout")
    home = tmp_path / "home"
    _write_engine(home)
    resolved = _resolve(cwd, override=override, home=home)
    assert resolved.mode == "override"
    prefix = str(resolved.command_prefix)
    assert prefix
    assert str(home / ".avo" / "bin" / "avo") not in prefix
    if override == "mcp":
        assert "mcp" in prefix.lower()
    else:
        assert "-m" in prefix
