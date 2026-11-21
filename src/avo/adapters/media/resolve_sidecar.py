"""Read bounded DRT metadata and inert static Text+ data without Resolve."""

import io
import json
import math
import os
import re
import struct
import xml.etree.ElementTree as ET
import zipfile
import zlib
from functools import lru_cache
from pathlib import Path

from avo.timeline.contracts import file_fingerprint, fingerprint_stage

MAX_XML = 8 * 1024 * 1024
MAX_FUSION = 256 * 1024


def _xml(data):
    if len(data) > MAX_XML or re.search(rb"<!\s*(DOCTYPE|ENTITY)", data, re.IGNORECASE):
        raise ValueError("Unsafe or oversized Resolve XML")
    text = data.decode("utf-8-sig")
    # Resolve serializes C++ type names as XML tags, e.g. ListMgt::Table.
    text = re.sub(
        r"<(/?)([A-Za-z_][\w:.-]*)",
        lambda m: "<" + m[1] + m[2].replace("::", "__"),
        text,
    )
    depth = count = 0
    parser = ET.iterparse(io.BytesIO(text.encode()), events=("start", "end"))
    try:
        for event, _ in parser:
            depth += 1 if event == "start" else -1
            count += event == "start"
            if depth > 128 or count > 100_000:
                raise ValueError("Resolve XML exceeds structural limits")
    except ET.ParseError as exc:
        raise ValueError("Malformed Resolve metadata XML") from exc
    return parser.root


def _entry(archive, info):
    if info.file_size > MAX_XML or info.file_size > max(1, info.compress_size) * 1024:
        raise ValueError("Resolve metadata entry exceeds its byte/ratio limit")
    return _xml(archive.read(info))


def _program(root):
    sequences = root.findall(".//Sm2Sequence")
    if len(sequences) != 1:
        raise ValueError("DRT must identify exactly one sequence")
    sequence = sequences[0]
    width, height = struct.unpack(
        ">qq", bytes.fromhex(sequence.findtext("Resolution", ""))
    )
    rate = struct.unpack("<d", bytes.fromhex(sequence.findtext("FrameRate", ""))[:8])[0]
    start, end = struct.unpack(
        "<dd", bytes.fromhex(sequence.findtext("MediaExtents", ""))
    )
    channels = int(sequence.findtext("NumOutputAudioChannels", "2"))
    if not (
        1 <= width <= 8192
        and 1 <= height <= 8192
        and math.isfinite(rate)
        and 0 < rate <= 240
    ):
        raise ValueError("Unsupported Resolve output geometry or rate")
    if not (math.isfinite(start) and math.isfinite(end) and 0 <= start < end):
        raise ValueError("Invalid Resolve program extent")
    if channels != 2:
        raise ValueError("Resolve output requires an explicit supported channel layout")
    from fractions import Fraction

    fps = Fraction(str(rate)).limit_denominator(1001)
    return {
        "output": {
            "width": width,
            "height": height,
            "frameRate": {"num": fps.numerator, "den": fps.denominator},
            "audioSampleRate": 48000,
            "channelLayout": "stereo",
        },
        "durationSeconds": end - start,
    }


def _inflate(data, expected=None):
    decoder = zlib.decompressobj()
    result = decoder.decompress(data, MAX_FUSION + 1)
    if len(result) > MAX_FUSION or not decoder.eof or decoder.unconsumed_tail:
        raise ValueError("Fusion reference exceeds decompression limits")
    if expected is not None and len(result) != expected:
        raise ValueError("Fusion reference length differs from its header")
    return result


