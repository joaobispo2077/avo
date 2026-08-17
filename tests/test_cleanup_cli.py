"""CLI tests for ``python -m avo.cli cleanup execute|dry-run``."""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
FIXTURE = ROOT / "tests" / "fixtures" / "stats-project"
MASTER_BASENAME = "20260801-demo-master-v001"

sys.path.insert(0, str(SRC))

from avo import scratch
from avo.cli import build_parser, main


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

        dry = parser.parse_args(
            [
                "cleanup",
                "dry-run",
                "--project",
                "avo.project.json",
                "--master-basename",
                MASTER_BASENAME,
            ]
        )
        self.assertEqual(dry.cleanup_command, "dry-run")
        self.assertFalse(hasattr(dry, "session_id"))

    def test_dry_run_writes_nothing_and_does_not_purge(self) -> None:
        with self._project() as (project, raw_dir, tmp_root):
            preview = raw_dir / "edit" / "preview" / "edit-proof.mp4"
            with patch.object(scratch, "tmp_dir", return_value=tmp_root):
                marker = scratch.scratch_path("qc", "sess-dry", "keep.bin")
                marker.write_bytes(b"keep")
                code = main(
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
                self.assertTrue(preview.is_file())
                self.assertTrue(marker.is_file())

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
                    code = main(
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
                code = main(
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
                self.assertTrue(marker.is_file())

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


if __name__ == "__main__":
    unittest.main()
