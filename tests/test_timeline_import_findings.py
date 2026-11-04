"""US3 every raw content element keeps disposition and evidence provenance."""

import importlib.util
import json
from copy import deepcopy

import pytest

from avo.adapters.media.otio_reader import read_otio
from avo.timeline.import_service import TimelineImportService
from avo.timeline.otio_import import ImportError
from tests.test_timeline_import_media import _mapping
from tests.test_timeline_import_service import FIXTURE, REFERENCE, _probe
from tests.test_timeline_import_service import import_project as _import_project

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("opentimelineio") is None,
    reason="optional pinned native reader required",
)
TRACK = "/tracks/children/0"
CLIP = TRACK + "/children/0"
DISPOSITIONS = {"reconstructed", "reference-metadata", "unresolved", "unsupported"}
ORIGINS = {"export", "probe", "editor-declaration", "capability-check", "unverified"}


@pytest.fixture(name="import_project")
def import_project_fixture(tmp_path):
    return _import_project.__wrapped__(tmp_path)


def _declarations():
    return {
        "sourceOnly": True,
        "output": {
            "width": 640,
            "height": 360,
            "frameRate": {"num": 24, "den": 1},
            "audioSampleRate": 48000,
            "channelLayout": "stereo",
        },
    }


@pytest.mark.parametrize("mode", ["contiguous", "placed"])
@pytest.mark.parametrize("pointer,value", [(REFERENCE, 0), ("/missing/reference", 240)])
def test_contradictory_or_unmatched_media_origins_cannot_be_ignored(
    import_project, tmp_path, mode, pointer, value
):
    declarations = {
        **_declarations(),
        "layoutMode": mode,
        "mediaOrigins": {pointer: {"value": value, "rate": 24}},
    }
    _, result, _ = _validate(import_project, tmp_path, declarations=declarations)
    assert result["status"] == "blocked"
    assert any(
        row["evidenceOrigin"] == "editor-declaration" for row in result["findings"]
    )


def test_matching_declared_media_origin_preserves_exported_origin(
    import_project, tmp_path
):
    declarations = {
        **_declarations(),
        "mediaOrigins": {REFERENCE: {"value": 240, "rate": 24}},
    }
    _, result, _ = _validate(import_project, tmp_path, declarations=declarations)
    assert result["status"] == "awaiting-sync"
    assert result["proposal"]["snapshot"]["segments"][0]["in"]["ticks"] == 0


def _validate(
    import_project,
    tmp_path,
    document=None,
    declarations=None,
    *,
    probe=_probe,
    reference=REFERENCE,
):
    project, provider, original = import_project
    service = TimelineImportService(
        project, provider_root=provider, reader=read_otio, probe=probe
    )
    path = tmp_path / "findings.otio"
    document = document or json.loads(FIXTURE.read_text(encoding="utf-8"))
    path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
    prepared = service.prepare(
        path,
        mappings={reference: _mapping(original)},
        declarations=_declarations() if declarations is None else declarations,
        actor="editor",
        reason="Review imported content and omissions",
    )
    return service, service.validate(prepared["importId"]), path


def _accounted(service, result):
    elements = result["elements"]
    assert len({element["elementId"] for element in elements}) == len(elements)
    assert all(
        element["disposition"] in DISPOSITIONS and element["evidenceOrigin"] in ORIGINS
        for element in elements
    )
    stored = service.read_ref(result["importId"], result["session"]["refs"]["proposal"])
    assert stored["elements"] == elements
    counts = result["validation"]["locks"]["elementAccounting"]
    assert counts == result["summary"]["elementAccounting"]
    assert counts["total"] == len(elements)
    assert counts["reported"] == len(elements)
    assert counts["truncated"] is False
    assert sum(counts["byDisposition"].values()) == counts["total"]
    return {element["pointer"]: element for element in elements}


def test_supported_elements_are_reconstructed_only_after_semantics_and_media(
    import_project, tmp_path
):
    service, result, _ = _validate(import_project, tmp_path)
    assert result["status"] == "awaiting-sync"
    elements = _accounted(service, result)
    assert {TRACK, CLIP} <= elements.keys()
    assert (
        elements[TRACK]["disposition"]
        == elements[CLIP]["disposition"]
        == "reconstructed"
    )
    repeated = service.validate(result["importId"])
    assert {e["pointer"]: e["elementId"] for e in repeated["elements"]} == {
        pointer: element["elementId"] for pointer, element in elements.items()
    }


