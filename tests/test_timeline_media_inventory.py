from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from avo.adapters.media.ffprobe import FfprobeMediaAdapter

BUILDER_PATH = Path(__file__).parent / "fixtures" / "timeline" / "build_fixtures.py"
spec = importlib.util.spec_from_file_location("builder", BUILDER_PATH)
assert spec and spec.loader
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


@pytest.mark.skipif(
    builder.shutil.which("ffprobe") is None, reason="ffprobe unavailable"
)
def test_inventory_exposes_hash_stream_clock_channel_and_risk(tmp_path: Path) -> None:
    builder.build_fixture_set(tmp_path)
    adapter = FfprobeMediaAdapter()
    result = adapter.inventory(
        [tmp_path / "clean-clock.mp4", tmp_path / "source-a.mp4"]
    )
    assert len(result["sources"]) == 2
    source = result["sources"][0]
    assert len(source["fingerprint"]["sha256"]) == 64
    assert source["streams"]["video"] and source["streams"]["audio"]
    assert source["streams"]["audio"][0]["sampleRate"] == 48000
    assert source["streams"]["audio"][0]["channels"] == 1
    assert result["syncRisk"]["status"] == "risk-detected"
    assert "multiple-source-clocks" in result["syncRisk"]["reasons"]


def test_single_muxed_source_requires_explicit_assessment(tmp_path: Path) -> None:
    builder.build_fixture_set(tmp_path)
    result = FfprobeMediaAdapter().inventory([tmp_path / "clean-clock.mp4"])
    assert result["syncRisk"] == {
        "status": "not-applicable",
        "reasons": ["single-muxed-clock"],
        "assessed": True,
    }
