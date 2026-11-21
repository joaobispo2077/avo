"""Verify AVO distributes ArtCraft knowledge and its own integration only."""

import json
import os
import subprocess
import sys
import tomllib
from pathlib import Path
from zipfile import ZipFile

import pytest

from avo.artcraft import catalog

ROOT = Path(__file__).resolve().parents[1]
_NATIVE_EXECUTABLE_SUFFIXES = {".exe", ".dll", ".msi", ".appimage", ".dylib", ".so"}


def test_focused_artcraft_guides_are_inside_the_existing_skill():
    skills = json.loads((ROOT / "skills.json").read_text(encoding="utf-8"))["skills"]
    assert {item["name"] for item in skills} == {"avo", "avo-pipeline", "avo-provider"}
    pipeline = ROOT / next(
        item["path"] for item in skills if item["name"] == "avo-pipeline"
    )
    reference = pipeline.parent / "references" / "artcraft.md"
    guide = reference.read_text(encoding="utf-8")
    for name in ("still-review.md", "effectcraft-mask.md", "texturecraft.md"):
        relative = f"artcraft/{name}"
        assert f"]({relative})" in guide
        assert (reference.parent / relative).is_file()


def test_packaging_keeps_catalog_and_schema_with_no_vendor_dependency():
    manifest = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    setuptools = manifest["tool"]["setuptools"]
    assert setuptools["package-data"]["avo.resources.artcraft"] == ["catalog.json"]
    assert "schemas/*.json" in setuptools["data-files"]["share/avo/schemas"]
    dependencies = manifest["project"]
    declared = [*dependencies["dependencies"]]
    for group in dependencies["optional-dependencies"].values():
        declared.extend(group)
    assert not any("artcraft" in entry.casefold() for entry in declared)


def test_bundled_catalog_does_not_probe_native_tools_or_initialize_connections(
    monkeypatch,
):
    def unexpected(*_args, **_kwargs):
        pytest.fail("Static ArtCraft knowledge attempted to start a process")

    before = set(sys.modules)
    monkeypatch.setattr(subprocess, "Popen", unexpected)
    assert len(catalog()["profiles"]) == 10
    concrete = set(sys.modules) - before
    assert not any(
        name.startswith(("avo.adapters.artcraft", "mcp.")) for name in concrete
    )


@pytest.mark.integration
def test_selected_wheel_contains_only_packaged_artcraft_knowledge_and_integration():
    candidate = os.environ.get("AVO_ARTCRAFT_DISTRIBUTION_WHEEL")
    if not candidate:
        pytest.skip(
            "Select the locally built AVO wheel using AVO_ARTCRAFT_DISTRIBUTION_WHEEL"
        )
    with ZipFile(Path(candidate).resolve(strict=True)) as wheel:
        names = set(wheel.namelist())
        assert "avo/resources/artcraft/catalog.json" in names
        assert any(
            name.endswith("/share/avo/schemas/avo.artcraft.schema.json")
            for name in names
        )
        assert "avo/adapters/artcraft.py" in names
        assert (
            json.loads(wheel.read("avo/resources/artcraft/catalog.json")) == catalog()
        )
        assert not any(
            Path(name).suffix.casefold() in _NATIVE_EXECUTABLE_SUFFIXES
            for name in names
        )


@pytest.mark.integration
def test_selected_portable_engine_reads_catalog_without_vendor_programs(tmp_path):
    selected = os.environ.get("AVO_ARTCRAFT_ENGINE_DIR")
    if not selected:
        pytest.skip(
            "Select the unpacked local AVO engine using AVO_ARTCRAFT_ENGINE_DIR"
        )
    directory = Path(selected).resolve(strict=True)
    launcher = directory / ("avo.exe" if os.name == "nt" else "avo")
    vendors = {item["app"] for item in catalog()["profiles"]}
    files = [item for item in directory.rglob("*") if item.is_file()]
    assert not any(
        path.suffix.casefold() in _NATIVE_EXECUTABLE_SUFFIXES
        and path.stem.casefold().removesuffix("-cli") in vendors
        for path in files
    )
    assert sum(path.name == "avo.artcraft.schema.json" for path in files) == 1
    result = subprocess.run(
        [str(launcher), "cli", "artcraft", "catalog", "--app", "figcraft", "--json"],
        cwd=tmp_path,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        encoding="utf-8",
        check=True,
        timeout=20,
    )
    assert json.loads(result.stdout) == catalog(app="figcraft")
    assert list(tmp_path.iterdir()) == []
