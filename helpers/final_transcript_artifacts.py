"""Create readable final-master transcript sidecars from local Whisper JSON."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from build_captions import timestamp, write_srt


def _plain_text(transcript: dict) -> str:
    text = str(transcript.get("text") or "").strip()
    if text:
        return re.sub(r"\s+", " ", text)
    words = [
        str(word.get("text") or "").strip()
        for word in transcript.get("words", [])
        if word.get("type") == "word" and str(word.get("text") or "").strip()
    ]
    return re.sub(r"\s+([,.;:!?])", r"\1", " ".join(words)).strip()


def _word_cues(words: list[dict]) -> list[tuple[float, float, str]]:
    cues: list[tuple[float, float, str]] = []
    current: list[dict] = []
    for word in words:
        if word.get("type") != "word" or word.get("start") is None or word.get("end") is None:
            continue
        text = str(word.get("text") or "").strip()
        if not text:
            continue
        current.append(word)
        span = float(current[-1]["end"]) - float(current[0]["start"])
        joined = " ".join(str(item.get("text") or "").strip() for item in current)
        if len(current) >= 8 or len(joined) >= 52 or span >= 3.2 or text.endswith((".", "?", "!")):
            cues.append(
                (
                    float(current[0]["start"]),
                    float(current[-1]["end"]),
                    re.sub(r"\s+([,.;:!?])", r"\1", joined).rstrip("."),
                )
            )
            current = []
    if current:
        joined = " ".join(str(item.get("text") or "").strip() for item in current)
        cues.append(
            (
                float(current[0]["start"]),
                float(current[-1]["end"]),
                re.sub(r"\s+([,.;:!?])", r"\1", joined).rstrip("."),
            )
        )
    return cues


def write_artifacts(transcript_json: Path, basename: str | None = None) -> dict[str, Path]:
    transcript_json = transcript_json.resolve()
    transcript = json.loads(transcript_json.read_text(encoding="utf-8"))
    stem = basename or transcript_json.stem
    txt_path = transcript_json.with_name(f"{stem}.txt")
    md_path = transcript_json.with_name(f"{stem}.md")
    srt_path = transcript_json.with_name(f"{stem}.srt")

    text = _plain_text(transcript)
    txt_path.write_text(text + "\n", encoding="utf-8")
    md_path.write_text(f"# {stem}\n\n{text}\n", encoding="utf-8")

    cues = _word_cues(transcript.get("words", []))
    if cues:
        write_srt(cues, srt_path)
    else:
        srt_path.write_text(
            f"1\n{timestamp(0)} --> {timestamp(1)}\n{text.rstrip('.')}\n",
            encoding="utf-8",
        )
    return {"json": transcript_json, "txt": txt_path, "md": md_path, "srt": srt_path}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("transcript_json", type=Path)
    parser.add_argument("--basename")
    args = parser.parse_args()
    outputs = write_artifacts(args.transcript_json, basename=args.basename)
    for kind, path in outputs.items():
        print(f"{kind}: {path}")


if __name__ == "__main__":
    main()
