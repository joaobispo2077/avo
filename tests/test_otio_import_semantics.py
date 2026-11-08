from __future__ import annotations

import importlib.util
import json
from copy import deepcopy
from fractions import Fraction
from pathlib import Path

import pytest

from avo.adapters.media.otio_reader import read_otio
from avo.timeline.otio_import import ImportError, exact_rate, normalize_contiguous

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("opentimelineio") is None,
    reason="Optional pinned native reader required",
)
FIXTURE = Path(__file__).parent / "fixtures/otio/clip-v1.otio"


@pytest.fixture
def raw():
    return json.loads(FIXTURE.read_text())


def _native(tmp_path, raw):
    path = tmp_path / "edit.otio"
    path.write_text(json.dumps(raw), encoding="utf-8")
    data = path.read_bytes()
    return data, read_otio(data)


def _normalize(tmp_path, raw, *, pointer="", declarations=None):
    data, native = _native(tmp_path, raw)
    return normalize_contiguous(data, native, pointer, declarations or {})


def _track(raw):
    return raw["tracks"]["children"][0]


def _clip(raw):
    return _track(raw)["children"][0]


def _effect():
    return {"OTIO_SCHEMA": "Effect.1", "effect_name": "vendor-color"}


def _retime():
    return {
        "OTIO_SCHEMA": "LinearTimeWarp.1",
        "effect_name": "LinearTimeWarp",
        "time_scalar": 2.0,
    }


def test_native_contiguous_fixture_preserves_exact_file_time_and_global_origin(
    tmp_path, raw
):
    result = _normalize(tmp_path, raw)
    assert result["duration"] == Fraction(2)
    assert result["globalStart"] == {"value": "86400", "rate": "24"}
    assert len(result["clips"]) == 1
    clip = result["clips"][0]
    assert clip["start"] == Fraction(0)
    assert isinstance(clip["start"], Fraction)
    assert clip["duration"] == Fraction(2)
    assert isinstance(clip["duration"], Fraction)
    assert clip["availableDuration"] == Fraction(100)
    assert clip["referencePointer"] == "/tracks/children/0/children/0/media_reference"


def _add_unsupported(raw, case):
    track, clip = _track(raw), _clip(raw)
    if case == "gap":
        track["children"].append(
            {"OTIO_SCHEMA": "Gap.1", "source_range": deepcopy(clip["source_range"])}
        )
    elif case == "effect":
        clip["effects"] = [_effect()]
    elif case == "retime":
        clip["effects"] = [_retime()]
    elif case == "disabled-clip":
        clip["enabled"] = False
    elif case == "disabled-track":
        track["enabled"] = False
    elif case == "parent-trim":
        track["source_range"] = deepcopy(clip["source_range"])
    elif case in {"second-video-layer", "separate-audio"}:
        additional = deepcopy(track)
        additional["kind"] = "Audio" if case == "separate-audio" else "Video"
        raw["tracks"]["children"].append(additional)
    elif case == "nested-stack":
        nested = {"OTIO_SCHEMA": "Stack.1", "children": [deepcopy(track)]}
        track["children"].append(nested)
    elif case == "unknown-content":
        raw["vendorContent"] = {"OTIO_SCHEMA": "VendorOperation.99", "value": 1}
    else:
        raise AssertionError(case)


@pytest.mark.parametrize(
    "case",
    [
        "gap",
        "effect",
        "retime",
        "disabled-clip",
        "disabled-track",
        "parent-trim",
        "second-video-layer",
        "separate-audio",
        "nested-stack",
        "unknown-content",
    ],
)
def test_native_readable_unsupported_edit_blocks_entire_selection(tmp_path, raw, case):
    _add_unsupported(raw, case)
    # Native parsing must succeed here, so this proves the semantic boundary.
    data, native = _native(tmp_path, raw)
    with pytest.raises(ImportError) as error:
        normalize_contiguous(data, native, "", {})
    assert error.value.code in {
        "OTIO_TREATMENT_UNSUPPORTED",
        "OTIO_SCHEMA_UNSUPPORTED",
    }


