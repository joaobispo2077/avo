from pathlib import Path
from unittest import mock

from avo import render


def test_concat_declares_exact_segment_durations(tmp_path: Path) -> None:
    first = tmp_path / "first.mp4"
    second = tmp_path / "second.mp4"
    first.write_bytes(b"first")
    second.write_bytes(b"second")
    captured = ""

    def inspect(command, **_kwargs):
        nonlocal captured
        list_path = Path(command[command.index("-i") + 1])
        captured = list_path.read_text(encoding="utf-8")

    with mock.patch.object(render.subprocess, "run", side_effect=inspect):
        render.concat_segments(
            [first, second],
            tmp_path / "out.mp4",
            tmp_path,
            durations=[1.25, 2.5],
        )

    assert "duration 1.250000" in captured
    assert "duration 2.500000" in captured
