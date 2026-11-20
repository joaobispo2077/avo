"""Canonical word sound flow with declared metadata fixtures, not listening ratings."""

from copy import deepcopy

import pytest
from tests import test_timeline_approval_service as approval_fixture
from tests.test_sound_application import application
from tests.test_sound_opportunities import intent
from tests.test_speech_coverage_service import GapAnalysis

from avo.editing_craft import resolve_editing_craft_selection
from avo.timeline import sound_word_evidence
from avo.timeline.cutting_contracts import make_document
from avo.timeline.cutting_service import segment_range
from avo.timeline.preparation_recovery import PreparationService
from avo.timeline.reconstruction import _required_files
from avo.timeline.sound_proof import _Selections

pytestmark = pytest.mark.integration


def declared_models():
    return {
        "transcription": {"status": "observed", "files": {"fixture-asr": "c" * 64}},
        "alignment": {"status": "observed", "files": {"fixture-alignment": "d" * 64}},
    }


def retained_word(workspace, models):
    preparation = PreparationService(workspace)
    cmap = workspace.store("cmap").load()["revisions"][-1]["snapshot"]
    source_range = segment_range(cmap["segments"][0])
    _, source, routing, sync_ref = preparation._canonical_source(source_range)
    analysis = GapAnalysis().analyze(
        source["locator"],
        selection=routing,
        source_range=source_range,
        fingerprint=source["fingerprint"],
        sync_ref=sync_ref,
    )
    analysis.update(
        words=[
            {
                "text": "selected",
                "start": 0.25,
                "end": 0.35,
                "alignmentStatus": "aligned",
                "eligibleEdge": True,
            }
        ],
        coverage={"observed": True, "start": 0, "end": 1},
        vad=[{"start": 0.25, "end": 0.35}],
        speechDependencies=deepcopy(models),
    )
    reference = preparation.store.save_document(
        make_document("source-analysis", analysis)
    )
    return {
        "sourceId": source["sourceId"],
        "sourceSha256": source["fingerprint"]["sha256"],
        "segmentId": cmap["segments"][0]["segmentId"],
        "spokenEvidence": {"analysisRef": reference, "wordIndex": 0},
    }, preparation.store.directory / reference["locator"]


def word_application(tmp_path, monkeypatch):
    original = approval_fixture.snapshot

    def routed(path):
        value = original(path)
        value["sources"][0]["streamMetadata"] = {
            "audioSelection": {
                "streamIndex": 0,
                "channels": [0],
                "sourceLayout": "mono",
                "outputLayout": "dual-mono",
                "sourceSampleRate": 48000,
            }
        }
        return value

    monkeypatch.setattr(approval_fixture, "snapshot", routed)
    workspace, _, service, _, request, _ = application(tmp_path)
    models = declared_models()
    monkeypatch.setattr(
        sound_word_evidence,
        "workspace_speech_dependencies",
        lambda ws: deepcopy(models),
    )
    anchor, analysis_path = retained_word(workspace, models)
    selected = intent(kind="explicit", sourceAnchor=anchor)
    selected.pop("phase")
    shown = service.propose(
        {
            "contractVersion": "1.0.0",
            "operation": "propose",
            "operationId": "word-accent",
            "actor": "fixture",
            "reason": "Select a retained word",
            "selection": resolve_editing_craft_selection(
                invocation={"soundMatching": {"enabled": True}}
            ),
            "expectedBasis": request["expectedBasis"],
            "expectedGeneration": request["expectedGeneration"],
            "clock": {
                "frameRate": {"num": 24, "den": 1},
                "sampleRate": 48000,
                "programEndFrame": 24,
            },
            "intents": [selected],
        }
    )
    record = shown["proposal"]["opportunities"][0]
    assert record["opportunity"] is not None, record["issues"]
    request.update(
        operationId="word-accent-apply",
        proposalHash=shown["proposalRef"]["sha256"],
        expectedBasis=shown["proposal"]["basisHeads"],
    )
    return workspace, service, request, shown, analysis_path, models


def test_word_sound_publication_retains_original_evidence_without_a_recovery_journal(
    tmp_path, monkeypatch
):
    workspace, service, request, shown, analysis, _ = word_application(
        tmp_path, monkeypatch
    )
    result = service.apply(request)
    tracks = workspace.store("tracks").load()["revisions"][-1]["snapshot"]
    (selected,) = _Selections(workspace, tracks).load()
    assert (
        selected["choice"]["fit"]["opportunity"]
        == shown["proposal"]["opportunities"][0]["opportunity"]
    )
    assert selected["choice"]["fit"]["event"]["resolvedImpactSample"] == 12000
    assert result["acceptance"] == "pending-listening"
    assert not (workspace.timeline_dir / "cutting/repair-ledger.json").exists()
    assert analysis in _required_files(workspace.raw_dir, [], workspace=workspace)


def test_changed_word_models_block_publication_before_canonical_writes(
    tmp_path, monkeypatch
):
    workspace, service, request, _, _, models = word_application(tmp_path, monkeypatch)
    before = {name: workspace.store(name).head_hash() for name in ("bmap", "tracks")}
    models["alignment"]["files"]["fixture-alignment"] = "e" * 64
    with pytest.raises(ValueError, match="model"):
        service.apply(request)
    assert {name: workspace.store(name).head_hash() for name in before} == before


def test_changed_word_models_block_final_sound_admission(tmp_path, monkeypatch):
    workspace, service, request, _, _, models = word_application(tmp_path, monkeypatch)
    service.apply(request)
    tracks = workspace.store("tracks").load()["revisions"][-1]["snapshot"]
    models["transcription"]["files"]["fixture-asr"] = "e" * 64
    with pytest.raises(ValueError, match="model"):
        _Selections(workspace, tracks).load()


def test_word_evidence_change_cannot_reuse_an_existing_plan_for_approval(
    tmp_path, monkeypatch
):
    from tests import test_sound_proof_plan as proof_fixture
    from tests.test_proof_plan import regression_contract

    from avo.timeline.approval_service import _require_plan_current_inputs

    workspace, service, request, shown, _, models = word_application(
        tmp_path, monkeypatch
    )
    monkeypatch.setattr(
        proof_fixture,
        "application",
        lambda directory: (
            workspace,
            service.catalogue,
            service,
            service.source_probe,
            request,
            shown,
        ),
    )
    _, compiler, proof_request, _ = proof_fixture.published_program(tmp_path)
    plan = compiler.compile(proof_request, regression_contract=regression_contract())
    dependencies = {
        **workspace.active_dependency_snapshot(),
        **{
            key: value
            for key, value in plan["canonicalInputLock"].items()
            if key.startswith("source:")
        },
    }
    review = {"candidate": {"dependencies": dependencies}}
    _require_plan_current_inputs(workspace, plan, review, None)
    models["alignment"]["files"]["fixture-alignment"] = "e" * 64
    with pytest.raises(ValueError, match="model"):
        _require_plan_current_inputs(workspace, plan, review, None)
