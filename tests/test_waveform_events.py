from __future__ import annotations

import pytest

from avo.adapters.media.waveform import (
    analyze_transient,
    analyze_transient_cached,
    transient_cache_key,
    verify_rendered_transients,
)


def _impulses(*positions: int, length: int = 2_000) -> list[list[float]]:
    channel = [0.0] * length
    for position in positions:
        channel[position] = 1.0
    return [channel, [-value for value in channel]]


def test_transient_cache_key_covers_every_analysis_parameter() -> None:
    common = {
        "asset_sha256": "a" * 64,
        "analyzer_id": "avo-energy",
        "analyzer_version": "1",
        "sample_rate": 48_000,
        "channel_policy": "sum-squared",
        "dc_removal": True,
        "window_samples": 16,
        "hop_samples": 4,
        "threshold": 0.1,
        "search_range": (0, 2_000),
        "manual_marker": None,
    }
    first = transient_cache_key(**common)
    assert first == transient_cache_key(**common)
    assert first != transient_cache_key(**{**common, "threshold": 0.2})

    cache: dict[str, dict[str, object]] = {}
    parameters = {
        "asset_sha256": "a" * 64,
        "sample_rate": 48_000,
        "window_samples": 8,
        "hop_samples": 1,
        "threshold": 0.05,
        "search_range": (0, 1_000),
    }
    left = analyze_transient_cached(cache, _impulses(240), **parameters)
    right = analyze_transient_cached(cache, _impulses(900), **parameters)
    assert left == right
    assert len(cache) == 1


def test_analysis_trims_leading_silence_and_preserves_original_offset() -> None:
    result = analyze_transient(
        _impulses(240),
        asset_sha256="a" * 64,
        sample_rate=48_000,
        window_samples=8,
        hop_samples=1,
        threshold=0.05,
        search_range=(0, 1_000),
    )
    assert 232 <= result["sourceSamples"] <= 240
    assert (
        result["trimmedSamples"][0][result["sourceSamples"] - result["trimStartSample"]]
        == 1.0
    )
    assert result["normalizedDerivativeHash"]
    assert result["status"] == "pass"


def test_multi_hit_requires_reviewed_marker_instead_of_guessing() -> None:
    ambiguous = analyze_transient(
        _impulses(200, 700),
        asset_sha256="b" * 64,
        sample_rate=48_000,
        window_samples=8,
        hop_samples=1,
        threshold=0.05,
        search_range=(0, 1_000),
    )
    assert ambiguous["status"] == "needs-human-judgment"
    reviewed = analyze_transient(
        _impulses(200, 700),
        asset_sha256="b" * 64,
        sample_rate=48_000,
        window_samples=8,
        hop_samples=1,
        threshold=0.05,
        search_range=(0, 1_000),
        manual_marker=200,
        manual_marker_reviewed=True,
    )
    assert reviewed["sourceSamples"] == 200
    assert reviewed["status"] == "pass"


@pytest.mark.parametrize("initially_reviewed", [False, True])
@pytest.mark.parametrize("legacy_cache", [False, True])
def test_cached_pcm_and_marker_do_not_reuse_old_review_disposition(
    monkeypatch, initially_reviewed, legacy_cache
):
    from avo.adapters.media import waveform

    parameters = {
        "asset_sha256": "b" * 64,
        "sample_rate": 48_000,
        "window_samples": 8,
        "hop_samples": 1,
        "threshold": 0.05,
        "search_range": (0, 1_000),
        "manual_marker": 200,
    }
    samples, cache = _impulses(200, 700), {}
    first = analyze_transient_cached(
        cache, samples, **parameters, manual_marker_reviewed=initially_reviewed
    )
    if legacy_cache:
        cache[first["cacheKey"]] = first.copy()

    def forbidden(*args, **kwargs):
        pytest.fail("Changing review disposition reanalyzed identical PCM")

    monkeypatch.setattr(waveform, "_energy", forbidden)
    second = analyze_transient_cached(
        cache, samples, **parameters, manual_marker_reviewed=not initially_reviewed
    )
    assert second["manualMarkerReviewed"] is not initially_reviewed
    assert second["status"] == (
        "needs-human-judgment" if initially_reviewed else "pass"
    )
    assert first["manualMarkerReviewed"] is initially_reviewed
    assert first["normalizedDerivativeHash"] == second["normalizedDerivativeHash"]
    assert len(cache) == 1
    assert "status" not in next(iter(cache.values()))
    assert "manualMarkerReviewed" not in next(iter(cache.values()))


def test_rendered_correlation_checks_tolerance_cardinality_and_masking() -> None:
    events = [
        {"eventId": "pop", "resolvedImpactSample": 48_000, "expectedOccurrences": 1}
    ]
    assert (
        verify_rendered_transients(
            events,
            {"pop": [{"sample": 48_200, "confidence": 0.95}]},
            tolerance_samples=1_600,
        )["status"]
        == "pass"
    )
    duplicate = verify_rendered_transients(
        events,
        {
            "pop": [
                {"sample": 48_000, "confidence": 0.9},
                {"sample": 48_200, "confidence": 0.9},
            ]
        },
        tolerance_samples=1_600,
    )
    assert duplicate["status"] == "fail"
    masked = verify_rendered_transients(
        events,
        {"pop": [{"sample": 48_000, "confidence": 0.2, "masked": True}]},
        tolerance_samples=1_600,
    )
    assert masked["status"] == "needs-human-judgment"
