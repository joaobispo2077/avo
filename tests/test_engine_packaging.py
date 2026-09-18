"""Packager contract (aeb-021). No freeze, no GitHub, no pip install avo."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = (ROOT / "packaging" / "avo.spec").read_text(encoding="utf-8")
SH = (ROOT / "scripts" / "ci" / "build-engine.sh").read_text(encoding="utf-8")
PS1 = (ROOT / "scripts" / "ci" / "build-engine.ps1").read_text(encoding="utf-8")


def test_spec_is_onedir_not_onefile() -> None:
    assert "exclude_binaries=True" in SPEC
    assert "COLLECT(" in SPEC
    assert "onefile=True" not in SPEC
    assert "Forbidden: PyOxidizer" in SPEC
    assert "--onefile" not in SH
    assert "--onefile" not in PS1


def test_spec_bundles_config_schemas_templates() -> None:
    assert '"config"' in SPEC
    assert '"schemas"' in SPEC
    assert "shorts_hyperframes" in SPEC
    assert 'collect_all("avo")' in SPEC or '_collect("avo")' in SPEC


def test_spec_cpu_only_ctranslate2() -> None:
    assert "_collect(\"ctranslate2\")" in SPEC or 'collect_all("ctranslate2")' in SPEC
    assert "_collect(\"faster_whisper\")" in SPEC or 'collect_all("faster_whisper")' in SPEC
    assert "matplotlib" in SPEC
    assert any(tok in SPEC for tok in ("cublas", "cudart", "cuda"))
    assert "__main__.py" in SPEC


def test_spec_does_not_collect_mcp_cli() -> None:
    assert "_collect(\"mcp\")" not in SPEC
    assert "collect_all" in SPEC
    assert not any(
        line.strip() and not line.lstrip().startswith("#") and 'collect_all("mcp")' in line
        for line in SPEC.splitlines()
    )
    assert "mcp.cli" in SPEC
    assert "typer" in SPEC


def test_build_scripts_zip_names_and_smoke() -> None:
    for text in (SH, PS1):
        assert "avo-${VERSION}-${PLATFORM}.zip" in text or "avo-$Version-$Platform" in text
        assert "version" in text
        assert "--help" in text
        assert "pip install avo" not in text
        assert "PyInstaller" in text
        assert "onefile" not in text.lower() or "Not onefile" in text
    assert "linux-x64" in SH
    assert "macos-arm64" in SH
    assert "windows-x64" in PS1
    assert "\u2014" not in PS1
    assert "\u2013" not in PS1
