from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from itertools import product
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.name == "posix", "Linux CI setup")
class FfmpegSetupTests(unittest.TestCase):
    def _run_installer(self, work, mirrors, failure=""):
        installed = work / "installed"
        calls = work / "calls"
        commands = {
            "sudo": 'exec "$@"',
            "apt-get": f"""
printf '%s\n' "$*" >> "{calls}"
for option; do
  case "$option" in
    update|install) operation="$option"; break ;;
  esac
done
if [[ "$AVO_TEST_APT_FAILURE" == always ]]; then
  exit 100
fi
if [[ "$operation" == "$AVO_TEST_APT_FAILURE" && ! -f "{work / "failed"}" ]]; then
  touch "{work / "failed"}"
  exit 100
fi
if [[ "$operation" == install ]]; then
  touch "{installed}"
fi
""",
            "ffmpeg": f'test -f "{installed}"',
            "ffprobe": f'test -f "{installed}"',
        }
        for name, body in commands.items():
            executable = work / name
            executable.write_text("#!/bin/bash\n" + body + "\n", encoding="utf-8")
            executable.chmod(0o755)
        script = work / "setup.sh"
        script.write_text(
            (ROOT / "scripts/ci/ensure-ffmpeg.sh")
            .read_text(encoding="utf-8")
            .replace("/etc/apt/apt-mirrors.txt", str(mirrors)),
            encoding="utf-8",
        )
        result = subprocess.run(
            ["bash", str(script)],
            env={
                **os.environ,
                "PATH": f"{work}:{os.environ['PATH']}",
                "AVO_TEST_APT_FAILURE": failure,
            },
            check=False,
            capture_output=True,
            text=True,
        )
        attempts = [
            "update" if "update" in line else "install"
            for line in calls.read_text(encoding="utf-8").splitlines()
        ]
        return result, attempts

    def test_initial_success_preserves_the_runner_mirror(self):
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            mirrors = work / "apt-mirrors.txt"
            original = "http://azure.archive.ubuntu.com/ubuntu\n"
            mirrors.write_text(original, encoding="utf-8")

            result, attempts = self._run_installer(work, mirrors)

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(attempts, ["update", "install"])
            self.assertEqual(mirrors.read_text(encoding="utf-8"), original)

    def test_failed_update_retries_with_main_https_mirror_and_preserves_other_sources(
        self,
    ):
        hosts = (
            "azure.archive.ubuntu.com",
            "us-east-2.ec2.archive.ubuntu.com",
            "archive.ubuntu.com",
        )
        for scheme, host in [*product(("http", "https"), hosts), (None, None)]:
            case = self.subTest(scheme=scheme, host=host)
            with case, tempfile.TemporaryDirectory() as directory:
                work = Path(directory)
                mirrors = work / "apt-mirrors.txt"
                other = (
                    "https://security.ubuntu.com/ubuntu\n"
                    "https://ports.ubuntu.com/ubuntu-ports\n"
                    "https://example.invalid/ubuntu\n"
                )
                if scheme:
                    mirrors.write_text(
                        f"{scheme}://{host}/ubuntu\n" + other, encoding="utf-8"
                    )
                result, attempts = self._run_installer(work, mirrors, "update")
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(attempts, ["update", "update", "install"])
                if scheme:
                    self.assertEqual(
                        mirrors.read_text(encoding="utf-8"),
                        "https://archive.ubuntu.com/ubuntu\n" + other,
                    )
                else:
                    self.assertFalse(mirrors.exists())

    def test_failed_install_refreshes_indexes_before_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            result, attempts = self._run_installer(work, work / "absent", "install")

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(attempts, ["update", "install", "update", "install"])
            calls = (work / "calls").read_text(encoding="utf-8")
            self.assertIn("update --error-on=any", calls)
            self.assertIn("install -y --no-install-recommends ffmpeg", calls)

    def test_second_failure_exits_without_further_attempts(self):
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            result, attempts = self._run_installer(work, work / "absent", "always")

            self.assertEqual(result.returncode, 100, result.stderr)
            self.assertEqual(attempts, ["update", "update"])


if __name__ == "__main__":
    unittest.main()
