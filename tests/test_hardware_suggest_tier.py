"""Unit tests for avo.hardware.suggest_tier (VRAM → llm map + Bonsai notes)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _report(
    *, vram_mb: int | None = None, ram_gb: float = 32.0, cores: int = 16
) -> dict:
    """Minimal hardware report for suggest_tier."""
    gpu: list[dict] = []
    if vram_mb is not None and vram_mb > 0:
        gpu = [{"name": "test-gpu", "vendor": "nvidia", "vramMB": vram_mb}]
    elif vram_mb == 0:
        gpu = [{"name": "test-gpu", "vendor": "nvidia", "vramMB": 0}]
    return {
        "gpu": gpu,
        "ram": {"totalBytes": int(ram_gb * (1024**3))},
        "cpu": {"logicalCores": cores},
    }


class SuggestTierTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        sys.path.insert(0, str(ROOT))

    def _tier(self, **kwargs):
        from avo.hardware import suggest_tier

        return suggest_tier(_report(**kwargs))

    def _joined_notes(self, tier: dict) -> str:
        return " ".join(tier.get("notes") or [])

    def test_10gb_qwen7b_bonsai_ternary_and_concurrent_warning(self) -> None:
        tier = self._tier(vram_mb=10240)
        self.assertEqual(tier["llm"], "qwen2.5-7b")
        self.assertEqual(tier["whisper"], "large-v3")
        notes = self._joined_notes(tier)
        self.assertIn("bonsai-27b-gguf", notes)
        self.assertIn("ternary-bonsai-27b-gguf", notes)
        self.assertIn("~4–8 GB", notes)
        self.assertIn("~54 GB", notes)
        self.assertIn("~7–12 GB", notes)
        self.assertIn("large-v3", notes)
        self.assertIn("~10 GB", notes)

    def test_16gb_qwen14b_bonsai_and_ternary(self) -> None:
        tier = self._tier(vram_mb=16 * 1024)
        self.assertEqual(tier["llm"], "qwen2.5-14b")
        notes = self._joined_notes(tier)
        self.assertIn("bonsai-27b-gguf", notes)
        self.assertIn("ternary-bonsai-27b-gguf", notes)

    def test_24gb_qwen32b(self) -> None:
        tier = self._tier(vram_mb=24 * 1024)
        self.assertEqual(tier["llm"], "qwen2.5-32b")
        notes = self._joined_notes(tier)
        self.assertIn("bonsai-27b-gguf", notes)
        self.assertIn("ternary-bonsai-27b-gguf", notes)

    def test_8gb_qwen3b_bonsai_no_ternary(self) -> None:
        tier = self._tier(vram_mb=8192)
        self.assertEqual(tier["llm"], "qwen2.5-3b")
        notes = self._joined_notes(tier)
        self.assertIn("bonsai-27b-gguf", notes)
        self.assertIn("~4–8 GB", notes)
        self.assertIn("~54 GB", notes)
        self.assertNotIn("ternary-bonsai-27b-gguf", notes)

    def test_6gb_experimental_1bit_no_ternary_no_concurrent_claim(self) -> None:
        tier = self._tier(vram_mb=6144)
        self.assertEqual(tier["llm"], "qwen2.5-3b")
        self.assertEqual(tier["whisper"], "medium")
        notes = self._joined_notes(tier)
        self.assertIn("bonsai-27b-gguf", notes)
        self.assertRegex(notes, r"tight|experimental")
        self.assertNotIn("ternary-bonsai-27b-gguf", notes)
        self.assertNotIn("~10 GB", notes)
        self.assertNotIn("large-v3 and bonsai", notes)

    def test_no_gpu_no_bonsai(self) -> None:
        tier = self._tier(vram_mb=None, ram_gb=32.0)
        notes = self._joined_notes(tier)
        self.assertNotIn("bonsai", notes.lower())
        # High RAM → local 3b fallback (or cloud if RAM were low)
        self.assertIn(tier["llm"], ("qwen2.5-3b", "cloud/paid recommended"))

    def test_vram_zero_no_bonsai(self) -> None:
        tier = self._tier(vram_mb=0, ram_gb=4.0)
        notes = self._joined_notes(tier)
        self.assertNotIn("bonsai", notes.lower())
        self.assertTrue(
            tier["llm"].startswith("cloud/") or tier["llm"].startswith("qwen2.5-"),
            msg=f"unexpected llm: {tier['llm']}",
        )


if __name__ == "__main__":
    unittest.main()
