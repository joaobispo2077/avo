"""Exact placed source assembly; no media execution or legacy projection."""

from fractions import Fraction

from .contracts import ContractError, validate_document
from .event_clock import sample_rate_boundary


class LayoutError(ValueError):
    pass


def picture_input_ids(placements):
    result = {item["sourceId"] for item in placements}
    result.update(
        item["fontSource"]["sourceId"]
        for item in placements
        if item["mediaKind"] == "title"
    )
    return sorted(result)


def _has_placement_field(layout, field):
    return any(field in item for item in layout["placements"])


def import_capability_version(snapshot):
    if snapshot.get("layoutMode") != "placed":
        return "contiguous-1.0.0"
    if _has_placement_field(snapshot["layout"], "pictureEndGapFrames"):
        return "placed-end-gap-1.0.0"
    if snapshot["layout"].get("importMode") == "export-driven":
        return "placed-export-driven-1.0.0"
    if any(item["mediaKind"] == "title" for item in snapshot["layout"]["placements"]):
        return "placed-title-1.0.0"
    if _has_picture_treatments(snapshot["layout"]):
        return "placed-treatments-1.0.0"
    if any(
        "audioTailSilenceSamples" in item for item in snapshot["layout"]["placements"]
    ):
        return "placed-audio-tail-1.0.0"
    if _has_placement_field(snapshot["layout"], "pictureSampling"):
        return "placed-sampling-1.0.0"
    return "placed-1.0.0"


def _has_picture_treatments(layout):
    return layout.get("inactiveEffects") or any(
        {"pictureTransform", "pictureFade"}.intersection(item)
        for item in layout["placements"]
    )


def seconds(value):
    base = value["timebase"]
    return Fraction(value["ticks"] * base["num"], base["den"])


def _sample(value, rate):
    value = seconds(value)
    return sample_rate_boundary(
        value.numerator, source_rate=value.denominator, target_rate=rate
    )


def audio_sample_ranges(item):
    native = item["routing"]["audioSelection"]["sourceSampleRate"]
    source = {
        "startSample": _sample(item["in"], native),
        "endSampleExclusive": _sample(item["out"], native),
    }
    output = {
        "startSample": _sample(item["start"], 48000),
        "endSampleExclusive": _sample(item["end"], 48000),
    }
    output["endSampleExclusive"] -= item.get("audioTailSilenceSamples", 0)
    expected = sample_rate_boundary(
        source["endSampleExclusive"], source_rate=native, target_rate=48000
    ) - sample_rate_boundary(
        source["startSample"], source_rate=native, target_rate=48000
    )
    if (
        expected <= 0
        or output["endSampleExclusive"] - output["startSample"] != expected
    ):
        raise LayoutError(
            "Placed audio endpoints do not preserve native PCM sample counts"
        )
    return source, output


def _unique(items, key):
    result = {item[key]: item for item in items}
    if len(result) != len(items):
        raise LayoutError(f"Placed {key} values must be unique")
    return result


def _clock(snapshot):
    layout = snapshot["layout"]
    clock = layout["programClock"]
    rate, base = clock["frameRate"], clock["timebase"]
    fps = Fraction(rate["num"], rate["den"])
    if fps * Fraction(base["num"], base["den"]) != 1:
        raise LayoutError("Placed program timebase must be the inverse frame rate")
    output = snapshot["importOutput"]
    if (
        Fraction(output["frameRate"]["num"], output["frameRate"]["den"]) != fps
        or output["audioSampleRate"] != clock["audioSampleRate"]
        or output["displayOrigin"] != layout["displayOrigin"]
    ):
        raise LayoutError("Placed clock/display origin contradicts canonical output")
    duration = seconds(layout["duration"])
    if duration <= 0 or (duration * fps).denominator != 1:
        raise LayoutError(
            "Placed duration must contain a positive integral frame count"
        )
    return fps, duration


def _interval(item, duration):
    start, end = seconds(item["start"]), seconds(item["end"])
    if not 0 <= start < end <= duration:
        raise LayoutError("Placed output interval is outside the program extent")
    return start, end


def _placement(item, sources, tracks, duration, fps):
    if item["sourceId"] not in sources or item["trackId"] not in tracks:
        raise LayoutError("Placed source or track reference is missing")
    _placement_sources(item, sources)
    start, end = _interval(item, duration)
    raw_start, raw_end = seconds(item["in"]), seconds(item["out"])
    if not 0 <= raw_start < raw_end:
        raise LayoutError("Placed raw interval must be positive and nonnegative")
    for time in (item["in"], item["out"]):
        if time["domain"] != "raw-source" or time["sourceId"] != item["sourceId"]:
            raise LayoutError("Placed raw times must use their exact source clock")
    _placement_kind(
        item, tracks[item["trackId"]], end - start, raw_end - raw_start, fps, start, end
    )
    _raw_picture_boundaries(item, raw_start, raw_end, fps)


