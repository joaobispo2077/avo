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

    @mock.patch("helpers.telemetry.avo_state.save_state")
    @mock.patch("helpers.telemetry.avo_state.load_state")
    def test_report_includes_active_models(
        self, load_state: mock.Mock, save_state: mock.Mock
    ) -> None:
        load_state.return_value = {"stats": {}}
        from helpers.telemetry import Telemetry

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

    @mock.patch("helpers.telemetry.avo_state.save_state")
    @mock.patch("helpers.telemetry.avo_state.load_state")
    @mock.patch("helpers.models.resolve_active_models")
    def test_report_resolves_models_when_omitted(
        self, resolve: mock.Mock, load_state: mock.Mock, save_state: mock.Mock
    ) -> None:
        load_state.return_value = {"stats": {}}
        resolve.return_value = {"transcribe": "faster-whisper:medium"}
        from helpers.telemetry import Telemetry

        tel = Telemetry(volume=ROOT)
        record = tel.report("cut", emit=False)
        self.assertEqual(record["activeModels"]["transcribe"], "faster-whisper:medium")
        resolve.assert_called_once()

    @mock.patch("helpers.telemetry.avo_state.save_state")
    @mock.patch("helpers.telemetry.avo_state.load_state")
    def test_report_survives_model_resolver_failure(
        self, load_state: mock.Mock, save_state: mock.Mock
    ) -> None:
        load_state.return_value = {"stats": {}}
        from helpers.telemetry import Telemetry

        tel = Telemetry(volume=ROOT)
        with mock.patch(
            "helpers.models.resolve_active_models",
            side_effect=RuntimeError("no catalog"),
        ):
            record = tel.report("plan", emit=False)
        self.assertNotIn("activeModels", record)


if __name__ == "__main__":
    unittest.main()
