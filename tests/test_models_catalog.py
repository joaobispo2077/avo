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
        from avo.models import load_catalog

        catalog = load_catalog(ROOT)
        opts = catalog["jobs"]["transcribe"]["options"]
        ids = [o["id"] for o in opts]
        self.assertIn("small", ids)
        self.assertIn("large-v3", ids)

    def test_resolve_default_transcribe(self) -> None:
        from avo.models import resolve_option_id

        with mock.patch("avo.models.avo_state.load_state", return_value={}):
            model_id = resolve_option_id("transcribe", root=ROOT)
        self.assertEqual(model_id, "small")

    def test_project_override_transcribe(self) -> None:
        from avo.models import resolve_option_id

        project = {"transcription": {"model": "medium"}}
        with mock.patch("avo.models.avo_state.load_state", return_value={}):
            model_id = resolve_option_id("transcribe", root=ROOT, project=project)
        self.assertEqual(model_id, "medium")

    def test_state_whisper_override(self) -> None:
        from avo.models import resolve_option_id

        state = {"transcription": {"model": "base"}}
        with mock.patch("avo.models.avo_state.load_state", return_value=state):
            model_id = resolve_option_id("transcribe", root=ROOT)
        self.assertEqual(model_id, "base")

    def test_list_alternatives_lighter_heavier(self) -> None:
        from avo.models import list_alternatives

        with mock.patch("avo.models.avo_state.load_state", return_value={}):
            alt = list_alternatives("transcribe", root=ROOT)
        self.assertEqual(alt.current_id, "small")
        self.assertTrue(any(o["id"] == "base" for o in alt.lighter))
        self.assertTrue(any(o["id"] == "medium" for o in alt.heavier))

    def test_resolve_active_models_shape(self) -> None:
        from avo.models import resolve_active_models

        with mock.patch("avo.models.avo_state.load_state", return_value={}):
            with mock.patch("avo.models._hardware_tier", return_value=None):
                active = resolve_active_models(ROOT)
        self.assertIn("transcribe", active)
        self.assertIn("understand", active)
        self.assertEqual(active["transcribe"], "faster-whisper:small")

    def test_paid_transcribe_job_key(self) -> None:
        from avo.models import resolve_option_id

        with mock.patch("avo.models.avo_state.load_state", return_value={}):
            pid = resolve_option_id("transcribe", root=ROOT, label="paid")
        catalog = json.loads(
            (ROOT / "config" / "avo.model-catalog.json").read_text(encoding="utf-8")
        )
        default_paid = catalog["jobs"]["transcribe_paid"]["default"]
        self.assertEqual(pid, default_paid)

    def test_understand_catalog_includes_bonsai_after_qwen32(self) -> None:
        from avo.models import load_catalog

        catalog = load_catalog(ROOT)
        understand = catalog["jobs"]["understand"]
        ids = [o["id"] for o in understand["options"]]
        self.assertEqual(understand["default"], "qwen2.5-7b")
        self.assertEqual(understand["backend"], "qwen2.5")
        self.assertIn("bonsai-27b-gguf", ids)
        self.assertIn("ternary-bonsai-27b-gguf", ids)
        self.assertGreater(ids.index("bonsai-27b-gguf"), ids.index("qwen2.5-32b"))
        self.assertGreater(
            ids.index("ternary-bonsai-27b-gguf"), ids.index("bonsai-27b-gguf")
        )
        plan_ids = [o["id"] for o in catalog["jobs"]["plan"]["options"]]
        self.assertNotIn("bonsai-27b-gguf", plan_ids)
        self.assertNotIn("ternary-bonsai-27b-gguf", plan_ids)
        one_bit = next(o for o in understand["options"] if o["id"] == "bonsai-27b-gguf")
        ternary = next(
            o for o in understand["options"] if o["id"] == "ternary-bonsai-27b-gguf"
        )
        self.assertEqual(
            one_bit["label"], "Bonsai 27B GGUF (1-bit · ~8 GB ≈ Qwen3.6-27B ~54 GB)"
        )
        self.assertEqual(one_bit["vramMB"], 8192)
        self.assertEqual(one_bit["diskMB"], 5000)
        self.assertEqual(one_bit["speed"], "balanced")
        self.assertEqual(one_bit["quality"], "high")
        self.assertEqual(one_bit["hfRepo"], "prism-ml/Bonsai-27B-gguf")
        self.assertIn("mmproj", one_bit["notes"])
        self.assertIn("custom", one_bit["notes"])
        self.assertIn("Apache 2.0", one_bit["notes"])
        self.assertIn("Not default", one_bit["notes"])
        self.assertIn("Qwen3.6-27B", one_bit["notes"])
        self.assertIn("~8 GB", one_bit["notes"])
        self.assertIn("~54 GB", one_bit["notes"])
        self.assertIn("not a 7B", one_bit["notes"])
        self.assertEqual(ternary["hfRepo"], "prism-ml/Ternary-Bonsai-27B-gguf")
        self.assertEqual(
            ternary["label"],
            "Ternary Bonsai 27B GGUF (~12 GB ≈ Qwen3.6-27B ~54 GB)",
        )
        self.assertGreater(ternary["vramMB"], one_bit["vramMB"])
        self.assertGreater(ternary["diskMB"], one_bit["diskMB"])
        self.assertIn("Heavier", ternary["notes"])
        self.assertIn("fits-like-7B", ternary["notes"])
        self.assertIn("Qwen3.6-27B", ternary["notes"])
        self.assertIn("~10–12 GB", ternary["notes"])
        self.assertIn("~54 GB", ternary["notes"])
        self.assertIn("mmproj", ternary["notes"])
        self.assertIn("Apache 2.0", ternary["notes"])

    def test_resolve_default_understand_is_qwen_7b(self) -> None:
        from avo.models import resolve_option_id

        with mock.patch("avo.models.avo_state.load_state", return_value={}):
            model_id = resolve_option_id("understand", root=ROOT)
        self.assertEqual(model_id, "qwen2.5-7b")

    def test_understand_7b_next_heavier_stays_14b(self) -> None:
        from avo.models import list_alternatives

        with mock.patch("avo.models.avo_state.load_state", return_value={}):
            alt = list_alternatives("understand", root=ROOT)
        self.assertEqual(alt.current_id, "qwen2.5-7b")
        self.assertEqual(alt.heavier[0]["id"], "qwen2.5-14b")

    def test_models_cli_show_json(self) -> None:
        from helpers import models_cli

        with mock.patch("avo.models.avo_state.load_state", return_value={}):
            with mock.patch("avo.models._hardware_tier", return_value=None):
                with mock.patch("sys.stdout") as out:
                    code = models_cli.main(["show", "--json", "--root", str(ROOT)])
        self.assertEqual(code, 0)
        payload = json.loads(
            "".join(c.args[0] for c in out.write.call_args_list if c.args)
        )
        self.assertIn("activeModels", payload)

    def test_state_pin_understand_bonsai_wins_over_hardware(self) -> None:
        from avo.models import resolve_option_id

        state = {"models": {"understand": "bonsai-27b-gguf"}}
        hardware = {"llm": "qwen2.5-32b"}
        with mock.patch("avo.models.avo_state.load_state", return_value=state):
            with mock.patch("avo.models._hardware_tier", return_value=hardware):
                model_id = resolve_option_id(
                    "understand",
                    root=ROOT,
                    hardware_tier=hardware,
                )
        self.assertEqual(model_id, "bonsai-27b-gguf")

    def test_project_pin_understand_wins_over_state(self) -> None:
        from avo.models import resolve_option_id

        state = {"models": {"understand": "bonsai-27b-gguf"}}
        project = {"models": {"understand": "ternary-bonsai-27b-gguf"}}
        with mock.patch("avo.models.avo_state.load_state", return_value=state):
            model_id = resolve_option_id("understand", root=ROOT, project=project)
        self.assertEqual(model_id, "ternary-bonsai-27b-gguf")

    def test_models_cli_show_json_pinned_bonsai_label(self) -> None:
        from helpers import models_cli

        state = {"models": {"understand": "bonsai-27b-gguf"}}
        with mock.patch("avo.models.avo_state.load_state", return_value=state):
            with mock.patch("avo.models._hardware_tier", return_value=None):
                with mock.patch("sys.stdout") as out:
                    code = models_cli.main(["show", "--json", "--root", str(ROOT)])
        self.assertEqual(code, 0)
        payload = json.loads(
            "".join(c.args[0] for c in out.write.call_args_list if c.args)
        )
        self.assertEqual(
            payload["activeModels"]["understand"],
            "Bonsai 27B GGUF (1-bit · ~8 GB ≈ Qwen3.6-27B ~54 GB)",
        )

    def test_unpinned_default_disclosure_names_qwen_7b(self) -> None:
        from helpers import models_cli

        with mock.patch("avo.models.avo_state.load_state", return_value={}):
            with mock.patch("avo.models._hardware_tier", return_value=None):
                with mock.patch("sys.stdout") as out:
                    code = models_cli.main(["show", "--json", "--root", str(ROOT)])
        self.assertEqual(code, 0)
        payload = json.loads(
            "".join(c.args[0] for c in out.write.call_args_list if c.args)
        )
        self.assertEqual(payload["activeModels"]["understand"], "Qwen 2.5 7B")


if __name__ == "__main__":
    unittest.main()
