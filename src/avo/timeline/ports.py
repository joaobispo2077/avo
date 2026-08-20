"""Protocols for the real external boundaries of the timeline runtime."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class ToolError(Exception):
    code: str
    message: str
    retryable: bool = False
    remediation: str = ""

    def __str__(self) -> str:
        return f"{self.code}: {self.message}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "retryable": self.retryable,
            "remediation": self.remediation,
        }


@runtime_checkable
class MediaIdentityPort(Protocol):
    def fingerprint(self, path: Path) -> dict[str, Any]: ...


@runtime_checkable
class RawInventoryPort(Protocol):
    def inventory(self, paths: list[Path]) -> dict[str, Any]: ...


@runtime_checkable
class TranscriptionPort(Protocol):
    def transcribe(self, candidate: Path, **options: Any) -> dict[str, Any]: ...


@runtime_checkable
class WatchReviewPort(Protocol):
    def review(self, candidate: Path, **request: Any) -> dict[str, Any]: ...


@runtime_checkable
class TimelineRenderPort(Protocol):
    def render(
        self, projection: Path, output: Path, **request: Any
    ) -> dict[str, Any]: ...


@runtime_checkable
class DeterministicQcPort(Protocol):
    def check(self, candidate: Path, **request: Any) -> dict[str, Any]: ...


@runtime_checkable
class AudioQcPort(Protocol):
    def check_audio(self, candidate: Path, **request: Any) -> dict[str, Any]: ...


@runtime_checkable
class VisualQcPort(Protocol):
    def check_visual(self, candidate: Path, **request: Any) -> dict[str, Any]: ...


@runtime_checkable
class AccessibilityQcPort(Protocol):
    def check_accessibility(
        self, candidate: Path, **request: Any
    ) -> dict[str, Any]: ...


@runtime_checkable
class RightsPolicyPort(Protocol):
    def check_rights(self, candidate: Path, **request: Any) -> dict[str, Any]: ...


@runtime_checkable
class SyncValidationPort(Protocol):
    def validate_sync(self, **request: Any) -> dict[str, Any]: ...


@runtime_checkable
class FixExecutorPort(Protocol):
    def apply_fix(
        self, findings: list[dict[str, Any]], **request: Any
    ) -> dict[str, Any]: ...


@runtime_checkable
class ApprovalPort(Protocol):
    def record_decision(self, **request: Any) -> dict[str, Any]: ...


@runtime_checkable
class ClockPort(Protocol):
    def now_iso(self) -> str: ...


@runtime_checkable
class ArtifactStorePort(Protocol):
    def load_index(self) -> dict[str, Any]: ...
    def append_revision(self, **request: Any) -> dict[str, Any]: ...
