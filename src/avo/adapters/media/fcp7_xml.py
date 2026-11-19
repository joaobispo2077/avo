"""Bounded, local-only reader for Final Cut Pro 7 xmeml interchange."""

import os
import re
from collections import Counter
from fractions import Fraction
from math import isfinite, log10
from pathlib import Path, PurePosixPath, PureWindowsPath
from urllib.parse import unquote, urlsplit
from xml.etree.ElementTree import Element, SubElement, TreeBuilder, tostring
from xml.parsers import expat

MAX_BYTES = 16 * 1024 * 1024
MAX_DEPTH = 64
MAX_ELEMENTS = 250_000
MAX_OCCURRENCES = 10_000
XINCLUDE_URI = "http://www.w3.org/2001/XInclude"
KNOWN_ELEMENTS = frozenset(
    [
        "xmeml",
        "project",
        "children",
        "sequence",
        "name",
        "duration",
        "rate",
        "timebase",
        "ntsc",
        "timecode",
        "frame",
        "string",
        "displayformat",
        "media",
        "video",
        "audio",
        "track",
        "enabled",
        "locked",
        "clipitem",
        "file",
        "pathurl",
        "start",
        "end",
        "in",
        "out",
        "sourcetrack",
        "mediatype",
        "trackindex",
        "outputchannelindex",
        "format",
        "samplecharacteristics",
        "width",
        "height",
        "pixelaspectratio",
        "marker",
        "comment",
    ]
)


class Fcp7Error(ValueError):
    """An interchange document cannot be inspected on its declared local scope."""


def _deny_external(*args):
    raise Fcp7Error("External XML resources and entities are disabled")


def _doctype(name, system, public, internal):
    if (name, system, public, internal) != ("xmeml", None, None, 0):
        raise Fcp7Error("Only the fixed xmeml DOCTYPE is supported")


def _declaration(version, encoding, _standalone):
    if version != "1.0" or (encoding and encoding.casefold() != "utf-8"):
        raise Fcp7Error("Interchange XML must use XML 1.0 and UTF-8")


def _namespace(prefix, uri):
    if uri == XINCLUDE_URI:
        raise Fcp7Error("XInclude resources are disabled")


class _BoundedTree:
    def __init__(self):
        self.builder = TreeBuilder()
        self.depth = self.elements = self.occurrences = 0

    def start(self, name, attributes):
        self.depth += 1
        self.elements += 1
        self.occurrences += name in {"clipitem", "generatoritem"}
        if (
            self.depth > MAX_DEPTH
            or self.elements > MAX_ELEMENTS
            or self.occurrences > MAX_OCCURRENCES
        ):
            raise Fcp7Error(
                "Interchange XML exceeds the nesting, element or occurrence budget"
            )
        self.builder.start(name, attributes)

    def end(self, name):
        self.builder.end(name)
        self.depth -= 1


def _tree(payload):
    if not isinstance(payload, bytes) or not 0 < len(payload) <= MAX_BYTES:
        raise Fcp7Error("Interchange XML exceeds the byte budget or is empty")
    tree = _BoundedTree()
    parser = expat.ParserCreate(namespace_separator=" ")
    handlers = {
        "StartElementHandler": tree.start,
        "EndElementHandler": tree.end,
        "CharacterDataHandler": tree.builder.data,
        "XmlDeclHandler": _declaration,
        "StartDoctypeDeclHandler": _doctype,
        "StartNamespaceDeclHandler": _namespace,
        "EntityDeclHandler": _deny_external,
        "ExternalEntityRefHandler": _deny_external,
        "ProcessingInstructionHandler": _deny_external,
    }
    for attribute, handler in handlers.items():
        setattr(parser, attribute, handler)
    parser.SetParamEntityParsing(expat.XML_PARAM_ENTITY_PARSING_NEVER)
    try:
        parser.Parse(payload.decode("utf-8-sig"), True)
        return tree.builder.close()
    except (UnicodeError, expat.ExpatError) as error:
        raise Fcp7Error(
            "Interchange XML is malformed or uses unsupported encoding"
        ) from error


def _clean_absolute(value):
    if value.replace("\\", "/").startswith("//") or any(
        ord(character) < 32 for character in value
    ):
        raise Fcp7Error("Interchange paths must name local volumes")
    path = Path(value)
    if not path.is_absolute() or ".." in path.parts:
        raise Fcp7Error("Interchange paths must be absolute local paths")
    return path


