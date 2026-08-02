"""Tests for src/avo/update.py."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from avo import update  # noqa: E402


class UpdateProviderTests(unittest.TestCase):
    def test_list_provider_workspaces_excludes_template(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            providers = root / "providers"
            (providers / "_template").mkdir(parents=True)
            (providers / "bishop").mkdir()
            (providers / "bishop" / "avo.provider.json").write_text("{}", encoding="utf-8")
            (providers / "other").mkdir()
            (providers / "other" / "avo.provider.json").write_text("{}", encoding="utf-8")
            slugs = {p.slug for p in update.list_provider_workspaces(root)}
            self.assertEqual(slugs, {"bishop", "other"})

    def test_verify_providers_preserved_detects_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            before = [
                update.ProviderWorkspace(
                    slug="bishop",
                    path=root / "providers" / "bishop",
                    manifest=root / "providers" / "bishop" / "avo.provider.json",
                )
            ]
            (root / "providers" / "bishop").mkdir(parents=True)
            (root / "providers" / "bishop" / "avo.provider.json").write_text(
                "{}", encoding="utf-8"
            )
            after = [
                update.ProviderWorkspace(
                    slug="bishop",
                    path=root / "providers" / "bishop",
                    manifest=root / "providers" / "bishop" / "avo.provider.json",
                ),
                update.ProviderWorkspace(
                    slug="other",
                    path=root / "providers" / "other",
                    manifest=root / "providers" / "other" / "avo.provider.json",
                ),
            ]
            self.assertEqual(update.verify_providers_preserved(before, before), [])
            errors = update.verify_providers_preserved(before, [])
            self.assertTrue(any("bishop" in e for e in errors))

    def test_verify_providers_preserved_detects_missing_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "p" / "bishop").mkdir(parents=True)
            manifest = root / "p" / "bishop" / "avo.provider.json"
            manifest.write_text("{}", encoding="utf-8")
            before = [
                update.ProviderWorkspace(
                    slug="bishop",
                    path=root / "p" / "bishop",
                    manifest=manifest,
                )
            ]
            after = [
                update.ProviderWorkspace(
                    slug="bishop",
                    path=root / "p" / "bishop",
                    manifest=root / "p" / "bishop" / "avo.provider.json",
                )
            ]
            self.assertEqual(update.verify_providers_preserved(before, after), [])
            manifest.unlink()
            missing_manifest_after = [
                update.ProviderWorkspace(
                    slug="bishop",
                    path=root / "p" / "bishop",
                    manifest=manifest,
                )
            ]
            errors = update.verify_providers_preserved(before, missing_manifest_after)
            self.assertTrue(any("manifest missing" in e for e in errors))


class UpdatePreflightTests(unittest.TestCase):
    def test_run_update_refuses_non_git_repo(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "providers" / "bishop").mkdir(parents=True)
            report = update.run_update(yes=True, root=root, dry_run=True)
            self.assertFalse(report.pulled)
            self.assertTrue(any("git clone" in m for m in report.messages))

    def test_run_update_check_only_does_not_pull(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._init_git(root)
            (root / "providers" / "bishop").mkdir(parents=True)
            (root / "providers" / "bishop" / "avo.provider.json").write_text(
                "{}", encoding="utf-8"
            )
            with patch.object(update, "git_fetch", return_value=True), patch.object(
                update,
                "git_upstream_status",
                return_value=update.GitStatus("main", 2, 0, "origin/main", True),
            ):
                report = update.run_update(check_only=True, root=root)
            self.assertTrue(report.check_only)
            self.assertFalse(report.pulled)

    def test_run_update_dry_run_apply_plans_pull_and_sync(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._init_git(root)
            (root / "bin").mkdir()
            (root / "bin" / "install.cjs").write_text("// stub", encoding="utf-8")
            (root / "scripts").mkdir()
            (root / "scripts" / "setup.sh").write_text("# stub", encoding="utf-8")
            with patch.object(update, "git_fetch", return_value=True), patch.object(
                update,
                "git_upstream_status",
                return_value=update.GitStatus("main", 1, 0, "origin/main", True),
            ), patch.object(update, "is_git_repo", return_value=True), patch.object(
                update, "tracked_tree_dirty", return_value=False
            ):
                report = update.run_update(yes=True, dry_run=True, root=root)
            self.assertTrue(report.pulled)
            joined = "\n".join(report.messages)
            self.assertIn("install.cjs", joined)
            self.assertIn("setup", joined)

    def test_run_update_preserves_providers_after_simulated_sync(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._init_git(root)
            prov = root / "providers" / "bishop"
            prov.mkdir(parents=True)
            (prov / "avo.provider.json").write_text('{"name":"bishop"}', encoding="utf-8")

            def fake_runner(cmd: list[str], cwd: Path) -> int:
                return 0

            with patch.object(update, "git_fetch", return_value=True), patch.object(
                update,
                "git_upstream_status",
                return_value=update.GitStatus("main", 0, 0, "origin/main", True),
            ), patch.object(update, "is_git_repo", return_value=True), patch.object(
                update, "tracked_tree_dirty", return_value=False
            ), patch.object(
                update, "run_install_skills", return_value=(True, "skills ok")
            ), patch.object(
                update, "run_toolchain_setup", return_value=(True, "setup ok")
            ), patch.object(update.avo_state, "save_state"), patch.object(
                update.avo_state, "load_state", return_value={"transcription": {"language": "pt"}}
            ):
                report = update.run_update(yes=True, root=root, runner=fake_runner)
            self.assertEqual(
                [p.slug for p in report.providers_before],
                [p.slug for p in report.providers_after],
            )
            self.assertEqual([], update.verify_providers_preserved(
                report.providers_before, report.providers_after
            ))

    @staticmethod
    def _init_git(root: Path) -> None:
        import subprocess

        subprocess.run(["git", "init", "-q"], cwd=root, check=True)
        subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=root, check=True)
        subprocess.run(["git", "config", "user.name", "test"], cwd=root, check=True)
        (root / "README.md").write_text("x", encoding="utf-8")
        subprocess.run(["git", "add", "README.md"], cwd=root, check=True)
        subprocess.run(["git", "commit", "-qm", "init"], cwd=root, check=True)


if __name__ == "__main__":
    unittest.main()
