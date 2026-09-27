from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from avo.timeline.contracts import (
    content_hash,
    file_fingerprint,
)
from avo.timeline.materialize import (
    ProofMaterializationError,
    materialize_proof_plan,
    render_proof_microproofs,
)
from avo.timeline.proof_plan import ProofPlanCompiler, ProofPlanError
from avo.timeline.store import ArtifactStore


class Workspace(SimpleNamespace):
    def store(self, artifact_type):
        return self.stores[artifact_type]

    def require_active(self, artifact_type):
        index = self.store(artifact_type).load_index()
        if index["activeState"] != "valid":
            raise RuntimeError(f"{artifact_type} is stale")
        return index


class Renderer:
    def __init__(self):
        self.calls = []
        self.ready = True

    def proof_tool_readiness(self, _plan):
        return {"ffmpeg": self.ready}

    def render_proof_plan(self, plan, output, *, window):
        self.calls.append((plan["proofPlanHash"], window))
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(f"render:{window}".encode())
        return {
            "status": "pass",
            "output": file_fingerprint(output),
            "graphHash": "d" * 64,
            "producer": {"name": "fixture", "version": "1"},
        }


def fixture(tmp_path):
    timeline = tmp_path / "edit" / "timeline"
    stores = {}
    for name in ("cmap", "bmap", "tracks", "animation", "sync-map"):
        store = ArtifactStore(timeline / f"{name}.json")
        store.initialize(
            artifact_type=name,
            artifact_id=f"fire-emblem:{name}",
            video_id="fire-emblem",
            provider="bishop",
            timeline_domain=(
                "raw-source" if name in {"cmap", "sync-map"} else "cmap-output"
            ),
        )
        store.append_revision(snapshot={"name": name}, actor="test", reason="fixture")
        stores[name] = store
    workspace = Workspace(
        timeline_dir=timeline,
        stores=stores,
        raw_dir=tmp_path,
        video_id="fire-emblem",
        project={"provider": "bishop"},
    )
    source = tmp_path / "camera.mp4"
    source.write_bytes(b"original")
    request = {
        "iterationId": "iteration-0001",
        "sourceFingerprints": {"camera": file_fingerprint(source)["sha256"]},
        "renderProfile": "proof",
        "output": {
            "path": str(tmp_path / "full-proof.mp4"),
            "width": 1280,
            "height": 720,
            "frameRate": {"num": 30, "den": 1},
            "audioSampleRate": 48000,
            "channelLayout": "stereo",
            "videoCodec": "h264",
            "audioCodec": "aac",
        },
        "videoGraph": {
            "operations": [
                {
                    "operationId": "operation-critical-card",
                    "kind": "overlay-image",
                    "inputs": ["camera"],
                    "outputRange": {"startFrame": 30, "endFrameExclusive": 90},
                    "parameters": {},
                }
            ]
        },
        "audioGraph": {
            "sampleRate": 48000,
            "nodes": [],
            "operations": [],
            "singleFinalEncode": True,
        },
        "events": [],
        "validationPlan": {
            "preflight": ["lineage", "dependency", "tool"],
            "microproof": [{"startFrame": 30, "endFrameExclusive": 90}],
            "fullReview": ["watch"],
            "historicalRegression": ["speech", "movement", "event-sync"],
        },
        "visionReviewPlanRef": None,
    }
    contract = {
        "contractId": "contract-iteration-0001",
        "ledgerHash": "a" * 64,
        "iterationId": "iteration-0001",
        "obligations": [],
        "historicalRiskWindows": [{"startFrame": 300, "endFrameExclusive": 360}],
        "conflicts": [],
        "contractHash": "b" * 64,
    }
    plan = ProofPlanCompiler(workspace).compile(request, regression_contract=contract)
    return workspace, plan, source


