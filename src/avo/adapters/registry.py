"""Central adapter registry keyed by job and routing suffix."""

from __future__ import annotations

from typing import TYPE_CHECKING

from avo.capabilities import (
    CapabilityImplementation,
    CapabilityRegistry,
    CapabilityRegistryError,
    default_proof_capability_registry,
)

__all__ = [
    "CapabilityImplementation",
    "CapabilityRegistry",
    "CapabilityRegistryError",
    "adapter_for_routing_suffix",
    "build_cutting_service",
    "build_preparation_service",
    "build_sfx_catalog",
    "build_sound_source_probe",
    "default_proof_capability_registry",
]

if TYPE_CHECKING:
    from avo.adapters.base import JobAdapter

TRANSCRIBE_ADAPTERS: dict[str, str] = {
    "faster-whisper": "avo.adapters.transcribe.faster_whisper:FasterWhisperAdapter",
    "elevenlabs": "avo.adapters.transcribe.elevenlabs:ElevenLabsAdapter",
}

UNDERSTAND_ADAPTERS: dict[str, str] = {
    "watch-skill": "avo.adapters.understand.watch_skill:WatchSkillAdapter",
}

MOTION_ADAPTERS: dict[str, str] = {
    "code-drawn": "avo.adapters.motion.code_drawn:CodeDrawnAdapter",
    "hyperframes": "avo.adapters.motion.hyperframes:HyperframesAdapter",
    "remotion": "avo.adapters.stubs.motion_remotion:RemotionStubAdapter",
}

MEMORY_ADAPTERS: dict[str, str] = {
    "ai-memory": "avo.adapters.stubs.memory_ai_memory:AiMemoryStubAdapter",
}

PLAN_ADAPTERS: dict[str, str] = {
    "speckit": "avo.adapters.stubs.plan_speckit:SpeckitStubAdapter",
}

JOB_REGISTRIES: dict[str, dict[str, str]] = {
    "transcribe": TRANSCRIBE_ADAPTERS,
    "understand": UNDERSTAND_ADAPTERS,
    "motion": MOTION_ADAPTERS,
    "memory": MEMORY_ADAPTERS,
    "plan": PLAN_ADAPTERS,
}


def build_sfx_catalog(
    workspace, *, roots, analyze=False, semantic=False, root=None, favorites=None
):
    """Compose only the explicitly selected sound-analysis or matching boundary."""
    from avo.sfx_catalog import SfxCatalogService

    analyzer = backend = None
    if analyze:
        from avo.adapters.media.sfx_analysis import SfxAnalyzer

        analyzer = SfxAnalyzer()
    if semantic:
        from avo.sfx_semantic import build_semantic_backend

        backend = build_semantic_backend(workspace, roots, root=root)
    preferences = {} if favorites is None else {"favorites": favorites}
    return SfxCatalogService(
        workspace, roots=roots, analyzer=analyzer, semantic=backend, **preferences
    )


def adapter_for_routing_suffix(job: str, suffix: str) -> type[JobAdapter]:
    from avo.adapters.base import AdapterError, load_adapter_class

    registry = JOB_REGISTRIES.get(job)
    if registry is None:
        raise AdapterError(f"no adapter registry for job '{job}'")
    module_path = registry.get(suffix)
    if module_path is None:
        known = ", ".join(sorted(registry))
        raise AdapterError(
            f"no adapter for job '{job}' routing suffix '{suffix}' (known: {known})"
        )
    return load_adapter_class(module_path)


def build_sound_source_probe():
    """Observe the first measured audio stream only for explicit sound admission."""
    import subprocess

    from .media.ffprobe import FfprobeMediaAdapter

    def probe(path, *, expected_sha256):
        try:
            source = FfprobeMediaAdapter().inventory([path])["sources"][0]
        except (OSError, subprocess.SubprocessError) as error:
            raise ValueError(
                f"Cannot inspect selected sound source: {error}"
            ) from error
        if source["fingerprint"]["sha256"] != expected_sha256:
            raise ValueError("Selected sound source fingerprint changed during probe")
        streams = source["streams"]["audio"]
        if not streams:
            raise ValueError("Selected sound source has no audio stream")
        stream = streams[0]
        return {
            "sourceSha256": expected_sha256,
            "streamIndex": stream["index"],
            "sampleRate": stream["sampleRate"],
            "channels": stream["channels"],
        }

    return probe


