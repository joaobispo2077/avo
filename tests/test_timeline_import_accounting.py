from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from avo.timeline import import_findings
from avo.timeline.contracts import canonical_json_bytes
from avo.timeline.otio_import import ImportError

FIXTURE = Path(__file__).parent / "fixtures/otio/clip-v1.otio"
TRACK = "/tracks/children/0"
CLIP = TRACK + "/children/0"
PASSED = {"semanticValidation": "passed", "mediaReady": "passed"}
FAILED = {"semanticValidation": "failed", "mediaReady": "not-checked"}


def _raw():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _account(raw, *, checks=PASSED, placed=False, pointer=""):
    data = json.dumps(raw, ensure_ascii=False).encode("utf-8")
    return import_findings.account_elements(
        data,
        pointer,
        checks=checks,
        declarations={"layoutMode": "placed"} if placed else {},
    )


def _by_pointer(elements):
    return {item["pointer"]: item for item in elements}


def test_supported_direct_track_and_clip_require_both_checks_and_exclude_scaffolding():
    elements, accounting, findings = _account(_raw())
    assert set(_by_pointer(elements)) == {TRACK, CLIP}
    assert all(item["disposition"] == "reconstructed" for item in elements)
    assert all(item["evidenceOrigin"] == "export" for item in elements)
    assert accounting["total"] == accounting["reported"] == 2
    assert accounting["truncated"] is False
    assert accounting["byDisposition"] == {
        "reconstructed": 2,
        "reference-metadata": 0,
        "unresolved": 0,
        "unsupported": 0,
    }
    assert findings == []


@pytest.mark.parametrize(
    "checks",
    [
        FAILED,
        {"semanticValidation": "passed", "mediaReady": "failed"},
        {"semanticValidation": True, "mediaReady": True},
        {},
    ],
)
def test_failed_or_unverified_whole_selection_never_claims_child_reconstruction(checks):
    elements, accounting, _ = _account(_raw(), checks=checks)
    assert all(item["disposition"] == "unresolved" for item in elements)
    assert accounting["byDisposition"]["unresolved"] == 2


def test_marker_is_reference_metadata_and_raw_metadata_urls_and_giant_times_stay_private():
    raw = _raw()
    clip = raw["tracks"]["children"][0]["children"][0]
    clip["media_reference"]["target_url"] = "file:///private/source-identity-token.mov"
    clip["source_range"]["start_time"]["value"] = 10**1000
    clip["metadata"] = {
        "private": "untrusted-private-token",
        "effects": [{"OTIO_SCHEMA": "UnknownTreatment.99"}],
    }
    clip["markers"] = [
        {
            "OTIO_SCHEMA": "Marker.1",
            "name": "Publish now is only a note",
            "metadata": {"private": "marker-private-token"},
        }
    ]
    elements, accounting, findings = _account(raw)
    marker = _by_pointer(elements)[CLIP + "/markers/0"]
    assert marker["disposition"] == "reference-metadata"
    assert marker["evidenceOrigin"] == "export"
    assert accounting["total"] == 3
    assert findings == []
    text = canonical_json_bytes((elements, accounting, findings)).decode()
    assert "private-token" not in text and "source-identity-token" not in text
    assert "1000000000000000000000000" not in text
    assert "UnknownTreatment" not in text


