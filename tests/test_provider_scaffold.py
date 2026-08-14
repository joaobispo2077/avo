from __future__ import annotations
import json
from pathlib import Path
import pytest
from avo.provider_scaffold import build_manifest, scaffold_provider

def _template(root: Path) -> None:
    base = root / "providers" / "_template"
    (base / "brand").mkdir(parents=True)
    (base / "logo").mkdir()
    (base / "DESIGN.md").write_text("# Design\n", encoding="utf-8")
    (base / "brand" / "palette.json").write_text("{}\n", encoding="utf-8")
    (base / "logo" / ".gitkeep").write_text("", encoding="utf-8")

def test_scaffold_provider_writes_template_and_manifest(tmp_path: Path) -> None:
    _template(tmp_path)
    manifest = build_manifest("demo", "youtube", "/media/raw", language="pt-BR")
    destination = scaffold_provider(tmp_path, manifest)
    stored = json.loads((destination / "avo.provider.json").read_text(encoding="utf-8"))
    assert stored == manifest
    assert (destination / "DESIGN.md").is_file()
    assert (destination / "brand" / "palette.json").is_file()

def test_build_manifest_rejects_invalid_identity() -> None:
    with pytest.raises(ValueError):
        build_manifest("Bad Name", "youtube", "/media/raw")
    with pytest.raises(ValueError):
        build_manifest("demo", "unknown", "/media/raw")