def _decoded_local_path(value):
    if any(ord(character) < 32 for character in value) or re.search(
        r"%(?![a-fA-F0-9]{2})", value
    ):
        raise Fcp7Error("Interchange media URLs must use valid local URI escaping")
    try:
        parsed = urlsplit(value)
        if (
            parsed.scheme != "file"
            or parsed.netloc.casefold() not in {"", "localhost"}
            or parsed.query
            or parsed.fragment
        ):
            raise Fcp7Error("Interchange media URLs must name local files")
        return unquote(parsed.path, encoding="utf-8", errors="strict")
    except (UnicodeError, ValueError) as error:
        raise Fcp7Error("Interchange media URLs must name local files") from error


def _local_url(value):
    path = _decoded_local_path(value)
    drive_path = path[1:] if re.match(r"^/[a-zA-Z]:/", path) else path
    if (
        re.match(r"^/(?!/)", path) is None
        or ".." in PurePosixPath(path).parts
        or any(ord(character) < 32 for character in path)
    ):
        raise Fcp7Error("Interchange media URLs must name absolute local paths")
    if "\\" in path or any(
        ":" in part for part in PureWindowsPath(drive_path).parts[1:]
    ):
        raise Fcp7Error("Interchange media URL contains an unsupported local path")
    return drive_path if os.name == "nt" else path


def _media_path(value, roots, relink):
    original = _local_url(value)
    selected = _clean_absolute(os.fspath(relink.get(value, original)))
    allowed = [
        resolved
        for declared, resolved in roots
        if selected.is_relative_to(declared) and selected != declared
    ]
    if not allowed:
        raise Fcp7Error("Interchange source is outside the selected local roots")
    resolved = selected.resolve()
    if not any(resolved.is_relative_to(root) and resolved != root for root in allowed):
        raise Fcp7Error("Interchange relink escapes the selected local roots")
    return resolved


def _text(element, path, default=None):
    value = element.findtext(path)
    return value.strip() if value is not None else default


def _integer(element, path, *, default=None, minimum=0, maximum=1_000_000_000):
    value = _text(element, path)
    if value is None and default is not None:
        return default
    if value is None or not re.fullmatch(r"-?[0-9]{1,10}", value):
        raise Fcp7Error(f"Expected integer frames in {path}")
    number = int(value)
    if not minimum <= number <= maximum:
        raise Fcp7Error(f"Frame value is outside the supported range in {path}")
    return number


def _boolean(element, path, default):
    value = _text(element, path)
    if value is None:
        return default
    if value.casefold() not in {"true", "false"}:
        raise Fcp7Error(f"Expected TRUE or FALSE in {path}")
    return value.casefold() == "true"


def _rate(element, fallback=None):
    rate = element.find("rate")
    if rate is None and fallback is not None:
        return fallback
    if rate is None:
        raise Fcp7Error("Interchange sequence is missing an explicit frame rate")
    base = _integer(rate, "timebase", minimum=1, maximum=240)
    return (
        Fraction(base * 1000, 1001) if _boolean(rate, "ntsc", False) else Fraction(base)
    )


def _unique_sequence(root, selected):
    if root.tag != "xmeml" or root.get("version") not in {"4", "5"}:
        raise Fcp7Error("Interchange requires xmeml version 4 or 5")
    sequences = root.findall("sequence") + root.findall("./project/children/sequence")
    matches = (
        sequences
        if selected is None
        else [row for row in sequences if row.get("id") == selected]
    )
    if len(matches) != 1:
        raise Fcp7Error("Select one exact interchange sequence")
    return matches[0]


def _file_definitions(root):
    sources = {}
    for node in root.iter("file"):
        url = _text(node, "pathurl")
        if url is None:
            continue
        _local_url(url)
        identity = node.get("id")
        if not identity:
            raise Fcp7Error("Interchange local file definitions need stable IDs")
        previous = sources.setdefault(identity, node)
        if previous is not node and _text(previous, "pathurl") != url:
            raise Fcp7Error("Interchange file ID has conflicting local paths")
    return sources


def _file_fact(node, rate, roots, relink):
    url = _text(node, "pathurl")
    return {
        "locator": _media_path(url, roots, relink),
        "originalUrl": url,
        "rate": _rate(node, rate),
        "originFrame": _integer(
            node, "timecode/frame", default=0, minimum=-1_000_000_000
        ),
        "duration": _integer(node, "duration", default=0),
    }


def _markers(element):
    return [
        {
            "name": _text(marker, "name", ""),
            "comment": _text(marker, "comment", ""),
            "in": _integer(marker, "in"),
            "out": _integer(marker, "out", default=-1, minimum=-1),
        }
        for marker in element.findall("marker")
    ]


def _unknown(element):
    return dict(
        sorted(
            Counter(
                row.tag for row in element.iter() if row.tag not in KNOWN_ELEMENTS
            ).items()
        )
    )


