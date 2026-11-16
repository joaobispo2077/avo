"""Build ordinary import options from the export and local media ports."""

from copy import deepcopy
from fractions import Fraction
from pathlib import Path

from .contracts import file_fingerprint, fingerprint_stage
from .otio_import import (
    ImportError,
    _active_reference,
    _pointer,
    _range,
    _seconds,
    _select,
    _time,
    parse_export_bytes,
    read_export,
)
from .resolve_export import EXPORT_MODE, plain_payload

_STILLS = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp"}


def _clips(selected, pointer):
    for ti, track in enumerate(selected.get("tracks", {}).get("children", [])):
        base = _pointer(_pointer(_pointer(pointer, "tracks"), "children"), ti)
        for ci, clip in enumerate(track.get("children", [])):
            if clip.get("OTIO_SCHEMA") not in {"Clip.1", "Clip.2"}:
                continue
            owner = _pointer(_pointer(base, "children"), ci)
            reference = _active_reference(clip, owner)
            suffix = (
                "/media_reference"
                if "media_reference" in clip
                else "/media_references/"
                + str(clip["active_media_reference_key"])
                .replace("~", "~0")
                .replace("/", "~1")
            )
            yield {
                "pointer": owner,
                "referencePointer": owner + suffix,
                "reference": reference,
                "clip": clip,
                "kind": track["kind"].lower(),
            }


def _duration(selected):
    ends = []
    for track in selected["tracks"]["children"]:
        total = Fraction(0)
        for child in track.get("children", []):
            value = _range(child.get("source_range"))
            if value is None:
                ref = (
                    _active_reference(child, "")
                    if child.get("OTIO_SCHEMA") in {"Clip.1", "Clip.2"}
                    else {}
                )
                value = _range(ref.get("available_range"))
            if value is not None:
                total += _seconds(value["duration"], {}, "")
        ends.append(total)
    return max(ends, default=Fraction(0))


def _sidecar(service, path, selected):
    companion = path.with_suffix(".drt")
    if service.metadata_reader is None or not companion.is_file():
        return {}, []
    try:
        facts = service.metadata_reader(companion)
        fps = facts["output"]["frameRate"]
        tolerance = Fraction(fps["den"], fps["num"])
        if (
            abs(Fraction(str(facts["durationSeconds"])) - _duration(selected))
            > tolerance
        ):
            raise ValueError("Paired DRT program extent differs from the OTIO")
        return facts, list(facts.get("warnings", []))
    except (OSError, ValueError, KeyError, RuntimeError) as exc:
        return {}, [
            "Paired Resolve metadata was retained but could not supply settings: "
            + str(exc)
        ]


def _local_paths(service, clips, root):
    from .import_service import _local_reference

    result = {}
    for clip in clips:
        ref = clip["reference"]
        if ref.get("OTIO_SCHEMA") != "ExternalReference.1":
            continue
        path = _local_reference(ref.get("target_url", ""))
        if not path.is_absolute():
            path = service.workspace.raw_dir / path
        path = path.resolve()
        service._source_boundary(
            path,
            {"identityConfirmed": True},
            {"options": {"mediaRoots": [str(root)]}},
            clip["referencePointer"],
        )
        result[clip["referencePointer"]] = path
    return result


def _output(selected, inventory, metadata, warnings):
    if metadata.get("output"):
        return deepcopy(metadata["output"])
    pictures = [
        stream
        for path, info in inventory.items()
        if path.suffix.lower() not in _STILLS
        for stream in info["streams"].get("video", [])
    ]
    if not pictures:
        raise ImportError(
            "OTIO_RATE_UNVERIFIED",
            "Export has no canvas metadata or available moving-picture source; set the canvas once in AVO",
        )
    picture = pictures[0]
    start = _time(selected.get("global_start_time"))
    rate = Fraction(start["rate"]) if start else Fraction(picture["frameRate"])
    warnings.append(
        "OTIO omitted canvas dimensions; the draft uses its first moving-picture source dimensions. Output settings remain editable in AVO."
    )
    return {
        "width": picture["width"],
        "height": picture["height"],
        "frameRate": {"num": rate.numerator, "den": rate.denominator},
        "audioSampleRate": 48000,
        "channelLayout": "stereo",
    }


def _export_audio_channels(clip, channels, streams):
    if not isinstance(channels, list) or any(not _channel_pair(c) for c in channels):
        raise ImportError(
            "OTIO_ROUTING_UNVERIFIED",
            "Invalid exported audio channel selection",
            scope=clip["pointer"],
        )
    tracks = {c["Source Track ID"] for c in channels}
    if len(tracks) != 1:
        raise ImportError(
            "OTIO_ROUTING_UNVERIFIED",
            "Cross-stream channel routing requires a supported AVO routing operation",
            scope=clip["pointer"],
        )
    ordinal = next(iter(tracks))
    if type(ordinal) is not int or not 0 <= ordinal < len(streams):
        raise ImportError(
            "OTIO_ROUTING_UNVERIFIED",
            "Exported audio stream ordinal is unavailable",
            scope=clip["pointer"],
        )
    stream = streams[ordinal]
    chosen = [c["Source Channel ID"] for c in channels]
    return stream, chosen