@pytest.mark.parametrize(
    ("regression", "status", "expected_code"),
    [
        ("truncated-speech", "fail", "PROOF_MICROPROOF_FAILED"),
        ("frozen-overlay", "fail", "PROOF_MICROPROOF_FAILED"),
        ("event-sync-ambiguous", "ambiguous", "PROOF_MICROPROOF_AMBIGUOUS"),
    ],
)
def test_full_render_is_blocked_by_required_regression_microproofs(
    tmp_path, regression, status, expected_code
):
    workspace, plan, source = fixture(tmp_path)
    renderer = Renderer()
    gate = render_proof_microproofs(
        workspace=workspace,
        proof_plan=plan,
        media_inputs={"camera": source},
        render_port=renderer,
    )
    microproof_call_count = len(renderer.calls)
    broken = deepcopy(gate)
    broken.pop("path", None)
    broken["results"][0]["status"] = status
    broken["results"][0]["finding"] = regression
    broken["status"] = "fail" if status != "pass" else "pass"
    broken["gateHash"] = content_hash(
        {key: value for key, value in broken.items() if key != "gateHash"}
    )
    with pytest.raises(ProofMaterializationError) as error:
        materialize_proof_plan(
            workspace=workspace,
            proof_plan=plan,
            microproof_gate=broken,
            media_inputs={"camera": source},
            render_port=renderer,
        )
    assert error.value.code == expected_code
    assert len(renderer.calls) == microproof_call_count


@pytest.mark.parametrize(
    ("defect", "expected_code"),
    [
        ("missing-media", "PROOF_MEDIA_MISSING"),
        ("tool", "PROOF_TOOL_NOT_READY"),
        ("lineage", "PROOF_FORBIDDEN_MEDIA_ANCESTRY"),
    ],
)
def test_preflight_defects_stop_before_any_render(tmp_path, defect, expected_code):
    workspace, plan, source = fixture(tmp_path)
    renderer = Renderer()
    media = {"camera": source}
    if defect == "missing-media":
        media = {}
    elif defect == "tool":
        renderer.ready = False
    else:
        media = {
            "camera": {
                "path": source,
                "mediaClass": "source",
                "ancestry": [{"mediaClass": "proof"}],
            }
        }
    with pytest.raises((ProofPlanError, ProofMaterializationError)) as error:
        render_proof_microproofs(
            workspace=workspace,
            proof_plan=plan,
            media_inputs=media,
            render_port=renderer,
        )
    assert error.value.code == expected_code
    assert renderer.calls == []


def test_stale_dependency_lock_stops_before_full_render(tmp_path):
    workspace, plan, source = fixture(tmp_path)
    renderer = Renderer()
    gate = render_proof_microproofs(
        workspace=workspace,
        proof_plan=plan,
        media_inputs={"camera": source},
        render_port=renderer,
    )
    calls = len(renderer.calls)
    workspace.store("animation").append_revision(
        snapshot={"changed": True}, actor="test", reason="stale the plan"
    )
    with pytest.raises(ProofPlanError) as error:
        materialize_proof_plan(
            workspace=workspace,
            proof_plan=plan,
            microproof_gate=gate,
            media_inputs={"camera": source},
            render_port=renderer,
        )
    assert error.value.code == "PROOF_REVISION_STALE"
    assert len(renderer.calls) == calls


def test_complete_sanitized_fire_emblem_regression_fixture_is_in_default_gate():
    path = (
        Path(__file__).parents[1]
        / "fixtures"
        / "iteration-proofing"
        / "fire-emblem-regressions.json"
    )
    corpus = json.loads(path.read_text(encoding="utf-8"))
    cases = {item["id"]: item for item in corpus["cases"]}
    assert set(cases) == {
        "audio-leak-wheel-scissors",
        "truncated-dialogue-at-cuts",
        "frozen-walking-overlay",
        "frozen-cutscene",
        "displaced-or-duplicate-sfx",
        "main-program-cutscene-given-insert-sfx",
        "late-creator-asset",
        "stale-active-candidate",
        "prior-proof-as-render-base",
    }
    assert cases["late-creator-asset"]["origin"] == "user-scope-change"
    assert all(item["gate"] for item in cases.values())
    assert all(
        item["origin"] != "user-scope-change"
        for key, item in cases.items()
        if key != "late-creator-asset"
    )
