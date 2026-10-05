"""Local breath audit/preview/apply CLI. Originals and approved masters are immutable."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

from avo.timeline.contracts import content_hash, file_fingerprint, validate_document

if TYPE_CHECKING:
    import numpy as np


def decode_pcm(path: Path, *, channels: int = 1, rate: int = 48000) -> np.ndarray:
    import numpy as np

    result = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            str(path),
            "-vn",
            "-ar",
            str(rate),
            "-ac",
            str(channels),
            "-f",
            "f32le",
            "pipe:1",
        ],
        capture_output=True,
        check=True,
    )
    pcm = np.frombuffer(result.stdout, dtype=np.float32)
    return pcm if channels == 1 else pcm.reshape(-1, channels)


def _write_json(path: Path, body: dict) -> None:
    with path.open("x", encoding="utf-8") as handle:
        json.dump(body, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.write("\n")


def _write_audio(path: Path, pcm: np.ndarray, rate: int) -> None:
    import numpy as np

    channels = 1 if pcm.ndim == 1 else pcm.shape[1]
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-n",
            "-f",
            "f32le",
            "-ar",
            str(rate),
            "-ac",
            str(channels),
            "-i",
            "pipe:0",
            "-c:a",
            "flac",
            str(path),
        ],
        input=pcm.astype(np.float32).tobytes(),
        capture_output=True,
        check=True,
    )


def _output_directory(project: Path, directory: Path) -> Path:
    from avo.breath_control import BreathControlError

    config = json.loads(project.read_text(encoding="utf-8-sig"))
    edit = (Path(config.get("rawDir") or project.parent) / "edit").resolve()
    target = directory.resolve()
    if edit not in target.parents:
        raise BreathControlError(
            "breath outputs must be inside the project's edit directory"
        )
    if target.exists():
        raise BreathControlError(
            "review version already exists; use a new immutable directory"
        )
    return target


def remap_raw_words(
    words: list[dict], ranges: list[dict], *, source_id: str
) -> list[dict]:
    """Map original word evidence through a canonical cut, not a proof's ASR."""
    result, offset = [], 0.0
    for item in ranges:
        left, right = float(item["start"]), float(item["end"])
        if item["source"] == source_id:
            for word in words:
                if word.get("type") == "spacing":
                    continue
                start, end = float(word["start"]), float(word["end"])
                if start < right and end > left:
                    result.append(
                        {
                            **word,
                            "start": offset + max(start, left) - left,
                            "end": offset + min(end, right) - left,
                        }
                    )
        offset += right - left
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    configure_parser(parser)
    return parser


def configure_parser(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "mode", choices=("audit", "review", "preview", "apply", "propose-cuts")
    )
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument(
        "--source",
        type=Path,
        required=True,
        help="Unmixed canonical dialogue, never a master",
    )
    parser.add_argument("--transcript", type=Path)
    parser.add_argument(
        "--raw-source-id", help="Remap raw transcript using current edit/edl.json"
    )
    parser.add_argument("--control", type=Path)
    parser.add_argument("--analysis", type=Path)
    parser.add_argument("--limit", type=int, default=12)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--room-tone", type=Path)
    parser.add_argument("--from", dest="start", type=float, default=0)
    parser.add_argument("--to", dest="end", type=float)


def _words(args: argparse.Namespace) -> tuple[list[dict], dict | None]:
    from avo.breath_control import BreathControlError

    if args.transcript is None:
        raise BreathControlError("audit needs a fingerprinted word transcript")
    transcript = json.loads(args.transcript.read_text(encoding="utf-8-sig"))
    words = transcript.get("words") or [
        word for seg in transcript.get("segments", []) for word in seg.get("words", [])
    ]
    if not words:
        raise BreathControlError("transcript contains no word timestamps")
    basis = None
    if args.raw_source_id:
        config = json.loads(args.project.read_text(encoding="utf-8-sig"))
        edl_path = (
            Path(config.get("rawDir") or args.project.parent) / "edit" / "edl.json"
        )
        edl = json.loads(edl_path.read_text(encoding="utf-8-sig"))
        words = remap_raw_words(words, edl["ranges"], source_id=args.raw_source_id)
        basis = file_fingerprint(edl_path)
        basis["durationSamples"] = round(
            sum(x["end"] - x["start"] for x in edl["ranges"]) * 48000
        )
    return words, basis


