from __future__ import annotations

from pathlib import Path
from unittest import mock

from avo import grade


def test_signalstats_uses_relative_metadata_path_in_private_scratch(
    tmp_path: Path,
) -> None:
    scratch = tmp_path / "avo-grade-test"
    captured: dict[str, object] = {}

    def fake_run(cmd: list[str], **kwargs: object) -> mock.Mock:
        captured["cmd"] = cmd
        captured["cwd"] = kwargs["cwd"]
        scratch.mkdir(parents=True, exist_ok=True)
        (scratch / "signalstats.txt").write_text(
            "lavfi.signalstats.YBITDEPTH=8\n"
            "lavfi.signalstats.YAVG=128\n"
            "lavfi.signalstats.YMIN=16\n"
            "lavfi.signalstats.YMAX=235\n"
            "lavfi.signalstats.SATAVG=64\n",
            encoding="utf-8",
        )
        return mock.Mock(returncode=0)

    with (
        mock.patch("avo.grade.tempfile.mkdtemp", return_value=str(scratch)),
        mock.patch("avo.grade.subprocess.run", side_effect=fake_run),
    ):
        result = grade._sample_frame_stats(Path("camera.mp4"), 0.0, 1.0, 1)

    cmd = captured["cmd"]
    assert isinstance(cmd, list)
    assert "metadata=print:file=signalstats.txt" in " ".join(cmd)
    assert captured["cwd"] == str(scratch)
    assert 0.49 < result["y_mean"] < 0.51
    assert not scratch.exists()
