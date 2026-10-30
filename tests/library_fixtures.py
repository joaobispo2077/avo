"""Deterministic external-library inputs; importing this module creates nothing.

Byte stubs suit mocked probe/ASR tests. Explicit ``playable=True`` creates real
non-sparse tone/video files, not speech ground truth or ASR performance evidence.
Large records are generic inputs, not a claim to implement the library schema.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from avo.transcribe import (
    build_transcript_payload,
    resolve_language,
    source_fingerprint,
)


@dataclass
class MetadataProbe:
    """Inject per-path metadata or exceptions and retain probe-call evidence."""

    results: dict[Path, dict[str, Any] | Exception]
    calls: list[Path] = field(default_factory=list)

    def __call__(self, path: Path) -> dict[str, Any]:
        path = Path(path).resolve()
        self.calls.append(path)
        result = self.results[path]
        if isinstance(result, Exception):
            raise result
        return deepcopy(result)


@dataclass
class LibraryFixture:
    root: Path
    files: list[Path]
    probe: MetadataProbe
    manifest: dict[str, Any]


def _external_root(root: Path) -> Path:
    root = Path(root).resolve()
    repository = Path(__file__).resolve().parents[1]
    if root == repository or root.is_relative_to(repository):
        raise ValueError("library fixture media must stay outside the repository")
    root.mkdir(parents=True, exist_ok=True)
    return root


def install_provider(root: Path, slug: str = "example") -> Path:
    """Create an isolated provider; callers may set AVO_ROOT to this install root."""
    if (
        not slug
        or slug[0] not in "abcdefghijklmnopqrstuvwxyz0123456789"
        or any(char not in "abcdefghijklmnopqrstuvwxyz0123456789-" for char in slug)
    ):
        raise ValueError(
            "fixture provider slug must use lowercase letters, digits or -"
        )
    root = _external_root(root)
    target = root / "providers" / slug / "avo.provider.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8") as output:
        json.dump(
            {
                "name": slug,
                "displayName": "Library fixture provider",
                "kind": "youtube",
                "media": {"rawRoot": str(root / "media")},
                "transcription": {"language": "en"},
            },
            output,
            ensure_ascii=False,
            indent=2,
        )
        output.write("\n")
    schemas = root / "schemas"
    schemas.mkdir(exist_ok=True)
    source = Path(__file__).resolve().parents[1] / "schemas" / "avo.library.schema.json"
    (schemas / source.name).write_bytes(source.read_bytes())
    return target


def manifest_hash(manifest: dict[str, Any]) -> str:
    """Hash fixture definitions without absolute paths, timestamps or self-hash."""
    body = {key: value for key, value in manifest.items() if key != "sha256"}
    encoded = json.dumps(
        body, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def write_playable_media(path: Path, *, duration: float = 1.0) -> Path:
    """Generate one tiny MP4 with a tone; never download or overwrite media."""
    if not 0 < duration <= 10:
        raise ValueError("fixture duration must be greater than zero and at most 10")
    path = Path(path).resolve()
    _external_root(path.parent)
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise FileNotFoundError("ffmpeg is required for playable library fixtures")
    subprocess.run(
        [
            ffmpeg,
            "-nostdin",
            "-v",
            "error",
            "-n",
            "-f",
            "lavfi",
            "-i",
            f"color=black:s=160x90:r=10:d={duration}",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=440:sample_rate=48000:duration={duration}",
            "-c:v",
            "mpeg4",
            "-q:v",
            "10",
            "-c:a",
            "aac",
            "-threads",
            "1",
            "-map_metadata",
            "-1",
            "-fflags",
            "+bitexact",
            "-flags:v",
            "+bitexact",
            "-shortest",
            str(path),
        ],
        check=True,
        capture_output=True,
    )
    return path


def make_library(
    root: Path, *, count: int = 6, playable: bool = False, seed: int = 10
) -> LibraryFixture:
    """Build F1/F3 small files with root/nested entries and duplicate stems.

    Use count=1,000 for F1 or 100 for F3 explicitly. Playable copies are full
    files, not sparse allocations or hardlinks; source copies retain separate
    identities. A caller can inject probe failure/unknowns through ``results``.
    """
    if count < 0:
        raise ValueError("fixture count cannot be negative")
    root = _external_root(root)
    files = []
    rows = []
    results = {}
    for index in range(count):
        folder = ("", "camera-a", "camera-b")[index % 3]
        path = root / folder / f"take-{index // 3:04d}.mp4"
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            raise FileExistsError(path)
        if playable and not files:
            write_playable_media(path)
        elif playable:
            with path.open("xb") as output, files[0].open("rb") as source:
                shutil.copyfileobj(source, output)
        else:
            with path.open("xb") as output:
                output.write(f"library-stub:{seed}:{index}\n".encode())
        files.append(path)
        results[path] = {
            "duration": 1.0,
            "streams": [
                {"codec_type": "video", "width": 160, "height": 90},
                {"codec_type": "audio", "sample_rate": "48000", "channels": 1},
            ],
        }
        rows.append(
            {
                "path": path.relative_to(root).as_posix(),
                "sizeBytes": path.stat().st_size,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "duration": 1.0,
                "format": "mp4",
            }
        )
    manifest = {
        "seed": seed,
        "mediaKind": "playable-tone" if playable else "byte-stub",
        "preparation": "unprepared",
        "files": rows,
    }
    manifest["sha256"] = manifest_hash(manifest)
    return LibraryFixture(root, files, MetadataProbe(results), manifest)


def transcript_payload(
    source: Path,
    *,
    text: str = "Fixture phrase xpto",
    language: str = "en",
    model: str = "fixture-local",
) -> dict[str, Any]:
    """Build the current native transcript shape with real source evidence."""
    _whisper_language, language_code, engine_language = resolve_language(language)
    words = [
        {"word": word, "start": index * 0.1, "end": (index + 1) * 0.1}
        for index, word in enumerate(text.split())
    ]
    return build_transcript_payload(
        [{"words": words}],
        source_fingerprint(source),
        model,
        "fixture",
        language_code=language_code,
        engine_language=engine_language,
    )


def large_library_data(
    *,
    recordings: int = 10_000,
    segments: int = 100_000,
    groups: int = 100,
    seed: int = 10,
) -> dict[str, Any]:
    """Explicit F2/F4 input generation; no disk writes or library API calls.

    Use recordings=100 for F4. Each row has deterministic IDs and source times;
    the caller admits these inputs through the eventual native fixture adapter.
    """
    if recordings < 1 or segments < 0 or groups < 1:
        raise ValueError("recordings/groups must be positive and segments nonnegative")
    records = [
        {
            "recordingId": f"recording-{index:05d}",
            "groupId": f"group-{index % groups:03d}",
            "path": (
                f"group-{index % groups:03d}/"
                + ("long-folder-" + "x" * 150 + "/" if index % 101 == 0 else "")
                + f"ação-{index:05d}.mp4"
            ),
            "duration": float((segments + recordings - 1) // recordings + 1),
            "availability": "missing" if index % 97 == 0 else "available",
            "transcriptStatus": "stale" if index % 89 == 0 else "ready",
        }
        for index in range(recordings)
    ]
    transcript_segments = [
        {
            "recordingId": f"recording-{index % recordings:05d}",
            "start": float(index // recordings),
            "end": float(index // recordings) + 0.8,
            "text": f"Fixture phrase xpto {seed} {index}",
            "language": "en",
        }
        for index in range(segments)
    ]
    manifest = {
        "seed": seed,
        "recordings": recordings,
        "segments": segments,
        "groups": groups,
        "preparation": "generic-inputs-not-admitted",
    }
    manifest["dataSha256"] = manifest_hash(
        {"records": records, "transcriptSegments": transcript_segments}
    )
    manifest["sha256"] = manifest_hash(manifest)
    return {
        "manifest": manifest,
        "recordings": records,
        "segments": transcript_segments,
    }
