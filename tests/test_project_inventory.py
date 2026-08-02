"""Unit tests for helpers/project_inventory.py preserved-set safety.

Fixture layout: ``tests/fixtures/stats-project/`` mirrors the external-project
``edit/`` subtree (transcripts, masters, preview, deletable scratch).
"""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
HELPERS = ROOT / "helpers"
FIXTURE = ROOT / "tests" / "fixtures" / "stats-project"
MASTER_BASENAME = "20260801-demo-master-v001"

sys.path.insert(0, str(HELPERS))

import project_inventory  # noqa: E402


class ProjectInventoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.raw_dir = FIXTURE
        self.master = MASTER_BASENAME

    def test_resolve_preserved_set_fixture(self) -> None:
        preserved = project_inventory.resolve_preserved_set(self.raw_dir, self.master)
        self.assertTrue(any(path.name == "source.mp4" for path in preserved.raw_sources))
        self.assertIsNotNone(preserved.initial_transcript)
        assert preserved.initial_transcript is not None
        self.assertEqual(preserved.initial_transcript.name, "initial-whisper.json")
        self.assertTrue(
            any(path.name == f"{self.master}.mp4" for path in preserved.final_master)
        )
        self.assertGreaterEqual(len(preserved.final_transcripts), 2)

    def test_verify_complete_fixture(self) -> None:
        errors = project_inventory.verify_preserved_complete(self.raw_dir, self.master)
        self.assertEqual(errors, [])

    def test_verify_fails_when_master_missing(self) -> None:
        errors = project_inventory.verify_preserved_complete(
            self.raw_dir, "missing-master-v001"
        )
        self.assertTrue(any("missing final master" in error for error in errors))
        self.assertTrue(any("missing final transcript" in error for error in errors))

    def test_preserved_never_in_delete_list(self) -> None:
        preserved = project_inventory.resolve_preserved_set(self.raw_dir, self.master)
        delete_list = project_inventory.list_delete_candidates(self.raw_dir, preserved)
        preserved_resolved = {
            str(path.resolve()) for path in preserved.all_paths
        }
        delete_resolved = {str(path.resolve()) for path in delete_list}
        self.assertFalse(preserved_resolved & delete_resolved)
        rel_paths = {
            project_inventory._relative_posix(self.raw_dir, path) for path in delete_list
        }
        self.assertIn("edit/preview/edit-proof.mp4", rel_paths)
        self.assertIn("edit/clips_graded/intermediate.mov", rel_paths)
        self.assertNotIn(f"edit/masters/{self.master}.mp4", rel_paths)
        self.assertNotIn("edit/transcripts/initial-whisper.json", rel_paths)

    def test_assert_no_preserved_in_delete_list_raises(self) -> None:
        preserved = project_inventory.resolve_preserved_set(self.raw_dir, self.master)
        master_path = self.raw_dir / "edit" / "masters" / f"{self.master}.mp4"
        with self.assertRaises(project_inventory.PreservedSetViolation):
            project_inventory.assert_no_preserved_in_delete_list(
                preserved, [master_path]
            )

    def test_initial_transcript_override(self) -> None:
        override = self.raw_dir / "edit" / "transcripts" / f"{self.master}.json"
        preserved = project_inventory.resolve_preserved_set(
            self.raw_dir, self.master, initial_transcript=override
        )
        self.assertEqual(preserved.initial_transcript, override.resolve())

    def test_build_inventory_report_degraded_without_pre(self) -> None:
        report = project_inventory.build_inventory_report(self.raw_dir, self.master)
        self.assertTrue(report.degraded_mode)
        self.assertIsNone(report.file_diff)
        payload = report.to_dict()
        self.assertGreater(payload["space"]["deleteCandidateBytes"], 0)
        self.assertGreater(payload["space"]["preservedBytes"], 0)

    def test_build_inventory_report_with_pre_json_diff(self) -> None:
        pre_path = FIXTURE / "pre.json"
        pre_payload = {
            "scannedAt": "2026-08-01T00:00:00Z",
            "files": {
                "edit/preview/edit-proof.mp4": 100,
                "edit/masters/20260801-demo-master-v001.mp4": 500,
            },
        }
        pre_path.write_text(json.dumps(pre_payload), encoding="utf-8")
        self.addCleanup(lambda: pre_path.unlink(missing_ok=True))

        report = project_inventory.build_inventory_report(
            self.raw_dir, self.master, pre_json_path=pre_path
        )
        self.assertFalse(report.degraded_mode)
        assert report.file_diff is not None
        self.assertTrue(
            any(entry.path == "edit/clips_graded/intermediate.mov" for entry in report.file_diff.added)
        )

    def test_empty_edit_dir_delete_list(self) -> None:
        with self._temp_project(include_edit=False) as raw_dir:
            preserved = project_inventory.resolve_preserved_set(raw_dir, self.master)
            delete_list = project_inventory.list_delete_candidates(raw_dir, preserved)
            self.assertEqual(delete_list, [])

    def test_delete_list_cli_json(self) -> None:
        proc = subprocess.run(
            [
                sys.executable,
                str(HELPERS / "project_inventory.py"),
                "delete-list",
                "--raw-dir",
                str(self.raw_dir),
                "--master-basename",
                self.master,
                "--json",
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertIn("deleteCandidates", payload)
        self.assertIn("edit/preview/edit-proof.mp4", payload["deleteCandidates"])

    def test_cleanup_dry_run_lists_only(self) -> None:
        proc = subprocess.run(
            [
                sys.executable,
                str(HELPERS / "project_inventory.py"),
                "cleanup",
                "--raw-dir",
                str(self.raw_dir),
                "--master-basename",
                self.master,
                "--dry-run",
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        self.assertIn("edit/preview/edit-proof.mp4", proc.stdout)
        preview = self.raw_dir / "edit" / "preview" / "edit-proof.mp4"
        self.assertTrue(preview.is_file())

    def test_cleanup_execute_mocks_rimraf(self) -> None:
        deleted: list[str] = []

        def fake_rimraf(path: Path) -> None:
            deleted.append(str(path.resolve()))
            if path.is_file():
                path.unlink()

        with self._temp_project(include_edit=True) as raw_dir:
            project_inventory.execute_cleanup(
                raw_dir,
                self.master,
                dry_run=False,
                rimraf_runner=fake_rimraf,
            )
            self.assertEqual(len(deleted), 3)
            self.assertFalse((raw_dir / "edit" / "preview" / "edit-proof.mp4").exists())
            self.assertFalse((raw_dir / "edit" / "clips_graded" / "intermediate.mov").exists())
            self.assertTrue(
                (raw_dir / "edit" / "masters" / f"{self.master}.mp4").exists()
            )
            self.assertTrue(
                (raw_dir / "edit" / "transcripts" / "initial-whisper.json").exists()
            )

    def test_cleanup_refuses_on_verify_failure(self) -> None:
        with self._temp_project(include_edit=True, include_master=False) as raw_dir:
            with self.assertRaises(SystemExit):
                project_inventory.execute_cleanup(
                    raw_dir,
                    self.master,
                    dry_run=True,
                )

    def test_scan_inventory_local_fallback(self) -> None:
        inventory = project_inventory.scan_inventory(self.raw_dir, relative_to=self.raw_dir)
        self.assertIn("source.mp4", inventory)
        self.assertIn("edit/preview/edit-proof.mp4", inventory)

    def _temp_project(
        self,
        *,
        include_edit: bool,
        include_master: bool = True,
    ):
        import shutil
        import tempfile

        class _Ctx:
            def __enter__(self):
                self.tmp = Path(tempfile.mkdtemp(prefix="avo-inventory-"))
                shutil.copytree(FIXTURE, self.tmp, dirs_exist_ok=True)
                if not include_edit:
                    shutil.rmtree(self.tmp / "edit")
                if not include_master:
                    master = self.tmp / "edit" / "masters" / f"{MASTER_BASENAME}.mp4"
                    master.unlink(missing_ok=True)
                return self.tmp

            def __exit__(self, exc_type, exc, tb):
                shutil.rmtree(self.tmp, ignore_errors=True)

        return _Ctx()


if __name__ == "__main__":
    unittest.main()
