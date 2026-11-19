"""Map canonical original-source placements onto the measured xmeml subset."""

from fractions import Fraction

from .event_clock import sample_rate_boundary
from .import_layout import seconds


def representable_clip_gain(gain):
    return type(gain) in (int, float) and -60 <= gain <= 12


def rational(value):
    return {"num": value.numerator, "den": value.denominator}


def _contiguous(snapshot):
    position = Fraction(0)
    sources = {row["sourceId"]: row for row in snapshot["sources"]}
    for segment in snapshot["segments"]:
        start, end = (seconds(segment[key]) for key in ("in", "out"))
        extent = (position, position + end - start)
        metadata = sources[segment["sourceId"]].get("streamMetadata", {})
        common = {
            "sourceId": segment["sourceId"],
            "raw": (start, end),
            "output": extent,
            "enabled": True,
            "muted": False,
            "effects": [],
        }
        yield {
            **common,
            "id": segment["segmentId"] + "-picture",
            "kind": "video",
            "mediaKind": "video",
            "laneId": "original-picture",
            "order": 0,
            "routing": {"videoStreamIndex": metadata.get("videoStreamIndex")},
        }
        if metadata.get("audioSelection"):
            yield {
                **common,
                "id": segment["segmentId"] + "-sound",
                "kind": "audio",
                "mediaKind": "audio",
                "laneId": "original-audio",
                "order": 0,
                "routing": {"audioSelection": metadata["audioSelection"]},
            }
        position = extent[1]


def _placed(snapshot):
    layout = snapshot["layout"]
    lanes = {row["trackId"]: row for row in layout["tracks"]}
    for row in layout["placements"]:
        lane = lanes[row["trackId"]]
        yield {
            "id": row["placementId"],
            "laneId": lane["trackId"],
            "order": lane["order"],
            "kind": lane["kind"],
            "mediaKind": row["mediaKind"],
            "sourceId": row["sourceId"],
            "raw": tuple(seconds(row[key]) for key in ("in", "out")),
            "output": tuple(seconds(row[key]) for key in ("start", "end")),
            "enabled": row["enabled"] and lane["enabled"],
            "muted": row.get("muted", False) or lane["muted"],
            "routing": row["routing"],
            "gainDb": row.get("gainDb"),
            "effects": [
                key
                for key in (
                    "pictureFade",
                    "pictureTransform",
                    "pictureSampling",
                    "pictureEndGapFrames",
                    "audioPeakCeilingDbfs",
                    "audioTailSilenceSamples",
                )
                if key in row
            ]
            + (["gainDb"] if row.get("gainDb", 0) else []),
        }


def selected_placements(snapshot, program_rate, window):
    """Use canonical source and program clocks before any interchange quantization."""
    placed = snapshot.get("layoutMode") == "placed"
    if placed:
        expected = snapshot["layout"]["programClock"]["frameRate"]
        if program_rate != Fraction(expected["num"], expected["den"]):
            raise ValueError(
                "Handoff program rate differs from the canonical placed clock"
            )
    rows = list(_placed(snapshot) if placed else _contiguous(snapshot))
    first = window["startFrame"] / program_rate
    end = window["endFrameExclusive"] / program_rate
    extent = (
        seconds(snapshot["layout"]["duration"])
        if placed
        else max((row["output"][1] for row in rows), default=Fraction(0))
    )
    if not 0 <= first < end <= extent:
        raise ValueError("Handoff window escapes the canonical program")
    selected = []
    for row in rows:
        start, stop = row["output"]
        overlap = (max(start, first), min(stop, end))
        if overlap[0] < overlap[1]:
            selected.append({**row, "window": overlap})
    return selected


def _stream(available, index):
    selected = [row for row in available if index is None or row["index"] == index]
    if len(selected) != 1:
        raise ValueError("Original source does not expose one selected stream")
    return selected[0]


def _encoded_duration(stream, base):
    ticks = stream.get("durationTicks")
    if type(ticks) is int:
        return ticks * base
    observed = stream.get("durationSeconds")
    if observed is None:
        raise ValueError("Original stream has no observed duration")
    return Fraction(str(observed))


def _picture_measurements(stream, base):
    rate = Fraction(stream["frameRate"])
    count = stream.get("frameCount")
    if rate <= 0 or Fraction(stream.get("averageFrameRate") or rate) != rate:
        raise ValueError("Original picture frame clock is unverified")
    duration = Fraction(count) / rate if count else _encoded_duration(stream, base)
    return rate, duration, stream


def program_picture_format(snapshot, sources):
    declared = snapshot.get("renderOutput") or snapshot.get("importOutput")
    if declared is not None:
        return {
            "width": declared["width"],
            "height": declared["height"],
            "pixelAspectRatio": "square",
        }
    return next(
        (
            source["pictureFormat"]
            for source in sources.values()
            if "pictureFormat" in source
        ),
        None,
    )


