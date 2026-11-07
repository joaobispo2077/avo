"""Retained output bytes cannot be relabeled as originals after relocation."""

from types import SimpleNamespace

import pytest

from avo.timeline.contracts import file_fingerprint
from avo.timeline.initial_cut import initial_cut_proof_request
from avo.timeline.materialize import canonical_proof_media_inputs, materialize_cut_proof
from avo.timeline.proof_plan import ProofPlanCompiler, ProofPlanError
from tests.test_historical_output_records import _record, _write
from tests.test_proof_plan import regression_contract
from tests.test_timeline_import_evidence import _activate, _prepare_evidence
from tests.test_timeline_import_media import _mapping, _prepare
from tests.test_timeline_import_service import FIXTURE, REFERENCE, _probe
from tests.test_timeline_import_service import import_project as _project
from tests.test_timeline_import_sources import _blocked, _service


@pytest.fixture(name="import_project")
def project_fixture(tmp_path):
    return _project.__wrapped__(tmp_path)


def test_removed_output_history_still_blocks_original_admission(import_project):
    original = import_project[2]
    fingerprint = file_fingerprint(original)
    fingerprint["locator"] = str(original.parent / "edit/proof/removed.mkv")
    _write(original.parent, _record(original.parent, output=fingerprint))
    service = _service(import_project, _probe)
    result = _blocked(
        service, _prepare(service, FIXTURE, mappings={REFERENCE: _mapping(original)})
    )
    assert any(row["code"] == "OTIO_SOURCE_PROHIBITED" for row in result["findings"])


def test_retained_output_record_blocks_compilation_preflight_and_legacy_render(
    tmp_path,
):
    service, ready = _prepare_evidence(tmp_path)
    revision = _activate(service, ready)
    workspace = service.workspace
    request = initial_cut_proof_request(
        workspace,
        iteration_id="iteration-0001",
        output=workspace.raw_dir / "edit/preview/unrendered.mkv",
        frame_rate={"num": 24, "den": 1},
        width=640,
        height=360,
    )
    compiler = ProofPlanCompiler(workspace)
    plan = compiler.compile(request, regression_contract=regression_contract())
    fingerprint = dict(revision["snapshot"]["sources"][0]["fingerprint"])
    fingerprint["locator"] = str(workspace.raw_dir / "edit/proof/removed.mkv")
    _write(
        workspace.raw_dir,
        _record(workspace.raw_dir, output=fingerprint),
        timeline_dir=workspace.timeline_dir,
    )
    with pytest.raises(ProofPlanError, match="FORBIDDEN"):
        compiler.compile(request, regression_contract=regression_contract())
    gate = compiler.preflight(
        plan,
        media_inputs=canonical_proof_media_inputs(workspace, plan),
        tool_readiness={"ffmpeg": True, "proof-plan-executor": True},
    )
    assert gate["status"] == "blocked"
    assert any(
        row["code"] == "PROOF_IMPORT_EVIDENCE_INVALID" for row in gate["blockers"]
    )

    class UnusedRenderer:
        def render(self, **kwargs):
            pytest.fail("forbidden ancestor reached the renderer")

    with pytest.raises(ProofPlanError, match="FORBIDDEN"):
        materialize_cut_proof(
            workspace=workspace,
            cmap_revision_id=revision["revisionId"],
            output_path=workspace.raw_dir / "edit/preview/never.mkv",
            render_port=UnusedRenderer(),
        )


def test_custom_timeline_root_retained_output_blocks_legacy_assembly(tmp_path):
    from avo.timeline.materialize import _preflight_assembly_media

    timeline = tmp_path / "edit" / "custom-timeline"
    relocated = tmp_path / "camera.mov"
    relocated.write_bytes(b"a previous proof copied into the originals folder")
    fingerprint = file_fingerprint(relocated)
    output = {**fingerprint, "locator": str(tmp_path / "deleted-proof.mkv")}
    _write(tmp_path, _record(tmp_path, output=output), timeline_dir=timeline)
    source = {
        "sourceId": "camera",
        "kind": "raw",
        "locator": str(relocated),
        "fingerprint": fingerprint,
    }
    revisions = {
        "cmap": {"snapshot": {"sources": [source]}},
        "tracks": {"snapshot": {}},
    }
    workspace = SimpleNamespace(raw_dir=tmp_path, timeline_dir=timeline)
    with pytest.raises(ValueError, match="PROOF_FORBIDDEN_ANCESTOR"):
        _preflight_assembly_media(workspace, revisions, None)
