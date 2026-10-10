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