def _source_measurements(row, facts, program_rate):
    kind, routing = row["kind"], row["routing"]
    selection = routing.get("audioSelection") or {}
    index = (
        routing.get("videoStreamIndex")
        if kind == "video"
        else selection.get("streamIndex")
    )
    stream = _stream(facts["streams"][kind], index)
    base = Fraction(stream["timeBase"])
    if kind == "audio":
        if stream.get("sampleRate") != selection.get(
            "sourceSampleRate", stream.get("sampleRate")
        ):
            raise ValueError("Original audio duration or sample route is unverified")
        return program_rate, _encoded_duration(stream, base), stream
    return _picture_measurements(stream, base)


def _loss(row, program_rate, reason, field=None):
    first, last = (point * program_rate for point in row["window"])
    start = first.numerator // first.denominator
    end = -(-last.numerator // last.denominator)
    return {
        "field": field or row["id"],
        "scope": {"startFrame": start, "endFrameExclusive": end},
        "reason": reason,
    }


def _quantize(frames, *, audio):
    if not audio and any(point.denominator != 1 for point in frames):
        raise ValueError("Picture interval falls between exact interchange frames")
    return [
        sample_rate_boundary(
            point.numerator, source_rate=point.denominator, target_rate=1
        )
        for point in frames
    ]


def _geometry(row, source_rate, source_duration, program_rate, start_frame):
    first, last = row["window"]
    raw_first, raw_last = row["raw"]
    program_first, program_last = row["output"]
    if raw_last - raw_first != program_last - program_first:
        raise ValueError("Retime or conform requires target qualification")
    selected_raw = (raw_first + first - program_first, raw_first + last - program_first)
    if not 0 <= selected_raw[0] < selected_raw[1] <= source_duration:
        raise ValueError("Selected source interval exceeds measured original media")
    exact = [
        first * program_rate - start_frame,
        last * program_rate - start_frame,
        *(time * source_rate for time in selected_raw),
    ]
    serialized = _quantize(exact, audio=row["kind"] == "audio")
    if serialized[0] >= serialized[1] or serialized[2] >= serialized[3]:
        raise ValueError("Audio interval collapses on the interchange frame grid")
    return dict(zip(("start", "end", "in", "out"), serialized, strict=True)), dict(
        zip(("start", "end", "in", "out"), map(rational, exact), strict=True)
    )


def _channels(row, facts, stream):
    if row["kind"] == "video":
        ports = [entry["index"] for entry in facts["streams"]["video"]]
        return [(None, ports.index(stream["index"]) + 1)]
    if len(facts["streams"]["audio"]) != 1:
        raise ValueError("Multiple embedded audio streams require target review")
    selection = row["routing"]["audioSelection"]
    channels = selection["channels"]
    if not channels or any(
        channel < 0 or channel >= stream["channels"] for channel in channels
    ):
        raise ValueError("Selected original channel is unavailable")
    if selection["outputLayout"] == "dual-mono":
        channels = [channels[0], channels[0]]
    return [(output, channel + 1) for output, channel in enumerate(channels, 1)]


def original_occurrences(row, original, facts, program_rate, start_frame):
    if row["mediaKind"] not in {"video", "audio"}:
        raise ValueError(
            "Selected still, title or generator needs target representation evidence"
        )
    rate, duration, stream = _source_measurements(row, facts, program_rate)
    geometry, exact = _geometry(row, rate, duration, program_rate, start_frame)
    file_id = f"{row['sourceId']}-{row['kind']}-{stream['index']}"
    source = {
        "locator": original["locator"],
        "rate": rate,
        "duration": _quantize([duration * rate], audio=row["kind"] == "audio")[0],
        "originFrame": 0,
    }
    if row["kind"] == "video" and stream["width"] > 0 and stream["height"] > 0:
        source["pictureFormat"] = {
            "width": stream["width"],
            "height": stream["height"],
            "pixelAspectRatio": "square"
            if stream.get("sampleAspectRatio") == "1:1"
            else None,
        }
    result = []
    for output, channel in _channels(row, facts, stream):
        identity = row["id"] if output is None else f"{row['id']}-channel-{output}"
        clip = {
            **geometry,
            "id": identity,
            "fileId": file_id,
            "rate": rate,
            "name": row["id"],
            "enabled": row["enabled"] and not row["muted"],
            "sourceTrack": channel,
        }
        evidence = {
            "id": identity,
            "placementId": row["id"],
            "sourceId": row["sourceId"],
            "streamIndex": stream["index"],
            "sourceOriginTicks": stream.get("startTicks"),
            "laneId": row["laneId"],
            "exactFrames": exact,
            "serializedFrames": geometry,
        }
        result.append((output, clip, evidence))
    return file_id, source, result
