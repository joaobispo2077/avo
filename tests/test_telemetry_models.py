from __future__ import annotations

import json
import sys
import unittest
from io import StringIO
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]


class TelemetryModelsTests(unittest.TestCase):
    def setUp(self) -> None:
        sys.path.insert(0, str(ROOT))

    @mock.patch("avo.telemetry.avo_state.save_state")
    @mock.patch("avo.telemetry.avo_state.load_state")
    def test_report_includes_active_models(
        self, load_state: mock.Mock, save_state: mock.Mock
    ) -> None:
        load_state.return_value = {"stats": {}}
        from avo.telemetry import Telemetry

        models = {
            "transcribe": "faster-whisper:small",
            "understand": "Qwen 2.5 7B",
        }
        tel = Telemetry(volume=ROOT)
        with mock.patch("sys.stderr", new_callable=StringIO) as err:
            record = tel.report("transcribe", active_models=models, emit=True)
        self.assertEqual(record["activeModels"], models)
        err_lines = err.getvalue().strip().splitlines()
        self.assertTrue(any(line.startswith("AVO_JSON ") for line in err_lines))
        json_line = next(line for line in err_lines if line.startswith("AVO_JSON "))
        payload = json.loads(json_line.removeprefix("AVO_JSON "))
        self.assertEqual(payload["activeModels"], models)

    @mock.patch("avo.telemetry.avo_state.save_state")
    @mock.patch("avo.telemetry.avo_state.load_state")
    @mock.patch("avo.models.resolve_active_models")
    def test_report_resolves_models_when_omitted(
        self, resolve: mock.Mock, load_state: mock.Mock, save_state: mock.Mock
    ) -> None:
        load_state.return_value = {"stats": {}}
        resolve.return_value = {"transcribe": "faster-whisper:medium"}
        from avo.telemetry import Telemetry

        tel = Telemetry(volume=ROOT)
        record = tel.report("cut", emit=False)
        self.assertEqual(record["activeModels"]["transcribe"], "faster-whisper:medium")
        resolve.assert_called_once()

    @mock.patch("avo.telemetry.avo_state.save_state")
    @mock.patch("avo.telemetry.avo_state.load_state")
    def test_report_survives_model_resolver_failure(
        self, load_state: mock.Mock, save_state: mock.Mock
    ) -> None:
        load_state.return_value = {"stats": {}}
        from avo.telemetry import Telemetry

        tel = Telemetry(volume=ROOT)
        with mock.patch(
            "avo.models.resolve_active_models",
            side_effect=RuntimeError("no catalog"),
        ):
            record = tel.report("plan", emit=False)
        self.assertNotIn("activeModels", record)

    @mock.patch("avo.telemetry.avo_state.save_state")
    @mock.patch("avo.telemetry.avo_state.load_state")
    def test_report_with_session_id_appends_phases_jsonl(
        self, load_state: mock.Mock, save_state: mock.Mock
    ) -> None:
        load_state.return_value = {"stats": {}}
        from avo.telemetry import Telemetry

        with mock.patch("avo.telemetry.avo_state.repo_root", return_value=ROOT):
            with mock.patch("avo.telemetry.avo_state.sessions_dir") as sessions_dir:
                session_root = ROOT / ".avo-test-sessions"
                session_root.mkdir(exist_ok=True)
                sessions_dir.return_value = session_root
                phase_file = session_root / "sess-abc" / "phases.jsonl"
                if phase_file.exists():
                    phase_file.unlink()

                tel = Telemetry(volume=ROOT)
                record = tel.report(
                    "transcribe",
                    created_bytes=42,
                    index=1,
                    session_id="sess-abc",
                    emit=False,
                )

        self.assertEqual(record["createdBytes"], 42)
        self.assertTrue(phase_file.is_file())
        lines = phase_file.read_text(encoding="utf-8").strip().splitlines()
        self.assertEqual(len(lines), 1)
        payload = json.loads(lines[0])
        self.assertEqual(payload["phase"], "transcribe")
        self.assertEqual(payload["createdBytes"], 42)
        self.assertEqual(payload["index"], 1)

    @mock.patch("avo.telemetry.avo_state.save_state")
    @mock.patch("avo.telemetry.avo_state.load_state")
    def test_cleanup_records_last_cleanup(
        self, load_state: mock.Mock, save_state: mock.Mock
    ) -> None:
        load_state.return_value = {"stats": {}}
        from avo.telemetry import Telemetry

        tel = Telemetry(volume=ROOT)
        with mock.patch("sys.stderr", new_callable=StringIO) as err:
            record = tel.cleanup(freed_bytes=1000, preserved_bytes=500, emit=True)

        self.assertEqual(record["event"], "cleanup")
        self.assertEqual(record["freedBytes"], 1000)
        self.assertEqual(record["preservedBytes"], 500)
        saved = save_state.call_args[0][0]
        self.assertEqual(saved["stats"]["lastCleanup"]["event"], "cleanup")
        err_lines = err.getvalue().strip().splitlines()
        self.assertTrue(any(line.startswith("AVO_JSON ") for line in err_lines))


if __name__ == "__main__":
    unittest.main()