def _clip_frames(element):
    frame = {
        key: _integer(element, key, minimum=-1 if key in {"start", "end"} else 0)
        for key in ("start", "end", "in", "out")
    }
    if frame["out"] <= frame["in"] or (
        min(frame["start"], frame["end"]) >= 0 and frame["end"] <= frame["start"]
    ):
        raise Fcp7Error("Interchange occurrence has an empty or reversed range")
    return frame


def _covers_source_range(filter_node, frames):
    start = _text(filter_node, "start", "-1")
    end = _text(filter_node, "end", "-1")
    if (start, end) == ("-1", "-1"):
        return True
    try:
        return 0 <= int(start) <= frames["in"] and frames["out"] <= int(end)
    except ValueError:
        return False


def _full_clip_audio_levels(element, frames):
    filters = [
        item
        for item in element.findall("filter")
        if _text(item, "effect/effectid", "").casefold()
        in {"audiolevels", "audio levels"}
    ]
    if len(filters) != 1:
        return None
    (item,) = filters
    if _text(item, "enabled", "TRUE").casefold() != "true":
        return None
    if not _covers_source_range(item, frames):
        return None
    return item.find("effect")


def _linear_level(effect):
    params = [
        row
        for row in effect.findall("parameter")
        if _text(row, "parameterid", "").casefold() == "level"
    ]
    if len(params) != 1:
        return None
    values = params[0].findall("value")
    if len(values) != 1 or len(values[0]):
        return None
    try:
        level = float(values[0].text or "")
    except ValueError:
        return None
    if level <= 0 or not isfinite(level):
        return None
    return level


def _observed_audio_gain(element, frames):
    effect = _full_clip_audio_levels(element, frames)
    if effect is None or effect.find(".//keyframe") is not None:
        return {}
    level = _linear_level(effect)
    return {"gainDb": 20 * log10(level)} if level is not None else {}


def _clip(element, rate, sources, kind):
    file = element.find("file")
    identity = file.get("id") if file is not None else None
    source = sources.get(identity)
    frame = _clip_frames(element)
    return {
        **frame,
        "id": element.get("id"),
        "name": _text(element, "name"),
        "fileId": identity,
        "rate": _rate(element, source["rate"] if source else rate),
        "sourceTrack": _integer(element, "sourcetrack/trackindex", default=0, minimum=1)
        or None,
        "enabled": _boolean(element, "enabled", True),
        "markers": _markers(element),
        "unknown": _unknown(element),
        **(_observed_audio_gain(element, frame) if kind == "audio" else {}),
        "rangeStatus": "external"
        if source is None or min(frame["start"], frame["end"]) < 0
        else "observed",
    }


def _tracks(sequence, rate, sources):
    return [
        {
            "kind": kind,
            "index": index,
            "enabled": _boolean(track, "enabled", True),
            "locked": _boolean(track, "locked", False),
            "outputChannel": _integer(track, "outputchannelindex", default=0, minimum=1)
            or None,
            "clips": [
                _clip(row, rate, sources, kind) for row in track.findall("clipitem")
            ],
        }
        for kind in ("video", "audio")
        for index, track in enumerate(sequence.findall(f"./media/{kind}/track"), 1)
    ]


def _picture_format(sequence):
    description = sequence.find("./media/video/format/samplecharacteristics")
    if description is None:
        return None
    width = _integer(description, "width", default=0, minimum=1)
    height = _integer(description, "height", default=0, minimum=1)
    if not width or not height:
        return None
    return {
        "width": width,
        "height": height,
        "pixelAspectRatio": _text(description, "pixelaspectratio"),
    }


def parse_fcp7_xml(payload, *, roots, relink=None, sequence_id=None):
    """Inspect exact frame declarations and retain unsupported-element counts."""
    root = _tree(payload)
    sequence = _unique_sequence(root, sequence_id)
    rate = _rate(sequence)
    known = _file_definitions(root)
    referenced = {
        row.get("id") for row in sequence.findall("./media/*/track/clipitem/file")
    }
    declared = [_clean_absolute(os.fspath(path)) for path in roots]
    local_roots = tuple((path, path.resolve()) for path in declared)
    sources = {
        key: _file_fact(known[key], rate, local_roots, relink or {})
        for key in sorted(referenced & known.keys())
    }
    return {
        "version": int(root.get("version")),
        "id": sequence.get("id"),
        "name": _text(sequence, "name"),
        "rate": rate,
        "originFrame": _integer(
            sequence, "timecode/frame", default=0, minimum=-1_000_000_000
        ),
        "duration": _integer(sequence, "duration"),
        "pictureFormat": _picture_format(sequence),
        "sources": sources,
        "tracks": _tracks(sequence, rate, sources),
        "markers": _markers(sequence),
        "unknown": _unknown(sequence),
    }


