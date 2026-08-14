"""Release-blocking checks for the refactored repository layout."""

from __future__ import annotations

import unittest
from pathlib import Path

from avo.paths import config_path, repo_root, schema_path


class RepoLayoutTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = repo_root()

    def test_config_manifests_live_under_config(self) -> None:
        for name in (
            "avo.config.json",
            "avo.dependencies.json",
            "avo.model-catalog.json",
            "avo.model-catalog.schema.json",
        ):
            path = config_path(name)
            self.assertEqual(path.parent, self.root / "config", msg=name)
            self.assertTrue(path.is_file(), msg=name)

    def test_schemas_live_under_schemas(self) -> None:
        for name in (
            "avo.project.schema.json",
            "edl.schema.json",
            "avo.shorts-batch.schema.json",
            "avo.shorts-plan.schema.json",
            "avo.shorts-status.schema.json",
            "avo.shorts-composition.schema.json",
        ):
            path = schema_path(name)
            self.assertEqual(path.parent, self.root / "schemas", msg=name)
            self.assertTrue(path.is_file(), msg=name)

    def test_shorts_runtime_layout(self) -> None:
        expected = (
            "src/avo/shorts.py",
            "src/avo/shorts_contract.py",
            "src/avo/shorts_plan.py",
            "src/avo/shorts_captions.py",
            "src/avo/shorts_media.py",
            "src/avo/shorts_qc.py",
            "src/avo/shorts_delivery.py",
            "src/avo/adapters/motion/hyperframes.py",
            "src/avo/templates/shorts_hyperframes/hyperframes.json",
            "src/avo/templates/shorts_hyperframes/index.html",
            "src/avo/templates/shorts_hyperframes/styles.css",
            "src/avo/templates/shorts_hyperframes/runtime.js",
        )
        for relative_path in expected:
            self.assertTrue((self.root / relative_path).is_file(), msg=relative_path)

    def test_no_duplicate_root_manifests(self) -> None:
        for name in (
            "avo.config.json",
            "avo.dependencies.json",
            "avo.model-catalog.json",
            "avo.project.schema.json",
        ):
            self.assertFalse((self.root / name).is_file(), msg=f"legacy root file: {name}")

    def test_no_runtime_dependency_on_switch_one_off_scripts(self) -> None:
        script_names = (
            "apply-anchor-rail-pilots.mjs", "build-continuous-caption-pilots.mjs",
            "clamp-caption-boundaries.mjs", "finalize-switch-shorts-docs.mjs",
            "fix-continuous-caption-pilots.mjs", "normalize-switch-short-transcripts.mjs",
            "qc-switch-shorts.sh", "revise-switch-short-layouts.mjs",
            "rebuild-nier-inserts.mjs",
        )
        roots = [self.root / "src", self.root / "commands", self.root / "agent-skills"]
        offenders = []
        for root in roots:
            for path in root.rglob("*"):
                if path.is_file() and path.suffix in {".py", ".md", ".json", ".js", ".mjs", ".sh"}:
                    text = path.read_text(encoding="utf-8", errors="ignore")
                    if any(name in text for name in script_names):
                        offenders.append(str(path.relative_to(self.root)))
        self.assertEqual(offenders, [], msg=f"one-off script dependencies: {offenders}")


if __name__ == "__main__":
    unittest.main()
