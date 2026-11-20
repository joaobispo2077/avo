"""Project declared assembly tracks and their links for the motion review."""

from copy import deepcopy
from fractions import Fraction
from html import escape
from pathlib import PureWindowsPath

from .contracts import content_hash

GROUPS = {"audio": "Production audio", "video": "Picture tracks"}


def _source_label(layer):
    source = layer.get("source") or {}
    locator = source.get("locator")
    if locator and source.get("sha256"):
        return PureWindowsPath(locator).name
    if source.get("generator") or layer.get("generator"):
        return str(source.get("generator") or "Generated contribution")
    return None


def _region(region, cues, linked_items):
    links = region.get("cueIds", [])
    return {
        "regionId": region["regionId"],
        "startTicks": region["startTicks"],
        "endTicks": region["endTicks"],
        "timebase": deepcopy(region.get("timebase", {"num": 1, "den": 1000})),
        "gainDb": region.get("gainDb"),
        "cueIds": sorted(set(links)),
        "itemIds": sorted({linked_items[cue] for cue in links if cue in linked_items}),
        "componentRefs": sorted({cues[cue] for cue in links if cues.get(cue)}),
        "missingCueIds": sorted(set(links) - cues.keys()),
    }


def _state(layer, regions, source):
    status = layer.get("status")
    if status == "disabled":
        return "disabled"
    if layer.get("mute") is True:
        return "muted"
    if (
        status in {"missing", "unavailable", "unresolved", "placeholder"}
        or source is None
        or not regions
        or any(region["missingCueIds"] for region in regions)
    ):
        return "unresolved"
    return "declared"


def _lane(kind, layer, cues, linked_items):
    order = layer["order"]
    region_rows = [
        _region(region, cues, linked_items) for region in layer.get("regions", [])
    ]
    source = _source_label(layer)
    return {
        "laneId": layer["layerId"],
        "role": layer["role"],
        "order": order,
        "pictureOrder": layer.get("zOrder", order) if kind == "video" else None,
        "state": _state(layer, region_rows, source),
        "source": source,
        "gainDb": layer.get("gainDb"),
        "channels": deepcopy(layer.get("channels")),
        "regions": region_rows,
    }


def _video_order(row):
    return row["role"] == "caption", row["pictureOrder"], row["laneId"]


def project_track_review(inspected, bmap, items, *, state):
    cues = {
        cue["cueId"]: cue.get("componentRef")
        or (cue.get("contentRef") or {}).get("componentId")
        for cue in bmap.get("cues", [])
    }
    linked_items = {
        part["cueId"]: item["itemId"]
        for item in items
        for part in item.get("parts", [])
    }
    return {
        "state": state,
        "audio": sorted(
            (
                _lane("audio", row, cues, linked_items)
                for row in inspected["audioLayers"]
            ),
            key=lambda row: (row["order"], row["laneId"]),
        ),
        "video": sorted(
            (
                _lane("video", row, cues, linked_items)
                for row in inspected["videoLayers"]
            ),
            key=_video_order,
        ),
        "findings": {
            "audio": inspected["audioFindings"],
            "video": inspected["visualFindings"],
        },
    }


def _range_text(region):
    clock = region["timebase"]
    scale = Fraction(clock["num"], clock["den"])
    start, end = region["startTicks"], region["endTicks"]
    fields = [
        f"{float(start * scale):.3f}–{float(end * scale):.3f} s (ticks {start}–{end} at {scale} s)"
    ]
    if region["gainDb"] is not None:
        fields.append(f"{region['gainDb']:g} dB region gain")
    for label, key in (
        ("Cues", "cueIds"),
        ("Components", "componentRefs"),
        ("Missing cues", "missingCueIds"),
    ):
        if region[key]:
            fields.append(f"{label} {', '.join(region[key])}")
    return " · ".join(fields)


def _lane_text(row):
    fields = [
        row["state"].capitalize(),
        f"Order {row['order']}",
        row["source"] or "Source unavailable",
    ]
    if row["pictureOrder"] is not None:
        fields.append(f"Picture order {row['pictureOrder']}")
    if row["gainDb"] is not None:
        fields.append(f"{row['gainDb']:g} dB lane gain")
    if row["channels"] is not None:
        fields.append("Channels " + ", ".join(map(str, row["channels"])))
    return " · ".join(fields)


def track_review_text(review):
    lines = []
    for kind, label in GROUPS.items():
        lines.append(label)
        for row in review[kind]:
            lines.append(f"{row['role']} ({row['laneId']}) | {_lane_text(row)}")
            intervals = [_range_text(region) for region in row["regions"]]
            lines.extend(
                f"  {value}" for value in intervals or ["No declared intervals"]
            )
        lines.extend(_group_notes(review, kind))
    return lines


def _group_notes(review, kind):
    if review["state"] == "unavailable":
        return ["Track evidence unavailable"]
    notes = (
        ["Tracks need review against the current edit"]
        if review["state"] == "stale"
        else []
    )
    findings = [
        finding.replace("-", " ").capitalize() for finding in review["findings"][kind]
    ]
    return notes + (findings if review[kind] else ["No declared tracks"])


def _region_html(region):
    links = " ".join(
        f'<a href="#item-{content_hash(item)}">{escape(item)}</a>'
        for item in region["itemIds"]
    )
    return f"<li>{escape(_range_text(region))} {links}</li>"


def _lane_html(row):
    regions = "".join(_region_html(region) for region in row["regions"])
    intervals = f"<ul>{regions}</ul>" if regions else "No declared intervals"
    return (
        f'<tr><th scope="row">{escape(row["role"])}<br>{escape(row["laneId"])}</th>'
        f"<td>{escape(_lane_text(row))}</td><td>{intervals}</td></tr>"
    )


def track_review_html(review):
    if review is None:
        return ""
    sections = []
    for kind, label in GROUPS.items():
        rows = "".join(_lane_html(row) for row in review[kind])
        table = (
            (
                f'<div class="track-table"><table aria-label="{label}">'
                "<thead><tr><th>Lane</th><th>Contribution</th><th>Program intervals</th></tr></thead>"
                f"<tbody>{rows}</tbody></table></div>"
            )
            if rows
            else ""
        )
        notes = "".join(f"<p>{escape(note)}</p>" for note in _group_notes(review, kind))
        sections.append(f"<section><h2>{label}</h2>{table}{notes}</section>")
    return "".join(sections)
