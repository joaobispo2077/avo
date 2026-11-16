"""Import a supplied export without Resolve or handwritten mapping documents."""

import json

import pytest

from avo.adapters.media.otio_reader import read_otio
from avo.timeline.import_service import TimelineImportService
from avo.timeline.initial_cut import initial_cut_proof_request
from avo.timeline.pipeline import TimelinePipeline
from tests import test_timeline_import_service as fixtures

project_fixture = pytest.fixture(name="import_project")(
    fixtures.import_project.__wrapped__
)


def _export(tmp_path, original, *, effect=None):
    raw = json.loads(fixtures.FIXTURE.read_text())
    clip = raw["tracks"]["children"][0]["children"][0]
    clip["media_reference"]["target_url"] = str(original)
    if effect is not None:
        clip["effects"] = [effect]
    path = tmp_path / "timeline.otio"
    path.write_text(json.dumps(raw))
    return path


def _service(import_project):
    project, provider, _ = import_project
    return TimelineImportService(
        project, provider_root=provider, reader=read_otio, probe=fixtures._probe
    )


def test_pipeline_reconstructs_draft_without_mapping_or_declaration_files(
    import_project, tmp_path
):
    service = _service(import_project)
    result = TimelinePipeline(service.workspace).prepare_timeline_import(
        service,
        _export(tmp_path, import_project[2]),
        actor="fixture",
        reason="Import exported edit",
    )
    assert result["status"] == "awaiting-sync", result.get("findings")
    snapshot = result["proposal"]["snapshot"]
    assert snapshot["layoutMode"] == "placed"
    assert len(snapshot["layout"]["placements"]) == 1
    assert result["proposal"]["output"]["width"] == 640
    assert result["readiness"]["renderSupported"] is True
    assert result["readiness"]["renderAllowed"] is False
    assert service.head_hash() == "empty"


def test_unknown_effect_is_retained_in_editable_draft_and_blocks_proof_only(
    import_project, tmp_path
):
    service = _service(import_project)
    effect = {
        "OTIO_SCHEMA": "Effect.1",
        "effect_name": "Resolve Effect",
        "metadata": {
            "Resolve_OTIO": {
                "Effect Name": "Cropping",
                "Enabled": True,
                "Parameters": [],
            },
        },
    }
    result = TimelinePipeline(service.workspace).prepare_timeline_import(
        service,
        _export(tmp_path, import_project[2], effect=effect),
        actor="fixture",
        reason="Retain unsupported effect",
    )
    assert result["status"] == "awaiting-sync", result.get("findings")
    retained = result["proposal"]["snapshot"]["layout"]["resolveEffects"]
    assert len(retained) == 1 and retained[0]["payload"] == effect
    assert retained[0]["state"] == "unresolved"
    assert result["readiness"]["renderAllowed"] is False
    assert result["warnings"] and not result["findings"]
    fixtures._approve_fixture_sync(service, result["proposal"])
    ready = service.validate(result["importId"])
    selected = service.activate(
        result["importId"],
        validation_hash=ready["validationHash"],
        expected_head="empty",
        actor="fixture",
        reason="Select editable draft only",
    )
    assert selected["revision"]["snapshot"]["layout"]["resolveEffects"] == retained
    with pytest.raises(ValueError, match="preserved|unsupported|unresolved"):
        initial_cut_proof_request(
            service.workspace,
            iteration_id="fixture",
            output=tmp_path / "proof.mkv",
            frame_rate={"num": 24, "den": 1},
            width=640,
            height=360,
        )
    from avo.timeline.materialize import (
        ProofMaterializationError,
        materialize_proof_plan,
    )
    from avo.timeline.proof_plan import ProofPlanCompiler
    from avo.timeline.resolve_export import import_approximation
    from tests.test_proof_plan import regression_contract

    declaration = import_approximation(
        selected["revision"]["snapshot"],
        authorization="User chose an approximation preview",
    )
    request = initial_cut_proof_request(
        service.workspace,
        iteration_id="fixture",
        output=tmp_path / "approximation.mp4",
        frame_rate={"num": 24, "den": 1},
        width=640,
        height=360,
        import_approximation=declaration,
    )
    plan = ProofPlanCompiler(service.workspace).compile(
        request, regression_contract=regression_contract("fixture")
    )
    assert plan["previewOnly"] is True and plan["importApproximation"] == declaration
    with pytest.raises(ProofMaterializationError, match="cannot be promoted"):
        materialize_proof_plan(
            workspace=service.workspace,
            proof_plan=plan,
            microproof_gate={},
            media_inputs={},
        )


def test_explicit_source_only_route_stays_strict(import_project, tmp_path):
    service = _service(import_project)
    effect = {"OTIO_SCHEMA": "Effect.1", "effect_name": "unimplemented", "metadata": {}}
    path = _export(tmp_path, import_project[2], effect=effect)
    prepared = service.prepare(
        path,
        mappings={},
        declarations={"sourceOnly": True},
        actor="fixture",
        reason="Strict route",
    )
    assert service.validate(prepared["importId"])["status"] == "blocked"