def _fusion_texts(value):
    if len(value) > MAX_FUSION * 2 + 8:
        raise ValueError("Fusion reference is oversized")
    blob = bytes.fromhex(value)
    if len(blob) < 6:
        raise ValueError("Incomplete Fusion reference")
    outer = _inflate(blob[4:], struct.unpack(">I", blob[:4])[0])
    candidates = [outer]
    offsets = [m.start() for m in re.finditer(b"\x78[\x01\x9c\xda]", outer)]
    if len(offsets) > 32:
        raise ValueError("Too many nested Fusion compression blocks")
    for offset in offsets:
        try:
            candidates.append(_inflate(outer[offset:]))
        except (ValueError, zlib.error):
            continue
    for candidate in candidates:
        try:
            text = candidate.decode("utf-8").rstrip("\x00")
        except UnicodeError:
            continue
        if "TextPlus" in text:
            yield text


def _input(text, name):
    token = r'("(?:[^"\\]|\\.)*"|[+-]?[0-9]+(?:\.[0-9]+)?)'
    matches = re.findall(
        r"\b"
        + re.escape(name)
        + r"\s*=\s*Input\s*\{\s*Value\s*=\s*"
        + token
        + r"\s*[,}]",
        text,
    )
    if len(matches) != 1:
        raise ValueError("Fusion input is absent or ambiguous: " + name)
    return json.loads(matches[0])


def _literal_inputs(text):
    unquoted = re.sub(r'"(?:[^"\\]|\\.)*"', '""', text)
    if re.search(r"[():;]|--|\b(function|require|dofile)\b", unquoted):
        raise ValueError("Fusion title contains executable or unsupported syntax")
    literal = r'Value\s*=\s*(?:"(?:[^"\\]|\\.)*"|[+-]?[0-9]+(?:\.[0-9]+)?)\s*,?'
    connection = r'SourceOp\s*=\s*"Template"\s*,\s*Source\s*=\s*"Output"\s*,?'
    bodies = re.findall(r"\bInput\s*\{([^{}]*)\}", text)
    if len(bodies) != len(re.findall(r"\bInput\s*\{", text)):
        raise ValueError("Fusion title contains nested inputs")
    if any(
        not re.fullmatch(r"\s*(?:" + literal + "|" + connection + r")\s*", body)
        for body in bodies
    ):
        raise ValueError("Fusion title input is not a supported literal")


def _plain_title_inputs(text):
    _literal_inputs(text)
    allowed = {
        "GlobalOut",
        "Width",
        "Height",
        "UseFrameFormatSettings",
        "StyledText",
        "Font",
        "Style",
        "Size",
        "VerticalJustificationNew",
        "HorizontalJustificationNew",
        "Index",
        "Input",
    }
    inputs = re.findall(r"\b([A-Za-z_][A-Za-z_0-9]*)\s*=\s*Input\s*\{", text)
    constructors = re.findall(r"\b([A-Za-z_][A-Za-z_0-9]*)\s*\{", text)
    if set(inputs) - allowed or set(constructors) - {
        "TextPlus",
        "Input",
        "OperatorInfo",
        "MediaOut",
    }:
        raise ValueError(
            "Fusion appearance or animation is outside the static title subset"
        )
    if re.search(
        r"\b(Expression|SourceOp|Source)\s*=",
        text.replace('SourceOp = "Template"', "").replace('Source = "Output"', ""),
    ):
        raise ValueError(
            "Fusion title contains an unsupported connection or expression"
        )
    for name in ("VerticalJustificationNew", "HorizontalJustificationNew"):
        if name in inputs and _input(text, name) != 3:
            raise ValueError("Fusion title is not centered")


def _static_title(text):
    _plain_title_inputs(text)
    if len(re.findall(r"\bTextPlus\s*\{", text)) != 1:
        raise ValueError("Fusion composition is not a single static Text+ template")
    title = {
        "text": _input(text, "StyledText"),
        "fontFamily": _input(text, "Font"),
        "fontStyle": _input(text, "Style"),
        "normalizedSize": _input(text, "Size"),
        "canvasWidth": _input(text, "Width"),
        "canvasHeight": _input(text, "Height"),
        "lastFrame": _input(text, "GlobalOut"),
    }
    _validate_title_values(title)
    title["fontPath"] = _font_file(title["fontFamily"], title["fontStyle"])
    return title


