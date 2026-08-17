from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Locked against plan/spec + task-003 npm umbrella names.
EXPECTED_QUALITY_SCRIPTS = (
    "quality",
    "quality:lint",
    "quality:format",
    "test:coverage",
    "quality:deps",
    "quality:complexity",
    "quality:deadcode",
    "quality:duplication",
    "quality:architecture",
    "quality:mutation",
    "quality:tree",
    "quality:dep-graph",
)

# Skeletons land in task-005; matrix asserts file presence.
# Spec v1.4: fast quality lives in ci.yml — not a separate quality.yml.
EXPECTED_QUALITY_WORKFLOWS = (
    ".github/workflows/ci.yml",
    ".github/workflows/mutation-full.yml",
    ".github/workflows/size-signal.yml",
    ".github/workflows/dependency-graph.yml",
    ".github/workflows/watch-skill-smoke.yml",
    ".github/workflows/quality-toolchain-smoke.yml",
)

# Concept labels that must appear in the software-quality dashboard stub.
EXPECTED_QUALITY_CONCEPTS = (
    "Static lint / format",
    "Type safety",
    "Test coverage floor",
    "Complexity",
    "Dependency security audit",
    "Lock / install reproducibility",
    "Dependency tree health",
    "Dead code",
    "Duplication",
    "Architecture / import boundaries",
    "Visual dependency graph",
    "Mutation testing",
    "Artifact / install weight",
)


