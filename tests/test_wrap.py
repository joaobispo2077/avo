"""Tests for helpers/wrap.py — payload build, markdown render, truncation."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HELPERS = ROOT / "helpers"
FIXTURE = ROOT / "tests" / "fixtures" / "stats-project"
MASTER = "20260801-demo-master-v001"

sys.path.insert(0, str(HELPERS))

import project_inventory  # noqa: E402
import wrap  # noqa: E402


class WrapTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.report = project_inventory.build_inventory_report(FIXTURE, MASTER)

    def test_truncate_path_list_caps_at_limit(self) -> None:
        paths = [{"path": f"edit/scratch/{i}.mp4", "bytes": i} for i in range(60)]
        sample, total = wrap.truncate_path_list(paths, max_items=50)
        self.assertEqual(total, 60)
        self.assertEqual(len(sample), 50)

    def test_build_wrap_payload_draft_shape(self) -> None:
        inv = self.report.to_dict()
        payload = wrap.build_wrap_payload(
            inv,
            session_id="abc123",
            provider="bishop",
            master_basename=MASTER,
            summary="Editorial summary.",
            status="draft",
            title="Stats fixture demo",
        )
        self.assertEqual(payload["schemaVersion"], 1)
        self.assertEqual(payload["status"], "draft")
        self.assertIsNone(payload["space"]["freedBytes"])
        self.assertEqual(payload["rawDir"], str(FIXTURE.resolve()))
        self.assertTrue(payload["files"]["degradedMode"])
        self.assertGreaterEqual(len(payload["files"]["scheduledForDeletion"]), 1)

    def test_build_wrap_payload_final_has_freed_bytes(self) -> None:
        payload = wrap.build_wrap_payload(
            self.report,
            session_id="final-id",
            provider="bishop",
            master_basename=MASTER,
            summary="Done.",
            status="final",
            freed_bytes=1234,
        )
        self.assertEqual(payload["status"], "final")
        self.assertEqual(payload["space"]["freedBytes"], 1234)
        self.assertGreaterEqual(payload["files"]["deletedCount"], 1)
        self.assertLessEqual(len(payload["files"]["deletedSample"]), 50)

    def test_render_markdown_includes_summary_and_status(self) -> None:
        payload = wrap.build_wrap_payload(
            self.report,
            session_id="md-test",
            provider="bishop",
            master_basename=MASTER,
            summary="Narrative block.",
            status="final",
            freed_bytes=500,
        )
        md = wrap.render_markdown(payload)
        self.assertIn("AVO Wrap (final)", md)
        self.assertIn("Narrative block.", md)
        self.assertIn("Preserved artifacts", md)

    def test_write_wrap_draft_and_final_retains_draft(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            raw_dir = Path(tmp) / "project"
            raw_dir.mkdir()
            payload = {
                "schemaVersion": 1,
                "status": "draft",
                "sessionId": "x",
                "rawDir": str(raw_dir),
                "provider": "bishop",
                "title": "t",
                "masterBasename": MASTER,
                "generatedAt": "2026-08-01T00:00:00Z",
                "summary": "s",
                "space": {
                    "preCleanupProjectBytes": 0,
                    "deleteCandidateBytes": 0,
                    "preservedBytes": 0,
                    "freedBytes": None,
                },
                "files": {
                    "scheduledForDeletion": [],
                    "preserved": [],
                    "addedThenRemoved": [],
                    "modified": [],
                    "deletedOnCleanup": [],
                    "deletedCount": 0,
                    "deletedSample": [],
                    "degradedMode": False,
                },
                "learning": {"aiMemory": "skipped", "note": ""},
                "links": {"editlog": None},
            }
            wrap.write_wrap_draft(raw_dir, payload)
            self.assertTrue((raw_dir / "avo.wrap.draft.json").is_file())
            self.assertTrue((raw_dir / "avo.wrap.draft.md").is_file())

            final_payload = dict(payload)
            final_payload["status"] = "final"
            final_payload["space"] = dict(payload["space"])
            final_payload["space"]["freedBytes"] = 100
            wrap.write_wrap_final(raw_dir, final_payload)
            self.assertTrue((raw_dir / "avo.wrap.json").is_file())
            self.assertTrue((raw_dir / "avo.wrap.draft.json").is_file())

    def test_final_payload_deleted_sample_capped(self) -> None:
        inv = self.report.to_dict()
        inv["files"]["scheduledForDeletion"] = [
            {"path": f"edit/preview/file{i}.mp4", "bytes": 10} for i in range(55)
        ]
        payload = wrap.build_wrap_payload(
            inv,
            session_id="cap",
            provider="bishop",
            master_basename=MASTER,
            summary="",
            status="final",
            freed_bytes=550,
        )
        self.assertEqual(payload["files"]["deletedCount"], 55)
        self.assertEqual(len(payload["files"]["deletedSample"]), 50)


if __name__ == "__main__":
    unittest.main()
