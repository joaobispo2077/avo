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


class PreparationFactoryTests(unittest.TestCase):
    def boundaries(self):
        preparation = ModuleType("avo.timeline.preparation_recovery")
        preparation.PreparationService = Mock(
            side_effect=lambda workspace, **kwargs: SimpleNamespace(
                workspace=workspace, **kwargs
            )
        )
        analysis = ModuleType("avo.adapters.media.cutting_analysis")
        analysis.CuttingAnalysisAdapter = Mock(return_value=object())
        context = ModuleType("avo.video_context")
        context.VideoContext = Mock(return_value=object())
        context.resolve_context_cutting_policy = Mock(return_value=object())
        return preparation, analysis, context

    def test_metadata_default_never_constructs_speech_or_resolves_model_policy(self):
        from avo.adapters.registry import build_preparation_service

        preparation, analysis, context = self.boundaries()
        workspace = SimpleNamespace(
            project={"provider": "channel"}, video_id="video", raw_dir=Path("footage")
        )
        with patch.dict(
            sys.modules,
            {module.__name__: module for module in (preparation, analysis, context)},
        ):
            service = build_preparation_service(workspace)
        self.assertIs(service.workspace, workspace)
        self.assertIsNone(service.recovery_port)
        analysis.CuttingAnalysisAdapter.assert_not_called()
        context.VideoContext.assert_not_called()
        context.resolve_context_cutting_policy.assert_not_called()

    def test_explicit_recovery_constructs_only_the_selected_speech_boundary(self):
        from avo.adapters.registry import build_preparation_service

        preparation, analysis, context = self.boundaries()
        workspace = SimpleNamespace(
            project={"provider": "channel"}, video_id="video", raw_dir=Path("footage")
        )
        with patch.dict(
            sys.modules,
            {module.__name__: module for module in (preparation, analysis, context)},
        ):
            service = build_preparation_service(workspace, recover=True)
        self.assertIs(
            service.recovery_port, analysis.CuttingAnalysisAdapter.return_value
        )
        context.VideoContext.assert_called_once_with(
            provider="channel",
            video_id="video",
            raw_dir=workspace.raw_dir,
            video_key=None,
            project=workspace.project,
        )
        context.resolve_context_cutting_policy.assert_called_once_with(
            context.VideoContext.return_value
        )


if __name__ == "__main__":
    unittest.main()
