"""Typed values shared by canonical timeline artifacts."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from fractions import Fraction
from typing import Any

_SHA256 = re.compile(r"^[a-f0-9]{64}$")


class TimelineDomain(str, Enum):
    RAW_SOURCE = "raw-source"
    SYNC_CORRECTED_SOURCE = "sync-corrected-source"
    CMAP_OUTPUT = "cmap-output"


class DependencyState(str, Enum):
    VALID = "valid"
    STALE = "stale"
    BLOCKED = "blocked"
    SUPERSEDED = "superseded"


class RevisionState(str, Enum):
    DRAFT = "draft"
    REVIEW_READY = "review-ready"
    APPROVED = "approved"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"
    STALE = "stale"
    BLOCKED = "blocked"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class Timebase:
    num: int
    den: int

    def __post_init__(self) -> None:
        if self.num <= 0 or self.den <= 0:
            raise ValueError("timebase numerator and denominator must be positive")

    @property
    def seconds_per_tick(self) -> Fraction:
        return Fraction(self.num, self.den)


@dataclass(frozen=True)
class FrameRate:
    """Exact video frame rate expressed as frames per second."""

    num: int
    den: int

    def __post_init__(self) -> None:
        if self.num <= 0 or self.den <= 0:
            raise ValueError("frame-rate numerator and denominator must be positive")

    @property
    def seconds_per_frame(self) -> Fraction:
        return Fraction(self.den, self.num)

    def to_dict(self) -> dict[str, int]:
        return {"num": self.num, "den": self.den}


@dataclass(frozen=True)
class ProgramFrame:
    frame: int
    frame_rate: FrameRate

    def __post_init__(self) -> None:
        if self.frame < 0:
            raise ValueError("program frame must be non-negative")

    @property
    def seconds(self) -> Fraction:
        return self.frame * self.frame_rate.seconds_per_frame

    def to_dict(self) -> dict[str, Any]:
        return {"frame": self.frame, "frameRate": self.frame_rate.to_dict()}


@dataclass(frozen=True)
class AudioSample:
    sample: int
    sample_rate: int

    def __post_init__(self) -> None:
        if self.sample < 0:
            raise ValueError("audio sample must be non-negative")
        if self.sample_rate <= 0:
            raise ValueError("sample rate must be positive")

    @property
    def seconds(self) -> Fraction:
        return Fraction(self.sample, self.sample_rate)

    def to_dict(self) -> dict[str, int]:
        return {"sample": self.sample, "sampleRate": self.sample_rate}


@dataclass(frozen=True)
class TimeValue:
    ticks: int
    timebase: Timebase
    domain: TimelineDomain
    source_id: str | None = None

    def __post_init__(self) -> None:
        if (
            self.domain
            in {
                TimelineDomain.RAW_SOURCE,
                TimelineDomain.SYNC_CORRECTED_SOURCE,
            }
            and not self.source_id
        ):
            raise ValueError("source-domain time requires source_id")

    @property
    def seconds(self) -> Fraction:
        return self.ticks * self.timebase.seconds_per_tick


@dataclass(frozen=True)
class Fingerprint:
    sha256: str
    size_bytes: int
    media_signature: dict[str, Any] | None = None
    locator: str | None = None

    def __post_init__(self) -> None:
        if not _SHA256.fullmatch(self.sha256):
            raise ValueError("sha256 must be 64 lowercase hexadecimal characters")
        if self.size_bytes < 0:
            raise ValueError("size_bytes must be non-negative")

    @property
    def identity(self) -> tuple[str, int]:
        """Portable byte identity; locators are deliberately excluded."""
        return self.sha256, self.size_bytes

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "sha256": self.sha256,
            "sizeBytes": self.size_bytes,
        }
        if self.media_signature is not None:
            result["mediaSignature"] = self.media_signature
        if self.locator is not None:
            result["locator"] = self.locator
        return result


@dataclass(frozen=True)
class ArtifactIdentity:
    artifact_type: str
    artifact_id: str
    revision_id: str
    content_sha256: str

    def __post_init__(self) -> None:
        if not all(
            value.strip()
            for value in (self.artifact_type, self.artifact_id, self.revision_id)
        ):
            raise ValueError("artifact identity fields are required")
        if not _SHA256.fullmatch(self.content_sha256):
            raise ValueError("artifact content_sha256 is invalid")

    def to_dict(self) -> dict[str, str]:
        return {
            "artifactType": self.artifact_type,
            "artifactId": self.artifact_id,
            "revisionId": self.revision_id,
            "contentSha256": self.content_sha256,
        }


@dataclass(frozen=True)
class DependencyRef:
    artifact_type: str
    artifact_id: str
    revision_id: str
    sha256: str
    state: DependencyState = DependencyState.VALID
    output_sha256: str | None = None

    def __post_init__(self) -> None:
        if not all((self.artifact_type, self.artifact_id, self.revision_id)):
            raise ValueError("dependency identity fields are required")
        if not _SHA256.fullmatch(self.sha256):
            raise ValueError("dependency sha256 is invalid")
        if self.output_sha256 and not _SHA256.fullmatch(self.output_sha256):
            raise ValueError("dependency output_sha256 is invalid")


_STABLE_ID = re.compile(r"^[a-z][a-z0-9-]{2,63}$")


@dataclass(frozen=True)
class Actor:
    actor_type: str
    actor_id: str
    tool_version: str | None = None

    def __post_init__(self) -> None:
        if self.actor_type not in {"user", "agent", "migration", "system"}:
            raise ValueError("actor_type is invalid")
        if not self.actor_id.strip():
            raise ValueError("actor_id is required")


@dataclass(frozen=True)
class TimeRange:
    start: TimeValue
    end: TimeValue

    def __post_init__(self) -> None:
        if (self.start.domain, self.start.source_id, self.start.timebase) != (
            self.end.domain,
            self.end.source_id,
            self.end.timebase,
        ):
            raise ValueError("range endpoints must share domain, source, and timebase")
        if self.end.ticks <= self.start.ticks:
            raise ValueError("range is half-open and end must be after start")


def validate_stable_id(value: str) -> str:
    if not _STABLE_ID.fullmatch(value):
        raise ValueError("stable ID must match [a-z][a-z0-9-]{2,63}")
    return value


@dataclass(frozen=True)
class StructuredTimelineError:
    code: str
    message: str
    remediation: str
    blocking: bool = True
    artifact_ref: str | None = None
    entity_ref: str | None = None
    field: str | None = None
    expected: Any = None
    actual: Any = None

    def __post_init__(self) -> None:
        if not self.code.strip():
            raise ValueError("failure code is required")
        if not self.message.strip():
            raise ValueError("failure message is required")
        if not self.remediation.strip():
            raise ValueError("failure remediation is required")

    def to_dict(self) -> dict[str, Any]:
        result = {
            "code": self.code,
            "message": self.message,
            "remediation": self.remediation,
            "blocking": self.blocking,
        }
        for key, value in (
            ("artifactRef", self.artifact_ref),
            ("entityRef", self.entity_ref),
            ("field", self.field),
            ("expected", self.expected),
            ("actual", self.actual),
        ):
            if value is not None:
                result[key] = value
        return result
