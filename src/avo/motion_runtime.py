"""Read-only metadata and prerequisites shared by motion inspection and capture.

Optional browser APIs are imported only when a selected runtime is inspected.
This module never downloads dependencies or imports an adapter.
"""

from __future__ import annotations

import importlib.metadata
import importlib.util
import json
import os
import shutil
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from avo.motion import MotionError
from avo.templates.code_drawn import (
    BRUSH_LICENSE_SHA256,
    BRUSH_SHA256,
    brush_cache_paths,
)
from avo.timeline.contracts import file_fingerprint

PLAYWRIGHT_VERSION = "1.64.1"
DriverPaths = Callable[[], tuple[Path, Path]]


def runtime_repair() -> str:
    if getattr(sys, "frozen", False):
        return "Reinstall or upgrade the AVO engine with its bundled Playwright driver."
    return "Install AVO with its optional code-drawn extra: uv sync --extra code-drawn."


def driver_paths() -> tuple[Path, Path]:
    from playwright._impl._driver import compute_driver_executable

    node_name, cli_name = compute_driver_executable()
    cli = Path(cli_name)
    node = cli.parent.parent / ("node.exe" if sys.platform == "win32" else "node")
    if Path(node_name).resolve() != node.resolve():
        raise MotionError(
            "CODE_DRAWN_RUNTIME_MISSING",
            "External Playwright Node runtimes are unsupported.",
            remediation="Unset PLAYWRIGHT_NODEJS_PATH to use the bundled driver.",
        )
    return node, cli


def _driver_readiness(paths: DriverPaths) -> tuple[bool, str]:
    try:
        node, cli = paths()
    except (ImportError, OSError, MotionError) as error:
        return False, f"Missing bundled driver: {error}. {runtime_repair()}"
    if not node.is_file() or not cli.is_file():
        return False, runtime_repair()
    return True, ""


def _package_ready(paths: DriverPaths) -> tuple[bool, str]:
    try:
        installed = importlib.metadata.version("playwright")
    except importlib.metadata.PackageNotFoundError:
        return False, runtime_repair()
    if installed != PLAYWRIGHT_VERSION:
        return (
            False,
            f"Expected Playwright {PLAYWRIGHT_VERSION}, found {installed}. {runtime_repair()}",
        )
    if importlib.util.find_spec("playwright") is None:
        return False, runtime_repair()
    return _driver_readiness(paths)


def browser_identity(*, paths: DriverPaths | None = None) -> dict[str, str]:
    _, cli = (paths or driver_paths)()
    manifest = json.loads((cli.parent / "browsers.json").read_text(encoding="utf-8"))
    return next(item for item in manifest["browsers"] if item["name"] == "chromium")


def _browser_cache(cli: Path) -> Path:
    configured = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    if configured == "0":
        return cli.parent / ".local-browsers"
    if configured:
        return Path(configured).expanduser().resolve()
    if sys.platform == "win32":
        return (
            Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local")))
            / "ms-playwright"
        )
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Caches" / "ms-playwright"
    return (
        Path(os.environ.get("XDG_CACHE_HOME", str(Path.home() / ".cache")))
        / "ms-playwright"
    )


def managed_browser_path(*, paths: DriverPaths | None = None) -> Path:
    selected_paths = paths or driver_paths
    _, cli = selected_paths()
    if sys.platform == "win32":
        executable = "chrome-win64/chrome.exe"
    elif sys.platform == "darwin":
        executable = "chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing"
    else:
        executable = "chrome-linux64/chrome"
    revision = browser_identity(paths=selected_paths)["revision"]
    return _browser_cache(cli) / ("chromium-" + revision) / executable


def brush_files(
    *,
    directory: Path | None = None,
    hashes: tuple[str, str] | None = None,
) -> tuple[Path, Path]:
    paths = (
        (directory / "brush.js", directory / "LICENSE.md")
        if directory is not None
        else brush_cache_paths()
    )
    for target, digest in zip(
        paths, hashes or (BRUSH_SHA256, BRUSH_LICENSE_SHA256), strict=True
    ):
        if not target.is_file() or file_fingerprint(target)["sha256"] != digest:
            raise MotionError(
                "CODE_DRAWN_ASSET_NOT_READY",
                f"Missing or changed local brush input: {target}",
                field=str(target),
                remediation="Run animation runtime-install --engine code-drawn --brush.",
            )
    return paths


def _browser_readiness(paths: DriverPaths) -> tuple[list[dict], list[str]]:
    try:
        browser = managed_browser_path(paths=paths)
        present = browser.is_file()
        checks = [{"name": "managed-chromium", "ready": present, "path": str(browser)}]
        blockers = (
            []
            if present
            else [
                "Managed Chromium is missing. Run animation runtime-install --engine code-drawn."
            ]
        )
        return checks, blockers
    except Exception as error:
        return [], [f"Cannot inspect managed Chromium: {error}. {runtime_repair()}"]


def _brush_readiness(check: Callable) -> tuple[dict, list[str]]:
    try:
        check()
        return {"name": "local-brush", "ready": True}, []
    except MotionError as error:
        return {"name": "local-brush", "ready": False}, [str(error)]


def runtime_readiness(
    *,
    brush: bool = False,
    paths: DriverPaths | None = None,
    brush_check: Callable[[], tuple[Path, Path]] | None = None,
) -> dict[str, Any]:
    selected_paths = paths or driver_paths
    available, reason = _package_ready(selected_paths)
    checks = [{"name": "playwright-driver", "ready": available}]
    blockers = [] if available else [reason]
    if available:
        browser_checks, browser_blockers = _browser_readiness(selected_paths)
        checks.extend(browser_checks)
        blockers.extend(browser_blockers)
    for tool in ("ffmpeg", "ffprobe"):
        present = shutil.which(tool) is not None
        checks.append({"name": tool, "ready": present})
        if not present:
            blockers.append(f"Install {tool} on PATH.")
    if brush:
        brush_result, brush_blockers = _brush_readiness(brush_check or brush_files)
        checks.append(brush_result)
        blockers.extend(brush_blockers)
    return {
        "ready": not blockers,
        "state": "unavailable" if blockers else "available",
        "checks": checks,
        "blockers": blockers,
        "nextActions": blockers.copy(),
    }
