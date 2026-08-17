"""Unit tests for src/avo/project_inventory.py preserved-set safety.

Fixture layout: ``tests/fixtures/stats-project/`` mirrors the external-project
``edit/`` subtree (transcripts, masters, preview, deletable scratch).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
FIXTURE = ROOT / "tests" / "fixtures" / "stats-project"
MASTER_BASENAME = "20260801-demo-master-v001"

sys.path.insert(0, str(SRC))

from avo import project_inventory


class ProjectInventoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.raw_dir = FIXTURE
        self.master = MASTER_BASENAME

    def test_resolve_preserved_set_fixture(self) -> None:
        preserved = project_inventory.resolve_preserved_set(self.raw_dir, self.master)
        self.assertTrue(
            any(path.name == "source.mp4" for path in preserved.raw_sources)
        )
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
        preserved_resolved = {str(path.resolve()) for path in preserved.all_paths}
        delete_resolved = {str(path.resolve()) for path in delete_list}
        self.assertFalse(preserved_resolved & delete_resolved)
        rel_paths = {
            project_inventory._relative_posix(self.raw_dir, path)
            for path in delete_list
        }
        self.assertIn("edit/preview/edit-proof.mp4", rel_paths)
        self.assertIn("edit/clips_graded/intermediate.mov", rel_paths)
        self.assertNotIn(f"edit/masters/{self.master}.mp4", rel_paths)
        self.assertNotIn("edit/transcripts/initial-whisper.json", rel_paths)

    def test_delete_candidates_skip_inaccessible_paths(self) -> None:
        preserved = project_inventory.resolve_preserved_set(self.raw_dir, self.master)
        original_is_file = Path.is_file

        def fake_is_file(self: Path) -> bool:
            if self.name == "edit-proof.mp4":
                raise OSError(1920, "unavailable")
            return original_is_file(self)

        with mock.patch.object(Path, "is_file", fake_is_file):
            delete_list, leftover = project_inventory.scan_delete_candidates(
                self.raw_dir, preserved
            )
        rel_paths = {
            project_inventory._relative_posix(self.raw_dir, path)
            for path in delete_list
        }
        self.assertNotIn("edit/preview/edit-proof.mp4", rel_paths)
        self.assertIn("edit/clips_graded/intermediate.mov", rel_paths)
        self.assertGreaterEqual(leftover, 1)

    def test_execute_counts_leftover_when_unlink_skipped(self) -> None:
        def skip_proof(path: Path) -> None:
            if path.name == "edit-proof.mp4":
                return
            if path.is_file():
                path.unlink()

        with self._temp_project(include_edit=True) as raw_dir:
            outcome = project_inventory.run_cleanup(
                raw_dir,
                self.master,
                dry_run=False,
                rimraf_runner=skip_proof,
                purge_session=False,
            )
            self.assertTrue((raw_dir / "edit" / "preview" / "edit-proof.mp4").is_file())
            self.assertGreaterEqual(outcome.leftover, 1)

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
            any(
                entry.path == "edit/clips_graded/intermediate.mov"
                for entry in report.file_diff.added
            )
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
                "-m",
                "avo.project_inventory",
                "delete-list",
                "--raw-dir",
                str(self.raw_dir),
                "--master-basename",
                self.master,
                "--json",
            ],
            cwd=ROOT,
            env={**os.environ, "PYTHONPATH": str(SRC)},
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["status"], "dry-run")
        self.assertNotIn("deleteCandidates", payload)
        self.assertIn("candidateCount", payload)
        self.assertGreaterEqual(payload["candidateCount"], 1)
        self.assertIn("edit/preview/edit-proof.mp4", payload["candidateSample"])

    def test_delete_list_cli_json_full_paths(self) -> None:
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "avo.project_inventory",
                "delete-list",
                "--raw-dir",
                str(self.raw_dir),
                "--master-basename",
                self.master,
                "--json",
                "--full-paths",
            ],
            cwd=ROOT,
            env={**os.environ, "PYTHONPATH": str(SRC)},
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertIn("deleteCandidates", payload)
        self.assertIn("edit/preview/edit-proof.mp4", payload["deleteCandidates"])

    def test_report_json_compact_scratch_keeps_full_list(self) -> None:
        from io import StringIO

        from avo import scratch
        from avo.project_inventory import main as inventory_main

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            buf = StringIO()
            with (
                mock.patch.object(scratch, "tmp_dir", return_value=root),
                mock.patch("sys.stdout", buf),
            ):
                code = inventory_main(
                    [
                        "report",
                        "--raw-dir",
                        str(self.raw_dir),
                        "--master-basename",
                        self.master,
                        "--json",
                        "--scratch-out",
                        "--session-id",
                        "sess-report",
                    ]
                )
            self.assertEqual(code, 0)
            start = buf.getvalue().find("{")
            payload = json.loads(buf.getvalue()[start:])
            self.assertIn("candidateCount", payload)
            self.assertNotIn("deleteCandidates", payload)
            report_path = root / "learndown" / "sess-report" / "inventory.report.json"
            self.assertTrue(report_path.is_file())
            full = json.loads(report_path.read_text(encoding="utf-8"))
            scheduled = [
                entry["path"] for entry in full["files"]["scheduledForDeletion"]
            ]
            self.assertIn("edit/preview/edit-proof.mp4", scheduled)
            self.assertEqual(len(scheduled), payload["candidateCount"])

    def test_cleanup_dry_run_lists_only(self) -> None:
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "avo.project_inventory",
                "cleanup",
                "--raw-dir",
                str(self.raw_dir),
                "--master-basename",
                self.master,
                "--dry-run",
            ],
            cwd=ROOT,
            env={**os.environ, "PYTHONPATH": str(SRC)},
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
            self.assertEqual(len(deleted), 2)
            self.assertFalse((raw_dir / "edit" / "preview" / "edit-proof.mp4").exists())
            self.assertFalse(
                (raw_dir / "edit" / "clips_graded" / "intermediate.mov").exists()
            )
            self.assertTrue(
                (raw_dir / "edit" / "masters" / f"{self.master}.mp4").exists()
            )
            self.assertTrue(
                (raw_dir / "edit" / "transcripts" / "initial-whisper.json").exists()
            )

    def test_cleanup_preserves_reconstruction_metadata(self) -> None:
        with self._temp_project(include_edit=True) as raw_dir:
            timeline = raw_dir / "edit" / "timeline"
            review = raw_dir / "edit" / "review" / "pre-master"
            timeline.mkdir(parents=True)
            review.mkdir(parents=True)
            (timeline / "cmap.json").write_text("{}", encoding="utf-8")
            (review / "review.json").write_text("{}", encoding="utf-8")
            preserved = project_inventory.resolve_preserved_set(raw_dir, self.master)
            names = {
                project_inventory._relative_posix(raw_dir, item)
                for item in preserved.reconstruction_metadata
            }
            self.assertIn("edit/timeline/cmap.json", names)
            self.assertIn("edit/review/pre-master/review.json", names)
            deleted = {
                project_inventory._relative_posix(raw_dir, item)
                for item in project_inventory.list_delete_candidates(raw_dir, preserved)
            }
            self.assertNotIn("edit/timeline/cmap.json", deleted)
            self.assertNotIn("edit/review/pre-master/review.json", deleted)

    def test_cleanup_refuses_on_verify_failure(self) -> None:
        with self._temp_project(include_edit=True, include_master=False) as raw_dir:
            with self.assertRaises(SystemExit):
                project_inventory.execute_cleanup(
                    raw_dir,
                    self.master,
                    dry_run=True,
                )

    def test_cleanup_execute_purges_all_session_tmp_kinds(self) -> None:
        from avo import scratch

        deleted: list[str] = []

        def fake_rimraf(path: Path) -> None:
            deleted.append(str(path.resolve()))
            if path.is_file():
                path.unlink()

        with self._temp_project(include_edit=True) as raw_dir:
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                with mock.patch.object(scratch, "tmp_dir", return_value=root):
                    keep = scratch.scratch_path("qc", "sess-keep", "a.bin")
                    keep.write_bytes(b"keep")
                    for kind in scratch.SCRATCH_KINDS:
                        target = scratch.scratch_path(kind, "sess-ok", "drop.bin")
                        target.write_bytes(b"drop")

                    project_inventory.execute_cleanup(
                        raw_dir,
                        self.master,
                        dry_run=False,
                        rimraf_runner=fake_rimraf,
                        session_id="sess-ok",
                    )
                    self.assertGreaterEqual(len(deleted), 1)
                    for kind in scratch.SCRATCH_KINDS:
                        self.assertFalse((root / kind / "sess-ok").exists())
                    self.assertTrue(keep.is_file())

    def test_cleanup_dry_run_with_session_id_does_not_purge(self) -> None:
        from avo import scratch

        with self._temp_project(include_edit=True) as raw_dir:
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                with mock.patch.object(scratch, "tmp_dir", return_value=root):
                    marker = scratch.scratch_path("shorts-proof", "sess-dry", "x.bin")
                    marker.write_bytes(b"x")
                    project_inventory.execute_cleanup(
                        raw_dir,
                        self.master,
                        dry_run=True,
                        session_id="sess-dry",
                    )
                    self.assertTrue(marker.is_file())
                    preview = raw_dir / "edit" / "preview" / "edit-proof.mp4"
                    self.assertTrue(preview.is_file())

    def test_cleanup_refuse_incomplete_does_not_purge_session_tmp(self) -> None:
        from avo import scratch

        with self._temp_project(include_edit=True, include_master=False) as raw_dir:
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                with mock.patch.object(scratch, "tmp_dir", return_value=root):
                    marker = scratch.scratch_path("session", "sess-fail", "x.bin")
                    marker.write_bytes(b"x")
                    with self.assertRaises(SystemExit):
                        project_inventory.execute_cleanup(
                            raw_dir,
                            self.master,
                            dry_run=False,
                            session_id="sess-fail",
                        )
                    self.assertTrue(marker.is_file())

    def test_legacy_reconstruction_dry_run_writes_nothing(self) -> None:
        with self._temp_project(include_edit=True) as raw_dir:
            self._add_legacy_sources(raw_dir)
            dest = raw_dir / "edit" / "review" / "legacy-reconstruction"
            dests = project_inventory.promote_legacy_reconstruction(
                raw_dir, apply=False
            )
            self.assertTrue(dests)
            self.assertFalse(dest.exists())
            self.assertFalse((raw_dir / "EDITLOG.md").exists())
            deleted = project_inventory.execute_cleanup(
                raw_dir, self.master, dry_run=True
            )
            self.assertFalse(dest.exists())
            rel = {project_inventory._relative_posix(raw_dir, path) for path in deleted}
            self.assertIn("edit/preview/edit-proof.mp4", rel)

    def test_legacy_reconstruction_execute_preserves_content(self) -> None:
        with self._temp_project(include_edit=True) as raw_dir:
            edl_text, log_text = self._add_legacy_sources(raw_dir)
            project_inventory.execute_cleanup(
                raw_dir,
                self.master,
                dry_run=False,
                rimraf_runner=lambda path: path.unlink() if path.is_file() else None,
            )
            copied_edl = (
                raw_dir / "edit" / "review" / "legacy-reconstruction" / "edl.json"
            )
            self.assertTrue(copied_edl.is_file())
            self.assertEqual(copied_edl.read_text(encoding="utf-8"), edl_text)
            self.assertTrue((raw_dir / "EDITLOG.md").is_file())
            self.assertEqual(
                (raw_dir / "EDITLOG.md").read_text(encoding="utf-8"), log_text
            )
            self.assertFalse((raw_dir / "edit" / "preview" / "edit-proof.mp4").exists())

    def test_promote_legacy_skips_when_canonical_indexes_exist(self) -> None:
        with self._temp_project(include_edit=True) as raw_dir:
            self._add_legacy_sources(raw_dir)
            timeline = raw_dir / "edit" / "timeline"
            timeline.mkdir(parents=True)
            for name in project_inventory.CANONICAL_INDEX_NAMES:
                (timeline / f"{name}.json").write_text("{}", encoding="utf-8")
            dests = project_inventory.promote_legacy_reconstruction(raw_dir, apply=True)
            self.assertEqual(dests, [])
            self.assertFalse(
                (raw_dir / "edit" / "review" / "legacy-reconstruction").exists()
            )

    def _add_legacy_sources(self, raw_dir: Path) -> tuple[str, str]:
        edl_text = '{"events":[{"id":"cut-1"}]}'
        log_text = "# Edit log\nKept decision.\n"
        (raw_dir / "edit" / "edl.json").write_text(edl_text, encoding="utf-8")
        (raw_dir / "edit" / "EDITLOG.md").write_text(log_text, encoding="utf-8")
        return edl_text, log_text

    def test_scan_inventory_local_fallback(self) -> None:
        inventory = project_inventory.scan_inventory(
            self.raw_dir, relative_to=self.raw_dir
        )
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
