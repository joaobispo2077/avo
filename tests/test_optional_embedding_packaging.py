"""The selected external Python needs actual worker bytes in every distribution."""

from __future__ import annotations

import inspect
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path
from zipfile import ZipFile

import pytest

ROOT = Path(__file__).resolve().parents[1]
WORKER = "avo/adapters/understand/clap_embeddings_worker.py"
RUNTIME_LOCKS = (
    "sfx-clap-cpu-windows.requirements.txt",
    "visual-motion-cpu-windows.requirements.txt",
)


def test_optional_worker_and_manifest_survive_actual_wheel_build(tmp_path):
    project = tmp_path / "distribution"
    project.mkdir()
    paths = (
        "pyproject.toml",
        "LICENSE",
        "src/avo/__init__.py",
        "src/avo/adapters/__init__.py",
        "src/avo/adapters/understand/__init__.py",
        "src/" + WORKER,
        "schemas/avo.clap-manifest.schema.json",
        *(f"config/{name}" for name in RUNTIME_LOCKS),
    )
    for name in paths:
        target = project / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / name, target)
    metadata = tomllib.loads((project / "pyproject.toml").read_text(encoding="utf-8"))
    assert (
        "clap_embeddings_worker.py"
        in metadata["tool"]["setuptools"]["package-data"]["avo.adapters.understand"]
    )
    output = tmp_path / "wheels"
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from setuptools.build_meta import build_wheel; import sys; build_wheel(sys.argv[1])",
            str(output),
        ],
        cwd=project,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    with ZipFile(next(output.glob("*.whl"))) as archive:
        assert archive.read(WORKER) == (ROOT / "src" / WORKER).read_bytes()
        manifest = next(
            name
            for name in archive.namelist()
            if name.endswith("share/avo/schemas/avo.clap-manifest.schema.json")
        )
        assert (
            archive.read(manifest)
            == (ROOT / "schemas/avo.clap-manifest.schema.json").read_bytes()
        )
        for lock in RUNTIME_LOCKS:
            member = next(
                name
                for name in archive.namelist()
                if name.endswith(f"share/avo/config/{lock}")
            )
            assert archive.read(member) == (ROOT / "config" / lock).read_bytes()


def test_actual_frozen_collector_includes_external_worker_source_bytes():
    pytest.importorskip("PyInstaller")
    from PyInstaller.utils.hooks import collect_all, collect_data_files

    include_sources = (
        inspect.signature(collect_all).parameters["include_py_files"].default
    )
    assert include_sources is True
    collected = collect_data_files("avo", include_py_files=include_sources)
    destinations = {
        (Path(target).as_posix() + "/" + Path(source).name): Path(source)
        for source, target in collected
    }
    assert destinations[WORKER].read_bytes() == (ROOT / "src" / WORKER).read_bytes()
    assert '_collect("avo")' in (ROOT / "packaging/avo.spec").read_text(
        encoding="utf-8"
    )