def _channel_pair(value):
    return isinstance(value, dict) and all(
        type(value.get(k)) is int and value[k] >= 0
        for k in ("Source Track ID", "Source Channel ID")
    )


def _audio_selection(clip, info):
    streams = sorted(info["streams"].get("audio", []), key=lambda s: s["index"])
    channels = (
        clip["clip"].get("metadata", {}).get("Resolve_OTIO", {}).get("Channels", [])
    )
    if channels:
        stream, chosen = _export_audio_channels(clip, channels, streams)
    else:
        if len(streams) != 1 or streams[0]["channels"] not in {1, 2}:
            raise ImportError(
                "OTIO_ROUTING_UNVERIFIED",
                "Export does not identify an unambiguous mono/stereo audio stream",
                scope=clip["pointer"],
            )
        stream = streams[0]
        chosen = [0, 1] if stream["channels"] == 2 else [0, 0]
    layout = stream.get("channelLayout") or {1: "mono", 2: "stereo"}.get(
        stream["channels"], "unknown"
    )
    return {
        "streamIndex": stream["index"],
        "channels": chosen,
        "sourceLayout": layout,
        "outputLayout": "stereo",
    }, stream


def _sample_count(service, clip, path, stream, fingerprint, cache):
    key = (path, stream["index"])
    if key not in cache:
        cache[key] = service.audio_clock_probe(
            path, stream["index"], expected_sha256=fingerprint["sha256"]
        )
    evidence = cache[key]
    from .import_service import _verified_audio_samples

    count = _verified_audio_samples(evidence, fingerprint, stream, clip["pointer"])
    return count


def _bounded_tail(gap, start, count):
    return 0 < gap <= 12000 and gap.denominator == 1 and start * 48000 < count


def _tail(service, clip, path, stream, fingerprint, cache):
    if stream["sampleRate"] != 48000 or service.audio_clock_probe is None:
        return {}
    source = _range(clip["clip"].get("source_range")) or _range(
        clip["reference"].get("available_range")
    )
    available = _range(clip["reference"].get("available_range"))
    origin = (
        _seconds(available["start"], {}, clip["pointer"]) if available else Fraction(0)
    )
    start = _seconds(source["start"], {}, clip["pointer"]) - origin
    end = start + _seconds(source["duration"], {}, clip["pointer"])
    duration = stream.get("durationSeconds")
    if duration is not None and end < Fraction(str(duration)) - 1:
        return {}
    count = _sample_count(service, clip, path, stream, fingerprint, cache)
    gap = end * 48000 - count
    if _bounded_tail(gap, start, count):
        return {"audioTailSilenceSamples": int(gap)}
    return {}


def _media_mapping(service, clip, path, info, output, cache):
    mapping = {
        "path": str(path),
        "identityConfirmed": True,
        "fingerprint": _mapping_fingerprint(path, info["fingerprint"]),
    }
    if clip["kind"] == "audio":
        selection, stream = _audio_selection(clip, info)
        return {
            **mapping,
            "audioSelection": selection,
            **_tail(service, clip, path, stream, info["fingerprint"], cache),
        }
    streams = info["streams"].get("video", [])
    if len(streams) != 1:
        raise ImportError(
            "OTIO_ROUTING_UNVERIFIED",
            "Export does not identify an unambiguous picture stream",
            scope=clip["pointer"],
        )
    stream = streams[0]
    mapping["videoStreamIndex"] = stream["index"]
    if path.suffix.lower() in _STILLS:
        mapping["mediaKind"] = "still"
    elif Fraction(stream["frameRate"]) * 2 == Fraction(
        output["frameRate"]["num"], output["frameRate"]["den"]
    ):
        mapping["pictureSampling"] = "repeat-2x"
    if mapping.get("mediaKind") != "still":
        mapping.update(
            _video_end_gap(service, path, stream, info["fingerprint"], cache)
        )
    return mapping


def _video_end_gap(service, path, stream, fingerprint, cache):
    if service.clock_probe is None:
        return {}
    key = ("video-end-gap", path, stream["index"])
    if key not in cache:
        try:
            cache[key] = service.clock_probe(
                path,
                stream["index"],
                Fraction(stream["frameRate"]),
                time_base=stream["timeBase"],
                expected_sha256=fingerprint["sha256"],
                expected_frames=stream.get("frameCount"),
                start_ticks=stream.get("startTicks"),
                allow_end_gap=True,
            )
        except (OSError, ValueError, RuntimeError):
            cache[key] = {}
    gap = cache[key].get("endGapFrames", 0)
    return {"pictureEndGapFrames": gap} if gap else {}


