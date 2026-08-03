"""Tests for video_context resolver and locks."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from avo import init_project, video_context, video_registry


class VideoContextTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.raw = self.root / "external-footage"
        self.raw.mkdir()
        (self.raw / "avo.project.json").write_text(
            json.dumps({"provider": "_template", "rawDir": str(self.raw)}),
            encoding="utf-8",
        )
        self.provider_dir = self.root / "providers" / "_template"
        self.provider_dir.mkdir(parents=True)
        (self.provider_dir / "avo.provider.json").write_text(
            json.dumps({"name": "_template", "kind": "youtube", "transcription": {"language": "en"}}),
            encoding="utf-8",
        )
        video_registry.write_registry("_template", "ctx-demo", self.raw, root=self.root)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_resolve_context_by_video_id(self) -> None:
        ctx = video_context.resolve_context(provider="_template", video_id="ctx-demo", root=self.root)
        self.assertEqual(ctx.video_id, "ctx-demo")
        self.assertEqual(ctx.video_key, "_template:ctx-demo")
        self.assertEqual(ctx.raw_dir.resolve(), self.raw.resolve())

    def test_merge_config_includes_project(self) -> None:
        ctx = video_context.resolve_context(provider="_template", video_id="ctx-demo", root=self.root)
        merged = video_context.merge_config(ctx, root=self.root)
        self.assertIn("transcription", merged)

    def test_advisory_lock_acquire_release(self) -> None:
        ctx = video_context.resolve_context(provider="_template", video_id="ctx-demo", root=self.root)
        path = video_context.acquire_lock(ctx)
        self.assertTrue(path.is_file())
        lock = video_context.read_lock(self.raw)
        self.assertIsNotNone(lock)
        self.assertTrue(video_context.release_lock(self.raw))
        self.assertIsNone(video_context.read_lock(self.raw))


class BuildProjectDefaultsTests(unittest.TestCase):
    def test_registry_defaults_applied(self) -> None:
        project = init_project.build_project(
            "_template",
            "H:/footage/x",
            provider_manifest={"assets": {}},
            registry_defaults={"transcription": {"model": "medium"}, "models": {"plan": "qwen2.5-7b"}},
        )
        self.assertEqual(project["transcription"]["model"], "medium")
        self.assertEqual(project["models"]["plan"], "qwen2.5-7b")


if __name__ == "__main__":
    unittest.main()
