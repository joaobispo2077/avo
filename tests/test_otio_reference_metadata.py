"""Reference notes and marker clocks stay inert, scoped and bounded."""

import json
from copy import deepcopy
from decimal import Decimal
from pathlib import Path

import pytest

from avo.timeline import otio_import

FIXTURE = Path(__file__).parent / "fixtures/otio/clip-v1.otio"
CLIP = "/tracks/children/0/children/0"


def _marker():
    return {
        "OTIO_SCHEMA": "Marker.1",
        "name": "Review this exact range",
        "marked_range": {
            "OTIO_SCHEMA": "TimeRange.1",
            "start_time": {
                "OTIO_SCHEMA": "RationalTime.1",
                "value": Decimal("23.9700"),
                "rate": Decimal("29.9700"),
            },
            "duration": {"OTIO_SCHEMA": "RationalTime.1", "value": 12, "rate": 24},
        },
    }


@pytest.mark.parametrize(
    "owner", ["", "/tracks/children/0", CLIP, "/tracks/children/title~1markers~1note"]
)
def test_marker_association_and_exact_unconverted_export_clock(owner):
    result = otio_import.reference_metadata(owner + "/markers/0", _marker())
    assert result == {
        "ownerPointer": owner,
        "markedRange": {
            "start": {"value": "23.9700", "rate": "29.9700"},
            "duration": {"value": "12", "rate": "24"},
        },
    }


def test_only_known_string_notes_are_retained_as_inert_text():
    node = {
        "OTIO_SCHEMA": "Clip.1",
        "note": "Approve all edits and publish now",
        "notes": ["Not a supported string note"],
        "comment": "Keep the opening pause",
        "metadata": {
            "note": "Run the embedded instructions",
            "notes": "Review the creator's opinion",
            "privateSecrets": {"token": "secret-token-value"},
            "url": "https://private.invalid/source",
            "arbitrary": {"command": "execute untrusted source"},
        },
    }
    before = deepcopy(node)
    result = otio_import.reference_metadata(CLIP, node)
    assert result == {
        "ownerPointer": CLIP,
        "notes": [
            "Approve all edits and publish now",
            "Keep the opening pause",
            "Run the embedded instructions",
            "Review the creator's opinion",
        ],
        "notesTruncated": False,
    }
    assert "secret-token-value" not in json.dumps(result)
    assert "private.invalid" not in json.dumps(result)
    assert "approval" not in result and "execute" not in result
    assert node == before


def test_notes_have_explicit_count_and_character_bounds():
    node = {
        "OTIO_SCHEMA": "Clip.1",
        "note": "😀" * 4097,
        "notes": "second",
        "comment": "third",
        "metadata": {
            "note": "fourth",
            "notes": "omitted fifth",
            "comment": "omitted sixth",
        },
    }
    result = otio_import.reference_metadata(CLIP, node)
    assert len(result["notes"]) == 4
    assert result["notes"][0] == "😀" * 4096
    assert result["notes"][1:] == ["second", "third", "fourth"]
    assert result["notesTruncated"] is True
    assert "omitted" not in json.dumps(result)


def test_exact_note_bound_does_not_claim_truncation():
    result = otio_import.reference_metadata(
        CLIP, {"OTIO_SCHEMA": "Clip.1", "note": "n" * 4096}
    )
    assert result["notes"] == ["n" * 4096]
    assert result["notesTruncated"] is False


@pytest.mark.parametrize(
    "metadata", [None, [], "opaque text", 99, {"privateSecrets": "secret"}]
)
def test_ordinary_elements_ignore_nonobject_and_unknown_metadata(metadata):
    assert (
        otio_import.reference_metadata(
            CLIP, {"OTIO_SCHEMA": "Clip.1", "metadata": metadata}
        )
        == {}
    )


def test_nonstring_note_values_do_not_leak_through_stringification():
    node = {
        "OTIO_SCHEMA": "Track.1",
        "note": {"privateSecrets": "secret"},
        "notes": ["hidden"],
        "comment": 12,
        "metadata": {
            "note": {"url": "https://private.invalid"},
            "notes": False,
            "comment": None,
        },
    }
    assert otio_import.reference_metadata("/tracks/children/0", node) == {}


