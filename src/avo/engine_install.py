"""Fetch and unpack the AVO engine zip into a user prefix (FR-2 / FR-7).

Callers inject ``http_get`` (tests use in-memory bytes). The Node installer
fetches GitHub Release assets; this module never emits ``pip install avo``.
"""

from __future__ import annotations

import hashlib
import io
import shutil
import zipfile
from collections.abc import Callable
from pathlib import Path

_ARCH = {
    ("Windows", "AMD64"): "win-x64",
    ("Darwin", "arm64"): "macos-arm64",
    ("Linux", "x86_64"): "linux-x64",
}
_SLUG = {
    "win-x64": "windows-x64",
    "macos-arm64": "macos-arm64",
    "linux-x64": "linux-x64",
}


class EngineChecksumError(Exception):
    """SHA-256 of the zip does not match SHA256SUMS."""


def detect_engine_arch(system: str, machine: str) -> str | None:
    return _ARCH.get((system, machine))


def install_engine(
    prefix: Path,
    version: str,
    *,
    system: str,
    machine: str,
    http_get: Callable[[str], bytes],
    install_skills: Callable[[], None],
) -> str | None:
    prefix = Path(prefix)
    arch = detect_engine_arch(system, machine)
    if arch is None:
        install_skills()
        return "engine unavailable for this platform; skills installed"
    zip_name = f"avo-{version}-{_SLUG[arch]}.zip"
    blob = http_get(zip_name)
    expected = _sum_for(http_get("SHA256SUMS"), zip_name)
    actual = hashlib.sha256(blob).hexdigest()
    if expected is None or actual.lower() != expected.lower():
        raise EngineChecksumError(f"SHA256 mismatch for {zip_name}")
    _unpack(blob, prefix)
    install_skills()
    return None


def _sum_for(sums: bytes, zip_name: str) -> str | None:
    for line in sums.decode("ascii", errors="replace").splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[-1].rstrip("*").endswith(zip_name):
            return parts[0]
    return None


def _unpack(blob: bytes, prefix: Path) -> None:
    staging = prefix / ".staging"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    try:
        with zipfile.ZipFile(io.BytesIO(blob)) as zf:
            for info in zf.infolist():
                target = _zip_target(staging, info.filename)
                if target is None:
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(zf.read(info))
        _merge(staging, prefix)
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def _zip_target(dest: Path, name: str) -> Path | None:
    if name.endswith("/"):
        return None
    rel = Path(name.replace("\\", "/"))
    if rel.is_absolute() or ".." in rel.parts:
        return None
    return dest / rel


def _merge(src: Path, dst: Path) -> None:
    for path in src.rglob("*"):
        if not path.is_file():
            continue
        out = dst / path.relative_to(src)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(path.read_bytes())
