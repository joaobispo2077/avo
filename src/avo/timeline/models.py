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