def test_unknown_schema_as_track_child_is_blocked_by_native_parser(tmp_path, raw):
    _track(raw)["children"].append({"OTIO_SCHEMA": "VendorOperation.99"})
    with pytest.raises(ImportError) as error:
        _native(tmp_path, raw)
    assert error.value.code == "OTIO_INPUT_INVALID"
    assert "Native OTIO interpretation failed" in str(error.value)


def test_missing_inactive_reference_does_not_replace_active_external(tmp_path, raw):
    clip = _clip(raw)
    external = clip.pop("media_reference")
    clip.update(
        OTIO_SCHEMA="Clip.2",
        active_media_reference_key="camera",
        media_references={
            "camera": external,
            "offline": {"OTIO_SCHEMA": "MissingReference.1"},
        },
    )
    result = _normalize(tmp_path, raw)
    selected = result["clips"][0]
    assert selected["targetUrl"] == "file:///originals/take.mov"
    assert selected["referencePointer"].endswith("/media_references/camera")
    assert selected["start"] == Fraction(0)


def test_effect_shaped_metadata_has_no_edit_authority(tmp_path, raw):
    _clip(raw)["metadata"] = {
        "enabled": False,
        "effects": [_retime()],
        "vendor": {"OTIO_SCHEMA": "VendorOperation.99"},
    }
    result = _normalize(tmp_path, raw)
    assert result["duration"] == Fraction(2)
    assert result["clips"][0]["start"] == Fraction(0)


def test_unsupported_sibling_does_not_change_explicit_timeline_selection(tmp_path, raw):
    unsupported = deepcopy(raw)
    _clip(unsupported)["effects"] = [_effect()]
    collection = {
        "OTIO_SCHEMA": "SerializableCollection.1",
        "children": [raw, unsupported],
    }
    data, native = _native(tmp_path, collection)
    assert normalize_contiguous(data, native, "/children/0", {})[
        "duration"
    ] == Fraction(2)
    with pytest.raises(ImportError) as error:
        normalize_contiguous(data, native, "/children/1", {})
    assert error.value.code == "OTIO_TREATMENT_UNSUPPORTED"


def _set_rates(value, rate):
    if isinstance(value, dict):
        if value.get("OTIO_SCHEMA") == "RationalTime.1":
            value["rate"] = rate
        for child in value.values():
            _set_rates(child, rate)
    elif isinstance(value, list):
        for child in value:
            _set_rates(child, rate)


def test_decimal_rate_never_implicitly_becomes_ntsc():
    with pytest.raises(ImportError) as error:
        exact_rate("29.97", {})
    assert error.value.code == "OTIO_RATE_UNVERIFIED"
    assert exact_rate(
        "29.97", {"rateInterpretations": {"29.97": "2997/100"}}
    ) == Fraction(2997, 100)
    assert exact_rate(
        "29.97", {"rateInterpretations": {"29.97": "30000/1001"}}
    ) == Fraction(30000, 1001)


@pytest.mark.parametrize(
    "exported,declared,expected",
    [
        (29.97, "2997/100", Fraction(1600, 999)),
        (29.97002997002997, "30000/1001", Fraction(1001, 625)),
    ],
)
def test_decimal_native_timing_requires_an_explicit_exact_rate(
    tmp_path, raw, exported, declared, expected
):
    _set_rates(raw, exported)
    data, native = _native(tmp_path, raw)
    with pytest.raises(ImportError) as error:
        normalize_contiguous(data, native, "", {})
    assert error.value.code == "OTIO_RATE_UNVERIFIED"
    result = normalize_contiguous(
        data, native, "", {"rateInterpretations": {str(exported): declared}}
    )
    assert result["duration"] == expected
    assert result["clips"][0]["duration"] == expected
    assert result["clips"][0]["start"] == Fraction(0)
