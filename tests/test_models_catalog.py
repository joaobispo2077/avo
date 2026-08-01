from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]


class ModelCatalogTests(unittest.TestCase):
    def setUp(self) -> None:
        sys.path.insert(0, str(ROOT))

    def test_catalog_loads_and_has_transcribe_options(self) -> None:
        from helpers.models import load_catalog

        catalog = load_catalog(ROOT)
        opts = catalog["jobs"]["transcribe"]["options"]
        ids = [o["id"] for o in opts]
        self.assertIn("small", ids)
        self.assertIn("large-v3", ids)

    def test_resolve_default_transcribe(self) -> None:
        from helpers.models import resolve_option_id

        with mock.patch("helpers.models.avo_state.load_state", return_value={}):
            model_id = resolve_option_id("transcribe", root=ROOT)
        self.assertEqual(model_id, "small")

    def test_project_override_transcribe(self) -> None:
        from helpers.models import resolve_option_id

        project = {"transcription": {"model": "medium"}}
        with mock.patch("helpers.models.avo_state.load_state", return_value={}):
            model_id = resolve_option_id("transcribe", root=ROOT, project=project)
        self.assertEqual(model_id, "medium")

    def test_state_whisper_override(self) -> None:
        from helpers.models import resolve_option_id

        state = {"transcription": {"model": "base"}}
        with mock.patch("helpers.models.avo_state.load_state", return_value=state):
            model_id = resolve_option_id("transcribe", root=ROOT)
        self.assertEqual(model_id, "base")

    def test_list_alternatives_lighter_heavier(self) -> None:
        from helpers.models import list_alternatives

        with mock.patch("helpers.models.avo_state.load_state", return_value={}):
            alt = list_alternatives("transcribe", root=ROOT)
        self.assertEqual(alt.current_id, "small")
        self.assertTrue(any(o["id"] == "base" for o in alt.lighter))
        self.assertTrue(any(o["id"] == "medium" for o in alt.heavier))

    def test_resolve_active_models_shape(self) -> None:
        from helpers.models import resolve_active_models

        with mock.patch("helpers.models.avo_state.load_state", return_value={}):
            with mock.patch("helpers.models._hardware_tier", return_value=None):
                active = resolve_active_models(ROOT)
        self.assertIn("transcribe", active)
        self.assertIn("understand", active)
        self.assertEqual(active["transcribe"], "faster-whisper:small")

    def test_paid_transcribe_job_key(self) -> None:
        from helpers.models import resolve_option_id

        with mock.patch("helpers.models.avo_state.load_state", return_value={}):
            pid = resolve_option_id("transcribe", root=ROOT, label="paid")
        catalog = json.loads((ROOT / "avo.model-catalog.json").read_text(encoding="utf-8"))
        default_paid = catalog["jobs"]["transcribe_paid"]["default"]
        self.assertEqual(pid, default_paid)

    def test_models_cli_show_json(self) -> None:
        from helpers import models_cli

        with mock.patch("helpers.models.avo_state.load_state", return_value={}):
            with mock.patch("helpers.models._hardware_tier", return_value=None):
                with mock.patch("sys.stdout") as out:
                    code = models_cli.main(["show", "--json", "--root", str(ROOT)])
        self.assertEqual(code, 0)
        payload = json.loads("".join(c.args[0] for c in out.write.call_args_list if c.args))
        self.assertIn("activeModels", payload)


if __name__ == "__main__":
    unittest.main()
