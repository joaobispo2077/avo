"""Release-blocking checks for the refactored repository layout."""

from __future__ import annotations

import unittest

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
            "avo.timeline-common.schema.json",
            "avo.cmap.schema.json",
            "avo.bmap.schema.json",
            "avo.tracks.schema.json",
            "avo.animation.schema.json",
            "avo.sync-map.schema.json",
            "avo.review-evidence.schema.json",
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

    def test_timeline_bounded_context_layout(self) -> None:
        expected = (
            "src/avo/timeline/__init__.py",
            "src/avo/timeline/models.py",
            "src/avo/timeline/contracts.py",
            "src/avo/timeline/store.py",
            "src/avo/timeline/lifecycle.py",
            "src/avo/timeline/mapping.py",
            "src/avo/timeline/lineage.py",
            "src/avo/timeline/projection.py",
            "src/avo/timeline/sync.py",
            "src/avo/timeline/review.py",
            "src/avo/timeline/migration.py",
            "src/avo/timeline/tracks.py",
            "src/avo/timeline/animation.py",
            "src/avo/adapters/media/__init__.py",
            "src/avo/adapters/media/ffprobe.py",
            "src/avo/adapters/media/sync_materializer.py",
            "src/avo/adapters/media/audio_tracks.py",
            "src/avo/adapters/media/video_tracks.py",
            "src/avo/adapters/media/timeline_render.py",
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
            self.assertFalse(
                (self.root / name).is_file(), msg=f"legacy root file: {name}"
            )

    def test_github_surfaces_do_not_embed_personal_absolute_paths(self) -> None:
        needles = ("/mnt/h/bishop/", "H:/bishop/", "C:/Users/vitor/")
        roots = (
            self.root / "src",
            self.root / "scripts",
            self.root / "commands",
            self.root / "agent-skills",
            self.root / "tests" / "fixtures",
        )
        offenders = []
        for root in roots:
            for path in root.rglob("*"):
                if (
                    not path.is_file()
                    or "__pycache__" in path.parts
                    or path.suffix
                    not in {
                        ".py",
                        ".md",
                        ".json",
                        ".js",
                        ".mjs",
                        ".sh",
                        ".ps1",
                        ".toml",
                        ".yml",
                        ".yaml",
                    }
                ):
                    continue
                content = path.read_text(encoding="utf-8", errors="ignore")
                if any(needle.lower() in content.lower() for needle in needles):
                    offenders.append(str(path.relative_to(self.root)))
        self.assertEqual(offenders, [], msg=f"personal absolute paths: {offenders}")

    def test_no_project_specific_one_off_scripts_or_dependencies(self) -> None:
        repository_scripts = (
            "apply-anchor-rail-pilots.mjs",
            "build-continuous-caption-pilots.mjs",
            "clamp-caption-boundaries.mjs",
            "finalize-switch-shorts-docs.mjs",
            "fix-continuous-caption-pilots.mjs",
            "normalize-switch-short-transcripts.mjs",
            "qc-switch-shorts.sh",
            "revise-switch-short-layouts.mjs",
        )
        known_external_helpers = ("rebuild-nier-inserts.mjs",)
        for name in repository_scripts:
            self.assertFalse(
                (self.root / "scripts" / name).exists(),
                msg=f"project-specific script must stay outside AVO: scripts/{name}",
            )
        self.assertFalse(
            (
                self.root / "tests/fixtures/shorts/switch-migration-inventory.json"
            ).exists(),
            msg="private project migration inventory must stay outside AVO",
        )
        names = repository_scripts + known_external_helpers
        roots = [self.root / "src", self.root / "commands", self.root / "agent-skills"]
        offenders = []
        for root in roots:
            for path in root.rglob("*"):
                if path.is_file() and path.suffix in {
                    ".py",
                    ".md",
                    ".json",
                    ".js",
                    ".mjs",
                    ".sh",
                }:
                    content = path.read_text(encoding="utf-8", errors="ignore")
                    if any(name in content for name in names):
                        offenders.append(str(path.relative_to(self.root)))
        self.assertEqual(offenders, [], msg=f"one-off script dependencies: {offenders}")


if __name__ == "__main__":
    unittest.main()
