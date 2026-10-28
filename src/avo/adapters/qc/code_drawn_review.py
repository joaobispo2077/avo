"""Decode exact candidate previews for the existing visual review evidence path."""

from __future__ import annotations

import json
import subprocess
from fractions import Fraction
from pathlib import Path


class CodeDrawnReviewProducer:
    @staticmethod
    def probe_contract(candidate: Path) -> dict:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-count_frames",
                "-select_streams",
                "v:0",
                "-show_streams",
                "-of",
                "json",
                str(candidate),
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=120,
        )
        video = json.loads(result.stdout)["streams"][0]
        rate = Fraction(video["r_frame_rate"])
        return {
            "width": int(video["width"]),
            "height": int(video["height"]),
            "frameRate": {"num": rate.numerator, "den": rate.denominator},
            "frameCount": int(video["nb_read_frames"]),
        }

    @staticmethod
    def _frame(candidate: Path, frame: int):
        import io

        from PIL import Image

        command = [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            str(candidate),
            "-vf",
            f"select=eq(n\\,{frame})",
            "-frames:v",
            "1",
            "-an",
            "-f",
            "image2pipe",
            "-vcodec",
            "png",
            "-",
        ]
        result = subprocess.run(command, check=True, capture_output=True, timeout=120)
        return Image.open(io.BytesIO(result.stdout)).convert("RGBA")

    @staticmethod
    def _sheet(images, labels, destination: Path):
        from PIL import Image, ImageDraw

        columns = min(4, len(images))
        thumb_width = min(360, images[0].width)
        thumb_height = max(1, round(images[0].height * thumb_width / images[0].width))
        rows = (len(images) + columns - 1) // columns
        sheet = Image.new(
            "RGB", (columns * thumb_width, rows * (thumb_height + 24)), "#202020"
        )
        draw = ImageDraw.Draw(sheet)
        for index, (image, label) in enumerate(zip(images, labels, strict=True)):
            x, y = index % columns * thumb_width, index // columns * (thumb_height + 24)
            composite = Image.new("RGBA", image.size, "#404040")
            composite.alpha_composite(image)
            sheet.paste(
                composite.convert("RGB").resize((thumb_width, thumb_height)), (x, y)
            )
            draw.text((x + 4, y + thumb_height + 4), str(label), fill="white")
        sheet.save(destination)

    def __call__(
        self,
        *,
        candidate: Path,
        output_dir: Path,
        candidate_contract: dict,
        sample_frames: list[int],
        transition_ranges: list[dict],
        loop_requested: bool,
    ) -> dict:
        if self.probe_contract(candidate) != candidate_contract:
            raise ValueError(
                "Decoded candidate contract differs from the review request"
            )
        output_dir.mkdir(parents=True, exist_ok=True)
        images, artifacts = {}, []
        for frame in sample_frames:
            image = self._frame(candidate, frame)
            images[frame] = image
            target = output_dir / f"frame-{frame:06d}.png"
            image.save(target)
            artifacts.append({"kind": "frame", "path": str(target), "frame": frame})
            small = output_dir / f"small-{frame:06d}.png"
            width = min(360, image.width)
            image.resize(
                (width, max(1, round(image.height * width / image.width)))
            ).save(small)
            artifacts.append(
                {"kind": "small-display", "path": str(small), "frame": frame}
            )
        sheet = output_dir / "contact-sheet.png"
        self._sheet(list(images.values()), list(images), sheet)
        artifacts.append({"kind": "contact-sheet", "path": str(sheet)})
        artifacts.extend(
            self._transition_strips(candidate, output_dir, transition_ranges)
        )
        if loop_requested:
            target = output_dir / "loop-strip.png"
            frames = [candidate_contract["frameCount"] - 1, 0]
            self._sheet(
                [self._frame(candidate, frame) for frame in frames], frames, target
            )
            artifacts.append(
                {
                    "kind": "loop-strip",
                    "path": str(target),
                    "frames": frames,
                    "range": {
                        "startFrame": 0,
                        "endFrameExclusive": candidate_contract["frameCount"],
                    },
                }
            )
        return {
            "artifacts": artifacts,
            "findings": [],
            "status": "needs-human-judgment",
        }

    def _transition_strips(self, candidate, output_dir, ranges):
        artifacts = []
        for index, bounds in enumerate(ranges):
            start, end = bounds["startFrame"], bounds["endFrameExclusive"]
            count = min(12, end - start)
            frames = sorted(
                {
                    round(start + i * (end - start - 1) / max(1, count - 1))
                    for i in range(count)
                }
            )
            target = output_dir / f"transition-{index:03d}.png"
            self._sheet(
                [self._frame(candidate, frame) for frame in frames], frames, target
            )
            artifacts.append(
                {
                    "kind": "transition-strip",
                    "path": str(target),
                    "range": bounds,
                    "frames": frames,
                }
            )
        return artifacts
