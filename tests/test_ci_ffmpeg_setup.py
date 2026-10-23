from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.name == "posix", "Linux CI setup")
class FfmpegSetupTests(unittest.TestCase):
    def test_install_uses_main_https_mirror_and_preserves_other_sources(self):
        for scheme in ("http", "https", None):
            with (
                self.subTest(scheme=scheme),
                tempfile.TemporaryDirectory() as directory,
            ):
                work = Path(directory)
                mirrors = work / "apt-mirrors.txt"
                other = "https://security.ubuntu.com/ubuntu\n"
                if scheme:
                    mirrors.write_text(
                        f"{scheme}://azure.archive.ubuntu.com/ubuntu\n" + other
                    )
                installed = work / "installed"
                calls = work / "calls"
                commands = {
                    "sudo": 'exec "$@"',
                    "apt-get": f'echo "$*" >> "{calls}"\ntouch "{installed}"',
                    "ffmpeg": f'test -f "{installed}"',
                    "ffprobe": f'test -f "{installed}"',
                }
                for name, body in commands.items():
                    executable = work / name
                    executable.write_text("#!/bin/bash\n" + body + "\n")
                    executable.chmod(0o755)
                script = work / "setup.sh"
                script.write_text(
                    (ROOT / "scripts/ci/ensure-ffmpeg.sh")
                    .read_text()
                    .replace("/etc/apt/apt-mirrors.txt", str(mirrors))
                )
                subprocess.run(
                    ["bash", str(script)],
                    env={**os.environ, "PATH": f"{work}:{os.environ['PATH']}"},
                    check=True,
                    capture_output=True,
                    text=True,
                )
                if scheme:
                    self.assertEqual(
                        mirrors.read_text(),
                        "https://archive.ubuntu.com/ubuntu\n" + other,
                    )
                else:
                    self.assertFalse(mirrors.exists())
                self.assertIn("update", calls.read_text())
                self.assertIn(
                    "install -y --no-install-recommends ffmpeg", calls.read_text()
                )


if __name__ == "__main__":
    unittest.main()
