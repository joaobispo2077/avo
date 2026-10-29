"""setup.sh and setup.ps1 stop before install when Python is below 3.11."""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION_PROBE = (
    'import sys; print("%d.%d.%d" % sys.version_info[:3]); '
    "raise SystemExit(0 if sys.version_info >= (3, 11) else 1)"
)
REQUIRED_SENTENCE = "found; Python 3.11+ is required."
INSTALL_STUBS = ("uv", "npm", "npx", "git")
ACCEPT_ARGS = [
    "--yes",
    "--dry-run",
    "--skip",
    "speckit",
    "--skip",
    "engine",
    "--skip",
    "watch",
    "--skip",
    "hyperframes",
    "--skip",
    "remotion",
]
FAKE_PYTHON = r"""
import os
import sys

version = tuple(int(part) for part in os.environ["AVO_FAKE_VERSION"].split("."))
with open(os.environ["AVO_FAKE_LOG"], "a", encoding="utf-8") as handle:
    handle.write("python " + " ".join(sys.argv[1:]) + "\n")

args = sys.argv[1:]
if "--version" in args or "-V" in args:
    print("Python " + ".".join(str(part) for part in version))
    raise SystemExit(0)

if "-c" in args:
    code = args[args.index("-c") + 1]
    patched = (
        "import sys\nsys.version_info = "
        + repr(version + ("final", 0))
        + "\n"
        + code
    )
    exec(patched, {"__name__": "__main__"})
    raise SystemExit(0)

sys.stderr.write("unexpected python arguments\n")
raise SystemExit(99)
""".lstrip()


def _message(version: str) -> str:
    return f"Python {version} {REQUIRED_SENTENCE}"


def _install_fakes(bin_dir: Path, versions: dict[str, str], log: Path) -> None:
    fake = bin_dir / "fake.py"
    fake.write_text(FAKE_PYTHON, encoding="utf-8")
    real = shlex.quote(sys.executable)
    fake_path = shlex.quote(str(fake))
    log_path = shlex.quote(str(log))
    for name, version in versions.items():
        if not version.replace(".", "").isdigit():
            raise ValueError(version)
        wrapper = bin_dir / name
        wrapper.write_text(
            "#!/bin/sh\n"
            f"export AVO_FAKE_VERSION='{version}'\n"
            f"export AVO_FAKE_LOG={log_path}\n"
            f'exec {real} {fake_path} "$@"\n',
            encoding="utf-8",
        )
        wrapper.chmod(0o755)
    stub = (
        "#!/bin/sh\n"
        'printf \'stub %s %s\\n\' "$(basename "$0")" "$*" >> '
        f"{log_path}\n"
        "exit 0\n"
    )
    for name in INSTALL_STUBS:
        path = bin_dir / name
        path.write_text(stub, encoding="utf-8")
        path.chmod(0o755)


def _run(
    kind: str, versions: dict[str, str], args: list[str]
) -> tuple[subprocess.CompletedProcess[str], str]:
    if kind == "ps1" and shutil.which("pwsh") is None:
        raise unittest.SkipTest("pwsh unavailable")
    with tempfile.TemporaryDirectory() as directory:
        work = Path(directory)
        bin_dir = work / "bin"
        bin_dir.mkdir()
        log = work / "calls"
        _install_fakes(bin_dir, versions, log)
        env = os.environ.copy()
        env["PATH"] = str(bin_dir) + os.pathsep + env.get("PATH", "")
        env["GIT_TERMINAL_PROMPT"] = "0"
        if kind == "sh":
            command = ["bash", str(ROOT / "scripts" / "setup.sh"), *args]
        else:
            command = [
                "pwsh",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(ROOT / "scripts" / "setup.ps1"),
                *args,
            ]
        result = subprocess.run(
            command,
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            timeout=60,
            check=False,
        )
        calls = log.read_text(encoding="utf-8") if log.exists() else ""
        return result, calls


class SetupPythonGateTests(unittest.TestCase):
    def test_both_scripts_share_the_probe_and_sentence(self) -> None:
        for name in ("setup.sh", "setup.ps1"):
            text = (ROOT / "scripts" / name).read_text(encoding="utf-8")
            gate = text.index(VERSION_PROBE)
            self.assertIn(REQUIRED_SENTENCE, text)
            for marker in ("uv sync", "pip install -e"):
                self.assertLess(gate, text.index(marker), msg=name)

    def test_setup_sh_rejects_python_below_311_before_install(self) -> None:
        self._assert_rejects("sh")

    @unittest.skipUnless(shutil.which("pwsh"), "pwsh unavailable")
    def test_setup_ps1_rejects_python_below_311_before_install(self) -> None:
        self._assert_rejects("ps1")

    def test_setup_sh_accepts_python_311(self) -> None:
        self._assert_accepts("sh")

    @unittest.skipUnless(shutil.which("pwsh"), "pwsh unavailable")
    def test_setup_ps1_accepts_python_311(self) -> None:
        self._assert_accepts("ps1")

    def test_setup_sh_checks_the_python3_it_already_prefers(self) -> None:
        result, calls = _run(
            "sh",
            {"python": "3.12.1", "python3": "3.10.4", "py": "3.12.1"},
            ["--yes"],
        )
        output = result.stdout + result.stderr
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(_message("3.10.4"), output)
        self.assertNotIn("3.12.1", output)
        self.assertNotIn("stub ", calls)

    @unittest.skipUnless(shutil.which("pwsh"), "pwsh unavailable")
    def test_setup_ps1_checks_the_python_it_already_prefers(self) -> None:
        result, calls = _run(
            "ps1",
            {"python": "3.12.1", "python3": "3.10.4", "py": "3.10.4"},
            ACCEPT_ARGS,
        )
        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, msg=output)
        self.assertNotIn(REQUIRED_SENTENCE, output)
        self._assert_not_installed(calls)

    def _assert_rejects(self, kind: str) -> None:
        versions = {"python": "3.10.4", "python3": "3.10.4", "py": "3.10.4"}
        result, calls = _run(kind, versions, ["--yes"])
        output = result.stdout + result.stderr
        self.assertNotEqual(result.returncode, 0)
        lines = [line for line in output.splitlines() if REQUIRED_SENTENCE in line]
        self.assertEqual(lines, [_message("3.10.4")])
        self.assertNotIn("stub ", calls)
        self.assertNotIn("video-use engine", result.stdout)
        self.assertNotIn("uv sync", result.stdout)
        self.assertNotIn("pip install", result.stdout)

    def _assert_accepts(self, kind: str) -> None:
        versions = {"python": "3.11.0", "python3": "3.11.0", "py": "3.11.0"}
        result, calls = _run(kind, versions, ACCEPT_ARGS)
        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, msg=output)
        self.assertNotIn(REQUIRED_SENTENCE, output)
        self.assertIn(VERSION_PROBE, calls)
        self._assert_not_installed(calls)

    def _assert_not_installed(self, calls: str) -> None:
        for marker in ("uv sync", "pip install", "git clone", "npm install", "npx "):
            self.assertNotIn(marker, calls)


if __name__ == "__main__":
    unittest.main()