def _placement_sources(item, sources):
    if item["mediaKind"] not in {"title", "generator"}:
        if sources[item["sourceId"]]["kind"] != "raw":
            raise LayoutError("Moving media requires raw media, not authorial data")
        return
    if item["mediaKind"] == "generator":
        if sources[item["sourceId"]]["kind"] != "authorial":
            raise LayoutError("Generated reference requires original authorial data")
        return
    font = sources.get(item.get("fontSourceId"), {})
    if (
        sources[item["sourceId"]]["kind"] != "authorial"
        or font.get("kind") != "authorial"
    ):
        raise LayoutError("Title requires original authorial and font dependencies")


def _raw_picture_boundaries(item, raw_start, raw_end, fps):
    source_fps = picture_source_rate(item, fps)
    if item["mediaKind"] in {"video", "title", "generator"} and any(
        (point * source_fps).denominator != 1 for point in (raw_start, raw_end)
    ):
        raise LayoutError(
            "Moving-picture raw boundaries must be integral verified source frames"
        )
    if item["mediaKind"] == "still" and (raw_start != 0 or raw_end != 1 / fps):
        raise LayoutError("A still must hold its verified original first frame")


def picture_source_rate(item, program_rate):
    """An explicit sampling operation changes frame count, never source time."""
    if "pictureSampling" not in item:
        return program_rate
    if item["pictureSampling"] != "repeat-2x" or item["mediaKind"] != "video":
        raise LayoutError("Unsupported picture sampling for this placement")
    return program_rate / 2


def validate_picture_operations(item, frames, *, canvas=None):
    if "pictureEndGapFrames" in item:
        gap = item["pictureEndGapFrames"]
        if item["mediaKind"] != "video" or type(gap) is not int or not 1 <= gap <= 3:
            raise LayoutError(
                "Picture end gaps require one to three verified missing source frames"
            )
    for key, schema in (
        ("pictureTransform", "placedPictureTransform"),
        ("pictureFade", "placedPictureFade"),
    ):
        if key not in item:
            continue
        allowed = (
            {"video", "still", "title", "generator"}
            if key == "pictureFade"
            else {"video", "still"}
        )
        if item["mediaKind"] not in allowed:
            raise LayoutError("Picture operations require picture placements")
        try:
            validate_document(item[key], f"avo.cmap.schema.json#/$defs/{schema}")
        except ContractError as exc:
            raise LayoutError(f"Unsupported picture operation: {exc}") from exc
    _validate_title_canvas(item, canvas)
    _validate_picture_extent(item, frames, canvas)


def _validate_title_canvas(item, canvas):
    if item["mediaKind"] == "title":
        validate_document(item["title"], "avo.cmap.schema.json#/$defs/placedTitle")
        if (
            canvas is not None
            and (item["title"]["canvasWidth"], item["title"]["canvasHeight"]) != canvas
        ):
            raise LayoutError("Title canvas differs from canonical output")


def _validate_picture_extent(item, frames, canvas):
    fade = item.get("pictureFade", {})
    if fade.get("inFrames", 0) + fade.get("outFrames", 0) > frames:
        raise LayoutError("Picture fade intervals overlap or exceed placement")
    transform = item.get("pictureTransform")
    if (
        transform
        and canvas is not None
        and (transform["canvasWidth"], transform["canvasHeight"]) != canvas
    ):
        raise LayoutError("Picture transform canvas differs from canonical output")


def _placement_kind(item, track, output_length, raw_length, fps, start, end):
    kind = item["mediaKind"]
    required = "audio" if kind == "audio" else "video"
    if track["kind"] != required:
        raise LayoutError("Placement kind contradicts its track")
    tail = Fraction(item.get("audioTailSilenceSamples", 0), 48000)
    if kind != "still" and output_length != raw_length + tail:
        raise LayoutError("Normal-speed source and output durations must match exactly")
    if kind != "audio" and any(
        (point * fps).denominator != 1 for point in (start, end)
    ):
        raise LayoutError("Picture placement boundaries must be integral output frames")
    if kind == "audio":
        _audio_placement_kind(item, tail)


