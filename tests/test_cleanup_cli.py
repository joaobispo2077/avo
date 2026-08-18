"""CLI tests for ``python -m avo.cli cleanup execute|dry-run``."""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from io import StringIO
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
FIXTURE = ROOT / "tests" / "fixtures" / "stats-project"
MASTER_BASENAME = "20260801-demo-master-v001"

sys.path.insert(0, str(SRC))

from avo import scratch
from avo.cli import build_parser, main
from avo.project_inventory import CANONICAL_INDEX_NAMES


class CleanupCliTests(unittest.TestCase):
    def test_parser_exposes_execute_with_optional_session_id(self) -> None:
        parser = build_parser()
        args = parser.parse_args(
            [
                "cleanup",
                "execute",
                "--project",
                "avo.project.json",
                "--master-basename",
                MASTER_BASENAME,
                "--session-id",
                "sess-1",
            ]
        )
        self.assertEqual(args.command, "cleanup")
        self.assertEqual(args.cleanup_command, "execute")
        self.assertEqual(args.session_id, "sess-1")
        self.assertFalse(args.full_paths)

        dry = parser.parse_args(
            [
                "cleanup",
                "dry-run",
                "--project",
                "avo.project.json",
                "--master-basename",
                MASTER_BASENAME,
                "--session-id",
                "sess-dry",
                "--scratch-out",
            ]
        )
        self.assertEqual(dry.cleanup_command, "dry-run")
        self.assertEqual(dry.session_id, "sess-dry")
        self.assertTrue(dry.scratch_out)
        self.assertFalse(dry.full_paths)

    def _run_cli(self, argv: list[str]) -> tuple[int, dict]:
        buf = StringIO()
        with patch("sys.stdout", buf):
            code = main(argv)
        payload = json.loads(buf.getvalue())
        return code, payload

    def test_dry_run_writes_nothing_and_does_not_purge(self) -> None:
        with self._project() as (project, raw_dir, tmp_root):
            preview = raw_dir / "edit" / "preview" / "edit-proof.mp4"
            with patch.object(scratch, "tmp_dir", return_value=tmp_root):
                marker = scratch.scratch_path("qc", "sess-dry", "keep.bin")
                marker.write_bytes(b"keep")
                code, payload = self._run_cli(
                    [
                        "cleanup",
                        "dry-run",
                        "--project",
                        str(project),
                        "--master-basename",
                        MASTER_BASENAME,
                    ]
                )
                self.assertEqual(code, 0)
                self.assertEqual(payload["status"], "dry-run")
                self.assertIn("candidateCount", payload)
                self.assertGreaterEqual(payload["candidateCount"], 1)
                self.assertLessEqual(len(payload["candidateSample"]), 50)
                self.assertNotIn("deleteCandidates", payload)
                self.assertTrue(preview.is_file())
                self.assertTrue(marker.is_file())
                recon = raw_dir / "edit" / "review" / "legacy-reconstruction"
                self.assertFalse(recon.exists())

    def test_execute_deletes_candidates_and_purges_session_tmp(self) -> None:
        with self._project() as (project, raw_dir, tmp_root):
            preview = raw_dir / "edit" / "preview" / "edit-proof.mp4"
            deleted: list[Path] = []

            def fake_rimraf(path: Path) -> None:
                deleted.append(path)
                if path.is_file() or path.is_symlink():
                    path.unlink(missing_ok=True)
                elif path.is_dir():
                    shutil.rmtree(path, ignore_errors=True)

            with patch.object(scratch, "tmp_dir", return_value=tmp_root):
                keep = scratch.scratch_path("qc", "sess-keep", "a.bin")
                keep.write_bytes(b"keep")
                for kind in scratch.SCRATCH_KINDS:
                    target = scratch.scratch_path(kind, "sess-run", "drop.bin")
                    target.write_bytes(b"drop")

                with patch(
                    "avo.project_inventory._default_rimraf_runner",
                    side_effect=fake_rimraf,
                ):
                    code, payload = self._run_cli(
                        [
                            "cleanup",
                            "execute",
                            "--project",
                            str(project),
                            "--master-basename",
                            MASTER_BASENAME,
                            "--session-id",
                            "sess-run",
                        ]
                    )
                self.assertEqual(code, 0)
                self.assertEqual(payload["status"], "executed")
                self.assertIn("deletedCount", payload)
                self.assertLessEqual(len(payload["deletedSample"]), 50)
                self.assertNotIn("deleted", payload)
                self.assertFalse(preview.exists())
                self.assertTrue(
                    (raw_dir / "edit" / "masters" / f"{MASTER_BASENAME}.mp4").exists()
                )
                self.assertGreaterEqual(len(deleted), 1)
                for kind in scratch.SCRATCH_KINDS:
                    self.assertFalse((tmp_root / kind / "sess-run").exists())
                self.assertTrue(keep.is_file())

    def test_execute_refuses_incomplete_preserved_without_purge(self) -> None:
        with self._project(include_master=False) as (project, _raw_dir, tmp_root):
            with patch.object(scratch, "tmp_dir", return_value=tmp_root):
                marker = scratch.scratch_path("learndown", "sess-block", "x.bin")
                marker.write_bytes(b"x")
                code, payload = self._run_cli(
                    [
                        "cleanup",
                        "execute",
                        "--project",
                        str(project),
                        "--master-basename",
                        MASTER_BASENAME,
                        "--session-id",
                        "sess-block",
                    ]
                )
                self.assertEqual(code, 3)
                self.assertEqual(payload["status"], "blocked")
                self.assertTrue(payload["verifyErrors"])
                self.assertNotIn("errors", payload)
                self.assertTrue(marker.is_file())

    def test_full_paths_opt_in_on_dry_run(self) -> None:
        with self._project() as (project, _raw_dir, _tmp_root):
            _code, payload = self._run_cli(
                [
                    "cleanup",
                    "dry-run",
                    "--project",
                    str(project),
                    "--master-basename",
                    MASTER_BASENAME,
                    "--full-paths",
                ]
            )
            self.assertIn("deleteCandidates", payload)
            self.assertIn("edit/preview/edit-proof.mp4", payload["deleteCandidates"])

    def test_canonical_dry_run_and_execute_preserve_root_editlog(self) -> None:
        with self._project() as (project, raw_dir, _tmp_root):
            root_text = self._add_canonical_indexes_and_root_editlog(raw_dir)
            root_log = raw_dir / "EDITLOG.md"
            argv_base = [
                "--project",
                str(project),
                "--master-basename",
                MASTER_BASENAME,
                "--full-paths",
            ]
            with patch(
                "avo.timeline.reconstruction.verify_reconstruction_bundle",
                return_value={"files": []},
            ):
                dry_code, dry_payload = self._run_cli(
                    ["cleanup", "dry-run", *argv_base]
                )
                self.assertEqual(dry_code, 0)
                self.assertEqual(dry_payload["status"], "dry-run")
                candidates = dry_payload["deleteCandidates"]
                self.assertNotIn("EDITLOG.md", candidates)
                self.assertIn("edit/EDITLOG.md", candidates)
                self.assertTrue(root_log.is_file())
                self.assertEqual(root_log.read_text(encoding="utf-8"), root_text)

                def fake_rimraf(path: Path) -> None:
                    if path.is_file() or path.is_symlink():
                        path.unlink(missing_ok=True)
                    elif path.is_dir():
                        shutil.rmtree(path, ignore_errors=True)

                with patch(
                    "avo.project_inventory._default_rimraf_runner",
                    side_effect=fake_rimraf,
                ):
                    exec_code, exec_payload = self._run_cli(
                        ["cleanup", "execute", *argv_base]
                    )
            self.assertEqual(exec_code, 0)
            self.assertEqual(exec_payload["status"], "executed")
            self.assertTrue(root_log.is_file())
            self.assertEqual(root_log.read_text(encoding="utf-8"), root_text)
            self.assertFalse((raw_dir / "edit" / "EDITLOG.md").exists())

    def test_dry_run_scratch_out_sets_scratch_paths(self) -> None:
        with self._project() as (project, _raw_dir, tmp_root):
            with patch.object(scratch, "tmp_dir", return_value=tmp_root):
                code, payload = self._run_cli(
                    [
                        "cleanup",
                        "dry-run",
                        "--project",
                        str(project),
                        "--master-basename",
                        MASTER_BASENAME,
                        "--session-id",
                        "sess-scratch",
                        "--scratch-out",
                    ]
                )
            self.assertEqual(code, 0)
            self.assertTrue(payload["scratchReport"])
            self.assertTrue(payload["scratchMeta"])
            self.assertTrue(Path(payload["scratchReport"]).is_file())
            full = json.loads(
                Path(payload["scratchReport"]).read_text(encoding="utf-8")
            )
            scheduled = [
                entry["path"] for entry in full["files"]["scheduledForDeletion"]
            ]
            self.assertIn("edit/preview/edit-proof.mp4", scheduled)
            self.assertNotIn("deleteCandidates", payload)

    def _project(self, *, include_master: bool = True):
        class _Ctx:
            def __enter__(self_inner):
                self_inner.tmp = Path(tempfile.mkdtemp(prefix="avo-cleanup-cli-"))
                raw = self_inner.tmp / "raw"
                shutil.copytree(FIXTURE, raw)
                if not include_master:
                    master = raw / "edit" / "masters" / f"{MASTER_BASENAME}.mp4"
                    master.unlink(missing_ok=True)
                project = self_inner.tmp / "avo.project.json"
                project.write_text(
                    json.dumps(
                        {
                            "schemaVersion": "1.0.0",
                            "provider": "bishop",
                            "videoId": "cleanup-cli",
                            "rawDir": str(raw),
                        }
                    ),
                    encoding="utf-8",
                )
                scratch_root = self_inner.tmp / "avo-tmp"
                scratch_root.mkdir()
                return project, raw, scratch_root

            def __exit__(self_inner, exc_type, exc, tb):
                shutil.rmtree(self_inner.tmp, ignore_errors=True)

        return _Ctx()

    def _add_canonical_indexes_and_root_editlog(self, raw_dir: Path) -> str:
        timeline = raw_dir / "edit" / "timeline"
        timeline.mkdir(parents=True, exist_ok=True)
        for name in CANONICAL_INDEX_NAMES:
            (timeline / f"{name}.json").write_text("{}", encoding="utf-8")
        root_text = "# EDITLOG\nLiving footage-root audit.\n"
        (raw_dir / "EDITLOG.md").write_text(root_text, encoding="utf-8")
        (raw_dir / "edit" / "EDITLOG.md").write_text(
            "# Migrated edit copy.\n", encoding="utf-8"
        )
        return root_text


if __name__ == "__main__":
    unittest.main()
