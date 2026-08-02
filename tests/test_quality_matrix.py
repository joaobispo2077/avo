from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class QualityMatrixTests(unittest.TestCase):
    def test_ci_uses_shared_test_runner(self) -> None:
        ci = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
        self.assertIn("run-unit-tests.sh", ci)
        self.assertIn('pip install -e ".[dev]"', ci)

    def test_release_uses_semantic_release_pipeline(self) -> None:
        import json

        release = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
        config = (ROOT / "release.config.mjs").read_text(encoding="utf-8")
        pkg = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
        self.assertIn("workflow_run", release)
        self.assertIn("semantic-release", release)
        self.assertIn("determine-next-release-version.sh", release)
        self.assertIn("GITHUB_REF: refs/heads/", release)
        self.assertIn("GITHUB_HEAD_REF:", release)
        self.assertIn("unset GITHUB_ACTIONS", release)
        self.assertIn("ref: ${{ steps.meta.outputs.branch }}", release)
        self.assertIn("branches:", release)
        self.assertIn("cancel-in-progress: true", release)
        self.assertIn("workflow_run.event == 'push'", release)
        self.assertIn("fetch-tags: true", release)
        self.assertIn("branches:", config)
        self.assertIn("prerelease: 'alpha'", config)
        self.assertIn("semantic-release", pkg.get("devDependencies", {}))
        self.assertIn("release", pkg.get("scripts", {}))

    def test_package_json_uses_pytest(self) -> None:
        import json

        pkg = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
        self.assertIn("not project", pkg["scripts"]["test:unit"])

    def test_pyproject_has_pytest_config(self) -> None:
        text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn("[tool.pytest.ini_options]", text)
        self.assertIn("pytest>=8.0", text)

    def test_agent_docs_reference_pytest(self) -> None:
        agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("pytest", agents)
        instructions = (
            ROOT / ".github" / "instructions" / "testing.instructions.md"
        ).read_text(encoding="utf-8")
        self.assertIn("pytest", instructions)

    def test_run_unit_tests_excludes_project_marker(self) -> None:
        script = (ROOT / "scripts/ci/run-unit-tests.sh").read_text(encoding="utf-8")
        self.assertIn("not project", script)

    def test_package_json_core_vs_projects(self) -> None:
        import json

        pkg = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
        self.assertIn("not project", pkg["scripts"]["test:unit"])
        self.assertEqual(pkg["scripts"]["test:projects"], "pytest tests/projects")

    def test_projects_readme_exists(self) -> None:
        readme = ROOT / "tests/projects/README.md"
        self.assertTrue(readme.is_file())

    def test_quality_audit_doc_exists(self) -> None:
        path = ROOT / "docs/software-quality-audit.md"
        self.assertTrue(path.is_file(), msg="docs/software-quality-audit.md")
        text = path.read_text(encoding="utf-8")
        self.assertIn("tests/projects", text)
        self.assertIn("not project", text)


if __name__ == "__main__":
    unittest.main()
