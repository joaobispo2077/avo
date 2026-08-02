from __future__ import annotations

import json
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]


class ValidateDependenciesManifestTests(unittest.TestCase):
    def test_manifest_required_tools(self) -> None:
        data = json.loads((ROOT / "config" / "avo.dependencies.json").read_text(encoding="utf-8"))
        tools = data["tools"]
        self.assertEqual(tools["watch-skill"]["repo"], "https://github.com/oxbshw/watch-skill")
        self.assertEqual(tools["watch-skill"]["path"], "tools/watch-skill")

    def test_routing_alignment(self) -> None:
        import sys

        sys.path.insert(0, str(ROOT))
        from avo.validate_dependencies import (
            load_manifest,
            load_routing,
            routing_covers_manifest,
        )

        manifest = load_manifest(ROOT)
        routing = load_routing(ROOT)
        missing = routing_covers_manifest(routing, manifest)
        self.assertEqual(missing, [])

    def test_python_project_check(self) -> None:
        import sys

        sys.path.insert(0, str(ROOT))
        from avo.validate_dependencies import check_python_project

        result = check_python_project(
            ROOT,
            "avo-engine",
            {
                "manifest": "pyproject.toml",
                "helpers": ["src/avo/transcribe.py"],
            },
        )
        self.assertEqual(result.status, "OK")

    def test_avo_engine_has_legacy_alias(self) -> None:
        data = json.loads((ROOT / "config" / "avo.dependencies.json").read_text(encoding="utf-8"))
        engine = data["tools"]["avo-engine"]
        self.assertIn("video-use-engine", engine.get("aliases", []))

    def test_deprecated_alias_tool_skipped_with_warn(self) -> None:
        import sys

        sys.path.insert(0, str(ROOT))
        from avo.validate_dependencies import iter_canonical_tools

        tools = {
            "avo-engine": {"aliases": ["video-use-engine"], "kind": "python-project"},
            "video-use-engine": {"kind": "python-project"},
        }
        canonical, warnings = iter_canonical_tools(tools)
        self.assertEqual(len(canonical), 1)
        self.assertEqual(canonical[0][0], "avo-engine")
        self.assertTrue(any(w.tool == "video-use-engine" for w in warnings))

    @mock.patch("avo.validate_dependencies.repo_reachable", return_value=True)
    @mock.patch("avo.validate_dependencies.shallow_clone", return_value=True)
    def test_watch_skill_shallow_clone_ci(self, _clone: mock.Mock, _reachable: mock.Mock) -> None:
        import sys

        sys.path.insert(0, str(ROOT))
        from avo.validate_dependencies import check_git_clone

        spec = {
            "repo": "https://github.com/oxbshw/watch-skill",
            "path": "tools/watch-skill-ci-test-mock",
            "ciPolicy": "shallow-clone-if-missing",
        }
        result = check_git_clone(ROOT, "watch-skill", spec, ci=True)
        self.assertIn(result.status, ("OK", "WARN"))


if __name__ == "__main__":
    unittest.main()
