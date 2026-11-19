"""Metadata-only sound admission follows the native programme frame boundary."""

from types import SimpleNamespace

import pytest

from avo.timeline.bmap_service import BMapService
from avo.timeline.sound_planning import SoundPlanningError, SoundPlanningService


def clock_service(monkeypatch, *, duration=1000, precise=False, placed=False):
    base = {"num": 1, "den": 1000}
    snapshot = {
        "segments": [
            {
                "in": {"ticks": 0, "timebase": base},
                "out": {"ticks": duration, "timebase": base},
            }
        ]
    }
    if precise:
        snapshot["sourceAssemblyPolicy"] = "preserve-import"
    if placed:
        snapshot = {
            "layoutMode": "placed",
            "layout": {
                "programClock": {"timebase": base, "frameRate": {"num": 24, "den": 1}},
                "duration": {"ticks": duration, "timebase": base},
            },
        }
    service = object.__new__(SoundPlanningService)
    service.workspace = SimpleNamespace(authority="canonical", store=lambda _: None)
    monkeypatch.setattr(
        BMapService, "current_basis", lambda _: ({}, {"snapshot": snapshot}, "")
    )
    return service


@pytest.mark.parametrize(
    "num,den,end,precise",
    [
        (30000, 1001, 30, False),
        (24000, 1001, 24, False),
        (60000, 1001, 60, False),
        (25, 2, 12, False),
        (25, 2, 13, True),
    ],
)
def test_fractional_programme_accepts_its_actual_native_frame_boundary(
    monkeypatch, num, den, end, precise
):
    service = clock_service(monkeypatch, precise=precise)

    def forbidden(*args, **kwargs):
        pytest.fail("Sound clock admission accessed source media")

    monkeypatch.setattr("avo.timeline.contracts.file_fingerprint", forbidden)
    clock = {
        "frameRate": {"num": num, "den": den},
        "sampleRate": 48000,
        "programEndFrame": end,
    }
    result = service._program_clock(clock)
    assert (result.numerator, result.denominator) == (num, den)


@pytest.mark.parametrize("end", [29, 31])
def test_fractional_programme_rejects_a_different_native_end(monkeypatch, end):
    service = clock_service(monkeypatch)
    with pytest.raises(SoundPlanningError):
        service._program_clock(
            {
                "frameRate": {"num": 30000, "den": 1001},
                "sampleRate": 48000,
                "programEndFrame": end,
            }
        )


def test_placed_sound_cannot_reinterpret_the_canonical_picture_clock(monkeypatch):
    service = clock_service(monkeypatch, placed=True)
    with pytest.raises(SoundPlanningError):
        service._program_clock(
            {
                "frameRate": {"num": 48, "den": 1},
                "sampleRate": 48000,
                "programEndFrame": 48,
            }
        )