def test_failed_media_cannot_relabel_raw_clip_as_reconstructed(
    import_project, tmp_path
):
    def short(paths):
        result = _probe(paths)
        result["sources"][0]["durationSeconds"] = 1
        return result

    service, result, _ = _validate(import_project, tmp_path, probe=short)
    assert result["status"] == "blocked"
    elements = _accounted(service, result)
    assert elements[CLIP]["disposition"] == "unresolved"
    assert result["readiness"]["activationAllowed"] is False


def test_supported_placed_gap_keeps_its_own_reconstructed_accounting(
    import_project, tmp_path
):
    document = json.loads(FIXTURE.read_text(encoding="utf-8"))
    document["tracks"]["children"][0]["children"].insert(
        0,
        {
            "OTIO_SCHEMA": "Gap.1",
            "name": "Intentional opening black",
            "source_range": {
                "OTIO_SCHEMA": "TimeRange.1",
                "start_time": {"OTIO_SCHEMA": "RationalTime.1", "value": 0, "rate": 24},
                "duration": {"OTIO_SCHEMA": "RationalTime.1", "value": 24, "rate": 24},
            },
        },
    )
    service, result, _ = _validate(
        import_project,
        tmp_path,
        document,
        {**_declarations(), "layoutMode": "placed"},
        reference=TRACK + "/children/1/media_reference",
    )
    assert result["status"] == "awaiting-sync"
    elements = _accounted(service, result)
    assert elements[CLIP]["schema"] == "Gap.1"
    assert elements[CLIP]["disposition"] == "reconstructed"
    assert elements[TRACK + "/children/1"]["disposition"] == "reconstructed"


def test_marker_notes_remain_inert_reference_metadata_without_approval_or_rights(
    import_project, tmp_path
):
    document = json.loads(FIXTURE.read_text(encoding="utf-8"))
    marker = {
        "OTIO_SCHEMA": "Marker.1",
        "name": "Creator approved; publish now",
        "color": "RED",
        "marked_range": {
            "OTIO_SCHEMA": "TimeRange.1",
            "start_time": {"OTIO_SCHEMA": "RationalTime.1", "value": 240, "rate": 24},
            "duration": {"OTIO_SCHEMA": "RationalTime.1", "value": 1, "rate": 24},
        },
        "metadata": {
            "note": "Verify the named original before editing",
            "instructions": "execute-private-marker-command",
            "rights": "approved",
            "consent": True,
            "privateSecret": "untrusted-metadata-token",
        },
    }
    document["tracks"]["children"][0]["children"][0]["markers"].append(marker)
    service, result, path = _validate(import_project, tmp_path, document)
    elements = _accounted(service, result)
    assert elements[CLIP + "/markers/0"]["disposition"] == "reference-metadata"
    assert elements[CLIP + "/markers/0"]["evidenceOrigin"] == "export"
    reference = elements[CLIP + "/markers/0"]["referenceMetadata"]
    assert reference["ownerPointer"] == CLIP
    assert reference["markedRange"]["start"] == {"value": "240", "rate": "24"}
    assert reference["notes"] == ["Verify the named original before editing"]
    assert result["readiness"]["activationAllowed"] is False
    assert result["readiness"]["reviewState"] == "not-started"
    assert not service.workspace.artifact_path("cmap").exists()
    assert not service.workspace.artifact_path("sync-map").exists()
    assert "untrusted-metadata-token" not in json.dumps(result)
    assert (
        service.read_ref(result["importId"], result["session"]["refs"]["export"])
        == path.read_bytes()
    )