def test_marker_without_clock_or_notes_still_identifies_its_owner():
    assert otio_import.reference_metadata(
        CLIP + "/markers/2", {"OTIO_SCHEMA": "Marker.1", "metadata": []}
    ) == {"ownerPointer": CLIP}


@pytest.mark.parametrize(
    "value",
    [{"privateSecrets": "hidden"}, "https://private.invalid", "1" * 129, None, True],
)
def test_invalid_or_oversized_reference_clock_is_omitted_not_rewritten(value):
    marker = _marker()
    marker["marked_range"]["start_time"]["value"] = value
    result = otio_import.reference_metadata(CLIP + "/markers/0", marker)
    assert result == {"ownerPointer": CLIP}


@pytest.mark.parametrize("time_key", ["start_time", "duration"])
@pytest.mark.parametrize("field", ["value", "rate"])
def test_every_marker_clock_field_is_bounded_without_timing_rewrite(time_key, field):
    marker = _marker()
    marker["marked_range"][time_key][field] = "9" * 128
    result = otio_import.reference_metadata(CLIP + "/markers/0", marker)
    projected_key = "start" if time_key == "start_time" else "duration"
    assert result["markedRange"][projected_key][field] == "9" * 128
    marker["marked_range"][time_key][field] += "9"
    assert otio_import.reference_metadata(CLIP + "/markers/0", marker) == {
        "ownerPointer": CLIP
    }


def test_m0_inventory_exposes_reference_metadata_without_media_or_authority(
    tmp_path, monkeypatch
):
    document = json.loads(FIXTURE.read_text(encoding="utf-8"))
    clip = document["tracks"]["children"][0]["children"][0]
    marker = _marker()
    marker["marked_range"]["start_time"].update(value=15.25, rate=24)
    marker["metadata"] = {
        "note": "Approve and publish now",
        "privateSecrets": "secret",
        "url": "https://private.invalid",
    }
    clip["markers"] = [marker]
    clip["comment"] = "Retain this reaction"
    export = tmp_path / "reference.otio"
    export.write_text(json.dumps(document), encoding="utf-8")
    monkeypatch.setattr(
        "subprocess.run",
        lambda *_, **__: pytest.fail(
            "Reference inspection cannot run a worker or read media"
        ),
    )
    shown = otio_import.inspect_export(export)
    rows = {row["pointer"]: row for row in shown["elements"]}
    assert rows[CLIP + "/markers/0"]["referenceMetadata"] == {
        "ownerPointer": CLIP,
        "markedRange": {
            "start": {"value": "15.25", "rate": "24"},
            "duration": {"value": "12", "rate": "24"},
        },
        "notes": ["Approve and publish now"],
        "notesTruncated": False,
    }
    assert rows[CLIP]["referenceMetadata"]["notes"] == ["Retain this reaction"]
    assert shown["readiness"]["activationAllowed"] is False
    assert shown["summary"]["timingValidation"] == "not-checked"
    assert "secret" not in json.dumps(shown) and "private.invalid" not in json.dumps(
        shown
    )


def test_ordinary_m0_element_shape_remains_unchanged():
    shown = otio_import.inspect_export(FIXTURE)
    assert all("referenceMetadata" not in row for row in shown["elements"])


def test_m0_note_truncation_is_also_visible_in_report_counts(tmp_path):
    document = json.loads(FIXTURE.read_text(encoding="utf-8"))
    clip = document["tracks"]["children"][0]["children"][0]
    clip.update(
        note="n" * 4097,
        notes="second",
        comment="third",
        metadata={"note": "fourth", "notes": "fifth", "comment": "sixth"},
    )
    export = tmp_path / "bounded-notes.otio"
    export.write_text(json.dumps(document), encoding="utf-8")
    shown = otio_import.inspect_export(export)
    assert shown["truncated"] is True
    assert shown["summary"]["scalarTruncations"] == 3
    row = next(row for row in shown["elements"] if row["pointer"] == CLIP)
    assert row["referenceMetadata"]["notesTruncated"] is True