@pytest.mark.parametrize(
    "schema",
    [
        "Effect.1",
        "TimeEffect.1",
        "LinearTimeWarp.1",
        "FreezeFrame.1",
        "Transition.1",
        "Clip.99",
    ],
)
def test_unknown_and_known_treatments_under_arbitrary_content_keys_are_scoped_unsupported(
    schema,
):
    raw = _raw()
    raw["tracks"]["children"][0]["children"][0]["resolve_treatment"] = {
        "OTIO_SCHEMA": schema,
        "name": "Declared treatment",
        "metadata": {"secret": "private-treatment-token"},
    }
    elements, accounting, findings = _account(raw, checks=FAILED)
    scope = CLIP + "/resolve_treatment"
    row = _by_pointer(elements)[scope]
    assert row["schema"] == schema
    assert row["disposition"] == "unsupported"
    assert accounting["byDisposition"]["unsupported"] == 1
    finding = next(item for item in findings if item["scope"] == scope)
    assert set(finding) == {
        "code",
        "scope",
        "message",
        "blocking",
        "evidenceOrigin",
        "remediation",
    }
    assert finding["blocking"] is True and finding["remediation"]
    assert "private-treatment-token" not in json.dumps(findings)
    assert _by_pointer(elements)[CLIP]["disposition"] == "unresolved"


def test_nested_stack_and_children_remain_counted_without_flattened_success():
    raw = _raw()
    track = raw["tracks"]["children"][0]
    track["children"] = [
        {
            "OTIO_SCHEMA": "Stack.1",
            "name": "Nested scene",
            "children": track["children"],
        }
    ]
    elements, accounting, findings = _account(raw, checks=FAILED)
    rows = _by_pointer(elements)
    assert accounting["total"] == 3
    assert rows[CLIP]["schema"] == "Stack.1"
    assert rows[CLIP]["disposition"] == "unsupported"
    assert rows[CLIP + "/children/0"]["disposition"] != "reconstructed"
    assert any(item["scope"] == CLIP and item["blocking"] for item in findings)


@pytest.mark.parametrize("owner", ["track", "root-stack"])
def test_parent_trim_owner_has_its_own_unsupported_scope(owner):
    raw = _raw()
    node = raw["tracks"]["children"][0] if owner == "track" else raw["tracks"]
    node["source_range"] = deepcopy(
        raw["tracks"]["children"][0]["children"][0]["source_range"]
    )
    elements, _, findings = _account(raw, checks=FAILED)
    scope = TRACK if owner == "track" else "/tracks"
    assert _by_pointer(elements)[scope]["disposition"] == "unsupported"
    assert any(item["scope"] == scope and item["blocking"] for item in findings)


@pytest.mark.parametrize("placed", [False, True])
def test_disabled_state_and_gap_are_accounted_without_a_rendered_pixels_claim(placed):
    raw = _raw()
    track = raw["tracks"]["children"][0]
    track["enabled"] = False
    clip = track["children"][0]
    clip["enabled"] = False
    track["children"].append({"OTIO_SCHEMA": "Gap.1", "name": "Explicit black"})
    elements, accounting, findings = _account(raw, placed=placed)
    rows = _by_pointer(elements)
    expected = "reconstructed" if placed else "unsupported"
    assert rows[TRACK]["enabled"] is False and rows[CLIP]["enabled"] is False
    assert all(item["disposition"] == expected for item in elements)
    assert accounting["byDisposition"][expected] == 3
    assert bool(findings) is not placed
    assert "rendered" not in json.dumps((elements, accounting, findings))


def test_unknown_reference_and_clock_schema_are_counted_but_known_objects_are_not():
    raw = _raw()
    clip = raw["tracks"]["children"][0]["children"][0]
    clip["media_reference"]["OTIO_SCHEMA"] = "ExternalReference.99"
    clip["source_range"]["duration"]["OTIO_SCHEMA"] = "RationalTime.99"
    elements, accounting, findings = _account(raw, checks=FAILED)
    scopes = {CLIP + "/media_reference", CLIP + "/source_range/duration"}
    assert accounting["total"] == 4
    assert {
        item["pointer"] for item in elements if item["disposition"] == "unsupported"
    } == scopes
    assert scopes <= {item["scope"] for item in findings}


