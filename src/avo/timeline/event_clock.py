"""Normative exact mappings between program frames and audio samples."""

from __future__ import annotations

from copy import deepcopy
from typing import Any


class EventClockError(ValueError):
    """Raised when an event-clock value cannot be resolved safely."""


TIMED_EVENT_ROLES = frozenset(
    {
        "main-scene",
        "overlay-image",
        "overlay-video",
        "authored-graphic",
        "caption",
        "source-audio",
        "music",
        "sfx",
        "ambience",
        "comparison-only",
    }
)
_ORDINARY_EFFECT_OVERLAYS = frozenset(
    {"overlay-image", "overlay-video", "authored-graphic"}
)


def _positive_integer(value: int, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise EventClockError(f"{label} must be a positive integer")
    return value


def frame_to_sample(
    frame: int,
    *,
    frame_rate_num: int,
    frame_rate_den: int,
    sample_rate: int = 48_000,
) -> int:
    """Map one non-negative program-frame boundary to an exact PCM sample.

    The mapping is nearest integer with non-negative exact halves rounded up.
    It performs one rational calculation from program origin, never iterative
    duration accumulation.
    """
    if isinstance(frame, bool) or not isinstance(frame, int) or frame < 0:
        raise EventClockError("program frame must be a non-negative integer")
    numerator = _positive_integer(frame_rate_num, "frame-rate numerator")
    denominator = _positive_integer(frame_rate_den, "frame-rate denominator")
    samples = _positive_integer(sample_rate, "sample rate")
    return (2 * frame * samples * denominator + numerator) // (2 * numerator)


def frame_range_to_samples(
    start_frame: int,
    end_frame_exclusive: int,
    *,
    frame_rate_num: int,
    frame_rate_den: int,
    sample_rate: int = 48_000,
) -> tuple[int, int]:
    """Resolve a half-open program-frame range to a half-open sample range."""
    if end_frame_exclusive < start_frame:
        raise EventClockError("frame range end must not precede start")
    arguments = {
        "frame_rate_num": frame_rate_num,
        "frame_rate_den": frame_rate_den,
        "sample_rate": sample_rate,
    }
    return (
        frame_to_sample(start_frame, **arguments),
        frame_to_sample(end_frame_exclusive, **arguments),
    )


def sample_rate_boundary(
    sample: int,
    *,
    source_rate: int,
    target_rate: int,
) -> int:
    """Map a native non-negative sample boundary with the same half-up rule."""
    if isinstance(sample, bool) or not isinstance(sample, int) or sample < 0:
        raise EventClockError("source sample must be a non-negative integer")
    source = _positive_integer(source_rate, "source sample rate")
    target = _positive_integer(target_rate, "target sample rate")
    return (2 * sample * target + source) // (2 * source)


def _validate_frame_range(value: Any, label: str) -> None:
    if value is None:
        return
    if not isinstance(value, dict):
        raise EventClockError(f"{label} must be an object or null")
    start = value.get("startFrame")
    end = value.get("endFrameExclusive")
    if any(
        isinstance(item, bool) or not isinstance(item, int) for item in (start, end)
    ):
        raise EventClockError(f"{label} must use integer frame boundaries")
    if start < 0 or end <= start:
        raise EventClockError(f"{label} must be a non-empty half-open frame range")


def resolve_timed_event(
    event: dict[str, Any],
    *,
    frame_rate_num: int,
    frame_rate_den: int,
    sample_rate: int = 48_000,
) -> dict[str, Any]:
    """Validate and resolve one shared visual/audio event-clock declaration."""
    result = deepcopy(event)
    event_id = result.get("eventId")
    if not isinstance(event_id, str) or not event_id.strip():
        raise EventClockError("timed event requires a stable eventId")
    role = result.get("role")
    if role not in TIMED_EVENT_ROLES:
        raise EventClockError(f"unsupported timed-event role: {role}")
    frame = result.get("programFrame")
    impact = frame_to_sample(
        frame,
        frame_rate_num=frame_rate_num,
        frame_rate_den=frame_rate_den,
        sample_rate=sample_rate,
    )
    _validate_frame_range(result.get("visibleRange"), "visibleRange")
    _validate_frame_range(result.get("sourceRange"), "sourceRange")
    if result.get("sourceRef") and result.get("sourceRange") is None:
        raise EventClockError("source media requires sourceRange")

    effects = result.get("entryEffectIds") or []
    if not isinstance(effects, list) or any(
        not isinstance(item, str) or not item.strip() for item in effects
    ):
        raise EventClockError("entryEffectIds must contain stable IDs")
    if len(effects) != len(set(effects)):
        raise EventClockError("entryEffectIds must be unique")
    if role == "main-scene" and effects and not result.get("syntheticEffectApproved"):
        raise EventClockError("main-scene synthetic entry effects require approval")
    if (
        role in _ORDINARY_EFFECT_OVERLAYS
        and len(effects) > 1
        and not result.get("orderedMultiEffect")
    ):
        raise EventClockError(
            "multiple overlay entry effects require an ordered sequence"
        )

    transient = result.get("transientOffset")
    if transient is not None:
        if not isinstance(transient, dict):
            raise EventClockError("transientOffset must be an object or null")
        source_samples = transient.get("sourceSamples")
        source_rate = transient.get("sourceRate")
        resolved = sample_rate_boundary(
            source_samples, source_rate=source_rate, target_rate=sample_rate
        )
        declared = transient.get("resolvedOutputSamples")
        if declared is not None and declared != resolved:
            raise EventClockError(
                "declared transient offset disagrees with event clock"
            )
        transient["resolvedOutputSamples"] = resolved
        scheduled = impact - resolved
        if scheduled < 0:
            raise EventClockError("effect transient requires undeclared pre-roll")
        result["scheduledAudioStartSample"] = scheduled
    result["resolvedImpactSample"] = impact
    return result
