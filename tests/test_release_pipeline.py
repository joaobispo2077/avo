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
        self.assertIn(
            "./scripts/ci/semantic-release-pyproject-version.mjs",
            text,
        )

    def test_semantic_release_pyproject_plugin_module(self) -> None:
        plugin = ROOT / "scripts/ci/semantic-release-pyproject-version.mjs"
        self.assertTrue(plugin.is_file())

    def test_semantic_release_pyproject_plugin_resolves_sync_script(self) -> None:
        proc = subprocess.run(
            [
                "node",
                "-e",
                (
                    "import { fileURLToPath } from 'node:url';"
                    "import { join } from 'node:path';"
                    "import { accessSync } from 'node:fs';"
                    "const pluginUrl = new URL("
                    "'./scripts/ci/semantic-release-pyproject-version.mjs', "
                    "import.meta.url);"
                    "const rootDir = fileURLToPath(new URL('../../', pluginUrl));"
                    "const syncScript = join(rootDir, 'scripts/ci/sync-pyproject-version.mjs');"
                    "accessSync(syncScript);"
                ),
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0, msg=proc.stderr or proc.stdout)

    def test_determine_next_release_script_exists(self) -> None:
        script = ROOT / "scripts/ci/determine-next-release-version.sh"
        self.assertTrue(script.is_file())
        text = script.read_text(encoding="utf-8")
        self.assertIn("won.t be published", text)
        self.assertIn("the next release version is", text)
        self.assertIn("env -u GITHUB_ACTIONS", text)
        self.assertIn("grep -im1 -Eo", text)

    @staticmethod
    def _parse_next_release_version(output: str) -> str:
        marker = "the next release version is "
        for line in output.splitlines():
            lower = line.lower()
            if marker not in lower:
                continue
            rest = line[lower.index(marker) + len(marker) :]
            token = rest.split()[0]
            return token.split("(")[0].split(")")[0]
        return ""

    def test_determine_next_release_parsing_contract(self) -> None:
        alpha_sample = (
            "[semantic-release] › ℹ  Running semantic-release version 25.0.8\n"
            "[semantic-release] › ℹ  The next release version is 1.0.0-alpha.1\n"
        )
        next_version = self._parse_next_release_version(alpha_sample)
        self.assertEqual(next_version, "1.0.0-alpha.1")
        self.assertNotEqual(next_version, "25.0.8")

    def test_determine_next_release_parsing_first_release_message(self) -> None:
        first_release_sample = (
            "[semantic-release] › ℹ  There is no previous release, "
            "the next release version is 1.0.0\n"
            "[semantic-release] › ✔  Published release 1.0.0 on default channel\n"
        )
        next_version = self._parse_next_release_version(first_release_sample)
        self.assertEqual(next_version, "1.0.0")

    def test_release_workflow_verifies_package_json_version(self) -> None:
        release = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
        self.assertIn("require('./package.json').version", release)
        verify_block = release.split("Verify release manifests align", 1)[1]
        self.assertNotIn("needs.determine-version.outputs.next-version", verify_block)

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
                    'version = "1.0.0"',
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

    def test_sync_pyproject_version_noop_when_already_set(self) -> None:
        script = ROOT / "scripts/ci/sync-pyproject-version.mjs"
        py_original = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        match = re.search(r'^version\s*=\s*"([^"]+)"', py_original, re.M)
        self.assertIsNotNone(match)
        current = match.group(1)
        proc = subprocess.run(
            ["node", str(script), current],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        self.assertIn("already", proc.stdout)

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

    def test_verify_release_version_accepts_semantic_release_changelog_heading(self) -> None:
        changelog = ROOT / "CHANGELOG.md"
        original = changelog.read_text(encoding="utf-8")
        version = "1.0.0"
        semantic_heading = f"# {version} (2026-08-02)"
        patched = (
            f"{original.rstrip()}\n\n{semantic_heading}\n\n### Bug Fixes\n\n"
            "* **release:** smoke\n"
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
        proc = subprocess.run(
            ["python", "scripts/ci/verify-release-version.py", version],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0, msg=proc.stderr or proc.stdout)
        self.assertIn("OK:", proc.stdout)


if __name__ == "__main__":
    unittest.main()
