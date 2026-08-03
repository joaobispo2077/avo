"""Create readable final-master transcript sidecars from local Whisper JSON."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from avo.build_captions import timestamp, write_srt


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


def generate_from_master(
    master_path: Path,
    edit_dir: Path | None = None,
    *,
    model: str = "small",
    device: str = "auto",
    compute_type: str = "auto",
    force: bool = False,
) -> dict[str, Path]:
    """Transcribe an exported master and write final transcript sidecars."""
    from avo.transcribe import transcribe_one

    master_path = master_path.resolve()
    if not master_path.is_file():
        raise FileNotFoundError(f"master not found: {master_path}")

    resolved_edit_dir = (edit_dir or master_path.parent.parent).resolve()
    transcript_json = transcribe_one(
        master_path,
        resolved_edit_dir,
        model=model,
        device=device,
        compute_type=compute_type,
        force=force,
    )
    return write_artifacts(transcript_json, basename=master_path.stem)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command")

    write_parser = sub.add_parser("write", help="Write sidecars from transcript JSON")
    write_parser.add_argument("transcript_json", type=Path)
    write_parser.add_argument("--basename")

    gen_parser = sub.add_parser(
        "generate",
        help="Transcribe exported master and write all final transcript sidecars",
    )
    gen_parser.add_argument("master", type=Path, help="Path to final master MP4")
    gen_parser.add_argument(
        "--edit-dir",
        type=Path,
        default=None,
        help="Edit folder (default: parent of masters/)",
    )
    gen_parser.add_argument("--model", default="small")
    gen_parser.add_argument("--device", default="auto")
    gen_parser.add_argument("--compute-type", default="auto")
    gen_parser.add_argument("--force", action="store_true")

    # Legacy: python -m avo.final_transcript_artifacts path/to/transcript.json
    parser.add_argument(
        "legacy_transcript_json",
        type=Path,
        nargs="?",
        help=argparse.SUPPRESS,
    )
    parser.add_argument("--basename", help=argparse.SUPPRESS)

    args = parser.parse_args()
    if args.command == "generate":
        outputs = generate_from_master(
            args.master,
            args.edit_dir,
            model=args.model,
            device=args.device,
            compute_type=args.compute_type,
            force=args.force,
        )
    elif args.command == "write":
        outputs = write_artifacts(args.transcript_json, basename=args.basename)
    elif args.legacy_transcript_json is not None:
        outputs = write_artifacts(args.legacy_transcript_json, basename=args.basename)
    else:
        parser.error("provide transcript JSON, or: generate <master.mp4>")
    for kind, path in outputs.items():
        print(f"{kind}: {path}")


if __name__ == "__main__":
    main()
