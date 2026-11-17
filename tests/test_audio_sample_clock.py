"""Audio endpoint evidence is counted from complete bounded decoded records."""

from io import BytesIO

import pytest

from avo.adapters.media import audio_clock


def test_complete_decoded_frames_count_samples_per_channel():
    assert audio_clock._read_samples(BytesIO(b"1024\n1024\r\n496\n")) == 2544


@pytest.mark.parametrize(
    "value", [b"", b"0\n", b"-1\n", b"1024", b"NaN\n", b"1024,side_data\n"]
)
def test_ambiguous_or_incomplete_sample_records_fail(value):
    with pytest.raises(ValueError):
        audio_clock._read_samples(BytesIO(value))


def test_audio_frame_budget_is_enforced(monkeypatch):
    monkeypatch.setattr(audio_clock, "MAX_PACKETS", 1)
    with pytest.raises(ValueError, match="limit"):
        audio_clock._read_samples(BytesIO(b"1024\n1024\n"))