def _scalar(element, key, value):
    if value is not None:
        SubElement(element, key).text = str(value)


def _frame_text(element, key, value):
    if type(value) is not int:
        raise Fcp7Error(f"Exact integer frames are required for {key}")
    _scalar(element, key, value)


def _write_rate(element, rate):
    rate = Fraction(rate)
    nominal = rate * Fraction(1001, 1000) if rate.denominator != 1 else rate
    if nominal.denominator != 1 or not 1 <= nominal <= 240:
        raise Fcp7Error("Interchange frame rate cannot be represented exactly")
    settings = SubElement(element, "rate")
    _frame_text(settings, "timebase", int(nominal))
    _scalar(settings, "ntsc", "TRUE" if nominal != rate else "FALSE")


def _write_markers(element, markers):
    for item in markers:
        marker = SubElement(element, "marker")
        for field in ("name", "comment"):
            _scalar(marker, field, item.get(field))
        _frame_text(marker, "in", item["in"])
        _frame_text(marker, "out", item.get("out", -1))


def _write_file(node, identity, sources, emitted):
    resource = SubElement(node, "file", {"id": identity})
    if identity in emitted:
        return
    source = sources[identity]
    locator = _clean_absolute(os.fspath(source["locator"]))
    _scalar(resource, "name", locator.name)
    _scalar(resource, "pathurl", locator.as_uri())
    _write_rate(resource, source["rate"])
    _frame_text(resource, "duration", source["duration"])
    _frame_text(SubElement(resource, "timecode"), "frame", source["originFrame"])
    emitted.add(identity)


def _write_clip(parent, lane, clip, sources, emitted):
    if (
        clip.get("rangeStatus", "observed") != "observed"
        or clip["fileId"] not in sources
    ):
        raise Fcp7Error(
            "Interchange export requires measured ranges and original file identities"
        )
    if not clip.get("id"):
        raise Fcp7Error("Interchange export needs a stable occurrence identity")
    node = SubElement(parent, "clipitem", {"id": clip["id"]})
    _scalar(node, "name", clip.get("name"))
    _write_rate(node, clip["rate"])
    _scalar(node, "enabled", "TRUE" if clip.get("enabled", True) else "FALSE")
    for name in ("start", "end", "in", "out"):
        _frame_text(node, name, clip[name])
    _write_file(node, clip["fileId"], sources, emitted)
    if clip.get("sourceTrack") is not None:
        port = SubElement(node, "sourcetrack")
        _scalar(port, "mediatype", lane["kind"])
        _frame_text(port, "trackindex", clip["sourceTrack"])
    _write_markers(node, clip.get("markers", []))


def _write_picture_format(video, description, rate):
    if description is None:
        return
    picture = SubElement(SubElement(video, "format"), "samplecharacteristics")
    for key in ("width", "height"):
        _frame_text(picture, key, description[key])
    _scalar(picture, "pixelaspectratio", description.get("pixelAspectRatio"))
    _write_rate(picture, rate)


def _write_tracks(sequence, data):
    media = SubElement(sequence, "media")
    emitted = set()
    for kind in ("video", "audio"):
        node = SubElement(media, kind)
        for lane in (row for row in data["tracks"] if row["kind"] == kind):
            track = SubElement(node, "track")
            for clip in lane["clips"]:
                _write_clip(track, lane, clip, data["sources"], emitted)
            _scalar(track, "enabled", "TRUE" if lane.get("enabled", True) else "FALSE")
            _scalar(track, "locked", "TRUE" if lane.get("locked", False) else "FALSE")
            if lane.get("outputChannel") is not None:
                _frame_text(track, "outputchannelindex", lane["outputChannel"])
        if kind == "video":
            _write_picture_format(node, data.get("pictureFormat"), data["rate"])


def write_fcp7_xml(data):
    """Emit the measured xmeml subset with exact original-time frame declarations."""
    if data.get("unknown"):
        raise Fcp7Error(
            "External finishing must remain with the original interchange bytes"
        )
    identities = [clip.get("id") for lane in data["tracks"] for clip in lane["clips"]]
    if len(set(identities)) != len(identities):
        raise Fcp7Error("Interchange export requires unique occurrence identities")
    root = Element("xmeml", {"version": str(data.get("version", 5))})
    sequence = SubElement(root, "sequence", {"id": data["id"]})
    _scalar(sequence, "name", data.get("name"))
    _frame_text(sequence, "duration", data["duration"])
    _write_rate(sequence, data["rate"])
    _frame_text(SubElement(sequence, "timecode"), "frame", data["originFrame"])
    _write_tracks(sequence, data)
    _write_markers(sequence, data.get("markers", []))
    return b'<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE xmeml>\n' + tostring(
        root, encoding="utf-8"
    )
