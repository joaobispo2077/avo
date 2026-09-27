"""Beat-edit technique map: probe, grid, merge, inventory, snap, rights, flash."""

from __future__ import annotations

import argparse
import json
import subprocess
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from avo.paths import repo_root, schema_path
from avo.timeline.contracts import file_fingerprint

TECHNIQUE_IDS = (
    "card_carousel",
    "punch_zoom",
    "whip_bump",
    "kinetic_text",
    "flip_3d",
    "stylize",
)
INSERT_VIDEO = {".mp4", ".mov", ".webm", ".mkv"}
INSERT_GIF = {".gif"}
INSERT_IMAGE = {".png", ".jpg", ".jpeg", ".webp"}
INSERT_EXTS = INSERT_VIDEO | INSERT_GIF | INSERT_IMAGE
DURATION_RATIO_MAX = 1.5
FLASH_MAX_PER_SEC = 3
GRID_MISSING = "analyze-beatgrid.py missing; install/update the music-to-video skill"
STARTER_VOCAB = {
    "card_carousel": "present",
    "punch_zoom": "present",
    "whip_bump": "absent",
    "kinetic_text": "present",
    "flip_3d": "absent",
    "stylize": "absent",
}


def load_json(path: Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def dump_json(path: Path, payload: Any) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def technique_map_schema() -> dict[str, Any]:
    return load_json(schema_path("avo.technique-map.schema.json"))


def aspect_of(width: int, height: int) -> str:
    if width <= 0 or height <= 0:
        return "other"
    ratio = width / height
    if abs(ratio - 1) < 0.05:
        return "1:1"
    if abs(ratio - 9 / 16) < 0.05:
        return "9:16"
    if abs(ratio - 16 / 9) < 0.05:
        return "16:9"
    return "other"


def canvas_for(
    technique_map: dict[str, Any] | None,
    project: dict[str, Any] | None = None,
) -> str:
    if technique_map:
        aspect = str(technique_map.get("source", {}).get("aspect") or "")
        if aspect in {"1:1", "9:16", "16:9"}:
            return aspect
    if project:
        aspect = str((project.get("deliverable") or {}).get("aspect") or "")
        if aspect in {"1:1", "9:16", "16:9"}:
            return aspect
    return "1:1"


def _fps_from_stream(stream: dict[str, Any]) -> float:
    for key in ("avg_frame_rate", "r_frame_rate"):
        raw = str(stream.get(key) or "")
        if raw and raw != "0/0" and "/" in raw:
            num, den = raw.split("/", 1)
            try:
                value = float(num) / float(den)
            except (TypeError, ValueError, ZeroDivisionError):
                continue
            if value > 0:
                return value
        try:
            value = float(raw)
        except (TypeError, ValueError):
            continue
        if value > 0:
            return value
    return 30.0


def _require_nonzero_duration(
    payload: dict[str, Any], path: Path
) -> tuple[dict[str, Any], float]:
    streams = payload.get("streams") or []
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    if not video:
        raise RuntimeError(f"no video stream in {path}")
    duration = float((payload.get("format") or {}).get("duration") or 0)
    if duration <= 0:
        raise RuntimeError(f"unreadable duration for {path}")
    return video, duration


def probe(path: Path, *, runner: Any = None) -> dict[str, Any]:
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"reference not found: {path}")
    runner = runner or subprocess.run
    result = runner(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration:stream=codec_type,codec_name,width,height,avg_frame_rate,r_frame_rate",
            "-of",
            "json",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if getattr(result, "returncode", 1) != 0:
        err = (getattr(result, "stderr", None) or str(result)).strip()
        raise RuntimeError(f"ffprobe failed for {path}: {err}")
    video, duration = _require_nonzero_duration(json.loads(result.stdout), path)
    width = int(video["width"])
    height = int(video["height"])
    fingerprint = file_fingerprint(path)
    return {
        "path": str(path),
        "sha256": fingerprint["sha256"],
        "durationSec": duration,
        "width": width,
        "height": height,
        "fps": _fps_from_stream(video),
        "aspect": aspect_of(width, height),
        "codec": str(video.get("codec_name") or ""),
    }


def find_analyze_beatgrid(root: Path | None = None) -> Path:
    root = Path(root) if root is not None else repo_root()
    for relative in (
        Path(".agents")
        / "skills"
        / "music-to-video"
        / "scripts"
        / "analyze-beatgrid.py",
        Path(".claude")
        / "skills"
        / "music-to-video"
        / "scripts"
        / "analyze-beatgrid.py",
    ):
        candidate = root / relative
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(GRID_MISSING)


def run_grid(
    audio: Path,
    out_path: Path,
    *,
    root: Path | None = None,
    runner: Any = None,
) -> Path:
    script = find_analyze_beatgrid(root)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    runner = runner or subprocess.run
    result = runner(
        ["python", str(script), str(audio), "-o", str(out_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    if getattr(result, "returncode", 1) != 0:
        err = (getattr(result, "stderr", None) or str(result)).strip()
        raise RuntimeError(f"analyze-beatgrid failed: {err}")
    return out_path


def infer_pacing(audiomap: dict[str, Any]) -> str:
    beats = list((audiomap.get("grid") or {}).get("beats_sec") or [])
    if len(beats) < 8:
        return "phrase_flow"
    gaps = [beats[i + 1] - beats[i] for i in range(len(beats) - 1)]
    mean = sum(gaps) / len(gaps)
    if mean <= 0:
        return "phrase_flow"
    variance = sum((gap - mean) ** 2 for gap in gaps) / len(gaps)
    cv = variance**0.5 / mean
    moments = audiomap.get("key_moments") or []
    if cv < 0.08 and len(moments) <= 2:
        return "phrase_flow"
    return "beat_cut"


def _labeled_times(
    prefix: str, items: list[Any], key: str = "t"
) -> list[tuple[str, float]]:
    labeled: list[tuple[str, float]] = []
    for item in items:
        t = float(item[key] if isinstance(item, dict) else item)
        labeled.append((f"{prefix}:{t:.3f}", t))
    return labeled


def _moment_anchors(audiomap: dict[str, Any]) -> list[tuple[str, float]]:
    labeled: list[tuple[str, float]] = []
    for moment in audiomap.get("key_moments") or []:
        t = float(moment["t"])
        labeled.append((f"moment:{moment.get('kind') or 'moment'}:{t:.3f}", t))
    return labeled


def _event_anchors(audiomap: dict[str, Any]) -> list[tuple[str, float]]:
    labeled: list[tuple[str, float]] = []
    for event in audiomap.get("events") or []:
        special = event.get("special")
        drum = event.get("drum")
        if special not in {"hard_stop", "riser"} and drum not in {"kick", "snare"}:
            continue
        t = float(event["t"])
        labeled.append((f"{special or drum}:{t:.3f}", t))
    return labeled


def _anchor_candidates(audiomap: dict[str, Any]) -> list[tuple[str, float]]:
    grid = audiomap.get("grid") or {}
    candidates = (
        [(f"downbeat:{t}", float(t)) for t in grid.get("downbeats_sec") or []]
        + _moment_anchors(audiomap)
        + _labeled_times("hard_stop", list(audiomap.get("hard_stops") or []))
        + _event_anchors(audiomap)
    )
    if candidates:
        return candidates
    return [(f"beat:{t}", float(t)) for t in grid.get("beats_sec") or []]


def _dedupe_anchors(
    candidates: list[tuple[str, float]], max_anchors: int
) -> list[dict[str, Any]]:
    unique: list[dict[str, Any]] = []
    seen: list[float] = []
    for anchor, t in sorted(candidates, key=lambda item: item[1]):
        if any(abs(t - previous) < 0.05 for previous in seen):
            continue
        seen.append(t)
        unique.append({"anchor": anchor, "t": t})
        if len(unique) >= max_anchors:
            break
    return unique


def pick_anchors(
    audiomap: dict[str, Any], max_anchors: int = 48
) -> list[dict[str, Any]]:
    return _dedupe_anchors(_anchor_candidates(audiomap), max_anchors)


def extract_stills(
    source: Path,
    anchors: list[dict[str, Any]],
    out_dir: Path,
    *,
    runner: Any = None,
) -> list[dict[str, Any]]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    frames: list[dict[str, Any]] = []
    runner = runner or subprocess.run
    for item in anchors:
        t = float(item["t"])
        name = f"t-{round(t * 1000):04d}.jpg"
        dest = out_dir / name
        result = runner(
            [
                "ffmpeg",
                "-y",
                "-ss",
                f"{t:.3f}",
                "-i",
                str(source),
                "-frames:v",
                "1",
                "-vf",
                "scale=720:-2",
                str(dest),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if getattr(result, "returncode", 1) != 0:
            err = (getattr(result, "stderr", None) or str(result)).strip()
            raise RuntimeError(f"ffmpeg still failed at {t:.3f}s: {err}")
        frames.append({**item, "path": str(dest)})
    return frames


def _event_bound_errors(event: dict[str, Any], duration: float) -> list[str]:
    errors: list[str] = []
    t = float(event["t"])
    t_end = float(event["tEnd"])
    if t > duration:
        errors.append(f"{event['id']}: t {t} exceeds duration {duration}")
    if t_end < t:
        errors.append(f"{event['id']}: tEnd before t")
    if t_end > duration + 1e-6:
        errors.append(f"{event['id']}: tEnd {t_end} exceeds duration {duration}")
    unknown = [tid for tid in event["techniques"] if tid not in TECHNIQUE_IDS]
    if unknown:
        errors.append(f"{event['id']}: unknown techniques {unknown}")
    return errors


def validate_map(document: dict[str, Any]) -> list[str]:
    from jsonschema import Draft202012Validator

    errors = [
        f"{'/'.join(str(part) for part in err.absolute_path) or '<root>'}: {err.message}"
        for err in Draft202012Validator(technique_map_schema()).iter_errors(document)
    ]
    if errors:
        return errors
    duration = float(document["source"]["durationSec"])
    seen: set[str] = set()
    for event in document["events"]:
        errors.extend(_event_bound_errors(event, duration))
        seen.update(event["techniques"])
    vocab = document["vocabulary"]
    for tid in TECHNIQUE_IDS:
        if vocab.get(tid) == "absent" and tid in seen:
            errors.append(f"vocabulary.{tid} is absent but used on an event")
    return errors


def _next_end(times: list[float], index: int, duration: float) -> float:
    if index + 1 < len(times):
        return times[index + 1]
    return duration


def _text_near(transcript: dict[str, Any] | None, start: float, end: float) -> str:
    if not transcript:
        return ""
    words = [
        str(word.get("text") or "").strip()
        for word in transcript.get("words") or []
        if isinstance(word, dict)
        and start - 0.05 <= float(word.get("start") or 0) < end + 0.05
    ]
    return " ".join(part for part in words if part)


def _event_from_frame(
    index: int,
    frame: dict[str, Any],
    times: list[float],
    duration: float,
    transcript: dict[str, Any] | None,
) -> dict[str, Any]:
    t = float(frame["t"])
    t_end = _next_end(times, index, duration)
    techniques = [tid for tid in frame.get("techniques") or [] if tid in TECHNIQUE_IDS]
    event: dict[str, Any] = {
        "id": f"e-{index:03d}",
        "t": t,
        "tEnd": t_end,
        "anchor": str(frame.get("anchor") or f"t:{t:.3f}"),
        "techniques": techniques,
        "insertSlot": f"slot-{index}",
        "confidence": float(frame.get("confidence") or 0),
    }
    text = _text_near(transcript, t, t_end)
    if text:
        event["text"] = text
    evidence = frame.get("path") or frame.get("evidenceFrame")
    if evidence:
        event["evidenceFrame"] = str(evidence)
    return event


def _events_from_labels(
    labels: dict[str, Any],
    duration: float,
    transcript: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    frames = list(labels.get("frames") or [])
    frames.sort(key=lambda item: float(item["t"]))
    times = [float(frame["t"]) for frame in frames]
    return [
        _event_from_frame(index, frame, times, duration, transcript)
        for index, frame in enumerate(frames)
    ]


def _source_from_probe(probe_doc: dict[str, Any], duration: float) -> dict[str, Any]:
    width = int(probe_doc["width"])
    height = int(probe_doc["height"])
    return {
        "path": probe_doc["path"],
        "sha256": probe_doc["sha256"],
        "durationSec": duration,
        "width": probe_doc["width"],
        "height": probe_doc["height"],
        "fps": probe_doc["fps"],
        "aspect": probe_doc.get("aspect") or aspect_of(width, height),
        "codec": probe_doc.get("codec") or "",
    }


def merge(
    *,
    probe_doc: dict[str, Any],
    audiomap: dict[str, Any],
    labels: dict[str, Any],
    transcript: dict[str, Any] | None = None,
    video_id: str,
    provider: str,
    audiomap_ref: str = "edit/audiomap.json",
    transcript_ref: str = "edit/transcripts/empty.json",
    transcribe_model: str = "large-v3",
    understand_model: str = "bonsai-27b-gguf",
) -> dict[str, Any]:
    duration = float(probe_doc["durationSec"])
    events = _events_from_labels(labels, duration, transcript)
    used = {tid for event in events for tid in event["techniques"]}
    return {
        "schemaVersion": "1.0.0",
        "kind": "technique-map",
        "videoId": video_id,
        "provider": provider,
        "source": _source_from_probe(probe_doc, duration),
        "models": {
            "transcribe": transcribe_model,
            "understand": understand_model,
            "promptHash": str(labels.get("promptHash") or ""),
        },
        "audiomapRef": audiomap_ref,
        "transcriptRef": transcript_ref,
        "pacing": infer_pacing(audiomap),
        "vocabulary": {
            tid: ("present" if tid in used else "absent") for tid in TECHNIQUE_IDS
        },
        "events": events,
        "rights": {"sourceLogRef": "edit/SOURCE-LOG.md"},
    }


def write_docs(technique_map: dict[str, Any], out_path: Path) -> Path:
    lines = [
        "# Technique map",
        "",
        f"Pacing: `{technique_map['pacing']}` · canvas `{technique_map['source']['aspect']}`",
        "",
        "| t | tEnd | techniques | text | evidence |",
        "| --- | --- | --- | --- | --- |",
    ]
    for event in technique_map["events"]:
        lines.append(
            "| {t:.3f} | {tEnd:.3f} | {tech} | {text} | {ev} |".format(
                t=event["t"],
                tEnd=event["tEnd"],
                tech=", ".join(event["techniques"]) or "—",
                text=(event.get("text") or "").replace("|", "/"),
                ev=event.get("evidenceFrame") or "—",
            )
        )
    lines.extend(["", "## Vocabulary", ""])
    for tid in TECHNIQUE_IDS:
        lines.append(f"- `{tid}`: {technique_map['vocabulary'][tid]}")
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out_path


def _kind_for(path: Path) -> str:
    ext = path.suffix.lower()
    if ext in INSERT_GIF:
        return "gif"
    if ext in INSERT_IMAGE:
        return "image"
    return "video"


def inventory(inserts_dir: Path) -> dict[str, Any]:
    root = Path(inserts_dir)
    if not root.is_dir():
        raise FileNotFoundError(f"inserts folder not found: {root}")
    files: list[dict[str, Any]] = []
    skipped: list[str] = []
    for path in sorted(p for p in root.iterdir() if p.is_file()):
        if path.suffix.lower() not in INSERT_EXTS:
            skipped.append(path.name)
            continue
        fingerprint = file_fingerprint(path)
        files.append(
            {
                "path": str(path),
                "kind": _kind_for(path),
                "sha256": fingerprint["sha256"],
            }
        )
    if not files:
        raise RuntimeError(f"no usable inserts in {root}")
    return {"files": files, "skipped": skipped}


def assign(
    technique_map: dict[str, Any],
    inventory_doc: dict[str, Any],
    *,
    allow_reference: bool = False,
) -> dict[str, Any]:
    files = list(inventory_doc.get("files") or [])
    if not files:
        raise RuntimeError("insert inventory is empty")
    reference = str(technique_map["source"]["sha256"])
    events = list(technique_map.get("events") or [])
    assignments: list[dict[str, Any]] = []
    recycle = 0
    for index, event in enumerate(events):
        asset = files[index % len(files)]
        recycled = index >= len(files)
        if recycled:
            recycle += 1
        if asset["sha256"] == reference and not allow_reference:
            raise ValueError(
                "reference clip SHA must not be used as an insert unless --allow-reference"
            )
        assignments.append(
            {
                "eventId": event["id"],
                "assetPath": asset["path"],
                "sha256": asset["sha256"],
                "kind": asset["kind"],
                "recycled": recycled,
            }
        )
    unused = [item["path"] for item in files[len(events) :]]
    return {
        "assignments": assignments,
        "recycleCount": recycle,
        "unused": unused,
    }


def _require_snap_duration(
    technique_map: dict[str, Any], new_audiomap: dict[str, Any], force: bool
) -> float:
    old = float(technique_map["source"]["durationSec"])
    new = float((new_audiomap.get("audio") or {}).get("duration_sec") or 0)
    if new <= 0:
        raise ValueError("new audiomap is missing audio.duration_sec")
    ratio = new / old
    if not force and (ratio > DURATION_RATIO_MAX or ratio < 1 / DURATION_RATIO_MAX):
        raise ValueError(
            f"duration ratio {ratio:.2f} exceeds {DURATION_RATIO_MAX}; "
            "make a new map or loop/trim the bed (or pass --force)"
        )
    return new


def snap(
    technique_map: dict[str, Any],
    new_audiomap: dict[str, Any],
    *,
    force: bool = False,
) -> dict[str, Any]:
    duration = _require_snap_duration(technique_map, new_audiomap, force)
    anchors = pick_anchors(
        new_audiomap, max_anchors=max(48, len(technique_map["events"]))
    )
    if not anchors:
        raise ValueError("new audiomap has no anchors")
    snapped = json.loads(json.dumps(technique_map))
    for index, event in enumerate(snapped["events"]):
        anchor = anchors[index % len(anchors)]
        event["t"] = float(anchor["t"])
        event["anchor"] = str(anchor["anchor"])
    times = [float(event["t"]) for event in snapped["events"]]
    for index, event in enumerate(snapped["events"]):
        event["tEnd"] = _next_end(times, index, duration)
    snapped["source"]["durationSec"] = duration
    snapped["pacing"] = infer_pacing(new_audiomap)
    return snapped


def flash_flags(technique_map: dict[str, Any]) -> dict[str, Any]:
    buckets: dict[int, int] = defaultdict(int)
    flagged = False
    for event in technique_map.get("events") or []:
        if "whip_bump" not in event.get("techniques", []):
            continue
        bucket = int(float(event["t"]))
        buckets[bucket] += 1
        if buckets[bucket] > FLASH_MAX_PER_SEC:
            flagged = True
            params = dict(event.get("params") or {})
            params["flashUnsafe"] = True
            event["params"] = params
    technique_map["safety"] = {
        "whipFlashFlag": flagged,
        "notes": "skip or lengthen whip_bump where flashUnsafe"
        if flagged
        else "whip density within 3 flashes/s",
    }
    return technique_map


def append_source_log(edit_dir: Path, rows: list[dict[str, str]]) -> Path:
    path = Path(edit_dir) / "SOURCE-LOG.md"
    if not path.is_file():
        path.write_text(
            "# SOURCE-LOG\n\n"
            "| Date | Asset | Role | Path | Rights note |\n"
            "| --- | --- | --- | --- | --- |\n",
            encoding="utf-8",
        )
    existing = path.read_text(encoding="utf-8")
    today = datetime.now(timezone.utc).date().isoformat()
    lines = [
        f"| {today} | {row['asset']} | {row['role']} | {row['path']} | {row['note']} |"
        for row in rows
    ]
    if not existing.endswith("\n"):
        existing += "\n"
    path.write_text(existing + "\n".join(lines) + "\n", encoding="utf-8")
    return path


def starter_map(
    *,
    video_id: str,
    provider: str,
    duration_sec: float,
    aspect: str = "1:1",
) -> dict[str, Any]:
    events = [
        {
            "id": "e-000",
            "t": 0.0,
            "tEnd": min(2.0, duration_sec),
            "anchor": "starter:0",
            "techniques": ["card_carousel", "kinetic_text"],
            "insertSlot": "slot-0",
            "confidence": 1.0,
        },
        {
            "id": "e-001",
            "t": min(2.0, duration_sec * 0.5),
            "tEnd": duration_sec,
            "anchor": "starter:1",
            "techniques": ["punch_zoom"],
            "insertSlot": "slot-1",
            "confidence": 1.0,
        },
    ]
    return {
        "schemaVersion": "1.0.0",
        "kind": "technique-map",
        "videoId": video_id,
        "provider": provider,
        "source": {
            "path": "starter",
            "sha256": "0" * 64,
            "durationSec": duration_sec,
            "width": 1080,
            "height": 1080 if aspect == "1:1" else (1920 if aspect == "9:16" else 608),
            "fps": 30,
            "aspect": aspect if aspect in {"1:1", "9:16", "16:9"} else "1:1",
        },
        "models": {
            "transcribe": "none",
            "understand": "none",
            "promptHash": "starter",
        },
        "audiomapRef": "edit/audiomap.json",
        "transcriptRef": "edit/transcripts/empty.json",
        "pacing": "beat_cut",
        "vocabulary": dict(STARTER_VOCAB),
        "events": events,
        "rights": {"sourceLogRef": "edit/SOURCE-LOG.md"},
    }


def _require_ok(document: dict[str, Any]) -> dict[str, Any]:
    errors = validate_map(document)
    if errors:
        raise ValueError("technique-map invalid:\n" + "\n".join(errors))
    return document


def _edit_dir(args: argparse.Namespace) -> Path:
    return Path(args.edit_dir).resolve()


def cmd_validate(args: argparse.Namespace) -> int:
    errors = validate_map(load_json(args.map))
    if errors:
        print("\n".join(errors))
        return 1
    print("ok")
    return 0


def cmd_probe(args: argparse.Namespace) -> int:
    document = probe(Path(args.input))
    out = (
        Path(args.out)
        if args.out
        else _edit_dir(args) / "timeline" / "reference-probe.json"
    )
    dump_json(out, document)
    print(out)
    return 0


def cmd_grid(args: argparse.Namespace) -> int:
    edit = _edit_dir(args)
    out = Path(args.out) if args.out else edit / "audiomap.json"
    run_grid(Path(args.audio), out, root=Path(args.root) if args.root else None)
    print(out)
    return 0


def cmd_stills(args: argparse.Namespace) -> int:
    edit = _edit_dir(args)
    audiomap = load_json(args.audiomap or (edit / "audiomap.json"))
    anchors = pick_anchors(audiomap, max_anchors=args.max)
    frames = extract_stills(
        Path(args.input),
        anchors,
        Path(args.out) if args.out else edit / "review" / "technique-frames",
    )
    dump_json(edit / "review" / "technique-frames.json", {"frames": frames})
    print(len(frames))
    return 0


def cmd_vision(args: argparse.Namespace) -> int:
    from avo.beat_edit_vision import label_frames_dir

    edit = _edit_dir(args)
    frames_dir = (
        Path(args.frames) if args.frames else edit / "review" / "technique-frames"
    )
    out = Path(args.out) if args.out else edit / "review" / "technique-labels.json"
    dump_json(out, label_frames_dir(frames_dir, root=repo_root()))
    print(out)
    return 0


def _transcript_for_merge(
    edit: Path, transcript_arg: Path | None
) -> tuple[dict[str, Any] | None, str]:
    transcript_path = Path(transcript_arg) if transcript_arg else None
    if transcript_path is None:
        matches = sorted((edit / "transcripts").glob("*.json"))
        transcript_path = matches[0] if matches else None
    if not transcript_path or not transcript_path.is_file():
        return None, "edit/transcripts/empty.json"
    try:
        ref = "edit/" + transcript_path.resolve().relative_to(edit).as_posix()
    except ValueError:
        ref = transcript_path.name
    return load_json(transcript_path), ref


def cmd_merge(args: argparse.Namespace) -> int:
    edit = _edit_dir(args)
    transcript, transcript_ref = _transcript_for_merge(edit, args.transcript)
    document = _require_ok(
        merge(
            probe_doc=load_json(
                args.probe or (edit / "timeline" / "reference-probe.json")
            ),
            audiomap=load_json(args.audiomap or (edit / "audiomap.json")),
            labels=load_json(
                args.labels or (edit / "review" / "technique-labels.json")
            ),
            transcript=transcript,
            video_id=args.video_id,
            provider=args.provider,
            audiomap_ref="edit/audiomap.json",
            transcript_ref=transcript_ref,
            transcribe_model=args.transcribe_model,
            understand_model=args.understand_model,
        )
    )
    map_path = edit / "timeline" / "technique-map.json"
    dump_json(map_path, document)
    write_docs(document, edit / "review" / "technique-map.md")
    print(map_path)
    return 0


def cmd_inventory(args: argparse.Namespace) -> int:
    document = inventory(Path(args.inserts))
    out = Path(args.out) if args.out else Path(args.inserts) / "inventory.json"
    dump_json(out, document)
    print(json.dumps(document, indent=2))
    return 0


def cmd_assign(args: argparse.Namespace) -> int:
    document = assign(
        load_json(args.map),
        load_json(args.inventory),
        allow_reference=args.allow_reference,
    )
    out = (
        Path(args.out) if args.out else Path(args.map).parent / "insert-assignment.json"
    )
    dump_json(out, document)
    print(json.dumps(document, indent=2))
    return 0


def cmd_snap(args: argparse.Namespace) -> int:
    document = snap(
        load_json(args.map),
        load_json(args.audiomap),
        force=args.force,
    )
    out = Path(args.out) if args.out else args.map
    dump_json(out, document)
    print(out)
    return 0


def cmd_flash(args: argparse.Namespace) -> int:
    document = flash_flags(load_json(args.map))
    dump_json(args.map, document)
    print("flagged" if document["safety"]["whipFlashFlag"] else "ok")
    return 0


def cmd_source_log(args: argparse.Namespace) -> int:
    rows = load_json(args.rows) if args.rows else []
    print(append_source_log(Path(args.edit_dir), rows))
    return 0


def cmd_canvas(args: argparse.Namespace) -> int:
    technique_map = load_json(args.map) if args.map else None
    project = load_json(args.project) if args.project else None
    print(canvas_for(technique_map, project))
    return 0


def cmd_starter(args: argparse.Namespace) -> int:
    document = starter_map(
        video_id=args.video_id,
        provider=args.provider,
        duration_sec=args.duration,
        aspect=args.aspect,
    )
    out = Path(args.out)
    dump_json(out, document)
    print(out)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="avo.beat_edit")
    sub = parser.add_subparsers(dest="cmd", required=True)

    validate = sub.add_parser("validate")
    validate.add_argument("--map", required=True, type=Path)
    validate.set_defaults(func=cmd_validate)

    probe_cmd = sub.add_parser("probe")
    probe_cmd.add_argument("--input", required=True, type=Path)
    probe_cmd.add_argument("--edit-dir", type=Path, default=Path("edit"))
    probe_cmd.add_argument("--out", type=Path, default=None)
    probe_cmd.set_defaults(func=cmd_probe)

    grid = sub.add_parser("grid")
    grid.add_argument("--audio", required=True, type=Path)
    grid.add_argument("--edit-dir", type=Path, default=Path("edit"))
    grid.add_argument("--out", type=Path, default=None)
    grid.add_argument("--root", type=Path, default=None)
    grid.set_defaults(func=cmd_grid)

    stills = sub.add_parser("stills")
    stills.add_argument("--input", required=True, type=Path)
    stills.add_argument("--edit-dir", type=Path, default=Path("edit"))
    stills.add_argument("--audiomap", type=Path, default=None)
    stills.add_argument("--out", type=Path, default=None)
    stills.add_argument("--max", type=int, default=48)
    stills.set_defaults(func=cmd_stills)

    vision = sub.add_parser("vision")
    vision.add_argument("--edit-dir", type=Path, default=Path("edit"))
    vision.add_argument("--frames", type=Path, default=None)
    vision.add_argument("--out", type=Path, default=None)
    vision.set_defaults(func=cmd_vision)

    merge_cmd = sub.add_parser("merge")
    merge_cmd.add_argument("--edit-dir", required=True, type=Path)
    merge_cmd.add_argument("--probe", type=Path, default=None)
    merge_cmd.add_argument("--audiomap", type=Path, default=None)
    merge_cmd.add_argument("--labels", type=Path, default=None)
    merge_cmd.add_argument("--transcript", type=Path, default=None)
    merge_cmd.add_argument("--video-id", required=True)
    merge_cmd.add_argument("--provider", required=True)
    merge_cmd.add_argument("--transcribe-model", default="large-v3")
    merge_cmd.add_argument("--understand-model", default="bonsai-27b-gguf")
    merge_cmd.set_defaults(func=cmd_merge)

    inv = sub.add_parser("inventory")
    inv.add_argument("--inserts", required=True, type=Path)
    inv.add_argument("--out", type=Path, default=None)
    inv.set_defaults(func=cmd_inventory)

    asg = sub.add_parser("assign")
    asg.add_argument("--map", required=True, type=Path)
    asg.add_argument("--inventory", required=True, type=Path)
    asg.add_argument("--out", type=Path, default=None)
    asg.add_argument("--allow-reference", action="store_true")
    asg.set_defaults(func=cmd_assign)

    snap_cmd = sub.add_parser("snap")
    snap_cmd.add_argument("--map", required=True, type=Path)
    snap_cmd.add_argument("--audiomap", required=True, type=Path)
    snap_cmd.add_argument("--out", type=Path, default=None)
    snap_cmd.add_argument("--force", action="store_true")
    snap_cmd.set_defaults(func=cmd_snap)

    flash = sub.add_parser("flash")
    flash.add_argument("--map", required=True, type=Path)
    flash.set_defaults(func=cmd_flash)

    slog = sub.add_parser("source-log")
    slog.add_argument("--edit-dir", required=True, type=Path)
    slog.add_argument("--rows", type=Path, default=None)
    slog.set_defaults(func=cmd_source_log)

    canvas = sub.add_parser("canvas")
    canvas.add_argument("--map", type=Path, default=None)
    canvas.add_argument("--project", type=Path, default=None)
    canvas.set_defaults(func=cmd_canvas)

    starter = sub.add_parser("starter")
    starter.add_argument("--video-id", required=True)
    starter.add_argument("--provider", required=True)
    starter.add_argument("--duration", type=float, required=True)
    starter.add_argument("--aspect", default="1:1")
    starter.add_argument("--out", required=True, type=Path)
    starter.set_defaults(func=cmd_starter)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args))
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        print(str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
