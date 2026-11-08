"""The shared unprocessed 48 kHz stereo excerpt for audio treatment previews."""

import subprocess
from pathlib import Path


def extract_preview_audio(
    media: Path, start: float, duration: float, output: Path
) -> None:
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-ss",
            f"{start:.3f}",
            "-i",
            str(media),
            "-t",
            f"{duration:.3f}",
            "-vn",
            "-ac",
            "2",
            "-ar",
            "48000",
            str(output),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
