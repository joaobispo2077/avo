# -*- mode: python ; coding: utf-8 -*-
"""AVO engine freeze — PyInstaller onedir (v1 default).

Entry: avo.__main__ → avo.engine_cli:main.
CPU-only CTranslate2: collect the wheel, then drop CUDA stubs.
Drop matplotlib (declared in pyproject, unused under src/avo).
Bundle config/, schemas/, motion templates, direction data and capture driver.

This spec is onedir (EXE exclude_binaries + COLLECT). Do not ship --onefile.
Forbidden: PyOxidizer. Forbidden: onefile as the shipped artifact.

Nuitka --mode=standalone is the only fallback, and only if a built onedir
cannot import faster_whisper. Do not add a second packager in this tree
“just in case.”

aeb-040 zip smoke may set AVO_CI_TRANSCRIBE_STUB=1 so `avo transcribe`
starts without downloading weights. That env is runtime, not a freeze flag.
This spec still collects CTranslate2 CPU so a real machine can transcribe.

Zip contents include AVO and the Playwright capture driver with its internal Node.
Browsers, ffmpeg, HyperFrames, watch-skill, CUDA and model weights stay external.
"""

from __future__ import annotations

import sys
from importlib.metadata import PackageNotFoundError, distribution
from importlib.resources import files
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_data_files, copy_metadata

# SPECPATH is packaging/; repo root is the parent.
REPO_ROOT = Path(SPECPATH).resolve().parent
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

try:
    capture_extras = distribution("avo").metadata.get_all("Provides-Extra", [])
    driver_root = files("playwright").joinpath("driver")
except (PackageNotFoundError, ModuleNotFoundError) as error:
    raise SystemExit(
        'Frozen capture support requires AVO installed with ".[mcp,code-drawn]".'
    ) from error
if "code-drawn" not in capture_extras:
    raise SystemExit("AVO metadata is missing the required code-drawn build extra.")
for driver_name in ("node.exe" if sys.platform == "win32" else "node", "package/cli.js"):
    if not driver_root.joinpath(driver_name).is_file():
        raise SystemExit(f"Missing Playwright build driver resource: {driver_name}")

# CUDA stub / NVIDIA runtime fragments that crash CPU-only CTranslate2 freezes.
_CUDA_MARKERS = (
    "cublas",
    "cudart",
    "cudnn",
    "cufft",
    "curand",
    "cusolver",
    "cusparse",
    "nvrtc",
    "nvinfer",
    "libcuda",
    "nvcuda",
    "cupti",
    "nvjitlink",
    "nvtx",
    "cuda_runtime",
    "/cuda/",
    "\\cuda\\",
    "nvidia/cuda",
    "nvidia/cublas",
    "nvidia/cudnn",
    "nvidia/cufft",
    "nvidia/curand",
    "nvidia/cusolver",
    "nvidia/cusparse",
    "nvidia/nvrtc",
    "nvidia/nvjitlink",
)

# Sidecars must stay out of the engine zip even if a hook tries to collect them.
_SIDECAR_NAMES = (
    "ffmpeg",
    "ffmpeg.exe",
    "ffprobe",
    "ffprobe.exe",
    "ffplay",
    "ffplay.exe",
)


def _blob(entry) -> str:
    name = str(entry[0]) if entry else ""
    src = str(entry[1]) if entry and len(entry) > 1 else ""
    return f"{name} {src}".replace("\\", "/").lower()


def _drop(entry) -> bool:
    blob = _blob(entry)
    if "matplotlib" in blob or "mpl_toolkits" in blob:
        return True
    # A developer may have installed browsers inside the package; never ship them.
    if "/.local-browsers/" in blob or "/ms-playwright/" in blob:
        return True
    if any(tok in blob for tok in _CUDA_MARKERS):
        return True
    base = blob.replace("\\", "/").rsplit("/", 1)[-1].strip()
    return base in _SIDECAR_NAMES


datas: list = [
    (str(REPO_ROOT / "config"), "config"),
    (str(REPO_ROOT / "schemas"), "schemas"),
]
binaries: list = []
hiddenimports: list = [
    "avo.__main__",
    "avo.engine_cli",
    "avo.consume_mode",
    "avo.paths",
    "avo.resources.directions",
    "avo.mcp.__main__",
    "avo.mcp.server",
    "mcp",
    "mcp.server",
]


def _collect(package: str) -> None:
    pkg_datas, pkg_binaries, pkg_hidden = collect_all(package)
    datas.extend(pkg_datas)
    binaries.extend(pkg_binaries)
    hiddenimports.extend(pkg_hidden)


_collect("avo")
_collect("ctranslate2")
_collect("faster_whisper")
_collect("playwright")
# Skip full MCP package walk: mcp.cli needs typer (optional CLI extra).
# avo mcp only imports mcp.server.MCPServer.
datas += collect_data_files("mcp")
datas += collect_data_files("avo.templates.shorts_hyperframes")
datas += collect_data_files("avo.templates.code_drawn")
datas += collect_data_files("avo.resources.directions")
datas += copy_metadata("avo")
datas += copy_metadata("faster-whisper")
datas += copy_metadata("mcp")
datas += copy_metadata("playwright")

excludes = [
    "matplotlib",
    "matplotlib.pyplot",
    "matplotlib.backends",
    "mpl_toolkits",
    "tkinter",
    "PyQt5",
    "PyQt6",
    "PySide2",
    "PySide6",
    "mcp.cli",
    "typer",
]

a = Analysis(
    [str(SRC / "avo" / "__main__.py")],
    pathex=[str(SRC)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)
a.binaries = [entry for entry in a.binaries if not _drop(entry)]
a.datas = [entry for entry in a.datas if not _drop(entry)]

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="avo",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="avo",
)
