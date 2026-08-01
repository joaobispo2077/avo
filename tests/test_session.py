"""Tests for helpers/session.py — path normalization, scan, diff, start/finalize."""
from __future__ import annotations

import json
import re
import sys
import tempfile
import unittest
from io import StringIO
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
HELPERS = ROOT / "helpers"
sys.path.insert(0, str(HELPERS))

import session  # noqa: E402


SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")


class SessionHelperTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp_dir = tempfile.mkdtemp()
        self.tmp_path = Path(self._temp_dir)

    def _patch_sessions(self) -> mock._patch:
        import avo_state

        return mock.patch.object(avo_state, "repo_root", return_value=self.tmp_path)

    def test_normalize_path_resolves_and_uses_posix(self) -> None:
        base = self.tmp_path / "project"
        base.mkdir()
        target = base / "edit" / "preview.mp4"
        target.parent.mkdir()
        target.write_bytes(b"x")

        normalized = session.normalize_path(base / "edit" / "preview.mp4")
        self.assertNotIn("\\", normalized)
        self.assertTrue(normalized.endswith("preview.mp4"))

    def test_normalize_path_casefolds_on_windows(self) -> None:
        folder = self.tmp_path / "Project"
        folder.mkdir()
        file_a = folder / "Clip.MP4"
        file_a.write_bytes(b"a")
        file_b = self.tmp_path / "project" / "clip.mp4"

        with mock.patch.object(session.sys, "platform", "win32"):
            self.assertEqual(session.normalize_path(file_a), session.normalize_path(file_b))

    def test_session_ids_are_sha256_hex(self) -> None:
        raw = self.tmp_path / "footage"
        raw.mkdir()
        prov = session.provisional_session_id(raw, "2026-08-01T12:00:00Z")
        final = session.final_session_id(raw, "20260801-demo-master-v001")

        self.assertRegex(prov, SHA256_HEX)
        self.assertRegex(final, SHA256_HEX)
        self.assertNotEqual(prov, final)

    def test_scan_inventory_maps_relative_paths_and_sizes(self) -> None:
        root = self.tmp_path / "rawDir"
        (root / "edit" / "preview").mkdir(parents=True)
        (root / "edit" / "preview" / "proof.mp4").write_bytes(b"12345")
        (root / "source.mov").write_bytes(b"ab")

        inventory = session.scan_inventory(root, relative_to=root)

        self.assertEqual(
            inventory,
            {"edit/preview/proof.mp4": 5, "source.mov": 2},
        )

    def test_diff_inventories_classifies_size_only(self) -> None:
        pre = {"a.txt": 10, "gone.txt": 1, "changed.txt": 5}
        post = {"a.txt": 10, "new.txt": 7, "changed.txt": 9}

        diff = session.diff_inventories(pre, post)

        self.assertEqual([e.path for e in diff.added], ["new.txt"])
        self.assertEqual(diff.added[0].size, 7)
        self.assertEqual([e.path for e in diff.removed], ["gone.txt"])
        self.assertEqual(diff.removed[0].size, 1)
        self.assertEqual([e.path for e in diff.modified], ["changed.txt"])
        self.assertEqual(diff.modified[0].size, 9)
        self.assertEqual([e.path for e in diff.unchanged], ["a.txt"])
        self.assertEqual(diff.unchanged[0].size, 10)

    def test_start_session_writes_meta_and_pre(self) -> None:
        import avo_state

        raw = self.tmp_path / "footage"
        (raw / "edit").mkdir(parents=True)
        (raw / "edit" / "scratch.txt").write_text("temp")

        with self._patch_sessions(), mock.patch.object(avo_state, "now_iso", return_value="2026-08-01T20:00:00Z"):
            ctx = session.start_session(raw, "bishop", title="Demo run")

        sessions_root = self.tmp_path / ".avo" / "sessions"
        self.assertRegex(ctx.id, SHA256_HEX)
        sdir = sessions_root / ctx.id
        self.assertTrue(sdir.is_dir())

        meta = json.loads((sdir / "meta.json").read_text(encoding="utf-8"))
        self.assertEqual(meta["id"], ctx.id)
        self.assertEqual(meta["provider"], "bishop")
        self.assertEqual(meta["title"], "Demo run")
        self.assertEqual(meta["startedAt"], "2026-08-01T20:00:00Z")
        self.assertIsNone(meta["masterBasename"])
        self.assertEqual(Path(meta["rawDir"]).resolve(), raw.resolve())

        pre = json.loads((sdir / "pre.json").read_text(encoding="utf-8"))
        self.assertEqual(pre["scannedAt"], "2026-08-01T20:00:00Z")
        self.assertEqual(pre["files"], {"edit/scratch.txt": 4})

    def test_finalize_session_updates_master_and_id(self) -> None:
        import avo_state

        raw = self.tmp_path / "footage"
        raw.mkdir()
        master = "20260801-footage-master-v001"

        with self._patch_sessions(), mock.patch.object(avo_state, "now_iso", return_value="2026-08-01T20:00:00Z"):
            ctx = session.start_session(raw, "bishop")
            final_ctx = session.finalize_session(ctx.id, master)

        sessions_root = self.tmp_path / ".avo" / "sessions"
        self.assertEqual(final_ctx.master_basename, master)
        self.assertEqual(final_ctx.id, session.final_session_id(raw, master))
        self.assertNotEqual(final_ctx.id, ctx.id)

        final_dir = sessions_root / final_ctx.id
        self.assertTrue(final_dir.is_dir())
        self.assertFalse((sessions_root / ctx.id).exists())

        meta = json.loads((final_dir / "meta.json").read_text(encoding="utf-8"))
        self.assertEqual(meta["masterBasename"], master)
        self.assertEqual(meta["id"], final_ctx.id)
        self.assertTrue((final_dir / "pre.json").is_file())

    def test_cli_start_emits_json(self) -> None:
        import avo_state

        raw = self.tmp_path / "footage"
        raw.mkdir()

        with self._patch_sessions(), mock.patch.object(avo_state, "now_iso", return_value="2026-08-01T20:00:00Z"):
            out = StringIO()
            with mock.patch("sys.stdout", out):
                code = session.main(["start", "--raw-dir", str(raw), "--provider", "bishop"])

        self.assertEqual(code, 0)
        payload = json.loads(out.getvalue())
        self.assertEqual(payload["provider"], "bishop")
        self.assertRegex(payload["id"], SHA256_HEX)


if __name__ == "__main__":
    unittest.main()
