from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]


class AdapterStubTests(unittest.TestCase):
    def setUp(self) -> None:
        sys.path.insert(0, str(ROOT))
        from avo.adapters.base import JobRequest

        self.request = JobRequest(job="plan", label="local", argv=[], root=ROOT)

    def test_speckit_stub_when_marker_present(self) -> None:
        from avo.adapters.stubs.plan_speckit import SpeckitStubAdapter

        if not (ROOT / ".specify").exists():
            self.skipTest(".specify marker missing")
        result = SpeckitStubAdapter().run(self.request)
        self.assertEqual(result.exit_code, 2)
        self.assertIn("stub", result.stderr)

    def test_registry_has_stub_jobs(self) -> None:
        from avo.adapters.registry import JOB_REGISTRIES

        for job in ("understand", "motion", "memory", "plan"):
            self.assertIn(job, JOB_REGISTRIES)

    def test_hyperframes_is_a_real_adapter_not_a_stub(self) -> None:
        from avo.adapters.motion.hyperframes import HyperframesAdapter
        from avo.adapters.registry import MOTION_ADAPTERS, adapter_for_routing_suffix

        self.assertNotIn(".stubs.", MOTION_ADAPTERS["hyperframes"])
        self.assertIs(
            adapter_for_routing_suffix("motion", "hyperframes"), HyperframesAdapter
        )


class SfxFactoryTests(unittest.TestCase):
    def modules(self):
        analysis = ModuleType("avo.adapters.media.sfx_analysis")
        analysis.SfxAnalyzer = Mock(return_value=object())
        semantic = ModuleType("avo.sfx_semantic")
        semantic.build_semantic_backend = Mock(return_value=object())
        return analysis, semantic

    def test_default_catalogue_does_not_construct_analysis_or_matching(self):
        from avo.adapters.registry import build_sfx_catalog

        analysis, semantic = self.modules()
        with (
            tempfile.TemporaryDirectory() as folder,
            patch.dict(
                sys.modules, {analysis.__name__: analysis, semantic.__name__: semantic}
            ),
        ):
            workspace = SimpleNamespace(raw_dir=Path(folder) / "footage")
            roots = {"sfx": Path(folder) / "sounds"}
            service = build_sfx_catalog(workspace, roots=roots)
            self.assertIs(service.workspace, workspace)
            self.assertIsNone(service.analyzer)
            self.assertIsNone(service.semantic)
            self.assertEqual(service.show()["entries"], [])
            self.assertFalse(service.directory.exists())
            analysis.SfxAnalyzer.assert_not_called()
            semantic.build_semantic_backend.assert_not_called()

    def test_explicit_modes_construct_only_the_selected_boundaries(self):
        from avo.adapters.registry import build_sfx_catalog

        for analyze, match in ((True, False), (False, True), (True, True)):
            with self.subTest(analyze=analyze, semantic=match):
                analysis, semantic = self.modules()
                with (
                    tempfile.TemporaryDirectory() as folder,
                    patch.dict(
                        sys.modules,
                        {analysis.__name__: analysis, semantic.__name__: semantic},
                    ),
                ):
                    workspace = SimpleNamespace(raw_dir=Path(folder) / "footage")
                    roots = {"sfx": Path(folder) / "sounds"}
                    repository = Path(folder) / "repository"
                    service = build_sfx_catalog(
                        workspace,
                        roots=roots,
                        analyze=analyze,
                        semantic=match,
                        root=repository,
                    )
                    self.assertIs(
                        service.analyzer,
                        analysis.SfxAnalyzer.return_value if analyze else None,
                    )
                    self.assertIs(
                        service.semantic,
                        semantic.build_semantic_backend.return_value if match else None,
                    )
                    self.assertEqual(analysis.SfxAnalyzer.call_count, int(analyze))
                    if match:
                        semantic.build_semantic_backend.assert_called_once_with(
                            workspace, roots, root=repository
                        )
                    else:
                        semantic.build_semantic_backend.assert_not_called()
                    self.assertFalse(service.directory.exists())


if __name__ == "__main__":
    unittest.main()