def _audit(args: argparse.Namespace, source: dict, pcm: np.ndarray) -> dict:
    from avo.breath_analysis import analyze_candidates

    words, basis = _words(args)
    analysis = analyze_candidates(pcm, 48000, words)
    body = {
        "schemaVersion": "1.0.0",
        "source": source,
        "transcript": file_fingerprint(args.transcript),
        "projection": basis,
        "durationSamples": len(pcm),
        "analysis": analysis,
        "treatmentStarted": False,
        "wordClock": _word_clock(basis, len(pcm)),
    }
    body["analysisSha256"] = content_hash(body)
    return body


def _word_clock(projection: dict | None, length: int) -> dict:
    if not projection:
        return {"state": "requires-word-alignment-review"}
    difference = length - projection["durationSamples"]
    return {
        "state": "duration-mismatch"
        if abs(difference) > 1600
        else "requires-word-alignment-review",
        "durationDifferenceSamples": difference,
        "note": "Duration agreement alone does not prove word alignment.",
    }


def _candidate_review(args: argparse.Namespace, source: dict, pcm: np.ndarray) -> dict:
    import numpy as np

    from avo.breath_control import BreathControlError

    if args.analysis is None or args.limit <= 0:
        raise BreathControlError("review needs an analysis and a positive limit")
    analysis = json.loads(args.analysis.read_text(encoding="utf-8-sig"))
    if analysis["source"]["sha256"] != source["sha256"]:
        raise BreathControlError("review source fingerprint mismatch")
    if analysis["analysisSha256"] != content_hash(
        {k: v for k, v in analysis.items() if k != "analysisSha256"}
    ):
        raise BreathControlError("review analysis fingerprint mismatch")
    events = _review_events(args, analysis["analysis"]["events"], len(pcm))
    if not events:
        raise BreathControlError("no candidates; inspect the gap inventory manually")
    clips, cues, cursor = [], [], 0
    for event in sorted(events, key=lambda e: e["startSample"]):
        start = max(0, event["startSample"] - 48000)
        end = min(len(pcm), event["endSampleExclusive"] + 48000)
        clip = pcm[start:end].copy()
        fade = min(480, len(clip) // 2)
        clip[:fade] *= np.linspace(0, 1, fade)[:, None]
        clip[-fade:] *= np.linspace(1, 0, fade)[:, None]
        clips.append(clip)
        cues.append(
            {
                **event,
                "sourceContextStartSample": start,
                "sourceContextEndSampleExclusive": end,
                "reelStartSample": cursor,
                "reelEventSample": cursor + event["startSample"] - start,
            }
        )
        cursor += len(clip)
    args.out_dir.mkdir(parents=True, exist_ok=False)
    path = args.out_dir / "candidate-listening.flac"
    _write_audio(path, np.concatenate(clips), 48000)
    return {
        "schemaVersion": "1.0.0",
        "source": source,
        "analysisSha256": analysis["analysisSha256"],
        "diagnosticOnly": True,
        "breathTreatmentApplied": False,
        "requestedWindowSeconds": [args.start, args.end],
        "sampleRate": 48000,
        "cues": cues,
        "output": file_fingerprint(path),
        "note": "Untreated candidates, not confirmed breaths or a master approval proof.",
    }


def _review_events(
    args: argparse.Namespace, events: list[dict], length: int
) -> list[dict]:
    start, end = _window(args, length)
    selected = [
        e
        for e in events
        if e["startSample"] >= start and e["endSampleExclusive"] <= end
    ]
    return sorted(
        selected,
        key=lambda e: (e["endSampleExclusive"] - e["startSample"], e["breathRmsDb"]),
        reverse=True,
    )[: args.limit]


def _reviewed_control(args: argparse.Namespace, source: dict, length: int) -> dict:
    from avo.breath_analysis import protected_word_ranges
    from avo.breath_control import BreathControlError, resolve_control, select_events

    if args.control is None:
        raise BreathControlError("processing needs a reviewed breathControl document")
    control = json.loads(args.control.read_text(encoding="utf-8-sig"))
    validate_document(control, "avo.breath-control.schema.json")
    policy = resolve_control(control)
    if policy is None:
        raise BreathControlError("processing is opt-in; enabled must be true")
    if policy.get("sourceSha256") != source["sha256"]:
        raise BreathControlError("control source fingerprint is missing or stale")
    if args.transcript is None or file_fingerprint(args.transcript)[
        "sha256"
    ] != policy.get("transcriptSha256"):
        raise BreathControlError(
            "processing requires the exact protected word transcript"
        )
    words, projection = _words(args)
    if projection and projection["sha256"] != policy.get("projectionSha256"):
        raise BreathControlError("raw word projection fingerprint is missing or stale")
    if _word_clock(projection, length)["state"] == "duration-mismatch":
        raise BreathControlError(
            "dialogue and raw word projection clocks differ; verify alignment before processing"
        )
    control["protectedRanges"] += protected_word_ranges(
        words, 48000, guard_ms=policy["guardMs"], length=length
    )
    if not select_events(control, 48000, length=length):
        raise BreathControlError(
            "no confirmed/safe breath events; review candidates first"
        )
    return control


def _window(args: argparse.Namespace, length: int) -> tuple[int, int]:
    from avo.breath_control import BreathControlError

    if args.mode == "apply" and (args.start or args.end is not None):
        raise BreathControlError(
            "apply must cover the full dialogue; use preview for windows"
        )
    start = round(args.start * 48000)
    end = round(args.end * 48000) if args.end is not None else length
    if start < 0 or end <= start or end > length:
        raise BreathControlError("preview window is outside the source")
    return start, end


def _process(args: argparse.Namespace, source: dict, pcm: np.ndarray) -> dict:
    from avo.breath_control import apply_control, cut_proposals

    control = _reviewed_control(args, source, len(pcm))
    if args.mode == "propose-cuts":
        proposals = cut_proposals(control, 48000)
        args.out_dir.mkdir(parents=True, exist_ok=False)
        return {
            "operation": "raw-cut-proposals-only",
            "source": source,
            "controlSha256": content_hash(control),
            "proposals": proposals,
            "requiresCMapApproval": True,
            "audioModified": False,
        }
    start, end = _window(args, len(pcm))
    tone = decode_pcm(args.room_tone, channels=2) if args.room_tone else None
    output, delta = apply_control(pcm, control, 48000, room_tone=tone)
    args.out_dir.mkdir(parents=True, exist_ok=False)
    for name, data in (("before", pcm), ("after", output), ("removed", delta)):
        _write_audio(args.out_dir / f"{name}.flac", data[start:end], 48000)
    return {
        "schemaVersion": "1.0.0",
        "source": source,
        "controlSha256": content_hash(control),
        "sampleRate": 48000,
        "durationSamples": end - start,
        "operation": "dialogue-only",
        "humanApprovalRequired": True,
        "roomToneSource": file_fingerprint(args.room_tone) if args.room_tone else None,
        "outputs": {
            name: file_fingerprint(args.out_dir / f"{name}.flac")
            for name in ("before", "after", "removed")
        },
    }


def run(args: argparse.Namespace) -> int:
    from avo.breath_control import BreathControlError

    target = _output_directory(args.project, args.out_dir)
    source_path = args.source.resolve()
    # Filename is an extra guard, not provenance. Canonical render preflight
    # remains responsible for recursively rejecting forbidden ancestors.
    if any(
        token in source_path.stem.lower()
        for token in ("master", "preview", "review-reel")
    ):
        raise BreathControlError("proof/master cannot be the dialogue source")
    source = file_fingerprint(source_path)
    pcm = decode_pcm(source_path, channels=1 if args.mode == "audit" else 2)
    if args.mode == "audit":
        body = _audit(args, source, pcm)
        target.mkdir(parents=True, exist_ok=False)
    elif args.mode == "review":
        body = _candidate_review(args, source, pcm)
    else:
        body = _process(args, source, pcm)
    _write_json(target / "manifest.json", body)
    print(
        json.dumps(
            {
                "mode": args.mode,
                "manifest": str(target / "manifest.json"),
                "requiresHumanReview": True,
            }
        )
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    return run(build_parser().parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