def _mapping_fingerprint(path, value):
    return {
        "path": str(path),
        "sha256": value["sha256"],
        "sizeBytes": value["sizeBytes"],
    }


def _recoverable_title(clip, titles, count, output):
    if count != 1 or len(titles) != 1 or not titles[0].get("fontPath"):
        return False
    data = titles[0]
    if round(data["normalizedSize"] * output["height"]) > 1024:
        return False
    if (data["canvasWidth"], data["canvasHeight"]) != (
        output["width"],
        output["height"],
    ):
        return False
    bounds = _range(clip["clip"].get("source_range"))
    if bounds is None:
        return False
    end = _seconds(bounds["start"], {}, clip["pointer"]) + _seconds(
        bounds["duration"], {}, clip["pointer"]
    )
    fps = Fraction(output["frameRate"]["num"], output["frameRate"]["den"])
    return end * fps <= data["lastFrame"] + 1


def _generated_mapping(clip, export, metadata, count, output):
    titles = metadata.get("titles", [])
    if _recoverable_title(clip, titles, count, output):
        data = titles[0]
        font = Path(data["fontPath"])
        return {
            "path": metadata["path"],
            "fingerprint": _mapping_fingerprint(
                metadata["path"], metadata["fingerprint"]
            ),
            "identityConfirmed": True,
            "mediaKind": "title",
            "title": {
                "text": data["text"],
                "canvasWidth": output["width"],
                "canvasHeight": output["height"],
                "x": output["width"] // 2,
                "y": output["height"] // 2,
                "fontSize": max(1, round(data["normalizedSize"] * output["height"])),
                "color": "#FFFFFFFF",
                "anchor": "center",
            },
            "font": {"path": str(font), "fingerprint": file_fingerprint(font)},
        }
    return {
        "path": str(export),
        "fingerprint": _mapping_fingerprint(export, file_fingerprint(export)),
        "identityConfirmed": True,
        "mediaKind": "generator",
        "generator": plain_payload(clip["clip"]),
    }


def _build_mappings(
    service,
    clips,
    paths,
    described,
    output,
    cache,
    path,
    metadata,
    count,
    mappings,
    titles,
    generated,
    origins,
):
    for clip in clips:
        ref = clip["referencePointer"]
        source = paths.get(ref)
        if source is not None:
            if source in described:
                mappings[ref] = _media_mapping(
                    service, clip, source, described[source], output, cache
                )
            continue
        mapping = _generated_mapping(clip, path, metadata, count, output)
        mappings[ref] = mapping
        (titles if mapping["mediaKind"] == "title" else generated).append(ref)
        bounds = _range(clip["clip"].get("source_range"))
        if bounds:
            origins[ref] = bounds["start"]


def automatic_options(service, input_path, *, timeline=None, media_roots=None):
    """Reuse admission ports; prepare no new creative edit and grant no approval."""
    path = Path(input_path).resolve()
    data, _, _ = read_export(path)
    _, document, _ = parse_export_bytes(data)
    pointer, selected = _select(document, timeline)
    clips = list(_clips(selected, pointer))
    roots = list(media_roots or [service.workspace.raw_dir])
    metadata, warnings = _sidecar(service, path, selected)
    paths = _local_paths(service, clips, roots[0])
    existing = sorted({p for p in paths.values() if p.is_file()})
    with fingerprint_stage(verify_on_exit=True):
        inventory = (
            service._local_probe(existing, pointer) if existing else {"sources": []}
        )
        described = {
            Path(item["locator"]).resolve(): item for item in inventory["sources"]
        }
        output = _output(selected, described, metadata, warnings)
        mappings, origins, titles, generated, cache = {}, {}, [], [], {}
        count = sum(
            c["reference"].get("OTIO_SCHEMA") != "ExternalReference.1" for c in clips
        )
        _build_mappings(
            service,
            clips,
            paths,
            described,
            output,
            cache,
            path,
            metadata,
            count,
            mappings,
            titles,
            generated,
            origins,
        )
    declarations = {
        "sourceOnly": False,
        "reconstructionMode": EXPORT_MODE,
        "layoutMode": "placed",
        "output": output,
        "generatedTitles": titles,
        "generatedReferences": generated,
        "mediaOrigins": origins,
        "automatic": {
            "warnings": warnings,
            "sidecar": metadata.get("path"),
            "sidecarFingerprint": metadata.get("fingerprint"),
            "samplingDefault": "nearest-repeat-for-exact-2x",
        },
    }
    return {
        "timeline": pointer,
        "media_roots": roots,
        "mappings": mappings,
        "declarations": declarations,
    }