def _audio_placement_kind(item, tail):
    selection = item["routing"]["audioSelection"]
    if tail and selection["sourceSampleRate"] != 48000:
        raise LayoutError("Audio tail silence requires native 48000 Hz source")
    audio_sample_ranges(item)
    if (
        len(selection["channels"])
        != {"stereo": 2, "dual-mono": 1}[selection["outputLayout"]]
    ):
        raise LayoutError("Placed audio channel selection contradicts its routing")


def _picture_gap(item, tracks, clock):
    if "gapId" not in item or tracks[item["trackId"]]["kind"] != "video":
        return
    rate = clock["frameRate"]
    fps = Fraction(rate["num"], rate["den"])
    if any((seconds(item[key]) * fps).denominator != 1 for key in ("start", "end")):
        raise LayoutError("Picture gap boundaries must be integral output frames")


def _track_intervals(layout, tracks, duration):
    intervals = {track_id: [] for track_id in tracks}
    for item in [*layout["placements"], *layout["gaps"]]:
        if item["trackId"] not in intervals:
            raise LayoutError("Placed gap/clip track reference is missing")
        start, end = _interval(item, duration)
        _picture_gap(item, tracks, layout["programClock"])
        intervals[item["trackId"]].append((start, end))
    for values in intervals.values():
        previous = Fraction(0)
        for start, end in sorted(values):
            if start < previous:
                raise LayoutError("Placed intervals overlap on one track")
            previous = end


def validate_layout(snapshot):
    try:
        validate_document(snapshot, "avo.cmap.schema.json#/$defs/cmapSnapshot")
    except ContractError as exc:
        raise LayoutError(f"Invalid placed CMap: {exc}") from exc
    validate_layout_content(snapshot, snapshot["importOutput"])


def validate_privacy_masks(value, total_frames, *, canvas=None):
    try:
        validate_document(value, "avo.cmap.schema.json#/$defs/placedPrivacyMasks")
    except ContractError as exc:
        raise LayoutError(f"Invalid privacy masks: {exc}") from exc
    width, height = value["canvasWidth"], value["canvasHeight"]
    if canvas is not None and (width, height) != canvas:
        raise LayoutError("Privacy mask canvas differs from canonical output")
    _unique(value["regions"], "maskId")
    for region in value["regions"]:
        if not (
            0 <= region["startFrame"] < region["endFrameExclusive"] <= total_frames
            and region["x"] + region["width"] <= width
            and region["y"] + region["height"] <= height
        ):
            raise LayoutError("Privacy mask lies outside the program or canvas")


def validate_layout_content(snapshot, output):
    """Validate staged placements before any activation journal can be written."""
    try:
        validate_document(
            snapshot["layout"], "avo.cmap.schema.json#/$defs/placedLayout"
        )
    except ContractError as exc:
        raise LayoutError(f"Invalid placed layout: {exc}") from exc
    snapshot = {**snapshot, "importOutput": output}
    layout = snapshot["layout"]
    fps, duration = _clock(snapshot)
    if "privacyMasks" in layout:
        validate_privacy_masks(
            layout["privacyMasks"],
            duration * fps,
            canvas=(output["width"], output["height"]),
        )
    sources = _unique(snapshot["sources"], "sourceId")
    tracks = _unique(layout["tracks"], "trackId")
    _unique(layout["placements"], "placementId")
    _unique(layout["gaps"], "gapId")
    orders = [(track["kind"], track["order"]) for track in tracks.values()]
    if len(set(orders)) != len(orders):
        raise LayoutError("Placed track order must be unique within its kind")
    for item in layout["placements"]:
        _placement(item, sources, tracks, duration, fps)
        validate_picture_operations(
            item,
            (seconds(item["end"]) - seconds(item["start"])) * fps,
            canvas=(output["width"], output["height"]),
        )
    _track_intervals(layout, tracks, duration)


def active_placements(snapshot, *, placement_id=None, track_id=None):
    tracks = {item["trackId"]: item for item in snapshot["layout"]["tracks"]}
    for item in snapshot["layout"]["placements"]:
        track = tracks[item["trackId"]]
        selected = (placement_id is None or item["placementId"] == placement_id) and (
            track_id is None or item["trackId"] == track_id
        )
        enabled = all(
            (
                item["enabled"],
                track["enabled"],
                item["mediaKind"] != "audio" or not item.get("muted", False),
                item["mediaKind"] != "audio" or not track["muted"],
            )
        )
        if selected and enabled:
            yield item
