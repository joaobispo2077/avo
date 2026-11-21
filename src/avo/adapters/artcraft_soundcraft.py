"""One isolated, editable SoundCraft cue and its independently measured PCM."""

from __future__ import annotations

import hashlib
import json
import subprocess
from decimal import Decimal
from pathlib import Path
from time import monotonic

from avo.artcraft import ArtCraftError, _copy_native_source
from avo.timeline.contracts import content_hash, file_fingerprint
from avo.timeline.store import write_immutable_json

from .media.local_source import local_source_arguments

ROOM_REVERB = "room_reverb"
_MAX_PCM_BYTES = 480_000 * 2 * 4
_CUE_COMMANDS = {"session.new", "file.import_audio", "mix.insert"}


def observe_soundcraft_profile(executable, environment):
    path = Path(executable["locator"])

    def inspect(*arguments):
        try:
            result = subprocess.run(
                [str(path), *arguments],
                cwd=path.parent,
                env=environment,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                timeout=7,
                check=True,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise ArtCraftError(
                "Could not observe the selected SoundCraft commands",
                code="ARTCRAFT_NOT_READY",
            ) from exc
        if len(result.stdout) > 2 * 1024 * 1024:
            raise ArtCraftError("SoundCraft observation exceeds its byte budget")
        return result.stdout

    commands = json.loads(inspect("commands", "--json", "--compact"))
    signatures = {
        row["id"]: row["params"] for row in commands if row["id"] in _CUE_COMMANDS
    }
    plugins = [
        line.split(maxsplit=1)[0]
        for line in inspect("plugins").decode().splitlines()
        if line.strip()
    ]
    if set(signatures) != _CUE_COMMANDS or ROOM_REVERB not in plugins:
        raise ArtCraftError(
            "SoundCraft is missing the selected cue commands or built-in room reverb",
            code="ARTCRAFT_NOT_READY",
        )
    if file_fingerprint(path) != executable:
        raise ArtCraftError("SoundCraft CLI changed during command inspection")
    return content_hash({"commands": signatures, "plugin": ROOM_REVERB})


def run_isolated_cue(output, source, *, directory, budget, invoke):
    """Save and reopen one owned room-reverb session before admitting its bounce."""
    if directory.exists() or directory.resolve() != directory:
        raise ArtCraftError("SoundCraft requires a fresh owned cue workspace")
    if budget["files"] < 7:
        raise ArtCraftError(
            "SoundCraft cue needs space for its source and reopen evidence"
        )
    directory.mkdir(parents=True)
    deadline = monotonic() + budget["seconds"]
    imported = directory / "source.wav"
    _copy_native_source(imported, source)
    dry = _audio_evidence(imported, deadline)
    steps = {
        "session.new": {"sample_rate": 48000, "bit_depth": 24, "template": "blank"},
        "file.import_audio": {"path": str(imported), "at": 0, "new_tracks": True},
    }
    call = _job_invocation(directory, budget, invoke, deadline)
    original = directory / "imported.scraft"
    found = _import_source(call, steps, original, dry)
    steps["mix.insert"] = {"track": found["track"], "slot": 0, "plugin": ROOM_REVERB}
    native = directory / "component.scraft"
    rendered = directory / "cue.wav"
    bounce = ["--start", "0", "--end", str(Decimal(output["sampleCount"]) / 48000)]
    recipe = write_immutable_json(directory / "recipe.json", steps)
    _apply_effect(call, steps["mix.insert"], original, native, rendered, bounce)
    media = _require_bounce(rendered, output, deadline)
    dependency = directory / "Audio Files" / "source.wav"
    retained = _audio_evidence(dependency, deadline)
    if any(
        retained[key] != dry[key] for key in ("pcmSha256", "channels", "sampleCount")
    ):
        raise ArtCraftError("SoundCraft changed the isolated input audio")
    locked = file_fingerprint(native)
    fresh = directory / "reopened.wav"
    reopened = call(
        "run", "--in", native, "--bounce", fresh, *bounce, "--inspect", "--compact"
    )
    _require_saved_session(_run_results(reopened, ()), found, dry)
    _require_unchanged_bounce(
        locked, native, media, _require_bounce(fresh, output, deadline)
    )
    return {
        "nativeSource": locked,
        "recipe": file_fingerprint(recipe),
        "media": file_fingerprint(rendered),
        "dependencies": [file_fingerprint(dependency)],
        "audioEvidence": media,
    }


def _require_unchanged_bounce(locked, native, media, reopened):
    if file_fingerprint(native) != locked or media != reopened:
        raise ArtCraftError("SoundCraft saved cue did not reproduce its exact audio")


def _job_invocation(directory, budget, invoke, deadline):
    def call(*arguments):
        response = invoke(directory, *arguments, timeout=_remaining(deadline))
        if len(response) > 1024 * 1024:
            raise ArtCraftError("SoundCraft response exceeds the cue budget")
        size = count = 0
        for path in directory.rglob("*"):
            if path.resolve() != path:
                raise ArtCraftError("SoundCraft created an external path alias")
            if path.is_dir():
                continue
            details = path.stat()
            if not path.is_file() or details.st_nlink != 1:
                raise ArtCraftError("SoundCraft created a nonregular or shared file")
            count += 1
            size += details.st_size
            if count > budget["files"] or size > budget["bytes"]:
                raise ArtCraftError("SoundCraft exhausted its cue file or byte budget")
        return response

    return call


def _remaining(deadline):
    remaining = deadline - monotonic()
    if remaining <= 0:
        raise ArtCraftError("SoundCraft exhausted its cue time budget")
    return remaining


def _command(identifier, options):
    return ["--cmd", f"{identifier}={json.dumps(options, ensure_ascii=False)}"]


def _run_results(response, identifiers):
    commands, records = [], []
    try:
        for line in response.decode("utf-8").splitlines():
            if line.startswith("{"):
                records.append(json.loads(line))
            else:
                identifier, payload = line.split(": ", 1)
                commands.append((identifier, json.loads(payload)))
    except ValueError as exc:
        raise ArtCraftError("SoundCraft returned an invalid command result") from exc
    if tuple(item[0] for item in commands) != identifiers:
        raise ArtCraftError(
            "SoundCraft returned incomplete or reordered command results"
        )
    return [result for _, result in commands], records


def _import_source(call, steps, original, dry):
    response = call(
        "run",
        *_command("session.new", steps["session.new"]),
        *_command("file.import_audio", steps["file.import_audio"]),
        "--save",
        original,
        "--inspect",
        "--compact",
    )
    commands, records = _run_results(response, ("session.new", "file.import_audio"))
    imported = commands[1]["imported"]
    if len(imported) != 1 or len(records) != 2 or not original.is_file():
        raise ArtCraftError("SoundCraft did not save one exact imported audio track")
    found = imported[0]
    _require_session_sources(records[-1], found, dry)
    return found


def _apply_effect(call, options, original, native, rendered, bounce):
    response = call(
        "run",
        "--in",
        original,
        *_command("mix.insert", options),
        "--bounce",
        rendered,
        *bounce,
        "--save",
        native,
        "--inspect",
        "--compact",
    )
    commands, records = _run_results(response, ("mix.insert",))
    if commands != [options] or len(records) != 3 or not native.is_file():
        raise ArtCraftError("SoundCraft did not save the selected native effect")


def _require_session_sources(session, found, dry):
    tracks, sources = session["tracks"], session["sources"]
    if len(tracks) != 1 or len(sources) != 1 or session["sample_rate"] != 48000:
        raise ArtCraftError(
            "SoundCraft cue session contains unrelated tracks or sources"
        )
    source = sources[0]
    expected = (
        found["source"],
        "Audio Files/source.wav",
        dry["sampleCount"],
        dry["channels"],
    )
    observed = tuple(source[key] for key in ("id", "path", "frames", "channels"))
    if tracks[0]["id"] != found["track"] or observed != expected:
        raise ArtCraftError("SoundCraft cue session source or clock changed")
    if (found["frames"], found["channels"]) != expected[2:]:
        raise ArtCraftError("SoundCraft cue session source or clock changed")
    return tracks[0]


def _require_saved_session(results, found, dry):
    _, records = results
    if len(records) != 2:
        raise ArtCraftError("SoundCraft reopened cue returned incomplete evidence")
    track = _require_session_sources(records[-1], found, dry)
    expected = [{"bypass": False, "params": None, "plugin": ROOM_REVERB, "slot": 0}]
    if track["inserts"] != expected:
        raise ArtCraftError(
            "SoundCraft reopened cue does not contain the selected effect"
        )


def _capture_media(executable, path, arguments, deadline):
    return subprocess.run(
        [
            executable,
            "-v",
            "error",
            *local_source_arguments(path),
            "-i",
            str(path),
            *arguments,
        ],
        check=True,
        capture_output=True,
        timeout=_remaining(deadline),
        stdin=subprocess.DEVNULL,
    ).stdout


def _wave_stream(path, deadline):
    if path.suffix != ".wav" or path.resolve() != path or path.stat().st_nlink != 1:
        raise ArtCraftError("SoundCraft cue requires one regular owned WAV")
    limit = _MAX_PCM_BYTES + 128 * 1024
    if path.stat().st_size > limit:
        raise ArtCraftError("SoundCraft cue exceeds the supported PCM byte limit")
    entries = "format=format_name:stream=codec_name,sample_rate,channels"
    probe = _capture_media(
        "ffprobe", path, ["-show_entries", entries, "-of", "json"], deadline
    )
    recorded = json.loads(probe)
    streams = recorded["streams"]
    if recorded["format"]["format_name"] != "wav" or len(streams) != 1:
        raise ArtCraftError("SoundCraft cue requires an isolated WAV audio stream")
    stream = streams[0]
    codec, rate, channels = (
        stream["codec_name"],
        stream["sample_rate"],
        stream["channels"],
    )
    if (
        codec not in {"pcm_s16le", "pcm_s24le", "pcm_f32le"}
        or rate != "48000"
        or channels not in (1, 2)
    ):
        raise ArtCraftError("SoundCraft cue requires 48 kHz mono or stereo PCM")
    return codec, channels


def _audio_evidence(path, deadline):
    import numpy as np

    codec, channels = _wave_stream(path, deadline)
    decoded = _capture_media(
        "ffmpeg",
        path,
        ["-t", "10.001", "-map", "0:a:0", "-c:a", "pcm_s32le", "-f", "s32le", "pipe:1"],
        deadline,
    )
    frame_bytes = 4 * channels
    count, residue = divmod(len(decoded), frame_bytes)
    if residue or not 0 < count <= 480_000:
        raise ArtCraftError("SoundCraft cue exceeds the supported decoded sample range")
    samples = np.frombuffer(decoded, dtype="<i4")
    if samples.min() <= -(2**31) or samples.max() >= 2**31 - 256:
        raise ArtCraftError("SoundCraft cue contains clipped PCM")
    return {
        "sampleRate": 48000,
        "sampleCount": count,
        "channels": channels,
        "codec": codec,
        "pcmSha256": hashlib.sha256(decoded).hexdigest(),
    }


def _require_bounce(path, output, deadline):
    evidence = _audio_evidence(path, deadline)
    if evidence["codec"] != "pcm_s24le" or any(
        evidence[key] != output[key]
        for key in ("sampleRate", "sampleCount", "channels")
    ):
        raise ArtCraftError("SoundCraft bounce differs from the selected PCM contract")
    return evidence
