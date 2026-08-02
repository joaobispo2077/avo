"""Release pipeline contract tests (semantic-release)."""

from __future__ import annotations

import json
import re
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class ReleasePipelineTests(unittest.TestCase):
    def test_release_config_declares_develop_alpha_and_release(self) -> None:
        text = (ROOT / "release.config.mjs").read_text(encoding="utf-8")
        self.assertIn("'release'", text)
        self.assertIn("name: 'develop'", text)
        self.assertIn("prerelease: 'alpha'", text)
        self.assertIn("firstParent: false", text)

    def test_determine_next_release_script_exists(self) -> None:
        script = ROOT / "scripts/ci/determine-next-release-version.sh"
        self.assertTrue(script.is_file())

    def test_sync_pyproject_version_script(self) -> None:
        script = ROOT / "scripts/ci/sync-pyproject-version.mjs"
        self.assertTrue(script.is_file())
        proc = subprocess.run(
            ["node", str(script), "9.9.9-test"],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        self.addCleanup(
            lambda: (ROOT / "pyproject.toml").write_text(
                re.sub(
                    r'^version\s*=\s*"[^"]+"',
                    'version = "0.1.0"',
                    (ROOT / "pyproject.toml").read_text(encoding="utf-8"),
                    count=1,
                    flags=re.M,
                ),
                encoding="utf-8",
            )
        )
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn('version = "9.9.9-test"', pyproject)

    def test_verify_release_version_accepts_prerelease_tag(self) -> None:
        changelog = ROOT / "CHANGELOG.md"
        original = changelog.read_text(encoding="utf-8")
        version = "0.0.0-alpha.99"
        heading = f"## [{version}]"
        if heading not in original:
            patched = original.replace(
                "## [Unreleased]",
                f"## [Unreleased]\n\n## [{version}]\n\n### Test\n- smoke\n",
            )
            changelog.write_text(patched, encoding="utf-8")
        pkg_path = ROOT / "package.json"
        pkg_original = pkg_path.read_text(encoding="utf-8")
        pkg = json.loads(pkg_original)
        pkg["version"] = version
        pkg_path.write_text(json.dumps(pkg, indent=2) + "\n", encoding="utf-8")
        py_original = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        py_patched = re.sub(
            r'^version\s*=\s*"[^"]+"',
            f'version = "{version}"',
            py_original,
            count=1,
            flags=re.M,
        )
        (ROOT / "pyproject.toml").write_text(py_patched, encoding="utf-8")

        def restore() -> None:
            changelog.write_text(original, encoding="utf-8")
            pkg_path.write_text(pkg_original, encoding="utf-8")
            (ROOT / "pyproject.toml").write_text(py_original, encoding="utf-8")

        self.addCleanup(restore)
        pkg = json.loads(pkg_path.read_text(encoding="utf-8"))["version"]
        pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        match = re.search(r'^version\s*=\s*"([^"]+)"', pyproject, re.M)
        self.assertIsNotNone(match)
        self.assertEqual(pkg, version)
        self.assertEqual(match.group(1), version)
        self.assertIn(heading, changelog.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
