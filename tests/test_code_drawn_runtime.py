"""Selected capture runtime and immutable generic source scaffolding."""

from __future__ import annotations

import importlib
import importlib.metadata
import io
import json
import shutil
import subprocess
import sys
import tempfile
import types
import urllib.error
from hashlib import sha256
from pathlib import Path

import pytest

from avo import motion
from avo.motion import MotionError, load_composition

ROOT = Path(__file__).resolve().parents[1]


def capture_runtime():
    return importlib.import_module("avo.adapters.motion.code_drawn")


@pytest.fixture
def runtime_home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(home / "managed-browsers"))
    return home


@pytest.fixture
def frozen_bundle(runtime_home):
    bundle = runtime_home / "bundle"
    shutil.copytree(ROOT / "schemas", bundle / "schemas")
    return bundle


def test_importing_capture_module_and_cli_does_not_import_optional_frameworks(tmp_path):
    script = """
import importlib
import importlib.abc
import sys
class BlockOptional(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'playwright', 'hyperframes', 'remotion'}:
            raise AssertionError('Eager optional import: ' + fullname)
sys.meta_path.insert(0, BlockOptional())
importlib.import_module('avo.adapters.motion.code_drawn')
importlib.import_module('avo.cli')
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_readiness_never_installs_and_reports_missing_selected_extra(
    runtime_home, monkeypatch
):
    runtime = capture_runtime()
    calls = []

    def forbidden_install(**kwargs):
        calls.append(kwargs)
        raise AssertionError("Inspection attempted a runtime installation")

    monkeypatch.setattr(runtime, "install_runtime", forbidden_install)
    monkeypatch.setitem(sys.modules, "playwright", None)
    monkeypatch.setitem(sys.modules, "playwright.sync_api", None)
    ready = runtime.runtime_readiness()
    assert ready["ready"] is False
    assert ready["state"] == "unavailable"
    assert ready["blockers"]
    assert "code-drawn" in json.dumps(ready["nextActions"]).casefold()
    assert calls == []
    assert not (runtime_home / "managed-browsers").exists()


def test_frozen_missing_driver_does_not_recommend_external_python(
    frozen_bundle, monkeypatch
):
    runtime = capture_runtime()
    monkeypatch.delenv("AVO_ROOT", raising=False)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(frozen_bundle), raising=False)
    monkeypatch.setitem(sys.modules, "playwright", None)
    monkeypatch.setitem(sys.modules, "playwright.sync_api", None)
    ready = runtime.runtime_readiness()
    assert ready["ready"] is False
    actions = json.dumps(ready["nextActions"]).casefold()
    assert "engine" in actions
    for wrong_repair in ("pip install", "uv sync", "python -m"):
        assert wrong_repair not in actions


def test_plain_readiness_does_not_require_optional_brush(runtime_home, monkeypatch):
    runtime = capture_runtime()
    calls = []

    def brush_not_needed():
        calls.append(True)
        raise AssertionError("Basic drawing requested the brush dependency")

    monkeypatch.setattr(runtime, "brush_files", brush_not_needed)
    monkeypatch.setitem(sys.modules, "playwright", None)
    monkeypatch.setitem(sys.modules, "playwright.sync_api", None)
    runtime.runtime_readiness(brush=False)
    assert calls == []


@pytest.fixture
def install_driver(runtime_home, frozen_bundle, monkeypatch):
    runtime = capture_runtime()
    driver = frozen_bundle / "playwright" / "driver"
    node = driver / ("node.exe" if sys.platform == "win32" else "node")
    cli = driver / "package" / "cli.js"
    cli.parent.mkdir(parents=True)
    node.write_bytes(b"bundled node fixture")
    cli.write_bytes(b"bundled package-matched installer fixture")
    package = types.ModuleType("playwright")
    package.__path__ = []
    implementation = types.ModuleType("playwright._impl")
    implementation.__path__ = []
    module = types.ModuleType("playwright._impl._driver")
    module.compute_driver_executable = lambda: (str(node), str(cli))
    environment = {"PLAYWRIGHT_BROWSERS_PATH": str(runtime_home / "managed-browsers")}
    module.get_driver_env = lambda: environment
    monkeypatch.setitem(sys.modules, "playwright", package)
    monkeypatch.setitem(sys.modules, "playwright._impl", implementation)
    monkeypatch.setitem(sys.modules, "playwright._impl._driver", module)
    original_version = importlib.metadata.version
    monkeypatch.setattr(
        importlib.metadata,
        "version",
        lambda name: "1.64.1" if name == "playwright" else original_version(name),
    )
    monkeypatch.setattr(
        runtime,
        "runtime_readiness",
        lambda **kwargs: {
            "ready": True,
            "state": "available",
            "checks": [],
            "blockers": [],
            "nextActions": [],
        },
    )
    return runtime, node, cli, environment


def test_driver_path_rejects_an_external_node_override(install_driver, monkeypatch):
    runtime, _node, cli, _environment = install_driver
    monkeypatch.setattr(
        sys.modules["playwright._impl._driver"],
        "compute_driver_executable",
        lambda: ("external-node-override", str(cli)),
    )
    with pytest.raises(MotionError) as caught:
        runtime._driver_paths()
    assert caught.value.code == "CODE_DRAWN_RUNTIME_MISSING"
    assert "unsupported" in str(caught.value)


def test_readiness_reports_unsupported_driver_without_crashing(
    runtime_home, monkeypatch
):
    runtime = capture_runtime()
    monkeypatch.setattr(
        importlib.metadata, "version", lambda name: runtime.PLAYWRIGHT_VERSION
    )
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: object())

    def unsupported_driver():
        raise MotionError(
            "CODE_DRAWN_RUNTIME_MISSING",
            "External Playwright Node runtimes are unsupported.",
        )

    monkeypatch.setattr(runtime, "_driver_paths", unsupported_driver)
    ready = runtime.runtime_readiness()
    assert ready["ready"] is False
    assert "unsupported" in " ".join(ready["blockers"])


@pytest.mark.parametrize("frozen", [False, True])
def test_explicit_install_uses_bundled_matched_driver_without_output_leak(
    install_driver, frozen_bundle, monkeypatch, capsys, frozen
):
    runtime, node, cli, environment = install_driver
    calls = []

    def launch(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(
            command, 0, "download progress\n", "driver warning\n"
        )

    monkeypatch.setattr(runtime.subprocess, "run", launch)
    if frozen:
        monkeypatch.delenv("AVO_ROOT", raising=False)
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.setattr(sys, "_MEIPASS", str(frozen_bundle), raising=False)
    before_argv = sys.argv[:]
    result = runtime.install_runtime(brush=False)
    assert result["status"] == "ok"
    assert result["readiness"]["ready"] is True
    assert calls == [
        (
            [str(node), str(cli), "install", "--no-shell", "chromium"],
            {"env": environment, "capture_output": True, "text": True, "timeout": 600},
        )
    ]
    assert sys.executable not in calls[0][0]
    assert sys.argv == before_argv
    assert runtime.PLAYWRIGHT_VERSION == "1.64.1"
    assert capsys.readouterr() == ("", "")


@pytest.mark.parametrize("failure", ["exit", "timeout", "io"])
def test_failed_install_preserves_existing_browser_cache(
    install_driver, runtime_home, monkeypatch, capsys, failure
):
    runtime, _node, _cli, _environment = install_driver
    cache = runtime_home / "managed-browsers"
    cache.mkdir()
    existing = cache / "working-browser"
    existing.write_bytes(b"existing verified runtime")

    def failed_install(command, **kwargs):
        if failure == "timeout":
            raise subprocess.TimeoutExpired(command, 600, output="partial progress")
        if failure == "io":
            raise OSError("cannot execute packaged driver")
        return subprocess.CompletedProcess(
            command, 1, "progress\n", "download failed\n"
        )

    monkeypatch.setattr(runtime.subprocess, "run", failed_install)
    before_argv = sys.argv[:]
    with pytest.raises(MotionError) as caught:
        runtime.install_runtime(brush=False)
    assert caught.value.code == "CODE_DRAWN_RUNTIME_MISSING"
    assert "Managed Chromium installation failed" in str(caught.value)
    assert existing.read_bytes() == b"existing verified runtime"
    assert sys.argv == before_argv
    assert capsys.readouterr() == ("", "")


@pytest.mark.parametrize("sensitive", [False, True])
def test_installer_failure_diagnostic_is_bounded_and_does_not_expose_urls(
    install_driver, monkeypatch, sensitive
):
    runtime, _node, _cli, _environment = install_driver
    diagnostic = "old prefix\n" + "x" * 6000 + "\ndownload unavailable"
    if sensitive:
        diagnostic += " https://user:password@example.invalid/download?token=private"
    monkeypatch.setattr(
        runtime.subprocess,
        "run",
        lambda command, **kwargs: subprocess.CompletedProcess(
            command, 1, "", diagnostic
        ),
    )
    with pytest.raises(MotionError) as caught:
        runtime.install_runtime()
    message = str(caught.value)
    assert len(message) <= 4050
    assert "old prefix" not in message
    if sensitive:
        assert "private" not in message
        assert "example.invalid" not in message
    else:
        assert message.endswith("download unavailable")


def test_mismatched_installer_package_never_launches_driver(
    install_driver, monkeypatch
):
    runtime, _node, _cli, _environment = install_driver
    original_version = importlib.metadata.version
    monkeypatch.setattr(
        importlib.metadata,
        "version",
        lambda name: "0.0.0" if name == "playwright" else original_version(name),
    )
    monkeypatch.setattr(
        runtime.subprocess,
        "run",
        lambda *args, **kwargs: pytest.fail("Mismatched installer was launched"),
    )
    with pytest.raises(MotionError) as caught:
        runtime.install_runtime()
    assert caught.value.code == "CODE_DRAWN_RUNTIME_MISSING"
    assert "1.64.1" in str(caught.value)


@pytest.mark.parametrize("failure", ["network", "staging"])
def test_brush_install_errors_preserve_verified_cache_and_are_motion_errors(
    install_driver, monkeypatch, failure
):
    runtime, _node, _cli, _environment = install_driver
    monkeypatch.setattr(
        runtime.subprocess,
        "run",
        lambda command, **kwargs: subprocess.CompletedProcess(command, 0, "", ""),
    )
    cache = runtime.brush_cache_dir()
    cache.mkdir(parents=True)
    brush, license_file = cache / "brush.js", cache / "LICENSE.md"
    brush.write_bytes(b"working brush")
    license_file.write_bytes(b"working license")
    payloads = (b"replacement brush", b"replacement license")
    monkeypatch.setattr(runtime, "BRUSH_SHA256", sha256(payloads[0]).hexdigest())
    monkeypatch.setattr(
        runtime, "BRUSH_LICENSE_SHA256", sha256(payloads[1]).hexdigest()
    )
    downloads = []

    def fetch(url, **kwargs):
        downloads.append(url)
        if failure == "network" and len(downloads) == 2:
            raise urllib.error.URLError("offline")
        return io.BytesIO(payloads[len(downloads) - 1])

    monkeypatch.setattr(runtime.urllib.request, "urlopen", fetch)
    if failure == "staging":
        original_mkstemp = tempfile.mkstemp
        staging = []

        def stage(**kwargs):
            staging.append(kwargs)
            if len(staging) == 2:
                raise OSError("cache disk full")
            return original_mkstemp(**kwargs)

        monkeypatch.setattr(tempfile, "mkstemp", stage)
    with pytest.raises(MotionError) as caught:
        runtime.install_runtime(brush=True)
    assert caught.value.code == "CODE_DRAWN_ASSET_NOT_READY"
    assert brush.read_bytes() == b"working brush"
    assert license_file.read_bytes() == b"working license"
    assert sorted(path.name for path in cache.iterdir()) == ["LICENSE.md", "brush.js"]


def test_brush_install_uses_unique_exclusive_staging_files(install_driver, monkeypatch):
    runtime, _node, _cli, _environment = install_driver
    monkeypatch.setattr(
        runtime.subprocess,
        "run",
        lambda command, **kwargs: subprocess.CompletedProcess(command, 0, "", ""),
    )
    cache = runtime.brush_cache_dir()
    cache.mkdir(parents=True)
    sentinel = cache / "brush.partial"
    sentinel.write_bytes(b"another attempt")
    payloads = {"dist/brush.js": b"fresh brush", "LICENSE.md": b"fresh license"}
    monkeypatch.setattr(
        runtime, "BRUSH_SHA256", sha256(payloads["dist/brush.js"]).hexdigest()
    )
    monkeypatch.setattr(
        runtime, "BRUSH_LICENSE_SHA256", sha256(payloads["LICENSE.md"]).hexdigest()
    )
    monkeypatch.setattr(
        runtime.urllib.request,
        "urlopen",
        lambda url, **kwargs: io.BytesIO(
            payloads[url.removeprefix(runtime.BRUSH_BASE_URL + "/")]
        ),
    )
    result = runtime.install_runtime(brush=True)
    assert result["status"] == "ok"
    assert (cache / "brush.js").read_bytes() == b"fresh brush"
    assert (cache / "LICENSE.md").read_bytes() == b"fresh license"
    assert sentinel.read_bytes() == b"another attempt"
    assert sorted(path.name for path in cache.iterdir()) == [
        "LICENSE.md",
        "brush.js",
        "brush.partial",
    ]


def test_brush_cache_requires_exact_local_script_and_license(runtime_home, monkeypatch):
    runtime = capture_runtime()
    assert runtime.BRUSH_VERSION == "2.2.3"
    cache = runtime.brush_cache_dir()
    assert cache.is_relative_to(runtime_home)
    cache.mkdir(parents=True)
    brush, license_file = cache / "brush.js", cache / "LICENSE.md"
    brush.write_bytes(b"synthetic brush fixture")
    license_file.write_bytes(b"synthetic license fixture")
    monkeypatch.setattr(runtime, "BRUSH_SHA256", sha256(brush.read_bytes()).hexdigest())
    monkeypatch.setattr(
        runtime, "BRUSH_LICENSE_SHA256", sha256(license_file.read_bytes()).hexdigest()
    )
    assert runtime.brush_files() == (brush, license_file)
    brush.write_bytes(b"changed dependency")
    with pytest.raises(MotionError):
        runtime.brush_files()
    assert license_file.read_bytes() == b"synthetic license fixture"


@pytest.mark.parametrize("route", ["canvas", "svg"])
def test_scaffold_emits_valid_editable_source_without_optional_runtime(
    tmp_path, monkeypatch, route
):
    monkeypatch.setitem(sys.modules, "playwright", None)
    monkeypatch.setitem(sys.modules, "hyperframes", None)
    monkeypatch.setitem(sys.modules, "remotion", None)
    destination = tmp_path / route
    motion.scaffold_code_drawn(
        destination,
        route=route,
        width=1280,
        height=720,
        fps="30000/1001",
        frames=90,
        background="opaque",
        background_color="#121212",
    )
    document = load_composition(destination / "composition.json")
    assert document["engine"] == "code-drawn"
    assert document["drawingRoute"] == route
    assert document["dependencies"] == []
    assert document["renderContract"]["frameRate"] == {"num": 30000, "den": 1001}
    assert document["renderContract"]["frameCount"] == 90
    assert document["renderContract"]["background"] == {
        "mode": "opaque",
        "color": "#121212",
    }
    assert document["renderContract"]["quality"] == {
        "spatialSamples": 1,
        "temporalSamples": 1,
    }
    assert (destination / document["entry"]).is_file()
    assert (destination / "assets").is_dir()
    for name in (
        "DESIGN.md",
        "STORYBOARD.md",
        "ANIMATION-EDITLOG.md",
        "ANIMATION-SOURCE-LOG.md",
        "README.md",
    ):
        assert (destination / name).is_file(), name
    assert not (destination / "input-lock.json").exists()
    assert not list(destination.rglob("*.mkv"))


def test_transparent_scaffold_does_not_require_an_opaque_color(tmp_path):
    destination = tmp_path / "overlay"
    motion.scaffold_code_drawn(
        destination,
        route="canvas",
        width=1280,
        height=720,
        fps="30/1",
        frames=90,
        background="transparent",
    )
    document = load_composition(destination / "composition.json")
    assert document["renderContract"]["background"] == {"mode": "transparent"}
    assert document["renderContract"]["alphaMode"] == "straight"


def test_scaffold_never_overwrites_existing_destination(tmp_path):
    destination = tmp_path / "existing"
    destination.mkdir()
    original = destination / "index.html"
    original.write_bytes(b"creator source")
    with pytest.raises((MotionError, FileExistsError)):
        motion.scaffold_code_drawn(
            destination,
            route="canvas",
            width=1280,
            height=720,
            fps="30/1",
            frames=90,
            background_color="#121212",
        )
    assert original.read_bytes() == b"creator source"
    assert sorted(path.name for path in destination.iterdir()) == ["index.html"]


@pytest.mark.parametrize(
    "change",
    [
        {"route": "hyperframes"},
        {"width": 0},
        {"height": -1},
        {"fps": "29.97"},
        {"fps": "30/0"},
        {"frames": 0},
        {"background": "automatic"},
        {"background_color": None},
    ],
)
def test_scaffold_rejects_invalid_targets_before_creation(tmp_path, change):
    destination = tmp_path / "invalid"
    values = {
        "route": "canvas",
        "width": 1280,
        "height": 720,
        "fps": "30/1",
        "frames": 90,
        "background": "opaque",
        "background_color": "#121212",
    }
    with pytest.raises(MotionError):
        motion.scaffold_code_drawn(destination, **{**values, **change})
    assert not destination.exists()


def test_brush_scaffold_without_provisioning_does_not_leave_partial_source(
    tmp_path, runtime_home
):
    destination = tmp_path / "brush"
    with pytest.raises(MotionError):
        motion.scaffold_code_drawn(
            destination,
            route="brush",
            width=720,
            height=1280,
            fps="30/1",
            frames=90,
            background_color="#121212",
        )
    assert not destination.exists()
