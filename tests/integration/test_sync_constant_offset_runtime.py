from __future__ import annotations

import importlib.util
import struct
import subprocess
from pathlib import Path

import pytest

from avo.adapters.media.sync_materializer import (
    SyncMaterializationError,
    SyncMaterializer,
)

BUILDER_PATH = Path(__file__).parents[1] / "fixtures" / "timeline" / "build_fixtures.py"
spec = importlib.util.spec_from_file_location("builder", BUILDER_PATH)
assert spec and spec.loader
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


def first_signal_seconds(path: Path) -> float:
    data = subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(path),
            "-map",
            "0:a:0",
            "-f",
            "f32le",
            "-ac",
            "1",
            "-ar",
            "48000",
            "-",
        ],
        check=True,
        stdout=subprocess.PIPE,
    ).stdout
    values = struct.iter_unpack("<f", data)
    for index, (value,) in enumerate(values):
        if abs(value) > 0.003:
            return index / 48000
    raise AssertionError("no signal")


@pytest.mark.skipif(builder.shutil.which("ffmpeg") is None, reason="ffmpeg unavailable")
def test_plus_128ms_is_applied_once_from_raw(tmp_path: Path) -> None:
    builder.build_fixture_set(tmp_path / "fixtures")
    raw = tmp_path / "fixtures" / "clean-clock.mp4"
    out = tmp_path / "plus128.mp4"
    result = SyncMaterializer().materialize(
        picture_path=raw,
        audio_path=raw,
        output_path=out,
        transform={
            "kind": "constant-offset",
            "offsetTicks": 128,
            "timebase": {"num": 1, "den": 1000},
        },
        sync_revision_hash="a" * 64,
    )
    assert result["appliedExactlyOnce"] is True
    assert 0.10 <= first_signal_seconds(out) <= 0.17
    with pytest.raises(SyncMaterializationError, match="already sync-materialized"):
        SyncMaterializer().materialize(
            picture_path=out,
            audio_path=out,
            output_path=tmp_path / "twice.mp4",
            transform={
                "kind": "constant-offset",
                "offsetTicks": 128,
                "timebase": {"num": 1, "den": 1000},
            },
            sync_revision_hash="b" * 64,
        )
