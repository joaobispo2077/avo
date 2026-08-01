"""Central adapter registry keyed by job and routing suffix."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from helpers.adapters.base import JobAdapter

TRANSCRIBE_ADAPTERS: dict[str, str] = {
    "faster-whisper": "helpers.adapters.transcribe.faster_whisper:FasterWhisperAdapter",
    "elevenlabs": "helpers.adapters.transcribe.elevenlabs:ElevenLabsAdapter",
}

UNDERSTAND_ADAPTERS: dict[str, str] = {
    "watch-skill": "helpers.adapters.stubs.understand_watch_skill:WatchSkillStubAdapter",
}

MOTION_ADAPTERS: dict[str, str] = {
    "hyperframes": "helpers.adapters.stubs.motion_hyperframes:HyperframesStubAdapter",
    "remotion": "helpers.adapters.stubs.motion_remotion:RemotionStubAdapter",
}

MEMORY_ADAPTERS: dict[str, str] = {
    "ai-memory": "helpers.adapters.stubs.memory_ai_memory:AiMemoryStubAdapter",
}

PLAN_ADAPTERS: dict[str, str] = {
    "speckit": "helpers.adapters.stubs.plan_speckit:SpeckitStubAdapter",
}

JOB_REGISTRIES: dict[str, dict[str, str]] = {
    "transcribe": TRANSCRIBE_ADAPTERS,
    "understand": UNDERSTAND_ADAPTERS,
    "motion": MOTION_ADAPTERS,
    "memory": MEMORY_ADAPTERS,
    "plan": PLAN_ADAPTERS,
}


def adapter_for_routing_suffix(job: str, suffix: str) -> type["JobAdapter"]:
    from helpers.adapters.base import AdapterError, load_adapter_class

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
