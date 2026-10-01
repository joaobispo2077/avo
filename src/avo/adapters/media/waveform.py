"""Deterministic transient analysis and exact-export waveform verification."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from avo.timeline.contracts import content_hash


class WaveformError(ValueError):
    """Raised when waveform evidence cannot satisfy the declared contract."""


def transient_cache_key(
    *,
    asset_sha256: str,
    analyzer_id: str,
    analyzer_version: str,
    sample_rate: int,
    channel_policy: str,
    dc_removal: bool,
    window_samples: int,
    hop_samples: int,
    threshold: float,
    search_range: tuple[int, int],
    manual_marker: int | None,
) -> str:
    """Hash the asset and every review-relevant analyzer parameter."""
    return content_hash(
        {
            "assetSha256": asset_sha256,
            "analyzerId": analyzer_id,
            "analyzerVersion": analyzer_version,
            "sampleRate": sample_rate,
            "channelPolicy": channel_policy,
            "dcRemoval": dc_removal,
            "windowSamples": window_samples,
            "hopSamples": hop_samples,
            "threshold": threshold,
            "searchRange": list(search_range),
            "manualMarker": manual_marker,
        }
    )


def _energy(samples: list[list[float]], *, dc_removal: bool) -> list[float]:
    if not samples or not samples[0]:
        raise WaveformError("decoded PCM samples are required")
    length = len(samples[0])
    if any(len(channel) != length for channel in samples):
        raise WaveformError("PCM channels must have equal length")
    means = [sum(channel) / length if dc_removal else 0.0 for channel in samples]
    return [
        sum(
            (float(channel[index]) - means[channel_index]) ** 2
            for channel_index, channel in enumerate(samples)
        )
        for index in range(length)
    ]


def _onset_clusters(
    energy: list[float],
    start: int,
    end: int,
    threshold: float,
    *,
    window_samples: int,
    hop_samples: int,
) -> list[int]:
    hits = []
    for window_start in range(
        start, max(start + 1, end - window_samples + 1), hop_samples
    ):
        window_end = min(end, window_start + window_samples)
        score = sum(energy[window_start:window_end]) / (window_end - window_start)
        if score >= threshold:
            hits.append(window_start)
    clusters: list[int] = []
    previous: int | None = None
    for hit in hits:
        if previous is None or hit - previous > window_samples:
            raw = next(
                (
                    index
                    for index in range(hit, min(end, hit + window_samples))
                    if energy[index] >= threshold
                ),
                hit,
            )
            clusters.append(raw)
        previous = hit
    return clusters


def analyze_transient(
    samples: list[list[float]],
    *,
    asset_sha256: str,
    sample_rate: int,
    window_samples: int,
    hop_samples: int,
    threshold: float,
    search_range: tuple[int, int],
    analyzer_id: str = "avo-energy",
    analyzer_version: str = "1",
    channel_policy: str = "sum-squared",
    dc_removal: bool = True,
    manual_marker: int | None = None,
    manual_marker_reviewed: bool = False,
) -> dict[str, Any]:
    """Find the earliest phase-safe onset and trim only its leading silence."""
    if channel_policy != "sum-squared":
        raise WaveformError("unsupported channel energy policy")
    if sample_rate <= 0 or window_samples <= 0 or hop_samples <= 0 or threshold <= 0:
        raise WaveformError("invalid transient analyzer parameters")
    start, end = search_range
    length = len(samples[0]) if samples else 0
    if start < 0 or end <= start or end > length:
        raise WaveformError("invalid transient search range")
    energy = _energy(samples, dc_removal=dc_removal)
    onsets = _onset_clusters(
        energy,
        start,
        end,
        threshold,
        window_samples=window_samples,
        hop_samples=hop_samples,
    )
    marker = (
        manual_marker if manual_marker is not None else (onsets[0] if onsets else None)
    )
    if marker is None:
        status = "needs-human-judgment"
        marker = start
    elif (
        len(onsets) > 1
        and not manual_marker_reviewed
        or manual_marker is not None
        and not manual_marker_reviewed
    ):
        status = "needs-human-judgment"
    else:
        status = "pass"
    if marker < start or marker >= end:
        raise WaveformError("manual transient marker is outside the search range")
    key = transient_cache_key(
        asset_sha256=asset_sha256,
        analyzer_id=analyzer_id,
        analyzer_version=analyzer_version,
        sample_rate=sample_rate,
        channel_policy=channel_policy,
        dc_removal=dc_removal,
        window_samples=window_samples,
        hop_samples=hop_samples,
        threshold=threshold,
        search_range=search_range,
        manual_marker=manual_marker,
    )
    result = {
        "status": status,
        "assetSha256": asset_sha256,
        "cacheKey": key,
        "analyzer": {"id": analyzer_id, "version": analyzer_version},
        "decodeSampleRate": sample_rate,
        "channelPolicy": channel_policy,
        "dcRemoval": dc_removal,
        "windowSamples": window_samples,
        "hopSamples": hop_samples,
        "threshold": threshold,
        "searchRange": {"startSample": start, "endSampleExclusive": end},
        "sourceSamples": marker,
        "sourceRate": sample_rate,
        "trimStartSample": marker,
        "trimmedSamples": [channel[marker:] for channel in samples],
        "detectedOnsets": onsets,
        "manualMarkerReviewed": bool(manual_marker_reviewed),
    }
    result["normalizedDerivativeHash"] = content_hash(
        {
            "assetSha256": asset_sha256,
            "trimStartSample": marker,
            "sampleRate": sample_rate,
            "channels": result["trimmedSamples"],
        }
    )
    return result


def analyze_transient_cached(
    cache: dict[str, dict[str, Any]],
    samples: list[list[float]],
    **parameters: Any,
) -> dict[str, Any]:
    """Reuse only an exact asset-and-parameter analysis identity."""
    key = transient_cache_key(
        asset_sha256=parameters["asset_sha256"],
        analyzer_id=parameters.get("analyzer_id", "avo-energy"),
        analyzer_version=parameters.get("analyzer_version", "1"),
        sample_rate=parameters["sample_rate"],
        channel_policy=parameters.get("channel_policy", "sum-squared"),
        dc_removal=parameters.get("dc_removal", True),
        window_samples=parameters["window_samples"],
        hop_samples=parameters["hop_samples"],
        threshold=parameters["threshold"],
        search_range=parameters["search_range"],
        manual_marker=parameters.get("manual_marker"),
    )
    if key not in cache:
        cache[key] = analyze_transient(samples, **parameters)
    return deepcopy(cache[key])


def verify_rendered_transients(
    events: list[dict[str, Any]],
    matches: dict[str, list[dict[str, Any]]],
    *,
    tolerance_samples: int,
) -> dict[str, Any]:
    """Verify exact-export timing and cardinality, preserving ambiguity."""
    findings: list[dict[str, Any]] = []
    listening_windows: list[dict[str, Any]] = []
    for event in events:
        event_id = str(event["eventId"])
        expected = int(event["resolvedImpactSample"])
        expected_count = int(
            event.get("expectedOccurrences")
            or (event.get("validation") or {}).get("expectedOccurrences")
            or 1
        )
        observed = matches.get(event_id) or []
        if len(observed) != expected_count:
            findings.append(
                {
                    "code": "event-cardinality-mismatch",
                    "eventId": event_id,
                    "expected": expected_count,
                    "observed": len(observed),
                }
            )
            continue
        for match in observed:
            confidence = float(match.get("confidence") or 0)
            if confidence < 0.5 or match.get("masked"):
                findings.append(
                    {
                        "code": "event-match-needs-human",
                        "eventId": event_id,
                        "confidence": confidence,
                    }
                )
                listening_windows.append(
                    {
                        "eventId": event_id,
                        "startSample": max(0, expected - tolerance_samples),
                        "endSampleExclusive": expected + tolerance_samples + 1,
                    }
                )
            elif abs(int(match["sample"]) - expected) > tolerance_samples:
                findings.append(
                    {
                        "code": "event-transient-out-of-tolerance",
                        "eventId": event_id,
                        "expectedSample": expected,
                        "observedSample": int(match["sample"]),
                    }
                )
    if any(
        item["code"]
        in {"event-cardinality-mismatch", "event-transient-out-of-tolerance"}
        for item in findings
    ):
        status = "fail"
    elif findings:
        status = "needs-human-judgment"
    else:
        status = "pass"
    return {
        "status": status,
        "findings": findings,
        "listeningWindows": listening_windows,
        "matches": deepcopy(matches),
    }


__all__ = [
    "WaveformError",
    "analyze_transient",
    "analyze_transient_cached",
    "transient_cache_key",
    "verify_rendered_transients",
]
