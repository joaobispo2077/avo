"""Exact raw clocks remain authoritative over native floating-point facts."""

import importlib.util
import json
from copy import deepcopy
from fractions import Fraction
from pathlib import Path

import pytest

from avo.adapters.media.otio_reader import read_otio
from avo.timeline import otio_import

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("opentimelineio") is None, reason="Optional native OTIO"
)


def _raw():
    return json.loads(
        (Path(__file__).parent / "fixtures/otio/clip-v1.otio").read_text()
    )


def _normalize(raw, declarations=None):
    data = json.dumps(raw).encode()
    return otio_import.normalize_placed(data, read_otio(data), "", declarations or {})


def test_gaps_layers_repeated_occurrences_and_independent_audio():
    raw = _raw()
    first = raw["tracks"]["children"][0]
    clip = deepcopy(first["children"][0])
    gap = {"OTIO_SCHEMA": "Gap.1", "source_range": deepcopy(clip["source_range"])}
    first["children"] = [gap, clip, deepcopy(clip)]
    upper = deepcopy(first)
    upper["children"] = [deepcopy(clip)]
    audio = deepcopy(upper)
    audio["kind"] = "Audio"
    raw["tracks"]["children"] += [upper, audio]
    result = _normalize(raw)
    assert result["duration"] == 6
    assert [item["kind"] for item in result["tracks"]] == ["video", "video", "audio"]
    assert [clip["programStart"] for clip in result["clips"]] == [2, 4, 0, 0]
    assert [clip["mediaKind"] for clip in result["clips"]] == ["video"] * 3 + ["audio"]
    assert result["gaps"][0]["duration"] == Fraction(2)
    assert result["globalStart"] == {"value": "86400", "rate": "24"}


def test_disabled_content_is_retained():
    raw = _raw()
    raw["tracks"]["children"][0]["enabled"] = False
    raw["tracks"]["children"][0]["children"][0]["enabled"] = False
    result = _normalize(raw)
    assert result["tracks"][0]["enabled"] is False
    assert result["clips"][0]["enabled"] is False


def test_missing_exported_media_origin_requires_scoped_declaration():
    raw = _raw()
    clip = raw["tracks"]["children"][0]["children"][0]
    clip["media_reference"]["available_range"] = None
    with pytest.raises(otio_import.ImportError, match="origin"):
        _normalize(raw)
    pointer = "/tracks/children/0/children/0/media_reference"
    result = _normalize(
        raw, {"mediaOrigins": {pointer: {"value": "240", "rate": "24"}}}
    )
    assert result["clips"][0]["start"] == Fraction(0)
    assert result["clips"][0]["availableDuration"] is None


@pytest.mark.parametrize(
    "case", ["effect", "parent-trim", "nested", "transition", "unknown"]
)
def test_placed_does_not_silently_simplify_unsupported_content(case):
    raw = _raw()
    track = raw["tracks"]["children"][0]
    if case == "effect":
        raw["treatment"] = {"OTIO_SCHEMA": "Effect.1", "effect_name": "color"}
    elif case == "parent-trim":
        track["source_range"] = deepcopy(track["children"][0]["source_range"])
    elif case == "nested":
        track["children"] = [{"OTIO_SCHEMA": "Stack.1", "children": []}]
    elif case == "transition":
        track["children"].append({"OTIO_SCHEMA": "Transition.1"})
    else:
        raw["treatment"] = {"OTIO_SCHEMA": "Mystery.99"}
    with pytest.raises(otio_import.ImportError):
        _normalize(raw)


def test_three_hour_fractional_program_keeps_exact_join_and_display_origin():
    raw = _raw()
    clip = raw["tracks"]["children"][0]["children"][0]
    clip["source_range"]["duration"]["value"] = 162000
    clip["media_reference"]["available_range"]["duration"]["value"] = 324000
    second = deepcopy(clip)
    second["source_range"]["start_time"]["value"] += 162001
    second["source_range"]["duration"]["value"] = 161999
    gap = {"OTIO_SCHEMA": "Gap.1", "source_range": deepcopy(clip["source_range"])}
    gap["source_range"]["duration"]["value"] = 1
    raw["tracks"]["children"][0]["children"] = [clip, gap, second]

    def rate(value):
        if isinstance(value, dict):
            if value.get("OTIO_SCHEMA") == "RationalTime.1":
                value["rate"] = 29.97
            for child in value.values():
                rate(child)
        elif isinstance(value, list):
            for child in value:
                rate(child)

    rate(raw)
    result = _normalize(raw, {"rateInterpretations": {"29.97": "30000/1001"}})
    assert result["duration"] == Fraction(324000 * 1001, 30000)
    assert result["clips"][1]["programStart"] == Fraction(162001 * 1001, 30000)
    assert result["clips"][1]["start"] == Fraction(162001 * 1001, 30000)
    assert result["gaps"][0]["duration"] == Fraction(1001, 30000)
    assert result["globalStart"] == {"value": "86400", "rate": "29.97"}