def test_ids_bind_exact_export_and_structural_selection_but_not_validation_result():
    raw = _raw()
    passed = _account(raw)[0]
    failed = _account(raw, checks=FAILED)[0]
    assert {item["pointer"]: item["elementId"] for item in passed} == {
        item["pointer"]: item["elementId"] for item in failed
    }
    changed = deepcopy(raw)
    changed["name"] = "Different exact export"
    assert {item["elementId"] for item in passed}.isdisjoint(
        item["elementId"] for item in _account(changed)[0]
    )
    collection = {
        "OTIO_SCHEMA": "SerializableCollection.1",
        "children": [raw, deepcopy(raw)],
    }
    first = _account(collection, pointer="/children/0")[0]
    second = _account(collection, pointer="/children/1")[0]
    assert {item["elementId"] for item in first}.isdisjoint(
        item["elementId"] for item in second
    )
    assert all(item["pointer"].startswith("/children/1/") for item in second)


def test_element_cap_preserves_all_disposition_counts_and_exposes_truncation():
    raw = _raw()
    track = raw["tracks"]["children"][0]
    track["children"] = [deepcopy(track["children"][0]) for _ in range(2100)]
    elements, accounting, findings = _account(raw)
    assert len(elements) == 2048
    assert accounting["total"] == accounting["byDisposition"]["reconstructed"] == 2101
    assert accounting["reported"] == 2048 and accounting["truncated"] is True
    assert any(
        item["code"] == "OTIO_INPUT_LIMIT" and item["blocking"] for item in findings
    )
    assert accounting["byDisposition"]["unsupported"] == 0


def test_finding_cap_keeps_counts_and_every_reported_unsupported_row_has_remedy(
    monkeypatch,
):
    monkeypatch.setattr(import_findings, "MAX_ELEMENTS", 10)
    monkeypatch.setattr(import_findings, "MAX_FINDINGS", 5)
    raw = _raw()
    raw["unsupported"] = [{"OTIO_SCHEMA": "VendorTreatment.99"} for _ in range(20)]
    elements, accounting, findings = _account(raw, checks=FAILED)
    assert accounting["total"] == 22
    assert accounting["byDisposition"] == {
        "reconstructed": 0,
        "reference-metadata": 0,
        "unresolved": 2,
        "unsupported": 20,
    }
    assert accounting["reported"] == len(elements) <= 10
    assert accounting["findingsTotal"] == 21
    assert accounting["findingsReported"] == len(findings) <= 6
    assert accounting["findingsTruncated"] is True
    assert accounting["truncated"] is True
    scopes = {
        item["scope"] for item in findings if item["blocking"] and item["remediation"]
    }
    assert all(
        item["pointer"] in scopes
        for item in elements
        if item["disposition"] == "unsupported"
    )


def test_detail_byte_budget_is_global_and_never_dumps_raw_metadata(monkeypatch):
    monkeypatch.setattr(import_findings, "MAX_DETAIL_BYTES", 4096)
    raw = _raw()
    raw["metadata"] = {"secret": "private-raw-token" * 1000}
    raw["tracks"]["children"][0]["children"][0]["name"] = "n" * 10000
    raw["界" * 1800] = {"OTIO_SCHEMA": "VendorTreatment.99", "name": "Unknown"}
    elements, accounting, findings = _account(raw, checks=FAILED)
    assert accounting["total"] == 3
    assert accounting["byDisposition"]["unsupported"] == 1
    assert accounting["truncated"] is True
    assert all(len(item["name"]) <= 240 for item in elements)
    output = canonical_json_bytes(
        {"elements": elements, "accounting": accounting, "findings": findings}
    )
    assert len(output) <= 4096
    assert b"private-raw-token" not in output
    assert any(item["code"] == "OTIO_INPUT_LIMIT" for item in findings)


def test_malformed_export_uses_the_existing_bounded_input_error():
    with pytest.raises(ImportError) as error:
        import_findings.account_elements(
            b"{invalid", "", checks=PASSED, declarations={}
        )
    assert error.value.code == "OTIO_INPUT_INVALID"