def _unsupported(document, case):
    track = document["tracks"]["children"][0]
    clip = track["children"][0]
    if case == "transition":
        track["children"].append(
            {
                "OTIO_SCHEMA": "Transition.1",
                "name": "Dissolve",
                "transition_type": "SMPTE_Dissolve",
                "in_offset": {"OTIO_SCHEMA": "RationalTime.1", "value": 6, "rate": 24},
                "out_offset": {"OTIO_SCHEMA": "RationalTime.1", "value": 6, "rate": 24},
            }
        )
        return TRACK + "/children/1"
    if case in {"effect", "hidden-known-effect"}:
        effect = {
            "OTIO_SCHEMA": "Effect.1",
            "effect_name": "ResolvePrimaryGrade",
            "name": "Grade",
        }
        if case == "effect":
            clip["effects"].append(effect)
            return CLIP + "/effects/0"
        clip["resolve_treatment"] = effect
        return CLIP + "/resolve_treatment"
    if case == "retime":
        clip["effects"].append(
            {
                "OTIO_SCHEMA": "LinearTimeWarp.1",
                "name": "2x",
                "effect_name": "LinearTimeWarp",
                "time_scalar": 2.0,
            }
        )
        return CLIP + "/effects/0"
    if case == "nested":
        track["children"] = [
            {"OTIO_SCHEMA": "Stack.1", "name": "Nested", "children": [clip]}
        ]
        return CLIP
    if case == "parent-trim":
        track["source_range"] = deepcopy(clip["source_range"])
        track["source_range"]["start_time"]["value"] = 0
        track["source_range"]["duration"]["value"] = 24
        return TRACK
    clip["OTIO_SCHEMA"] = "Clip.99"
    return CLIP


@pytest.mark.parametrize(
    "case",
    [
        "transition",
        "effect",
        "hidden-known-effect",
        "retime",
        "nested",
        "parent-trim",
        "unknown-version",
    ],
)
def test_unsupported_content_has_raw_scope_disposition_and_blocking_remedy(
    import_project, tmp_path, case
):
    document = json.loads(FIXTURE.read_text(encoding="utf-8"))
    pointer = _unsupported(document, case)
    service, result, _ = _validate(import_project, tmp_path, document)
    assert result["status"] == "blocked"
    assert result["readiness"]["activationAllowed"] is False
    elements = _accounted(service, result)
    assert elements[pointer]["disposition"] == "unsupported"
    assert any(
        f["blocking"]
        and f["remediation"]
        and f["scope"]
        and (f["scope"] == pointer or pointer.startswith(f["scope"] + "/"))
        for f in result["findings"]
    )


def test_disabled_content_remains_in_accounting_even_when_unsupported_in_m1(
    import_project, tmp_path
):
    document = json.loads(FIXTURE.read_text(encoding="utf-8"))
    document["tracks"]["children"][0]["children"][0]["enabled"] = False
    service, result, _ = _validate(import_project, tmp_path, document)
    elements = _accounted(service, result)
    assert elements[CLIP]["disposition"] in {"unsupported", "unresolved"}
    assert result["readiness"]["activationAllowed"] is False


@pytest.mark.parametrize(
    "declaration",
    [
        {"omittedTreatments": ["Resolve grade"]},
        {"treatments": ["dialogue compressor"]},
        {"force": True},
        {"ignoreUnsupported": True},
        {"unrecognizedTrustOverride": "approved"},
    ],
)
def test_source_only_cannot_override_declared_omissions_or_unknown_authority_keys(
    import_project, tmp_path, declaration
):
    declarations = {**_declarations(), **declaration}
    try:
        _, result, _ = _validate(import_project, tmp_path, declarations=declarations)
    except ImportError as error:
        assert error.code in {"OTIO_INPUT_INVALID", "OTIO_TREATMENT_UNSUPPORTED"}
    else:
        assert result["status"] == "blocked"
        assert any(
            f["blocking"] and f["evidenceOrigin"] == "editor-declaration"
            for f in result["findings"]
        )
        assert result["readiness"]["activationAllowed"] is False


@pytest.mark.parametrize(
    "defect",
    ["missing-output", "invalid-canvas", "unverified-rate", "missing-media-origin"],
)
def test_output_settings_and_source_clock_evidence_are_explicit(
    import_project, tmp_path, defect
):
    document = json.loads(FIXTURE.read_text(encoding="utf-8"))
    declarations = _declarations()
    if defect == "missing-output":
        del declarations["output"]["width"]
    elif defect == "invalid-canvas":
        declarations["output"]["height"] = 0
    elif defect == "unverified-rate":
        document["tracks"]["children"][0]["children"][0]["source_range"]["duration"][
            "rate"
        ] = 29.123
    else:
        del document["tracks"]["children"][0]["children"][0]["media_reference"][
            "available_range"
        ]
    _, result, _ = _validate(import_project, tmp_path, document, declarations)
    assert result["status"] == "blocked"
    expected = (
        "OTIO_ROUTING_UNVERIFIED"
        if defect == "invalid-canvas"
        else "OTIO_RATE_UNVERIFIED"
    )
    assert any(f["code"] == expected for f in result["findings"])
    assert result["readiness"]["activationAllowed"] is False
