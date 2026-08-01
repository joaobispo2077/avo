"""Build readable output-timeline SRT captions from an AVO EDL."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


SRT_TIMING_RE = re.compile(
    r"^(?P<start>\d{2}:\d{2}:\d{2},\d{3})\s+-->\s+"
    r"(?P<end>\d{2}:\d{2}:\d{2},\d{3})$"
)


def timestamp(seconds: float) -> str:
    total_ms = int(round(seconds * 1000))
    hours, rem = divmod(total_ms, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    secs, millis = divmod(rem, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def parse_timestamp(value: str) -> float:
    hours, minutes, rest = value.split(":")
    seconds, millis = rest.split(",")
    return (
        int(hours) * 3600
        + int(minutes) * 60
        + int(seconds)
        + int(millis) / 1000.0
    )


def strip_terminal_periods(text: str) -> str:
    """Remove sentence-final periods while preserving other punctuation."""
    return "\n".join(re.sub(r"\.$", "", line.rstrip()) for line in text.splitlines())


def parse_srt(text: str) -> list[tuple[float, float, str]]:
    cues: list[tuple[float, float, str]] = []
    normalized = text.replace("\r\n", "\n").strip()
    if not normalized:
        return cues
    for block in re.split(r"\n{2,}", normalized):
        lines = block.splitlines()
        if len(lines) < 3:
            continue
        timing_index = 1 if lines[0].strip().isdigit() else 0
        match = SRT_TIMING_RE.match(lines[timing_index].strip())
        if not match:
            continue
        cue_text = "\n".join(lines[timing_index + 1 :]).strip()
        cues.append(
            (
                parse_timestamp(match.group("start")),
                parse_timestamp(match.group("end")),
                cue_text,
            )
        )
    return cues


def write_srt(cues: list[tuple[float, float, str]], output: Path) -> None:
    lines: list[str] = []
    for index, (start, end, text) in enumerate(cues, 1):
        lines.extend(
            [
                str(index),
                f"{timestamp(start)} --> {timestamp(end)}",
                strip_terminal_periods(text),
                "",
            ]
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines), encoding="utf-8")


def derive_burn_in_srt(
    full_srt: Path,
    output: Path,
    end_seconds: float = 60.0,
) -> int:
    cues = parse_srt(full_srt.read_text(encoding="utf-8"))
    selected: list[tuple[float, float, str]] = []
    for start, end, text in cues:
        if start >= end_seconds:
            continue
        clamped_end = min(end, end_seconds)
        if clamped_end > start:
            selected.append((start, clamped_end, strip_terminal_periods(text)))
    write_srt(selected, output)
    return len(selected)


def normalized_token(text: str) -> str:
    return re.sub(r"[^\w]+", "", text, flags=re.UNICODE).casefold()


def apply_corrections(words: list[dict], corrections: list[dict]) -> list[dict]:
    prepared = [
        ([normalized_token(token) for token in item["match"]], item["replace"])
        for item in corrections
    ]
    prepared.sort(key=lambda item: len(item[0]), reverse=True)

    corrected: list[dict] = []
    index = 0
    while index < len(words):
        for match, replacement in prepared:
            candidate = words[index : index + len(match)]
            if len(candidate) != len(match):
                continue
            if [normalized_token(word["text"]) for word in candidate] != match:
                continue
            corrected.append(
                {
                    "text": replacement,
                    "start": candidate[0]["start"],
                    "end": candidate[-1]["end"],
                }
            )
            index += len(match)
            break
        else:
            corrected.append(dict(words[index]))
            index += 1
    return corrected


def group_words(words: list[dict]) -> list[list[dict]]:
    groups: list[list[dict]] = []
    current: list[dict] = []
    for word in words:
        text = (word.get("text") or "").strip()
        if not text:
            continue
        projected = " ".join([*(item["text"] for item in current), text])
        duration = float(word["end"]) - float(current[0]["start"]) if current else 0
        if current and (len(current) >= 6 or len(projected) > 42 or duration > 3.2):
            groups.append(current)
            current = []
        current.append(word)
        if text.endswith((".", "?", "!")):
            groups.append(current)
            current = []
    if current:
        groups.append(current)
    return groups


def build(edl_path: Path, output: Path, corrections_path: Path | None) -> int:
    edl = json.loads(edl_path.read_text(encoding="utf-8"))
    edit_dir = edl_path.parent
    corrections = []
    if corrections_path:
        corrections = json.loads(corrections_path.read_text(encoding="utf-8"))

    cues: list[tuple[float, float, str]] = []
    output_offset = 0.0
    for item in edl["ranges"]:
        start = float(item["start"])
        end = float(item["end"])
        transcript_path = edit_dir / "transcripts" / f"{item['source']}.json"
        transcript = json.loads(transcript_path.read_text(encoding="utf-8"))
        words = [
            word
            for word in transcript.get("words", [])
            if word.get("type") == "word"
            and word.get("start") is not None
            and word.get("end") is not None
            and word["end"] > start
            and word["start"] < end
        ]
        words = apply_corrections(words, corrections)
        for group in group_words(words):
            cue_start = max(start, float(group[0]["start"])) - start + output_offset
            cue_end = min(end, float(group[-1]["end"])) - start + output_offset
            if cue_end <= cue_start:
                cue_end = cue_start + 0.4
            text = re.sub(
                r"\s+([,.;:!?])", r"\1", " ".join(word["text"] for word in group)
            )
            cues.append((cue_start, cue_end, strip_terminal_periods(text)))
        output_offset += end - start

    write_srt(cues, output)
    return len(cues)


def build_selectable_only(
    edl_path: Path,
    output: Path,
    corrections_path: Path | None = None,
) -> int:
    """Build uploadable/selectable captions without any burn-in sidecar."""
    return build(edl_path, output, corrections_path)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("edl", type=Path)
    parser.add_argument("-o", "--output", type=Path, required=True)
    parser.add_argument("--corrections", type=Path)
    parser.add_argument("--burn-in-output", type=Path)
    parser.add_argument("--burn-in-end", type=float, default=60.0)
    args = parser.parse_args()
    count = build(args.edl.resolve(), args.output.resolve(), args.corrections)
    print(f"captions: {count} cues -> {args.output}")
    if args.burn_in_output:
        burn_count = derive_burn_in_srt(
            args.output.resolve(),
            args.burn_in_output.resolve(),
            end_seconds=args.burn_in_end,
        )
        print(f"burn-in captions: {burn_count} cues -> {args.burn_in_output}")


if __name__ == "__main__":
    main()