def test_irregular_original_clock_preserves_draft_but_never_grants_rendering(
    import_project, tmp_path
):
    project, provider, original = import_project

    def irregular(*args, **kwargs):
        raise ValueError("Irregular packet PTS")

    service = TimelineImportService(
        project,
        provider_root=provider,
        reader=read_otio,
        probe=fixtures._probe,
        clock_probe=irregular,
    )
    result = TimelinePipeline(service.workspace).prepare_timeline_import(
        service,
        _export(tmp_path, original),
        actor="fixture",
        reason="Retain source timing",
    )
    assert result["status"] == "awaiting-sync", result.get("findings")
    snapshot = result["proposal"]["snapshot"]
    assert len(snapshot["layout"]["placements"]) == 1
    assert (
        snapshot["sources"][0]["streamMetadata"]["videoClock"]["status"] == "unverified"
    )
    assert result["readiness"]["renderSupported"] is False
    assert any("Original video clock" in w["message"] for w in result["warnings"])
    from avo.timeline.resolve_export import require_renderable_import

    with pytest.raises(ValueError, match="Original video clock"):
        require_renderable_import(snapshot)
    assert service.head_hash() == "empty"


def test_generated_reference_without_title_metadata_is_preserved(
    import_project, tmp_path
):
    service = _service(import_project)
    path = _export(tmp_path, import_project[2])
    raw = json.loads(path.read_text())
    clip = raw["tracks"]["children"][0]["children"][0]
    clip["media_reference"] = {"OTIO_SCHEMA": "MissingReference.1"}
    clip["source_range"]["start_time"]["value"] = 0
    # Keep another picture clip to supply an unambiguous fallback canvas.
    from copy import deepcopy

    second = deepcopy(clip)
    second["media_reference"] = {
        "OTIO_SCHEMA": "ExternalReference.1",
        "target_url": str(import_project[2]),
        "available_range": {
            "OTIO_SCHEMA": "TimeRange.1",
            "start_time": {"OTIO_SCHEMA": "RationalTime.1", "value": 0, "rate": 24},
            "duration": {"OTIO_SCHEMA": "RationalTime.1", "value": 240, "rate": 24},
        },
    }
    raw["tracks"]["children"][0]["children"].append(second)
    path.write_text(json.dumps(raw))
    result = TimelinePipeline(service.workspace).prepare_timeline_import(
        service, path, actor="fixture", reason="Retain generator"
    )
    assert result["status"] == "awaiting-sync", result.get("findings")
    placement = result["proposal"]["snapshot"]["layout"]["placements"][0]
    assert placement["mediaKind"] == "generator"
    assert placement["generator"] == clip
    assert result["readiness"]["renderSupported"] is False


def test_cli_prepare_uses_automatic_path_by_default(
    import_project, tmp_path, monkeypatch, capsys
):
    from avo.cli import main

    service = _service(import_project)
    monkeypatch.setattr("avo.timeline_import_cli.create_service", lambda args: service)
    assert (
        main(
            [
                "timeline-import",
                "prepare",
                "--input",
                str(_export(tmp_path, import_project[2])),
                "--project",
                str(import_project[0]),
                "--actor",
                "fixture",
                "--reason",
                "Import",
                "--json",
            ]
        )
        == 0
    )
    result = json.loads(capsys.readouterr().out)
    assert (
        result["session"]["options"]["declarations"]["reconstructionMode"]
        == "export-driven"
    )
    assert service.head_hash() == "empty"


@pytest.mark.parametrize(
    "duration,status", [(99.9995, "awaiting-sync"), (99.998, "blocked")]
)
def test_container_duration_quantization_keeps_exact_packet_extent_guard(
    import_project, tmp_path, duration, status
):
    project, provider, original = import_project

    def quantized(paths):
        info = fixtures._probe(paths)
        for source in info["sources"]:
            video = source["streams"]["video"][0]
            video.update(
                timeBase="1/1000", durationTicks=None, durationSeconds=duration
            )
        return info

    service = TimelineImportService(
        project, provider_root=provider, reader=read_otio, probe=quantized
    )
    result = TimelinePipeline(service.workspace).prepare_timeline_import(
        service,
        _export(tmp_path, original),
        actor="fixture",
        reason="Check tag quantization",
    )
    assert result["status"] == status, result.get("findings")
    if status == "awaiting-sync":
        assert result["readiness"]["renderSupported"] is True
    else:
        assert any(f["code"] == "OTIO_SOURCE_CHANGED" for f in result["findings"])


@pytest.mark.parametrize(
    "name,parameters",
    [
        (
            "Transform",
            {
                "transformationZoomX": 0,
                "transformationZoomY": 0.5,
                "transformationPan": 0,
                "transformationTilt": 0,
            },
        ),
        ("Video Faders", {"videoFaderOut": 1_000_000}),
    ],
)
def test_exported_treatment_outside_supported_bounds_stays_in_draft(
    import_project, tmp_path, name, parameters
):
    effect = {
        "OTIO_SCHEMA": "Effect.1",
        "effect_name": name,
        "metadata": {
            "Resolve_OTIO": {
                "Effect Name": name,
                "Enabled": True,
                "Parameters": [
                    {"Parameter ID": k, "Parameter Value": v, "Key Frames": {}}
                    for k, v in parameters.items()
                ],
            }
        },
    }
    service = _service(import_project)
    result = TimelinePipeline(service.workspace).prepare_timeline_import(
        service,
        _export(tmp_path, import_project[2], effect=effect),
        actor="fixture",
        reason="Retain unsupported operation",
    )
    assert result["status"] == "awaiting-sync", result.get("findings")
    layout = result["proposal"]["snapshot"]["layout"]
    assert layout["resolveEffects"][0]["state"] == "unresolved"
    assert result["readiness"]["renderSupported"] is False