def _validate_title_frame(title):
    if not all(isinstance(title[k], str) for k in ("fontFamily", "fontStyle")):
        raise ValueError("Invalid title font metadata")
    if not all(
        type(title[k]) is int and 0 < title[k] <= 8192
        for k in ("canvasWidth", "canvasHeight")
    ):
        raise ValueError("Invalid title canvas")
    if type(title["lastFrame"]) is not int or not 0 <= title["lastFrame"] <= 1_000_000:
        raise ValueError("Invalid title extent")


def _validate_title_values(title):
    _validate_title_frame(title)
    if not isinstance(title["text"], str) or not 0 < len(title["text"]) <= 256:
        raise ValueError("Unsupported static title text")
    if any(ord(c) < 32 or ord(c) == 127 for c in title["text"]):
        raise ValueError("Static title requires a single supported text line")
    if (
        not isinstance(title["normalizedSize"], (int, float))
        or not 0 < title["normalizedSize"] <= 1
    ):
        raise ValueError("Invalid static title size")


def _font_paths():
    roots = [
        Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts",
        Path("/usr/share/fonts"),
        Path.home() / ".local/share/fonts",
    ]
    return (
        p
        for root in roots
        if root.is_dir()
        for p in root.rglob("*")
        if p.suffix.lower() in {".ttf", ".otf"}
    )


@lru_cache(maxsize=128)
def _font_file(family, style):
    from PIL import ImageFont

    if not isinstance(family, str) or not isinstance(style, str):
        raise ValueError("Invalid title font metadata")
    paths = _font_paths()
    matches = []
    for count, path in enumerate(paths):
        if count >= 4096:
            raise ValueError("Installed font inventory exceeds its limit")
        try:
            name = ImageFont.truetype(str(path), size=16).getname()
        except (OSError, ValueError):
            continue
        if tuple(s.casefold() for s in name) == (family.casefold(), style.casefold()):
            matches.append(str(path.resolve()))
    return matches[0] if len(matches) == 1 else None


def _titles(archive, entries):
    titles, warnings = [], []
    for info in entries:
        if not (
            info.filename.startswith("SeqContainer/") and info.filename.endswith(".xml")
        ):
            continue
        root = _entry(archive, info)
        for value in root.iter("CompositionBA"):
            try:
                for text in _fusion_texts(value.text or ""):
                    titles.append(_static_title(text))
            except (ValueError, zlib.error, UnicodeError) as exc:
                warnings.append(str(exc))
            if len(titles) > 128:
                raise ValueError("Too many generated title references")
    return titles, warnings


def _read_sidecar(path):
    """Return export facts only; never import a project or execute Fusion/Lua."""
    path = Path(path)
    if path.stat().st_size > 64 * 1024 * 1024:
        raise ValueError("DRT exceeds its byte limit")
    with fingerprint_stage(verify_on_exit=True), zipfile.ZipFile(path) as archive:
        fingerprint = file_fingerprint(path)
        entries = archive.infolist()
        if len(entries) > 128 or sum(i.file_size for i in entries) > 32 * 1024 * 1024:
            raise ValueError("DRT exceeds its entry/uncompressed-byte limit")
        root = _entry(archive, archive.getinfo("MediaPool/Master/MpFolder.xml"))
        facts = _program(root)
        facts["titles"], facts["warnings"] = _titles(archive, entries)
    return {**facts, "path": str(path.resolve()), "fingerprint": fingerprint}


def read_resolve_sidecar(path):
    """Convert malformed archives to a bounded metadata warning at the core port."""
    try:
        return _read_sidecar(path)
    except (zipfile.BadZipFile, struct.error, KeyError, UnicodeError) as exc:
        raise ValueError("Malformed Resolve metadata archive") from exc
