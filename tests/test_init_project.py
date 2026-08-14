from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"

from avo import init_project  # noqa: E402


class InitProjectTests(unittest.TestCase):
    def test_print_only_with_template_provider(self) -> None:
        code = init_project.main(
            [
                "--provider",
                "_template",
                "--raw-dir",
                "/tmp/avo-test-raw",
                "--print",
                "--yes",
            ]
        )
        self.assertEqual(code, 0)

    def test_build_project_structure(self) -> None:
        manifest = init_project.load_provider("_template", root=ROOT)
        project = init_project.build_project(
            "_template",
            "H:/footage/demo",
            provider_manifest=manifest,
            config=init_project.load_config(ROOT),
        )
        self.assertEqual(project["provider"], "_template")
        self.assertEqual(project["rawDir"], "H:/footage/demo")
        self.assertIn("assets", project)

    def test_initialize_timeline_layout_is_additive(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            raw = Path(tmp)
            timeline = init_project.initialize_timeline_layout(raw)
            self.assertEqual(timeline, raw / "edit" / "timeline")
            for artifact in init_project.TIMELINE_ARTIFACTS:
                self.assertTrue((timeline / "revisions" / artifact).is_dir())
            projection = json.loads(
                (timeline / "projection.json").read_text(encoding="utf-8")
            )
            self.assertEqual(projection["status"], "not-generated")
            init_project.initialize_timeline_layout(raw)
            self.assertEqual(
                json.loads((timeline / "projection.json").read_text())["status"],
                "not-generated",
            )


    def test_initialize_with_identity_creates_valid_empty_indexes(self) -> None:
        import tempfile
        from avo.timeline.store import ArtifactStore
        with tempfile.TemporaryDirectory() as tmp:
            timeline=init_project.initialize_timeline_layout(tmp,video_id="demo",provider="bishop")
            for artifact in init_project.TIMELINE_ARTIFACTS:
                index=ArtifactStore(timeline/f"{artifact}.json").load_index()
                self.assertIsNone(index["headRevisionId"])
                self.assertIsNone(index["approvedRevisionId"])
                self.assertEqual(index["revisionRefs"],[])

    def test_help_exits_zero(self) -> None:
        proc = subprocess.run(
            [sys.executable, "-m", "avo.init_project", "--help"],
            cwd=ROOT,
            env={**os.environ, "PYTHONPATH": str(SRC)},
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0)
        self.assertIn("avo.project.json", proc.stdout)


if __name__ == "__main__":
    unittest.main()
