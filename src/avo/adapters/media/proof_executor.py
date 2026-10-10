"""Execute source-only sequential ProofPlan cuts, with one final audio encode.

Unsupported composition operations fail before media creation. Microproofs use
the same source routing and complete segment fade envelope as the full graph.
Lossless temporary segments are never reused across plans.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from fractions import Fraction
from pathlib import Path
from typing import Any

from avo.audio_restoration import afftdn_filter, validate_dialogue_noise_policy
from avo.capabilities import default_proof_capability_registry
from avo.timeline.contracts import file_fingerprint


def _run(arguments: list[str]) -> None:
    result = subprocess.run(arguments, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(f"ProofPlan ffmpeg failed: {result.stderr[-4000:]}")


def _bounds(value: dict[str, Any], first: str, last: str) -> tuple[int, int]:
    start, end = value[first], value[last]
    if any(isinstance(v, bool) or not isinstance(v, int) for v in (start, end)):
        raise RuntimeError("ProofPlan boundaries must be integers")
    if start < 0 or end <= start:
        raise RuntimeError("ProofPlan requires nonempty half-open ranges")
    return start, end


def _seconds(ticks: int, timebase: dict[str, int]) -> Fraction:
    return Fraction(ticks * timebase["num"], timebase["den"])


def _validate_ancestry(value: Any) -> None:
    if isinstance(value, dict):
        if value.get("mediaClass") in {
            "proof",
            "preview",
            "proxy",
            "master",
            "delivery",
        }:
            raise RuntimeError(
                f"Prohibited recursive ProofPlan ancestry: {value.get('locator')}"
            )
        if "locator" in value and any(
            p.casefold() in {"proof", "preview", "proxy", "master", "delivery"}
            for p in Path(value["locator"]).parts
        ):
            raise RuntimeError(
                f"Prohibited recursive ProofPlan ancestry: {value['locator']}"
            )
        for item in value.values():
            _validate_ancestry(item)
    elif isinstance(value, list):
        for item in value:
            _validate_ancestry(item)


def _source_identity(parameters, lock):
    source = parameters["source"]
    path = Path(source["locator"])
    if set(source) - {"locator", "sha256", "mediaClass", "streamIndex", "ancestry"}:
        raise RuntimeError(f"Unsupported source metadata or ancestry: {path}")
    _validate_ancestry(source.get("ancestry", []))
    if source.get("mediaClass") != "source" or any(
        part.casefold() in {"preview", "proof", "proxy", "master", "delivery"}
        for part in path.parts
    ):
        raise RuntimeError(f"Prohibited ProofPlan ancestry: {path}")
    expected = lock.get(f"source:{parameters['sourceId']}")
    if not expected or expected != source.get("sha256"):
        raise RuntimeError(f"ProofPlan source lock mismatch: {path}")
    return source, path, expected


def _stream_index(source, path):
    stream = source["streamIndex"]
    if isinstance(stream, bool) or not isinstance(stream, int) or stream < 0:
        raise RuntimeError(f"Invalid source stream: {path}")
    return stream


def _selected_stream(source, path, streams, audio_node):
    stream = _stream_index(source, path)
    metadata = next((s for s in streams if s["index"] == stream), {})
    expected_type = "audio" if audio_node is not None else "video"
    if metadata.get("codec_type") != expected_type:
        raise RuntimeError(f"Selected stream is not {expected_type}: {path}:{stream}")
    if audio_node is not None and (
        int(metadata["sample_rate"]) != audio_node["sourceSampleRate"]
        or int(metadata["channels"])
        != {"mono": 1, "stereo": 2}[audio_node["sourceLayout"]]
    ):
        raise RuntimeError(
            f"Actual audio source rate/layout differs from graph: {path}:{stream}"
        )
    return path, stream


def _source(
    parameters: dict[str, Any],
    lock: dict[str, str],
    cache: dict[str, dict],
    *,
    audio_node: dict | None = None,
) -> tuple[Path, int]:
    source, path, expected = _source_identity(parameters, lock)
    key = str(path.resolve())
    if key not in cache:
        actual_hash = file_fingerprint(path)["sha256"]
        if actual_hash != expected:
            raise RuntimeError(f"ProofPlan source bytes changed: {path}")
        probe = json.loads(
            subprocess.run(
                [
                    "ffprobe",
                    "-v",
                    "error",
                    "-show_streams",
                    "-show_format",
                    "-of",
                    "json",
                    str(path),
                ],
                capture_output=True,
                text=True,
                check=True,
            ).stdout
        )
        cache[key] = {
            "sha256": actual_hash,
            "streams": probe["streams"],
            "format": probe.get("format", {}),
        }
    if cache[key]["sha256"] != expected:
        raise RuntimeError(f"ProofPlan source bytes changed: {path}")
    return _selected_stream(source, path, cache[key]["streams"], audio_node)


def _validate_audio_node(node, rate):
    if node["kind"] not in {"source", "silence"}:
        raise RuntimeError(f"Unsupported ProofPlan audio node: {node['kind']}")
    if node["targetLayout"] != "stereo" or node["targetSampleRate"] != rate:
        raise RuntimeError("Unsupported ProofPlan audio target mapping")
    if node["latencyCompensationSamples"]:
        raise RuntimeError("Explicit latency reconciliation is not implemented")
    count = {"mono": 1, "stereo": 2}.get(node["sourceLayout"], 0)
    if len(node["channelMap"]) != 2 or any(
        v < 0 or v >= count for v in node["channelMap"]
    ):
        raise RuntimeError("Invalid ProofPlan source channel mapping")


def _audio_nodes(nodes: list[dict[str, Any]], rate: int) -> dict:
    node_by_range = {}
    for node in nodes:
        bounds = _bounds(node["outputRange"], "startSample", "endSampleExclusive")
        if bounds in node_by_range:
            raise RuntimeError("Unsupported overlapping ProofPlan audio nodes")
        _validate_audio_node(node, rate)
        node_by_range[bounds] = node
    return node_by_range


def _video_parameters(operation: dict, refs: dict, registry: Any) -> dict:
    if operation["kind"] != "trim":
        raise RuntimeError(
            f"Unsupported ProofPlan video operation: {operation['kind']}"
        )
    implementation = registry.resolve(
        "trim", implementation_id=operation["implementationId"]
    )
    if (
        implementation is None
        or refs.get(operation["implementationId"]) != implementation.proof_reference()
    ):
        raise RuntimeError("ProofPlan trim implementation is unsupported or stale")
    parameters = operation["parameters"]
    required = {"sourceId", "source", "sourceRange"}
    if not required <= set(parameters) or set(parameters) - required - {
        "videoTailPolicy"
    }:
        raise RuntimeError("Unsupported video trim parameters")
    if operation["inputs"] != [parameters["sourceId"]]:
        raise RuntimeError("Unconsumed video trim input")
    return parameters


def _tail_policy(value):
    if not isinstance(value, dict) or set(value) != {"mode", "maxHoldMilliseconds"}:
        raise RuntimeError("Invalid explicit video tail policy")
    budget = value["maxHoldMilliseconds"]
    if (
        value["mode"] != "hold-last-frame"
        or type(budget) is not int
        or not 1 <= budget <= 200
    ):
        raise RuntimeError("Video tail policy requires hold-last-frame budget 1..200ms")
    return Fraction(budget, 1000)


def _video_eof(path, stream, metadata):
    if "duration" not in metadata:
        raise RuntimeError("Explicit video tail policy requires video duration")
    probe = json.loads(
        subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                str(stream),
                "-show_packets",
                "-show_entries",
                "packet=pts_time,duration_time",
                "-of",
                "json",
                str(path),
            ],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    )
    packets = probe.get("packets", [])
    if not packets or any(
        "pts_time" not in p or "duration_time" not in p for p in packets
    ):
        raise RuntimeError(
            "Explicit video tail policy requires packet timestamps/durations"
        )
    if any(Fraction(p["duration_time"]) <= 0 for p in packets):
        raise RuntimeError(
            "Explicit video tail policy requires positive packet durations"
        )
    return max(Fraction(p["pts_time"]) + Fraction(p["duration_time"]) for p in packets)


def _video_tail(
    parameters, picture, cache, source_start, source_duration, target_duration
):
    if "videoTailPolicy" not in parameters:
        return None
    budget = _tail_policy(parameters["videoTailPolicy"])
    path, stream = picture
    probe = cache[str(path.resolve())]
    metadata = next(s for s in probe["streams"] if s["index"] == stream)
    container_duration = probe["format"].get("duration")
    if container_duration is None or source_start + source_duration > Fraction(
        container_duration
    ):
        raise RuntimeError("Explicit video tail range exceeds container duration")
    # Input -ss uses the container-relative clock, whereas packet PTS may be offset.
    eof = _video_eof(path, stream, metadata) - Fraction(
        probe["format"].get("start_time", "0")
    )
    if source_start >= eof:
        raise RuntimeError("Explicit video tail requires an available source frame")
    hold = max(Fraction(0), source_start + max(source_duration, target_duration) - eof)
    if hold > budget:
        raise RuntimeError("Explicit video tail hold exceeds declared budget")
    return {
        "sourceId": parameters["sourceId"],
        "policy": parameters["videoTailPolicy"],
        "sourceVideoEndSeconds": float(eof),
        "actualHoldMilliseconds": float(hold * 1000),
        "padSeconds": float(budget),
    }


def _output_settings(execution: dict) -> tuple:
    spec = execution["output"]
    fps = Fraction(spec["frameRate"]["num"], spec["frameRate"]["den"])
    rate = spec["audioSampleRate"]
    if (
        spec["channelLayout"] != "stereo"
        or rate != execution["audioGraph"]["sampleRate"]
    ):
        raise RuntimeError("ProofPlan requires consistent stereo output/sample rate")
    if (
        spec["videoCodec"] not in {"libx264", "h264_nvenc"}
        or spec["audioCodec"] != "aac"
    ):
        raise RuntimeError("Unsupported ProofPlan output codec")
    if execution["events"]:
        raise RuntimeError(
            "ProofPlan timed events require an implemented event renderer"
        )
    if not execution["audioGraph"]["singleFinalEncode"]:
        raise RuntimeError("ProofPlan requires one final audio encode")
    return spec, fps, rate


def _audio_operations(graph: dict) -> tuple:
    audio_trims, encodes = {}, []
    for operation in graph["operations"]:
        if operation["kind"] == "resample":
            continue
        if operation["kind"] == "encode":
            if operation["parameters"]:
                raise RuntimeError("Unsupported final encode parameters")
            encodes.append(operation)
        elif operation["kind"] == "trim":
            parameters = operation["parameters"]
            if set(parameters) - {
                "nodeId",
                "sourceId",
                "source",
                "fadeInSamples",
                "fadeOutSamples",
                "dialogueNoiseReductionPolicy",
            }:
                raise RuntimeError("Unsupported audio trim parameters")
            if parameters["nodeId"] in audio_trims:
                raise RuntimeError("Duplicate audio trim operation")
            audio_trims[parameters["nodeId"]] = operation
        else:
            raise RuntimeError(
                f"Unsupported ProofPlan audio operation: {operation['kind']}"
            )
    return audio_trims, encodes


def _resample_operations(graph: dict) -> dict:
    operations = {}
    for operation in graph["operations"]:
        if operation["kind"] != "resample":
            continue
        parameters = operation["parameters"]
        if set(parameters) != {"nodeId", "sourceSampleRate", "targetSampleRate"}:
            raise RuntimeError("Unsupported resample parameters")
        node_id = parameters["nodeId"]
        if node_id in operations:
            raise RuntimeError("Duplicate resample operation")
        operations[node_id] = operation
    return operations


def _validate_resampling(graph: dict, nodes: list[dict], rate: int) -> None:
    operations = _resample_operations(graph)
    required = {
        n["nodeId"]
        for n in nodes
        if n["kind"] == "source" and n["sourceSampleRate"] != rate
    }
    if set(operations) != required:
        raise RuntimeError("Missing or unused explicit resample operation")
    for node in nodes:
        if node["nodeId"] in required:
            operation = operations[node["nodeId"]]
            if operation["range"] != node["outputRange"] or operation["parameters"] != {
                "nodeId": node["nodeId"],
                "sourceSampleRate": node["sourceSampleRate"],
                "targetSampleRate": rate,
            }:
                raise RuntimeError(
                    "Resample operation differs from source/target contract"
                )


def _segment_audio(node, audio_trims, execution, cache, sample_bounds, rate, fps):
    audio = None
    fades = (0, 0)
    if node["kind"] == "source":
        trim = audio_trims.get(node["nodeId"])
        if trim is None or trim["range"] != node["outputRange"]:
            raise RuntimeError("Missing exact audio source trim operation")
        audio = _source(
            trim["parameters"],
            execution["canonicalInputLock"],
            cache,
            audio_node=node,
        )
        fades = tuple(
            trim["parameters"].get(key, 0)
            for key in ("fadeInSamples", "fadeOutSamples")
        )
        if any(not isinstance(v, int) or v < 0 for v in fades):
            raise RuntimeError("Audio fades require nonnegative sample counts")
        astart, aend = _bounds(node["sourceRange"], "startSample", "endSampleExclusive")
        if (
            abs(
                round(Fraction(aend - astart, node["sourceSampleRate"]) * rate)
                - (sample_bounds[1] - sample_bounds[0])
            )
            > rate / fps
            or max(fades) > sample_bounds[1] - sample_bounds[0]
        ):
            raise RuntimeError(
                "Audio source duration/fades differ from target duration"
            )
    return audio, fades


def _dialogue_noise_policy(node, audio_trims):
    parameters = audio_trims.get(node["nodeId"], {}).get("parameters", {})
    if "dialogueNoiseReductionPolicy" not in parameters:
        return None
    if node["targetSampleRate"] != 48000:
        raise ValueError("Dialogue noise policy requires calibrated 48 kHz output")
    return validate_dialogue_noise_policy(
        parameters["dialogueNoiseReductionPolicy"],
        parameters["source"]["streamIndex"],
        node["channelMap"],
    )


def _validate_consumed(cursor, used_audio, nodes, audio_trims):
    if (
        not cursor
        or len(used_audio) != len(nodes)
        or set(audio_trims) != {n["nodeId"] for n in nodes if n["kind"] == "source"}
    ):
        raise RuntimeError("Unconsumed or empty ProofPlan graph")


def _segments(execution, node_by_range, audio_trims, fps, rate, nodes):
    operations = execution["videoGraph"]["operations"]
    registry = default_proof_capability_registry()
    refs = {item["implementationId"]: item for item in execution["implementationRefs"]}
    cursor, segments, cache, used_audio = 0, [], {}, set()
    for operation in operations:
        parameters = _video_parameters(operation, refs, registry)
        start, end = _bounds(
            operation["outputRange"], "startFrame", "endFrameExclusive"
        )
        if start != cursor:
            raise RuntimeError("Video trims must completely cover a sequential output")
        cursor = end
        sample_bounds = (
            round(Fraction(start, 1) / fps * rate),
            round(Fraction(end, 1) / fps * rate),
        )
        node = node_by_range.get(sample_bounds)
        if node is None:
            raise RuntimeError(
                "Every video trim requires matching absolute audio coverage"
            )
        used_audio.add(node["nodeId"])
        picture = _source(parameters, execution["canonicalInputLock"], cache)
        source_range = parameters["sourceRange"]
        raw_start, raw_end = _bounds(source_range, "startTicks", "endTicks")
        timebase = source_range["timebase"]
        source_start = _seconds(raw_start, timebase)
        source_duration = _seconds(raw_end - raw_start, timebase)
        if abs(source_duration - Fraction(end - start, 1) / fps) > 1 / fps:
            raise RuntimeError("Source/video duration differs by more than one frame")
        audio, fades = _segment_audio(
            node, audio_trims, execution, cache, sample_bounds, rate, fps
        )
        noise_policy = _dialogue_noise_policy(node, audio_trims)
        tail = _video_tail(
            parameters,
            picture,
            cache,
            source_start,
            source_duration,
            Fraction(end - start, 1) / fps,
        )
        segments.append(
            (
                start,
                end,
                picture,
                source_start,
                source_duration,
                node,
                audio,
                fades,
                tail,
                noise_policy,
            )
        )
    _validate_consumed(cursor, used_audio, nodes, audio_trims)
    return cursor, segments


def _dialogue_noise_filter(policy, node):
    if policy is None:
        return f",pan=stereo|c0=c{node['channelMap'][0]}|c1=c{node['channelMap'][1]}"
    channel = policy["channelIndex"]
    denoise = afftdn_filter(policy["strengthPercent"])
    chain = f",pan=mono|c0=c{channel}"
    if denoise:
        # afftdn retains two 12.5 ms windows. Feed its tail, then remove
        # exactly that 25 ms buffering delay without shifting raw words.
        chain += f",apad=pad_len=1200,{denoise},atrim=start_sample=1200,asetpts=N/SR/TB"
    return chain + ",pan=stereo|c0=c0|c1=c0"


def _noise_policy_records(graph):
    return [
        {
            "sourceId": operation["parameters"]["sourceId"],
            "nodeId": operation["parameters"]["nodeId"],
            "policy": operation["parameters"]["dialogueNoiseReductionPolicy"],
            "filter": afftdn_filter(
                operation["parameters"]["dialogueNoiseReductionPolicy"][
                    "strengthPercent"
                ]
            ),
            "latencyCompensationSamples": 1200
            if operation["parameters"]["dialogueNoiseReductionPolicy"][
                "strengthPercent"
            ]
            else 0,
        }
        for operation in graph["operations"]
        if operation["kind"] == "trim"
        and "dialogueNoiseReductionPolicy" in operation["parameters"]
    ]


def _render_piece(segment, left, right, spec, fps, rate, piece):
    (
        start,
        _end,
        picture,
        source_start,
        source_duration,
        node,
        audio,
        fades,
        tail,
        noise_policy,
    ) = segment
    path, stream = picture
    duration = Fraction(right - left, 1) / fps
    arguments = [
        "ffmpeg",
        "-v",
        "error",
        "-nostdin",
        "-ss",
        str(float(source_start)),
        "-i",
        str(path),
    ]
    pad_seconds = tail["padSeconds"] if tail else float(1 / fps)
    vfilter = f"[0:{stream}]trim=duration={float(source_duration)},setpts=PTS-STARTPTS,fps={fps.numerator}/{fps.denominator},tpad=stop_mode=clone:stop_duration={pad_seconds},trim=start_frame={left - start}:end_frame={right - start},setpts=PTS-STARTPTS,scale={spec['width']}:{spec['height']}:force_original_aspect_ratio=decrease,pad={spec['width']}:{spec['height']}:(ow-iw)/2:(oh-ih)/2,setsar=1,format=yuv420p[v]"
    target_start = round(Fraction(left, 1) / fps * rate)
    target_end = round(Fraction(right, 1) / fps * rate)
    length = target_end - target_start
    if audio:
        apath, astream = audio
        astart = node["sourceRange"]["startSample"]
        full_length = (
            node["outputRange"]["endSampleExclusive"]
            - node["outputRange"]["startSample"]
        )
        offset = target_start - node["outputRange"]["startSample"]
        arguments += ["-ss", str(astart / node["sourceSampleRate"]), "-i", str(apath)]
        raw_length = node["sourceRange"]["endSampleExclusive"] - astart
        afilter = f"[1:{astream}]atrim=end_sample={raw_length},asetpts=PTS-STARTPTS"
        if node["sourceSampleRate"] != rate:
            afilter += f",aresample={rate}"
        afilter += _dialogue_noise_filter(noise_policy, node)
        afilter += f",apad,atrim=end_sample={full_length}"
        if fades[0]:
            afilter += f",afade=t=in:ss=0:ns={fades[0]}"
        if fades[1]:
            afilter += f",afade=t=out:ss={full_length - fades[1]}:ns={fades[1]}"
        afilter += f",atrim=start_sample={offset}:end_sample={offset + length},asetpts=PTS-STARTPTS[a]"
    else:
        afilter = f"anullsrc=r={rate}:cl=stereo,atrim=end_sample={length}[a]"
    _run(
        arguments
        + [
            "-filter_complex",
            vfilter + ";" + afilter,
            "-map",
            "[v]",
            "-map",
            "[a]",
            "-c:v",
            "ffv1",
            "-c:a",
            "pcm_s32le",
            "-ar",
            str(rate),
            "-t",
            str(float(duration)),
            str(piece),
        ]
    )


def _render_media(output, segments, spec, fps, rate, wstart, wend):
    if output.exists():
        raise RuntimeError(f"Refusing to replace existing proof: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="proof-plan-", dir=output.parent) as folder:
        directory = Path(folder)
        pieces = []
        for (
            start,
            end,
            picture,
            source_start,
            source_duration,
            node,
            audio,
            fades,
            tail,
            noise_policy,
        ) in segments:
            left, right = max(start, wstart), min(end, wend)
            if left >= right:
                continue
            piece = directory / f"{len(pieces):06d}.mkv"
            _render_piece(
                (
                    start,
                    end,
                    picture,
                    source_start,
                    source_duration,
                    node,
                    audio,
                    fades,
                    tail,
                    noise_policy,
                ),
                left,
                right,
                spec,
                fps,
                rate,
                piece,
            )
            pieces.append(piece)
        listing = directory / "concat.txt"
        listing.write_text(
            "".join(f"file '{p.name}'\n" for p in pieces), encoding="utf-8"
        )
        candidate = directory / "candidate.mp4"
        _run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-nostdin",
                "-f",
                "concat",
                "-safe",
                "1",
                "-i",
                str(listing),
                "-vf",
                f"setpts=N/({fps.numerator}/{fps.denominator}*TB)",
                "-af",
                "asetpts=N/SR/TB",
                "-c:v",
                spec["videoCodec"],
                "-c:a",
                "aac",
                "-b:a",
                "192k",
                "-ar",
                str(rate),
                "-r",
                f"{fps.numerator}/{fps.denominator}",
                "-frames:v",
                str(wend - wstart),
                "-movflags",
                "+faststart",
                str(candidate),
            ]
        )
        media = json.loads(
            subprocess.run(
                [
                    "ffprobe",
                    "-v",
                    "error",
                    "-show_streams",
                    "-of",
                    "json",
                    str(candidate),
                ],
                capture_output=True,
                text=True,
                check=True,
            ).stdout
        )
        video = next(s for s in media["streams"] if s["codec_type"] == "video")
        if (
            int(video["nb_frames"]) != wend - wstart
            or Fraction(video["r_frame_rate"]) != fps
        ):
            raise RuntimeError("Encoded proof violates its exact frame contract")
        candidate.replace(output)
    return media


def execute_ffmpeg_proof(execution: dict[str, Any], output: Path) -> dict[str, Any]:
    """Render the supported immutable graph without falling back to an EDL."""
    spec, fps, rate = _output_settings(execution)
    nodes = execution["audioGraph"]["nodes"]
    node_by_range = _audio_nodes(nodes, rate)
    _validate_resampling(execution["audioGraph"], nodes, rate)
    audio_trims, encodes = _audio_operations(execution["audioGraph"])
    cursor, segments = _segments(
        execution, node_by_range, audio_trims, fps, rate, nodes
    )
    total_samples = round(Fraction(cursor, 1) / fps * rate)
    if len(encodes) != 1 or encodes[0]["range"] != {
        "startSample": 0,
        "endSampleExclusive": total_samples,
    }:
        raise RuntimeError("One encode must cover the complete audio graph")
    window = execution["window"]
    wstart, wend = (
        (0, cursor)
        if window is None
        else _bounds(window, "startFrame", "endFrameExclusive")
    )
    if wend > cursor:
        raise RuntimeError("Microproof window exceeds ProofPlan output")
    media = _render_media(output, segments, spec, fps, rate, wstart, wend)
    return {
        "status": "pass",
        "output": file_fingerprint(output),
        "path": str(output),
        "audioEncodeCount": 1,
        "producer": {"name": "avo.ffmpeg-proof-plan", "version": "1"},
        "media": media,
        "sourceVideoTailPolicies": [s[-2] for s in segments if s[-2] is not None],
        "sourceDialogueNoisePolicies": _noise_policy_records(execution["audioGraph"]),
    }
