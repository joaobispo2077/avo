"""Convert an SRT file into an ASS subtitle file with fixed center placement."""

from __future__ import annotations

import argparse
import re
from pathlib import Path


TIMING_RE = re.compile(
    r"(?P<start>\d\d:\d\d:\d\d,\d\d\d)\s+-->\s+"
    r"(?P<end>\d\d:\d\d:\d\d,\d\d\d)"
)


def ass_time(srt_time: str) -> str:
    hh, mm, rest = srt_time.split(":")
    ss, ms = rest.split(",")
    centiseconds = int(round(int(ms) / 10))
    return f"{int(hh)}:{mm}:{ss}.{centiseconds:02d}"


def escape_ass_text(text: str) -> str:
    return (
        text.replace("\\", r"\\")
        .replace("{", r"\{")
        .replace("}", r"\}")
        .replace("\n", r"\N")
    )


def parse_srt(path: Path) -> list[tuple[str, str, str]]:
    blocks = re.split(r"\n\s*\n", path.read_text(encoding="utf-8").strip())
    cues: list[tuple[str, str, str]] = []
    for block in blocks:
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        if not lines:
            continue
        timing_index = 1 if lines[0].isdigit() and len(lines) > 1 else 0
        match = TIMING_RE.match(lines[timing_index])
        if not match:
            continue
        text = "\n".join(lines[timing_index + 1 :]).rstrip(".")
        cues.append((match.group("start"), match.group("end"), text))
    return cues


def write_ass(
    cues: list[tuple[str, str, str]],
    out_path: Path,
    width: int,
    height: int,
    center_y_ratio: float,
) -> None:
    x = width // 2
    y = int(round(height * center_y_ratio))
    font_size = 72 if height >= 2160 else 36
    outline = 4 if height >= 2160 else 2
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
ScaledBorderAndShadow: yes
WrapStyle: 2

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: CenterSeam,Helvetica,{font_size},&H00FFFFFF,&H000000FF,&H00000000,&H00000000,-1,0,0,0,100,100,0,0,1,{outline},0,5,0,0,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = [header]
    for start, end, text in cues:
        positioned = r"{\an5\pos(%d,%d)}%s" % (x, y, escape_ass_text(text))
        lines.append(
            f"Dialogue: 0,{ass_time(start)},{ass_time(end)},CenterSeam,,0,0,0,,{positioned}"
        )
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--width", type=int, default=3840)
    parser.add_argument("--height", type=int, default=2160)
    parser.add_argument("--center-y-ratio", type=float, default=0.5)
    args = parser.parse_args()

    cues = parse_srt(args.input)
    write_ass(cues, args.output, args.width, args.height, args.center_y_ratio)
    print(f"ASS -> {args.output} ({len(cues)} cues, y={round(args.height * args.center_y_ratio)})")


if __name__ == "__main__":
    main()