class QualityMatrixTests(unittest.TestCase):
    def test_ci_uses_shared_test_runner(self) -> None:
        ci = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
        self.assertIn("run-unit-tests.sh", ci)
        self.assertIn("uv sync --frozen --extra dev", ci)
        self.assertIn("astral-sh/setup-uv", ci)

    def test_ci_quality_and_unit_use_uv_frozen_sync(self) -> None:
        """task-012 / FR-6: quality + unit jobs use locked uv sync (not unlocked pip)."""
        ci = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
        self.assertIn("astral-sh/setup-uv", ci)
        self.assertGreaterEqual(
            ci.count("uv sync --frozen --extra dev"),
            2,
            msg="repo-unit-tests and software-quality must both uv sync --frozen",
        )
        self.assertNotIn(
            'pip install -e ".[dev]"',
            ci,
            msg='quality/unit CI must not use unlocked pip install -e ".[dev]"',
        )
        # Gate 2 may still use unlocked editable install without extras.
        self.assertIn("pip install -e .", ci)

    def test_release_uses_semantic_release_pipeline(self) -> None:
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
        self.assertIn("workflow_run.event || github.event_name", release)
        self.assertIn("workflow_run.event == 'push'", release)
        self.assertIn("fetch-tags: true", release)
        self.assertIn("branches:", config)
        self.assertIn("'release'", config)
        self.assertNotIn("prerelease:", config)
        self.assertIn("semantic-release", pkg.get("devDependencies", {}))
        self.assertIn("release", pkg.get("scripts", {}))

    def test_package_json_uses_pytest(self) -> None:
        pkg = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
        self.assertIn("not project", pkg["scripts"]["test:unit"])

    def test_pyproject_has_pytest_config(self) -> None:
        text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn("[tool.pytest.ini_options]", text)
        self.assertIn("pytest>=8.0", text)

    def test_agent_docs_reference_pytest(self) -> None:
        agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("pytest", agents)
        self.assertIn("npm run quality", agents)
        self.assertIn("Software quality", agents)
        instructions = (
            ROOT / ".github" / "instructions" / "testing.instructions.md"
        ).read_text(encoding="utf-8")
        self.assertIn("pytest", instructions)
        self.assertIn("npm run quality", instructions)

    def test_run_unit_tests_excludes_project_marker(self) -> None:
        script = (ROOT / "scripts/ci/run-unit-tests.sh").read_text(encoding="utf-8")
        self.assertIn("not project", script)

    def test_package_json_core_vs_projects(self) -> None:
        pkg = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
        self.assertIn("not project", pkg["scripts"]["test:unit"])
        self.assertIn("pytest", pkg["scripts"]["test:projects"])
        self.assertIn("tests/projects", pkg["scripts"]["test:projects"])
        self.assertIn("uv run --frozen --extra dev", pkg["scripts"]["test:projects"])

    def test_projects_readme_exists(self) -> None:
        readme = ROOT / "tests/projects/README.md"
        self.assertTrue(readme.is_file())

    def test_quality_audit_doc_exists(self) -> None:
        path = ROOT / "docs/software-quality-audit.md"
        self.assertTrue(path.is_file(), msg="docs/software-quality-audit.md")
        text = path.read_text(encoding="utf-8")
        self.assertIn("tests/projects", text)
        self.assertIn("not project", text)

    def test_package_json_declares_quality_scripts(self) -> None:
        pkg = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
        scripts = pkg.get("scripts", {})
        missing = [name for name in EXPECTED_QUALITY_SCRIPTS if name not in scripts]
        self.assertEqual(
            missing,
            [],
            msg=f"package.json missing quality scripts (task-003): {missing}",
        )

    def test_quality_docs_list_software_quality_concepts(self) -> None:
        audit = (ROOT / "docs/software-quality-audit.md").read_text(encoding="utf-8")
        ci = (ROOT / "docs/ci.md").read_text(encoding="utf-8")
        self.assertIn("Software quality", audit)
        self.assertIn("Software quality", ci)
        self.assertIn("npm run quality", audit)
        self.assertIn("ci.yml", audit)
        for concept in EXPECTED_QUALITY_CONCEPTS:
            self.assertIn(
                concept,
                audit,
                msg=f"docs/software-quality-audit.md missing concept: {concept}",
            )

    def test_quality_docs_list_expected_workflows(self) -> None:
        audit = (ROOT / "docs/software-quality-audit.md").read_text(encoding="utf-8")
        ci = (ROOT / "docs/ci.md").read_text(encoding="utf-8")
        for rel in EXPECTED_QUALITY_WORKFLOWS:
            name = Path(rel).name
            self.assertIn(name, audit, msg=f"audit doc missing workflow {name}")
            self.assertIn(name, ci, msg=f"ci.md missing workflow {name}")
        self.assertNotIn("quality.yml", audit)
        self.assertNotIn("quality.yml", ci)

    def test_quality_lives_in_ci_yml(self) -> None:
        """Software quality is a ci.yml job; no separate quality.yml (spec v1.4)."""
        missing = [
            rel for rel in EXPECTED_QUALITY_WORKFLOWS if not (ROOT / rel).is_file()
        ]
        self.assertEqual(missing, [], msg=f"missing workflows: {missing}")
        self.assertFalse(
            (ROOT / ".github/workflows/quality.yml").is_file(),
            msg="quality.yml must not exist — software quality lives in ci.yml",
        )
        ci = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
        self.assertIn("software-quality", ci)
        self.assertIn("Software quality", ci)

    def test_ci_software_quality_runs_lint_format_fail_immediately(self) -> None:
        """task-008: software-quality job runs lint/format and must not soft-exit."""
        ci = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
        # Job must invoke the shared CI scripts (same as local quality:lint/format).
        self.assertIn("quality-lint.sh", ci)
        self.assertIn("quality-format.sh", ci)
        # Soft placeholder must be gone (fail-immediately posture).
        self.assertNotIn("soft until enablement", ci.lower())
        self.assertNotIn("non-failing until enablement", ci.lower())
        self.assertNotIn("Status: soft", ci)
        self.assertNotIn("exit 0", ci)

        for rel in (
            "scripts/ci/quality-lint.sh",
            "scripts/ci/quality-format.sh",
            "scripts/ci/quality.sh",
        ):
            path = ROOT / rel
            self.assertTrue(path.is_file(), msg=f"missing {rel}")
            text = path.read_text(encoding="utf-8")
            self.assertIn("set -euo pipefail", text)

        pkg = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
        scripts = pkg.get("scripts", {})
        self.assertIn("quality:lint", scripts)
        self.assertIn("quality:format", scripts)
        self.assertIn("ruff check", scripts["quality:lint"])
        self.assertIn("eslint", scripts["quality:lint"])
        self.assertIn("ruff format --check", scripts["quality:format"])
        self.assertIn("prettier --check", scripts["quality:format"])
        # Umbrella runs lint/format first so violations fail npm run quality.
        quality = scripts.get("quality", "")
        self.assertIn("quality:lint", quality)
        self.assertIn("quality:format", quality)
        self.assertTrue(
            quality.index("quality:lint") < quality.index("quality:format"),
            msg="quality umbrella must run lint before format",
        )

    def test_ci_software_quality_enforces_coverage_fail_under(self) -> None:
        """task-009: coverage floor wired in pyproject, npm, run-coverage.sh, ci.yml."""
        ci = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
        self.assertIn("run-coverage.sh", ci)
        self.assertIn("Software quality — coverage", ci)

        pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn("[tool.coverage.report]", pyproject)
        self.assertIn("fail_under = 68", pyproject)

        pkg = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
        coverage_script = pkg["scripts"]["test:coverage"]
        self.assertIn("--cov-fail-under=68", coverage_script)
        self.assertIn("quality", pkg["scripts"]["quality"])
        self.assertIn("test:coverage", pkg["scripts"]["quality"])

        runner = (ROOT / "scripts/ci/run-coverage.sh").read_text(encoding="utf-8")
        self.assertIn("set -euo pipefail", runner)
        self.assertIn("--cov-fail-under", runner)
        self.assertIn("COV_FAIL_UNDER:-68", runner)

        audit = (ROOT / "docs/software-quality-audit.md").read_text(encoding="utf-8")
        self.assertIn("68", audit)
        self.assertIn("run-coverage.sh", audit)
        self.assertFalse(
            (ROOT / ".github/workflows/quality.yml").is_file(),
            msg="separate Gate 3 workflow must not exist — coverage gate lives in ci.yml",
        )

    def test_ci_software_quality_enforces_complexity_xenon(self) -> None:
        """task-010: xenon max-absolute B + allowlist wired in npm, scripts, ci.yml."""
        ci = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
        self.assertIn("quality-complexity.sh", ci)
        self.assertNotIn("quality.yml", ci)

        pkg = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
        complexity = pkg["scripts"]["quality:complexity"]
        self.assertIn("check_complexity.py", complexity)
        self.assertIn("quality:complexity", pkg["scripts"]["quality"])

        runner = (ROOT / "scripts/ci/quality-complexity.sh").read_text(encoding="utf-8")
        self.assertIn("set -euo pipefail", runner)
        self.assertIn("check_complexity.py", runner)

        checker = (ROOT / "scripts/ci/check_complexity.py").read_text(encoding="utf-8")
        self.assertIn('MAX_ABSOLUTE = "B"', checker)
        self.assertIn("complexity-allowlist.json", checker)

        allowlist_path = ROOT / "scripts/ci/complexity-allowlist.json"
        self.assertTrue(allowlist_path.is_file())
        allowlist = json.loads(allowlist_path.read_text(encoding="utf-8"))
        self.assertEqual(allowlist.get("max_absolute"), "B")
        self.assertGreater(len(allowlist.get("blocks", [])), 0)
        for entry in allowlist["blocks"]:
            self.assertTrue(entry.get("reason"), msg=f"missing reason: {entry}")
            self.assertIn("complexity", entry)
            self.assertIn("path", entry)
            self.assertIn("name", entry)

        pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn('"C901"', pyproject)
        self.assertIn("max-complexity = 31", pyproject)
        self.assertIn("check_complexity.py", pyproject)

        audit = (ROOT / "docs/software-quality-audit.md").read_text(encoding="utf-8")
        self.assertIn("xenon", audit.lower())
        self.assertIn("quality-complexity.sh", audit)
        self.assertIn("complexity-allowlist.json", audit)
        self.assertIn("C901", audit)
        self.assertFalse(
            (ROOT / ".github/workflows/quality.yml").is_file(),
            msg="quality.yml must not exist — complexity gate lives in ci.yml",
        )

    def test_ci_software_quality_enforces_deps_audit_fail_immediately(self) -> None:
        """task-011: pip-audit + npm audit high+ wired in npm, scripts, ci.yml."""
        ci = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
        self.assertIn("quality-deps.sh", ci)
        self.assertIn("Software quality — deps", ci)
        self.assertNotIn("Deps enable in later tasks", ci)
        self.assertNotIn("quality.yml", ci)

        pkg = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
        deps = pkg["scripts"]["quality:deps"]
        self.assertIn("pip-audit", deps)
        self.assertIn("check_npm_audit.py", deps)
        self.assertIn("quality:deps", pkg["scripts"]["quality"])
        self.assertIn("overrides", pkg)
        self.assertIn(
            "semantic-release-npm-stub",
            pkg["overrides"].get("@semantic-release/npm", ""),
        )
        self.assertTrue(
            (ROOT / "scripts/ci/semantic-release-npm-stub/package.json").is_file(),
            msg="stub package required to avoid nested npm CLI audit failures",
        )

        runner = (ROOT / "scripts/ci/quality-deps.sh").read_text(encoding="utf-8")
        self.assertIn("set -euo pipefail", runner)
        self.assertIn("uv run --frozen --extra dev pip-audit --skip-editable", runner)
        self.assertIn("check_npm_audit.py", runner)
        self.assertIn("uv run --frozen --extra dev pip-audit --skip-editable", deps)

        checker = (ROOT / "scripts/ci/check_npm_audit.py").read_text(encoding="utf-8")
        self.assertIn("deps-audit-allowlist.json", checker)
        self.assertIn("FAIL_SEVERITIES", checker)

        allowlist = json.loads(
            (ROOT / "scripts/ci/deps-audit-allowlist.json").read_text(encoding="utf-8")
        )
        self.assertIn("npm", allowlist)
        self.assertIn("pip", allowlist)
        for entry in allowlist["npm"]["advisory_ids"]:
            self.assertTrue(str(entry.get("id", "")).startswith("GHSA-"))
            self.assertTrue(entry.get("reason"))
            self.assertTrue(entry.get("package"))
            self.assertTrue(entry.get("expires"))

        # Debt fix: stub out @semantic-release/npm so the vulnerable bundled npm CLI
        # is not installed (release uses semantic-release-package-version.mjs instead).
        stub = ROOT / "scripts/ci/semantic-release-npm-stub/package.json"
        self.assertTrue(stub.is_file())
        overrides = pkg.get("overrides") or {}
        self.assertIn("@semantic-release/npm", overrides)
        self.assertIn(
            "semantic-release-npm-stub", str(overrides["@semantic-release/npm"])
        )
        self.assertNotIn(
            "@semantic-release/npm",
            (ROOT / "release.config.mjs").read_text(encoding="utf-8"),
        )
        self.assertIn(
            "semantic-release-package-version.mjs",
            (ROOT / "release.config.mjs").read_text(encoding="utf-8"),
        )

        pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn("pip-audit", pyproject)

        audit = (ROOT / "docs/software-quality-audit.md").read_text(encoding="utf-8")
        self.assertIn("quality-deps.sh", audit)
        self.assertIn("pip-audit", audit)
        self.assertIn("check_npm_audit.py", audit)
        self.assertIn("deps-audit-allowlist.json", audit)
        self.assertFalse(
            (ROOT / ".github/workflows/quality.yml").is_file(),
            msg="quality.yml must not exist — deps gate lives in ci.yml",
        )

    def test_ci_software_quality_is_blocking_phase1_umbrella(self) -> None:
        """task-013: Phase-1 fast gates block PR path; document required check name."""
        ci = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
        self.assertIn("pull_request:", ci)
        self.assertIn("software-quality:", ci)
        # Exact GitHub Actions check name operators must require in branch protection.
        self.assertRegex(
            ci,
            r"(?m)^\s*name:\s*Software quality\s*$",
            msg="job display name must be exactly 'Software quality'",
        )
        # Gate 2 must wait on software-quality (same pattern as unit tests → merge readiness).
        self.assertIn(
            "needs: [prerequisites-gate, repo-unit-tests, software-quality]",
            ci,
        )
        quality_block = ci.split("software-quality:", 1)[1].split("usability-gate:", 1)[
            0
        ]
        # Fail-immediately: no soft/continue-on-error escape hatch on the umbrella.
        self.assertNotIn("continue-on-error:", quality_block)
        quality_lower = quality_block.lower()
        self.assertNotIn("soft until enablement", quality_lower)
        self.assertNotIn("non-failing until enablement", quality_lower)
        self.assertNotIn("status: soft", quality_lower)
        # All Phase-1 fast gate scripts under the umbrella job.
        for script in (
            "quality-lint.sh",
            "quality-format.sh",
            "run-coverage.sh",
            "quality-complexity.sh",
            "quality-deps.sh",
        ):
            self.assertIn(
                script,
                quality_block,
                msg=f"Phase-1 gate missing from software-quality: {script}",
            )
        self.assertFalse(
            (ROOT / ".github/workflows/quality.yml").is_file(),
            msg="separate Gate 3 workflow must not exist — quality lives in ci.yml",
        )
        self.assertNotIn("quality.yml", ci)

        docs_ci = (ROOT / "docs/ci.md").read_text(encoding="utf-8")
        self.assertIn("Software quality", docs_ci)
        self.assertIn("branch protection", docs_ci.lower())
        self.assertIn("`Software quality`", docs_ci)
        self.assertIn("software-quality", docs_ci)
        # Operator recipe must include the exact check context for rulesets.
        self.assertIn('"context":"Software quality"', docs_ci)

        audit = (ROOT / "docs/software-quality-audit.md").read_text(encoding="utf-8")
        self.assertIn("Software quality", audit)
        self.assertIn("blocking", audit.lower())
        self.assertIn("task-013", audit)

        # Local umbrella still mirrors CI Phase-1 set.
        pkg = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
        quality = pkg["scripts"]["quality"]
        for part in (
            "quality:lint",
            "quality:format",
            "test:coverage",
            "quality:complexity",
            "quality:deps",
            "quality:deadcode",
            "quality:architecture",
            "quality:tree",
        ):
            self.assertIn(part, quality)

    def test_ci_software_quality_enforces_deadcode_vulture(self) -> None:
        """task-014: vulture dead-code gate wired in npm, scripts, ci.yml."""
        ci = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
        self.assertIn("quality-deadcode.sh", ci)
        self.assertIn("Software quality — deadcode", ci)

        pkg = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
        deadcode = pkg["scripts"]["quality:deadcode"]
        self.assertIn("check_deadcode.py", deadcode)

        runner = (ROOT / "scripts/ci/quality-deadcode.sh").read_text(encoding="utf-8")
        self.assertIn("set -euo pipefail", runner)
        self.assertIn("check_deadcode.py", runner)
        self.assertIn("uv run --frozen --extra dev", runner)

        checker = (ROOT / "scripts/ci/check_deadcode.py").read_text(encoding="utf-8")
        self.assertIn("deadcode-allowlist.json", checker)
        self.assertIn("DEFAULT_MIN_CONFIDENCE = 60", checker)
        self.assertIn("intentionally absent", checker.lower())

        allowlist = json.loads(
            (ROOT / "scripts/ci/deadcode-allowlist.json").read_text(encoding="utf-8")
        )
        self.assertEqual(allowlist.get("min_confidence"), 60)
        self.assertGreater(
            len(allowlist.get("items", [])),
            0,
            msg="deadcode-allowlist.json must document dynamic/CLI entrypoints",
        )
        for entry in allowlist["items"]:
            self.assertTrue(entry.get("path"))
            self.assertTrue(entry.get("name"))
            self.assertTrue(entry.get("reason"))

        docs_ci = (ROOT / "docs/ci.md").read_text(encoding="utf-8")
        self.assertIn("quality-deadcode.sh", docs_ci)
        self.assertIn("deadcode-allowlist.json", docs_ci)

        umbrella = (ROOT / "scripts/ci/quality.sh").read_text(encoding="utf-8")
        self.assertIn("quality-deadcode.sh", umbrella)

        audit = (ROOT / "docs/software-quality-audit.md").read_text(encoding="utf-8")
        self.assertIn("deadcode-allowlist.json", audit)
        self.assertIn("check_deadcode.py", audit)
        self.assertFalse(
            (ROOT / ".github/workflows/quality.yml").is_file(),
            msg="separate Gate 3 workflow must not exist — deadcode lives in ci.yml",
        )

    def test_ci_software_quality_enforces_duplication_jscpd(self) -> None:
        """task-015: jscpd duplication gate wired in npm, scripts, ci.yml."""
        ci = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
        self.assertIn("quality-duplication.sh", ci)
        self.assertIn("Software quality — duplication", ci)

        pkg = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
        duplication = pkg["scripts"]["quality:duplication"]
        self.assertIn("jscpd", duplication)
        self.assertIn(".jscpd.json", duplication)

        runner = (ROOT / "scripts/ci/quality-duplication.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn("set -euo pipefail", runner)
        self.assertIn("jscpd", runner)
        self.assertIn(".jscpd.json", runner)

        config = json.loads((ROOT / ".jscpd.json").read_text(encoding="utf-8"))
        self.assertEqual(config.get("threshold"), 2)
        self.assertIn("src/avo", config.get("path", []))

        audit = (ROOT / "docs/software-quality-audit.md").read_text(encoding="utf-8")
        self.assertIn(".jscpd.json", audit)
        self.assertIn("quality-duplication.sh", audit)
        self.assertFalse(
            (ROOT / ".github/workflows/quality.yml").is_file(),
            msg="separate Gate 3 workflow must not exist — duplication lives in ci.yml",
        )

    def test_ci_software_quality_enforces_architecture_import_linter(self) -> None:
        """task-016: import-linter contracts wired in npm, scripts, ci.yml."""
        ci = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
        self.assertIn("quality-architecture.sh", ci)
        self.assertIn("Software quality — architecture", ci)

        pkg = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
        architecture = pkg["scripts"]["quality:architecture"]
        self.assertIn("lint-imports", architecture)
        self.assertIn(".importlinter", architecture)
        self.assertIn("quality:architecture", pkg["scripts"]["quality"])

        runner = (ROOT / "scripts/ci/quality-architecture.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn("set -euo pipefail", runner)
        self.assertIn("lint-imports", runner)
        self.assertIn(".importlinter", runner)
        self.assertIn("uv run --frozen --extra dev", runner)

        config = (ROOT / ".importlinter").read_text(encoding="utf-8")
        self.assertIn("root_package = avo", config)
        self.assertIn("helpers/", config)
        for contract in (
            "adapters-not-cli-mcp",
            "timeline-not-cli-mcp",
            "core-not-mcp-tools",
            "domain-not-adapters",
        ):
            self.assertIn(
                f"[importlinter:contract:{contract}]",
                config,
                msg=f"missing import-linter contract {contract}",
            )
        self.assertIn("avo.mcp.tools", config)
        self.assertIn("avo.adapters", config)
        self.assertIn("ignore_imports", config)

        pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn("import-linter", pyproject)

        umbrella = (ROOT / "scripts/ci/quality.sh").read_text(encoding="utf-8")
        self.assertIn("quality-architecture.sh", umbrella)

        audit = (ROOT / "docs/software-quality-audit.md").read_text(encoding="utf-8")
        self.assertIn(".importlinter", audit)
        self.assertIn("quality-architecture.sh", audit)
        self.assertIn("helpers/", audit)

        docs_ci = (ROOT / "docs/ci.md").read_text(encoding="utf-8")
        self.assertIn("quality-architecture.sh", docs_ci)
        self.assertIn(".importlinter", docs_ci)
        self.assertFalse(
            (ROOT / ".github/workflows/quality.yml").is_file(),
            msg="separate Gate 3 workflow must not exist — architecture lives in ci.yml",
        )

    def test_ci_software_quality_enforces_tree_health_find_dupes(self) -> None:
        """task-017: npm find-dupes tree-health wired in npm, scripts, ci.yml."""
        ci = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
        self.assertIn("quality-tree.sh", ci)
        self.assertIn("Software quality — tree", ci)

        pkg = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
        tree = pkg["scripts"]["quality:tree"]
        self.assertIn("npm find-dupes", tree)
        self.assertIn("--ignore-scripts", tree)

        runner = (ROOT / "scripts/ci/quality-tree.sh").read_text(encoding="utf-8")
        self.assertIn("set -euo pipefail", runner)
        self.assertIn("npm find-dupes", runner)
        self.assertIn("--ignore-scripts", runner)
        self.assertIn("report-only", runner)

        audit = (ROOT / "docs/software-quality-audit.md").read_text(encoding="utf-8")
        self.assertIn("quality-tree.sh", audit)
        self.assertIn("find-dupes", audit)

        docs_ci = (ROOT / "docs/ci.md").read_text(encoding="utf-8")
        self.assertIn("quality-tree.sh", docs_ci)
        self.assertIn("find-dupes", docs_ci)
        self.assertFalse(
            (ROOT / ".github/workflows/quality.yml").is_file(),
            msg="separate Gate 3 workflow must not exist — tree health lives in ci.yml",
        )

    def test_ci_light_mutation_and_weekly_full(self) -> None:
        """task-018/019/027: dual mutation — light in ci.yml, full weekly workflow."""
        ci = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
        self.assertIn("run-mutation-light.sh", ci)
        self.assertIn("Mutation tests (light)", ci)
        self.assertNotIn("continue-on-error:", ci.split("mutation-light:", 1)[1][:800])

        full = (ROOT / ".github/workflows/mutation-full.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("run-mutation.sh", full)
        self.assertIn("uv sync --frozen --extra dev", full)
        self.assertNotIn("soft stub", full.lower())

        cfg = json.loads(
            (ROOT / "scripts/ci/mutation-config.json").read_text(encoding="utf-8")
        )
        self.assertIn("light", cfg)
        self.assertIn("full", cfg)

        pkg = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
        self.assertIn("quality-mutation.sh", pkg["scripts"]["quality:mutation"])

        pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn("[tool.mutmut]", pyproject)
        self.assertIn("src/avo/mcp", pyproject)

        audit = (ROOT / "docs/software-quality-audit.md").read_text(encoding="utf-8")
        self.assertIn("light/PR", audit)
        self.assertIn("full/weekly", audit)
        docs_ci = (ROOT / "docs/ci.md").read_text(encoding="utf-8")
        self.assertIn("Mutation tests (light)", docs_ci)

    def test_size_signal_uses_shared_script(self) -> None:
        """task-020: size-signal.yml calls scripts/ci/size-signal.sh."""
        workflow = (ROOT / ".github/workflows/size-signal.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("scripts/ci/size-signal.sh", workflow)
        self.assertIn("non-blocking", workflow.lower())
        script = (ROOT / "scripts/ci/size-signal.sh").read_text(encoding="utf-8")
        self.assertIn("npm pack --dry-run", script)
        self.assertIn("exit 0", script)

    def test_weekly_dependency_graph_workflow(self) -> None:
        """task-026 / FR-12: visual graph is a dedicated weekly workflow."""
        workflow = (ROOT / ".github/workflows/dependency-graph.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("run-dep-graph.sh", workflow)
        self.assertIn("retention-days: 14", workflow)
        pkg = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
        self.assertIn("run-dep-graph.sh", pkg["scripts"]["quality:dep-graph"])
        ci = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
        self.assertNotIn("run-dep-graph.sh", ci)

    def test_toolchain_smokes_are_dedicated_workflows(self) -> None:
        """task-028 / FR-13: watch-skill + quality CLI smokes, not PR fast path."""
        watch = (ROOT / ".github/workflows/watch-skill-smoke.yml").read_text(
            encoding="utf-8"
        )
        tools = (ROOT / ".github/workflows/quality-toolchain-smoke.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("watch-skill-smoke.sh", watch)
        self.assertIn("quality-toolchain-smoke.sh", tools)
        self.assertIn("retention-days: 7", watch)
        self.assertIn("retention-days: 7", tools)
        ci = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
        self.assertNotIn("watch-skill-smoke.sh", ci)
        self.assertNotIn("quality-toolchain-smoke.sh", ci)


if __name__ == "__main__":
    unittest.main()
