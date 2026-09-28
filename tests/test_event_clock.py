from __future__ import annotations

import pytest

from avo.timeline.event_clock import (
    EventClockError,
    frame_range_to_samples,
    frame_to_sample,
    sample_rate_boundary,
)


@pytest.mark.parametrize(
    ("num", "den"),
    [(24_000, 1_001), (25, 1), (30_000, 1_001), (30, 1), (50, 1), (60_000, 1_001)],
)
def test_frame_mapping_is_exact_from_origin_and_adjacent_ranges_join(
    num: int, den: int
) -> None:
    boundary = frame_to_sample(
        123_456, frame_rate_num=num, frame_rate_den=den, sample_rate=48_000
    )
    assert boundary == (2 * 123_456 * 48_000 * den + num) // (2 * num)
    left = frame_range_to_samples(
        123_455,
        123_456,
        frame_rate_num=num,
        frame_rate_den=den,
    )
    right = frame_range_to_samples(
        123_456,
        123_457,
        frame_rate_num=num,
        frame_rate_den=den,
    )
    assert left[1] == boundary == right[0]


def test_zero_large_counts_and_exact_half_ties_are_deterministic() -> None:
    assert frame_to_sample(0, frame_rate_num=30_000, frame_rate_den=1_001) == 0
    assert frame_to_sample(10**12, frame_rate_num=60_000, frame_rate_den=1_001) == (
        2 * 10**12 * 48_000 * 1_001 + 60_000
    ) // (2 * 60_000)
    assert frame_to_sample(1, frame_rate_num=2, frame_rate_den=1, sample_rate=1) == 1
    assert sample_rate_boundary(1, source_rate=2, target_rate=1) == 1


def test_ranges_are_half_open_and_zero_length_is_valid() -> None:
    assert frame_range_to_samples(10, 10, frame_rate_num=25, frame_rate_den=1) == (
        19_200,
        19_200,
    )
    assert frame_range_to_samples(0, 1, frame_rate_num=25, frame_rate_den=1) == (
        0,
        1_920,
    )


@pytest.mark.parametrize(
    "call",
    [
        lambda: frame_to_sample(-1, frame_rate_num=30, frame_rate_den=1),
        lambda: frame_to_sample(True, frame_rate_num=30, frame_rate_den=1),
        lambda: frame_to_sample(0, frame_rate_num=0, frame_rate_den=1),
        lambda: frame_to_sample(0, frame_rate_num=30, frame_rate_den=0),
        lambda: frame_to_sample(0, frame_rate_num=30, frame_rate_den=1, sample_rate=0),
        lambda: frame_range_to_samples(2, 1, frame_rate_num=30, frame_rate_den=1),
        lambda: sample_rate_boundary(-1, source_rate=48_000, target_rate=48_000),
        lambda: sample_rate_boundary(0, source_rate=0, target_rate=48_000),
    ],
)
def test_invalid_clock_values_fail_closed(call) -> None:
    with pytest.raises(EventClockError):
        call()