def build_face_analyzer(workspace):
    """Construct the optional adapter only when the source request is admitted."""

    def analyze(source, request):
        from avo.adapters.understand.visual_motion import observe_selected_face
        from avo.model_sources import resolve_job

        resolved = resolve_job(
            "face_detect", project=workspace.project, video_key=workspace.video_id
        )
        return observe_selected_face(resolved, source, request)

    return analyze


def build_reference_analyzer():
    from avo.adapters.understand.visual_motion import observe_reference_clip

    return observe_reference_clip


def build_editor_handoff(workspace):
    from avo.adapters.media.fcp7_xml import parse_fcp7_xml, write_fcp7_xml
    from avo.adapters.media.ffprobe import FfprobeMediaAdapter
    from avo.timeline.editor_handoff import EditorHandoffService

    def inspect_generated(plan, fps):
        from avo.adapters.media.editor_alpha import editor_alpha_copy
        from avo.adapters.media.proof_executor import _generated_inputs
        from avo.proof_composition import create_generated_asset_validator
        from avo.timeline.editor_generated import is_full_canvas_alpha

        sources = _generated_inputs(
            plan, plan["output"], fps, create_generated_asset_validator(workspace)
        )
        for asset in sources.values():
            if is_full_canvas_alpha(asset, plan["output"]):
                asset["editorSource"] = editor_alpha_copy(asset, fps)
        return sources

    return EditorHandoffService(
        workspace,
        inventory=FfprobeMediaAdapter(include_display_rotation=True).inventory,
        write_xml=write_fcp7_xml,
        read_xml=parse_fcp7_xml,
        inspect_generated=inspect_generated,
    )


def build_preparation_service(workspace, *, recover=False):
    """Read-only construction imports no speech adapter or model readiness checks."""
    from avo.timeline.preparation_recovery import PreparationService

    port = None
    if recover:
        from avo.adapters.media.cutting_analysis import CuttingAnalysisAdapter
        from avo.video_context import VideoContext, resolve_context_cutting_policy

        context = VideoContext(
            provider=workspace.project["provider"],
            video_id=workspace.video_id,
            raw_dir=workspace.raw_dir,
            video_key=None,
            project=workspace.project,
        )
        port = CuttingAnalysisAdapter(
            workspace, resolve_context_cutting_policy(context)
        )
    return PreparationService(workspace, recovery_port=port)


def build_cutting_service(workspace, *, invocation=None):
    """Compose cutting tool adapters at the existing external-tool boundary."""
    from avo.adapters.media.cutting_analysis import CuttingAnalysisAdapter
    from avo.adapters.media.cutting_preview import CuttingPreviewAdapter
    from avo.adapters.understand.cutting_context import CuttingContextAdapter
    from avo.adapters.understand.cutting_take_analysis import CuttingTakeAnalysisAdapter
    from avo.adapters.understand.watch_skill import WatchSkillAdapter
    from avo.timeline.cutting_service import CuttingService
    from avo.video_context import (
        VideoContext,
        resolve_context_cutting_policy,
        resolve_context_watch_policy,
    )

    context = VideoContext(
        provider=workspace.project["provider"],
        video_id=workspace.video_id,
        raw_dir=workspace.raw_dir,
        video_key=None,
        project=workspace.project,
    )
    policy = resolve_context_cutting_policy(
        context, invocation=(invocation or {}).get("cutting")
    )
    preview = CuttingPreviewAdapter(workspace)
    watch_policy = resolve_context_watch_policy(context)
    watch_request = {
        "artifact_dir": str(workspace.raw_dir / "edit/review/source-context"),
        "policy": watch_policy.payload(),
        "model_pin": workspace.project.get("models", {}).get("understand", {}),
    }
    watch_request["option_id"] = watch_request["model_pin"].get("id")
    watch = WatchSkillAdapter()
    return CuttingService(
        workspace,
        policy=policy,
        analysis_port=CuttingAnalysisAdapter(workspace, policy),
        preview_port=preview,
        verification_port=preview,
        context_port=CuttingContextAdapter(
            workspace.raw_dir,
            policy.effective,
            watch=watch,
            watch_request=watch_request,
            raw_dir=workspace.raw_dir,
        ),
        retake_port=CuttingTakeAnalysisAdapter(
            watch=watch, watch_request=watch_request, raw_dir=workspace.raw_dir
        ),
    )
