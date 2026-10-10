"""Proof capability registry shared by timeline compilation and adapters."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar


class CapabilityRegistryError(RuntimeError):
    """Raised when a proof capability cannot be registered or resolved safely."""


@dataclass(frozen=True)
class CapabilityImplementation:
    implementation_id: str
    capability: str
    kind: str
    adapter_id: str
    version: str
    sha256: str
    compatible: bool = True
    component_instance_id: str | None = None
    generated_asset_id: str | None = None

    def proof_reference(self) -> dict[str, Any]:
        value: dict[str, Any] = {
            "implementationId": self.implementation_id,
            "kind": self.kind,
            "adapterId": self.adapter_id,
            "version": self.version,
            "sha256": self.sha256,
        }
        if self.component_instance_id:
            value["componentInstanceId"] = self.component_instance_id
        if self.generated_asset_id:
            value["generatedAssetId"] = self.generated_asset_id
        return value


class CapabilityRegistry:
    """Resolve built-ins before provider and project-local implementations."""

    _PRIORITY: ClassVar[dict[str, int]] = {
        "built-in": 0,
        "provider-component": 1,
        "project-component": 2,
        "custom-project": 3,
    }
    _FORBIDDEN_METADATA: ClassVar[set[str]] = {
        "command",
        "argv",
        "shell",
        "executable",
        "scriptText",
    }

    def __init__(self) -> None:
        self._items: dict[str, CapabilityImplementation] = {}

    def register(self, implementation: CapabilityImplementation) -> None:
        if implementation.kind not in self._PRIORITY:
            raise CapabilityRegistryError(
                f"unsupported implementation kind: {implementation.kind}"
            )
        if not re.fullmatch(r"[a-f0-9]{64}", implementation.sha256):
            raise CapabilityRegistryError("implementation requires an exact sha256")
        previous = self._items.get(implementation.implementation_id)
        if previous is not None and previous != implementation:
            raise CapabilityRegistryError(
                "implementation ID is already registered with different content: "
                f"{implementation.implementation_id}"
            )
        self._items[implementation.implementation_id] = implementation

    def register_record(self, record: dict[str, Any]) -> CapabilityImplementation:
        forbidden = self._FORBIDDEN_METADATA.intersection(record)
        if forbidden:
            raise CapabilityRegistryError(
                "capability records cannot contain executable command text: "
                + ", ".join(sorted(forbidden))
            )
        implementation = CapabilityImplementation(
            implementation_id=str(record["implementationId"]),
            capability=str(record["capability"]),
            kind=str(record["kind"]),
            adapter_id=str(record["adapterId"]),
            version=str(record["version"]),
            sha256=str(record["sha256"]),
            compatible=bool(record.get("compatible", True)),
            component_instance_id=record.get("componentInstanceId"),
            generated_asset_id=record.get("generatedAssetId"),
        )
        self.register(implementation)
        return implementation

    def resolve(
        self, capability: str, *, implementation_id: str | None = None
    ) -> CapabilityImplementation | None:
        candidates = [
            item
            for item in self._items.values()
            if item.capability == capability and item.compatible
        ]
        if implementation_id is not None:
            candidates = [
                item
                for item in candidates
                if item.implementation_id == implementation_id
            ]
        if not candidates:
            return None
        return min(
            candidates,
            key=lambda item: (self._PRIORITY[item.kind], item.implementation_id),
        )

    def implementations(self) -> tuple[CapabilityImplementation, ...]:
        return tuple(self._items[key] for key in sorted(self._items))


_PROOF_BUILTINS = {
    "trim": "ffmpeg.trim",
    "concatenate": "ffmpeg.concat",
    "crop": "ffmpeg.crop",
    "rotate": "ffmpeg.rotate",
    "scale": "ffmpeg.scale",
    "place-composite": "ffmpeg.overlay",
    "overlay-image": "ffmpeg.overlay",
    "overlay-video": "ffmpeg.overlay",
    "opacity-fade": "ffmpeg.fade",
    "gain": "ffmpeg.volume",
    "ducking": "ffmpeg.sidechaincompress",
    "source-audio-retention": "ffmpeg.audio-source",
    "sfx-placement": "ffmpeg.amix",
    "text-card-graphic": "hyperframes.timeline-instance",
    "caption-ordering": "hyperframes.timeline-instance",
    "color-grade-reference": "ffmpeg.color",
    "encode": "ffmpeg.encode",
}

_PROOF_CODE_PATHS = (
    Path(__file__).parent / "adapters" / "media" / "proof_executor.py",
    Path(__file__).parent / "adapters" / "media" / "timeline_render.py",
    Path(__file__).parent / "audio_restoration.py",
)


def _implementation_digest(capability: str, adapter_id: str) -> str:
    digest = hashlib.sha256(
        f"avo-proof-capability-v1:{capability}:{adapter_id}".encode()
    )
    if adapter_id.startswith("ffmpeg."):
        for path in _PROOF_CODE_PATHS:
            data = path.read_bytes()
            digest.update(path.name.encode())
            digest.update(len(data).to_bytes(8, "big"))
            digest.update(data)
    return digest.hexdigest()


def default_proof_capability_registry() -> CapabilityRegistry:
    registry = CapabilityRegistry()
    for capability, adapter_id in sorted(_PROOF_BUILTINS.items()):
        digest = _implementation_digest(capability, adapter_id)
        registry.register(
            CapabilityImplementation(
                implementation_id=f"impl-{capability}"[:64],
                capability=capability,
                kind="built-in",
                adapter_id=adapter_id,
                version="1.0.0",
                sha256=digest,
            )
        )
    return registry
