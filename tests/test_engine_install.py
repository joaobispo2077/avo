"""TDD-red (aeb-004 / FR-2 / FR-7): installer engine fetch. Fails until aeb-030.

In-process mock HTTP only — do not hit live GitHub. Engine zip is AVO Python,
not ffmpeg, HyperFrames, or watch-skill. Never ``pip install avo``.
"""

from __future__ import annotations

import hashlib
import io
import os
import tempfile
import unittest
import urllib.request
import zipfile
from collections.abc import Callable
from pathlib import Path
from unittest.mock import patch


def _fetch_api():
    """Load the engine fetch API. Missing until aeb-030."""
    try:
        from avo import engine_install
    except ImportError as exc:
        raise AssertionError("missing fetch API") from exc
    for name in ("detect_engine_arch", "install_engine", "EngineChecksumError"):
        if not hasattr(engine_install, name):
            raise AssertionError("missing fetch API")
    return engine_install


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _engine_zip(payload: bytes = b"avo-engine-1.2.3\n") -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("bin/avo", payload)
    return buf.getvalue()


def _sums(filename: str, blob: bytes) -> bytes:
    return f"{_sha256(blob)}  {filename}\n".encode()


def _launcher(prefix: Path) -> Path:
    exe = prefix / "bin" / "avo.exe"
    return exe if exe.exists() else prefix / "bin" / "avo"


# detect id (task aeb-004) → GitHub asset slug (spec FR-1)
V1_ARCH = (
    ("Windows", "AMD64", "win-x64", "windows-x64"),
    ("Darwin", "arm64", "macos-arm64", "macos-arm64"),
    ("Linux", "x86_64", "linux-x64", "linux-x64"),
)


class MockRelease:
    """In-memory GitHub Releases stand-in. Never opens a socket."""

    def __init__(self, zip_name: str, zip_bytes: bytes, sums: bytes | None = None) -> None:
        self.zip_name = zip_name
        self.zip_bytes = zip_bytes
        self.sums = sums if sums is not None else _sums(zip_name, zip_bytes)
        self.urls: list[str] = []

    def get(self, url: str) -> bytes:
        self.urls.append(url)
        if "github.com" in url:
            raise AssertionError("do not hit live GitHub")
        if url.rstrip("/").endswith("SHA256SUMS"):
            return self.sums
        if url.endswith(("/" + self.zip_name, self.zip_name)):
            return self.zip_bytes
        raise FileNotFoundError(url)


def _block_live_github():
    blocked = AssertionError("do not hit live GitHub")
    return (
        patch.object(urllib.request, "urlopen", side_effect=blocked),
        patch.object(urllib.request, "urlretrieve", side_effect=blocked),
    )


def _install(
    api,
    prefix: Path,
    *,
    version: str = "1.2.3",
    system: str,
    machine: str,
    http_get: Callable[[str], bytes],
    install_skills: Callable[[], None],
):
    net = _block_live_github()
    with net[0], net[1]:
        return api.install_engine(
            prefix,
            version,
            system=system,
            machine=machine,
            http_get=http_get,
            install_skills=install_skills,
        )


