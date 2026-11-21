"""Translate exact selected editor edges to ordinary original-source removals."""

from fractions import Fraction

from .cutting_service import segment_range

EDGES = (("start", "in"), ("end", "out"))


class ManualEditorFeedback(ValueError):
    """The selected changes need review outside the supported native trim subset."""


def _clips(model):
    return {clip["id"]: clip for lane in model["tracks"] for clip in lane["clips"]}


def _edge_delta(clip, selected, fields, program_rate):
    program, source = fields
    if not all(field in selected for field in fields):
        raise ManualEditorFeedback(
            "Select both the program edge and its original source edge on each linked clip"
        )
    new_program, new_source = (selected[field] for field in fields)
    program_delta = Fraction(new_program - clip[program], program_rate)
    source_delta = Fraction(new_source - clip[source], clip["rate"])
    if program_delta != source_delta or source_delta == 0:
        raise ManualEditorFeedback(
            "The selected editor edge retimes or slips the source"
        )
    return source_delta


def _clock_ticks(frame, rate, clock):
    ticks = Fraction(frame, rate) / Fraction(clock["num"], clock["den"])
    if ticks.denominator != 1:
        raise ManualEditorFeedback(
            "The returned edge falls between canonical source ticks"
        )
    return ticks.numerator


def _source_removal(segment, picture, selected, fields):
    source_field = fields[1]
    interval = segment_range(segment)
    clock = interval["timebase"]
    old = _clock_ticks(picture[source_field], picture["rate"], clock)
    new = _clock_ticks(selected[source_field], picture["rate"], clock)
    start, stop = interval["startTicks"], interval["endTicksExclusive"]
    if source_field == "in" and old == start and start < new < stop:
        return {**interval, "endTicksExclusive": new}
    if source_field == "out" and old == stop and start < new < stop:
        return {**interval, "startTicks": new}
    raise ManualEditorFeedback(
        "Only inward trims of an actual retained source boundary can be routed"
    )


def _audio_ids(segment, source):
    selection = source.get("streamMetadata", {}).get("audioSelection")
    if not selection:
        return []
    count = (
        2 if selection["outputLayout"] == "dual-mono" else len(selection["channels"])
    )
    prefix = f"{segment['segmentId']}-sound-channel-"
    return [prefix + str(index) for index in range(1, count + 1)]


def _selected_linked_clips(segment, source, clips, chosen):
    identifiers = [segment["segmentId"] + "-picture", *_audio_ids(segment, source)]
    if not chosen.keys() & set(identifiers):
        return []
    linked = [clips.get(identity) for identity in identifiers]
    if None in linked:
        raise ManualEditorFeedback(
            "A linked original picture or audio occurrence is unavailable"
        )
    return linked


def _segment_removals(segment, source, clips, chosen, program_rate):
    linked = _selected_linked_clips(segment, source, clips, chosen)
    if not linked:
        return [], set()
    picture = linked[0]
    selection = chosen.get(picture["id"], {})
    removals, consumed = [], set()
    for fields in EDGES:
        if not set(fields).intersection(selection):
            continue
        deltas = {
            _edge_delta(clip, chosen.get(clip["id"], {}), fields, program_rate)
            for clip in linked
        }
        if len(deltas) != 1:
            raise ManualEditorFeedback(
                "The selected picture and audio cuts have different source timing"
            )
        interval = _source_removal(segment, picture, selection, fields)
        removals.append({"segmentId": segment["segmentId"], "removeRange": interval})
        consumed.update((clip["id"], field) for clip in linked for field in fields)
    return removals, consumed


def selected_editor_trims(snapshot, current, chosen):
    """Return only complete linked, inward trims on the contiguous CMap."""
    if "segments" not in snapshot:
        raise ManualEditorFeedback(
            "Placed timeline changes require editor finishing review"
        )
    sources = {source["sourceId"]: source for source in snapshot["sources"]}
    clips = _clips(current)
    removals, consumed = [], set()
    for segment in snapshot["segments"]:
        rows, keys = _segment_removals(
            segment, sources[segment["sourceId"]], clips, chosen, current["rate"]
        )
        removals.extend(rows)
        consumed.update(keys)
    selected = {
        (identity, field) for identity, fields in chosen.items() for field in fields
    }
    if selected != consumed:
        raise ManualEditorFeedback(
            "Selected markers, finishing or unpaired edges require manual review"
        )
    return removals
