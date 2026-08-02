"""Tests for src/avo/learndown_export.py."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
FIXTURE = ROOT / "tests" / "fixtures" / "stats-project"
MASTER = "20260801-demo-master-v001"

sys.path.insert(0, str(SRC))

from avo import learndown_export  # noqa: E402
from avo import project_inventory  # noqa: E402
from avo import wrap  # noqa: E402


class LearndownExportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.report = project_inventory.build_inventory_report(FIXTURE, MASTER)

    def test_build_entry_id_from_master(self) -> None:
        entry_id = learndown_export.build_entry_id(
            "20260720-switch-save-transfer-master-v001-4k"
        )
        self.assertEqual(entry_id, "20260720-switch-save-transfer")

    def test_build_learndown_payload_shape(self) -> None:
        wrap_payload = wrap.build_wrap_payload(
            self.report,
            session_id="sess",
            provider="bishop",
            master_basename=MASTER,
            summary="Summary text.",
            status="draft",
            title="Demo",
        )
        payload = learndown_export.build_learndown_payload(wrap_payload)
        self.assertEqual(payload["schemaVersion"], 1)
        self.assertEqual(payload["provider"], "bishop")
        self.assertEqual(payload["learning"]["aiMemory"], "exported")

    def test_export_writes_provider_entry_and_index(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "providers" / "bishop" / "learndowns").mkdir(parents=True)
            wrap_payload = wrap.build_wrap_payload(
                self.report,
                session_id="sess",
                provider="bishop",
                master_basename=MASTER,
                summary="Export test.",
                status="draft",
                title="Demo",
            )
            entry_dir = learndown_export.export_provider_learndown(
                wrap_payload, root=root
            )
            self.assertIsNotNone(entry_dir)
            assert entry_dir is not None
            self.assertTrue((entry_dir / "learndown.json").is_file())
            self.assertTrue((entry_dir / "learndown.md").is_file())
            index = json.loads(
                (root / "providers" / "bishop" / "learndowns" / "index.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(index["provider"], "bishop")
            self.assertEqual(len(index["entries"]), 1)

    def test_export_skips_unknown_provider(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            wrap_payload = wrap.build_wrap_payload(
                self.report,
                session_id="sess",
                provider="unknown",
                master_basename=MASTER,
                summary="Skip.",
                status="draft",
            )
            entry = learndown_export.export_provider_learndown(wrap_payload, root=root)
            self.assertIsNone(entry)

    def test_backfill_resolves_provider_from_project_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw_dir = root / "footage"
            raw_dir.mkdir()
            (raw_dir / "avo.project.json").write_text(
                json.dumps({"provider": "bishop"}),
                encoding="utf-8",
            )
            (root / "providers" / "bishop" / "learndowns").mkdir(parents=True)
            wrap_payload = wrap.build_wrap_payload(
                self.report,
                session_id="sess",
                provider="unknown",
                master_basename=MASTER,
                summary="Backfill.",
                status="draft",
            )
            wrap_payload["rawDir"] = str(raw_dir)
            provider = learndown_export._resolve_backfill_provider(wrap_payload)
            self.assertEqual(provider, "bishop")
            entry = learndown_export.export_provider_learndown(
                {**wrap_payload, "provider": provider}, root=root
            )
            self.assertIsNotNone(entry)

    def test_final_export_copies_final_wrap_sidecars(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw_dir = root / "footage"
            raw_dir.mkdir()
            (root / "providers" / "bishop" / "learndowns").mkdir(parents=True)
            wrap_payload = wrap.build_wrap_payload(
                self.report,
                session_id="sess",
                provider="bishop",
                master_basename=MASTER,
                summary="Final export.",
                status="final",
                freed_bytes=99,
            )
            wrap_payload["rawDir"] = str(raw_dir)
            (raw_dir / "avo.wrap.draft.json").write_text("{}", encoding="utf-8")
            (raw_dir / "avo.wrap.json").write_text("{}", encoding="utf-8")
            entry_dir = learndown_export.export_provider_learndown(wrap_payload, root=root)
            assert entry_dir is not None
            self.assertTrue((entry_dir / "wrap.json").is_file())
            payload = json.loads((entry_dir / "learndown.json").read_text(encoding="utf-8"))
            self.assertEqual(payload["status"], "final")


if __name__ == "__main__":
    unittest.main()