class EngineInstallTests(unittest.TestCase):
    def test_detect_arch_win_x64(self) -> None:
        api = _fetch_api()
        self.assertEqual(api.detect_engine_arch("Windows", "AMD64"), "win-x64")

    def test_detect_arch_macos_arm64(self) -> None:
        api = _fetch_api()
        self.assertEqual(api.detect_engine_arch("Darwin", "arm64"), "macos-arm64")

    def test_detect_arch_linux_x64(self) -> None:
        api = _fetch_api()
        self.assertEqual(api.detect_engine_arch("Linux", "x86_64"), "linux-x64")

    def test_v1_platforms_fetch_matching_release_zip(self) -> None:
        api = _fetch_api()
        payload = b"AVO-ENGINE-1.2.3"
        for system, machine, _arch, slug in V1_ARCH:
            zip_name = f"avo-1.2.3-{slug}.zip"
            with self.subTest(system=system, machine=machine, zip_name=zip_name):
                http = MockRelease(zip_name, _engine_zip(payload))
                skills: list[str] = []
                with tempfile.TemporaryDirectory() as tmp:
                    prefix = Path(tmp) / ".avo"
                    _install(
                        api,
                        prefix,
                        system=system,
                        machine=machine,
                        http_get=http.get,
                        install_skills=lambda bucket=skills: bucket.append("ok"),
                    )
                    launcher = _launcher(prefix)
                    self.assertTrue(launcher.is_file(), msg=zip_name)
                    self.assertEqual(launcher.read_bytes(), payload)
                    self.assertEqual(skills, ["ok"])
                    self.assertTrue(
                        any(u.endswith(zip_name) for u in http.urls),
                        msg=http.urls,
                    )
                    self.assertTrue(
                        any(u.rstrip("/").endswith("SHA256SUMS") for u in http.urls),
                        msg=http.urls,
                    )
                    joined = "\n".join(http.urls)
                    self.assertNotIn("github.com", joined)
                    self.assertNotIn("pip install avo", joined)

    def test_sha256_mismatch_aborts_and_keeps_previous(self) -> None:
        api = _fetch_api()
        zip_name = "avo-1.2.3-windows-x64.zip"
        blob = _engine_zip(b"NEW-ENGINE")
        http = MockRelease(zip_name, blob, sums=_sums(zip_name, b"not-the-zip"))
        skills: list[str] = []
        with tempfile.TemporaryDirectory() as tmp:
            prefix = Path(tmp) / ".avo"
            previous = prefix / "bin" / "avo"
            previous.parent.mkdir(parents=True)
            previous.write_bytes(b"PREVIOUS-ENGINE")
            with self.assertRaises(api.EngineChecksumError):
                _install(
                    api,
                    prefix,
                    system="Windows",
                    machine="AMD64",
                    http_get=http.get,
                    install_skills=lambda bucket=skills: bucket.append("ok"),
                )
            self.assertEqual(previous.read_bytes(), b"PREVIOUS-ENGINE")
            self.assertTrue(http.urls, msg="checksum check must use mock HTTP")
            self.assertFalse(any("github.com" in u for u in http.urls))

    def test_idempotent_same_version(self) -> None:
        api = _fetch_api()
        zip_name = "avo-1.2.3-linux-x64.zip"
        payload = b"avo-engine-1.2.3\n"
        http = MockRelease(zip_name, _engine_zip(payload))
        skills: list[str] = []
        with tempfile.TemporaryDirectory() as tmp:
            prefix = Path(tmp) / ".avo"
            kwargs = {
                "system": "Linux",
                "machine": "x86_64",
                "http_get": http.get,
                "install_skills": lambda bucket=skills: bucket.append("ok"),
            }
            _install(api, prefix, **kwargs)
            first = _launcher(prefix).read_bytes()
            self.assertEqual(first, payload)
            _install(api, prefix, **kwargs)
            launcher = _launcher(prefix)
            self.assertTrue(launcher.is_file())
            self.assertEqual(launcher.read_bytes(), first)
            self.assertNotIn(b"ffmpeg", first)
            self.assertFalse(
                any(
                    "ffmpeg" in u or "hyperframes" in u or "watch" in u
                    for u in http.urls
                )
            )
            text = "\n".join(http.urls)
            self.assertNotIn("pip install avo", text)
            self.assertGreaterEqual(len(skills), 1)

    def test_unsupported_arch_skips_zip_still_installs_skills(self) -> None:
        api = _fetch_api()
        self.assertIsNone(api.detect_engine_arch("Windows", "ARM64"))
        self.assertIsNone(api.detect_engine_arch("Darwin", "x86_64"))
        http = MockRelease("avo-1.2.3-windows-x64.zip", _engine_zip())
        for system, machine in (("Windows", "ARM64"), ("Darwin", "x86_64")):
            with self.subTest(system=system, machine=machine):
                skills: list[str] = []
                http.urls = []
                with tempfile.TemporaryDirectory() as tmp:
                    prefix = Path(tmp) / ".avo"
                    result = _install(
                        api,
                        prefix,
                        system=system,
                        machine=machine,
                        http_get=http.get,
                        install_skills=lambda bucket=skills: bucket.append("ok"),
                    )
                    self.assertEqual(skills, ["ok"])
                    self.assertFalse(_launcher(prefix).exists())
                    self.assertFalse(any(u.endswith(".zip") for u in http.urls))
                    self.assertFalse((prefix / "bin" / "ffmpeg").exists())
                    self.assertFalse((prefix / "bin" / "ffmpeg.exe").exists())
                    self.assertFalse((prefix / "hyperframes").exists())
                    self.assertFalse((prefix / "watch-skill").exists())
                    if result is not None:
                        blob = str(
                            getattr(result, "message", None)
                            or getattr(result, "messages", result)
                        ).lower()
                        self.assertNotIn("pip install avo", blob)

    def test_prefix_launcher_is_not_path_avo(self) -> None:
        """FR-7: prefix ~/.avo/bin/avo is this engine, not Soteria on PATH."""
        api = _fetch_api()
        payload = b"AVO-ENGINE-NOT-SOTERIA"
        zip_name = "avo-1.2.3-linux-x64.zip"
        http = MockRelease(zip_name, _engine_zip(payload))
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            prefix = home / ".avo"
            path_dir = home / "on-path"
            path_dir.mkdir()
            decoy = path_dir / "avo"
            decoy.write_bytes(b"soteria-avo")
            env_path = os.pathsep.join((str(path_dir), os.environ.get("PATH", "")))
            with patch.dict(os.environ, {"PATH": env_path}):
                _install(
                    api,
                    prefix,
                    system="Linux",
                    machine="x86_64",
                    http_get=http.get,
                    install_skills=lambda: None,
                )
            launcher = _launcher(prefix)
            self.assertTrue(launcher.is_file())
            self.assertEqual(launcher.read_bytes(), payload)
            self.assertNotEqual(launcher.read_bytes(), b"soteria-avo")
            self.assertEqual(decoy.read_bytes(), b"soteria-avo")
            self.assertEqual(launcher.resolve().parent, (prefix / "bin").resolve())


if __name__ == "__main__":
    unittest.main()
