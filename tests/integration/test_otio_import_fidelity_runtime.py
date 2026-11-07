"""Unsupported native handoffs stay staged; activation cannot acknowledge them away."""

import json
from copy import deepcopy

import pytest
from tests.integration.test_otio_import_media_runtime import (
    FIRST,
    SECOND,
    _declarations,
    _mapping,
)
from tests.integration.test_otio_import_media_runtime import (
    trial as _trial,
)
from tests.test_proof_plan import regression_contract
from tests.test_timeline_import_service import _approve_fixture_sync

from avo.timeline.import_service import TimelineImportService
from avo.timeline.initial_cut import initial_cut_proof_request
from avo.timeline.materialize import canonical_proof_media_inputs
from avo.timeline.otio_import import ImportError, inspect_export
from avo.timeline.proof_plan import ProofPlanCompiler

pytestmark = pytest.mark.integration


@pytest.fixture(name="trial")
def native_trial(tmp_path):
    return _trial.__wrapped__(tmp_path)


@pytest.mark.parametrize(
    "treatment", ["supported", "transition", "retime", "nested", "omitted"]
)
def test_native_fidelity_matrix_stays_blocked_until_reconstructable(trial, treatment):
    service, export, paths = trial
    document = json.loads(export.read_text())
    children = document["tracks"]["children"][0]["children"]
    declarations = _declarations()
    if treatment == "transition":
        children.insert(
            1,
            {
                "OTIO_SCHEMA": "Transition.1",
                "name": "Dissolve",
                "transition_type": "SMPTE_Dissolve",
                "in_offset": {"OTIO_SCHEMA": "RationalTime.1", "value": 3, "rate": 24},
                "out_offset": {"OTIO_SCHEMA": "RationalTime.1", "value": 3, "rate": 24},
            },
        )
    elif treatment == "retime":
        children[0]["effects"] = [
            {
                "OTIO_SCHEMA": "LinearTimeWarp.1",
                "name": "Speed",
                "effect_name": "LinearTimeWarp",
                "time_scalar": 2,
            }
        ]
    elif treatment == "nested":
        children[0] = {"OTIO_SCHEMA": "Stack.1", "children": [deepcopy(children[0])]}
    elif treatment == "omitted":
        declarations["omittedTreatments"] = ["Resolve grade not included in export"]
    export.write_text(json.dumps(document))
    original = export.read_bytes()
    inspected = inspect_export(export)
    assert inspected["readiness"]["mediaReady"] == "not-checked"
    prepared = service.prepare(
        export,
        media_roots=[path.parent for path in paths],
        mappings={FIRST: _mapping(paths[0]), SECOND: _mapping(paths[1])},
        declarations=declarations,
        actor="fixture",
        reason="Synthetic fidelity matrix",
    )
    result = service.validate(prepared["importId"])
    if treatment != "supported":
        assert result["status"] == "blocked"
        assert any(
            row["code"] in {"OTIO_TREATMENT_UNSUPPORTED", "OTIO_SCHEMA_UNSUPPORTED"}
            for row in result["findings"]
        )
        with pytest.raises(ImportError):
            service.activate(
                prepared["importId"],
                validation_hash=result["validationHash"],
                expected_head="empty",
                actor="fixture",
                reason="Acknowledgement cannot approve fidelity",
            )
        assert not service.workspace.artifact_path("cmap").exists()
    else:
        assert result["status"] == "awaiting-sync", result["findings"]
        _approve_fixture_sync(service, result["proposal"])
        ready = service.validate(prepared["importId"])
        service.activate(
            prepared["importId"],
            validation_hash=ready["validationHash"],
            expected_head="empty",
            actor="fixture",
            reason="Synthetic supported draft",
        )
        request = initial_cut_proof_request(
            service.workspace,
            iteration_id="iteration-0001",
            output=service.workspace.raw_dir / "edit/preview/fidelity.mkv",
            frame_rate={"num": 24, "den": 1},
            width=128,
            height=96,
        )
        compiler = ProofPlanCompiler(service.workspace)
        plan = compiler.compile(request, regression_contract=regression_contract())
        preflight = compiler.preflight(
            plan,
            media_inputs=canonical_proof_media_inputs(service.workspace, plan),
            tool_readiness={"ffmpeg": True, "proof-plan-executor": True},
        )
        assert preflight["status"] == "pass", preflight
        # Reloading the service changes no selected canonical head or approvals.
        resumed = TimelineImportService(
            service.workspace.project_path,
            provider_root=service.provider_manifest_path.parent,
            reader=service.reader,
            probe=service.probe,
        )
        assert resumed.status(prepared["importId"])["status"] == "active-draft"
    assert export.read_bytes() == original
