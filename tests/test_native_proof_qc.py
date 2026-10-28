"""Later native proofs use the same current-source QC authority as native cuts."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from avo.adapters.qc import cut_proof
from avo.timeline import approval_service
from avo.timeline.projection import ProjectionError


@pytest.fixture
def native_qc(monkeypatch):
    calls = []
    heads = []
    workspace = SimpleNamespace()
    dependencies = {"proof-plan": "a" * 64, "microproof-gate": "b" * 64}

    def verify(actual_workspace, materialization, candidate):
        assert actual_workspace is workspace
        calls.append((materialization, candidate))
        return dependencies

    def cut_only(*_args):
        pytest.fail("a later native proof entered the strict initial-cut verifier")

    monkeypatch.setattr(
        approval_service, "require_native_proof_materialization", verify
    )
    monkeypatch.setattr(
        approval_service, "require_native_cut_materialization", cut_only
    )
    monkeypatch.setattr(
        cut_proof, "_require_current_cut_heads", lambda *args: heads.append(args)
    )
    return SimpleNamespace(
        workspace=workspace, dependencies=dependencies, calls=calls, heads=heads
    )


@pytest.mark.parametrize("checkpoint", ["motion-proof", "pre-master", "deliver"])
def test_later_native_qc_uses_generic_current_source_and_microproof_authority(
    native_qc,
    checkpoint,
):
    case = native_qc
    record = {"kind": "proof-plan", "checkpoint": checkpoint}
    candidate = Path("exact-native-candidate.mkv")
    cut_proof._require_cut_lineage(
        case.workspace, record, candidate, dict(case.dependencies)
    )
    assert case.calls == [(record, candidate)]
    assert case.heads == [(case.workspace, candidate, case.dependencies)]


def test_later_native_qc_rejects_mismatched_frozen_dependencies(native_qc):
    case = native_qc
    with pytest.raises(ProjectionError, match="dependenc"):
        cut_proof._require_cut_lineage(
            case.workspace,
            {"kind": "proof-plan", "checkpoint": "pre-master"},
            Path("exact-native-candidate.mkv"),
            {**case.dependencies, "microproof-gate": "0" * 64},
        )
    assert not case.heads


def test_later_native_qc_cannot_skip_current_source_or_microproof_failure(
    native_qc,
    monkeypatch,
):
    case = native_qc

    def reject(*_args):
        raise ValueError("current original source or microproof gate is stale")

    monkeypatch.setattr(
        approval_service, "require_native_proof_materialization", reject
    )
    with pytest.raises(ValueError, match="source|microproof"):
        cut_proof._require_cut_lineage(
            case.workspace,
            {"kind": "proof-plan", "checkpoint": "deliver"},
            Path("exact-native-candidate.mkv"),
            dict(case.dependencies),
        )
    assert not case.heads


@pytest.fixture(scope="module")
def native_fidelity_media(tmp_path_factory):
    """Real FFmpeg media; canonical verification is an injected unit boundary."""
    import json
    import shutil

    from avo.adapters.media.proof_executor import execute_ffmpeg_proof
    from avo.timeline.contracts import content_hash, file_fingerprint
    from tests.integration.test_ffmpeg_proof_executor import _execution

    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("FFmpeg and FFprobe required")
    root = tmp_path_factory.mktemp("native-fidelity")
    plan = _execution(root)
    candidate = root / "candidate.mp4"
    execute_ffmpeg_proof(plan, candidate)
    plan["output"]["path"] = str(candidate)
    plan.update(
        proofPlanId="proof-plan-" + "a" * 12,
        proofPlanHash="a" * 64,
        renderProfile="master",
    )
    body = {
        "kind": "proof-plan",
        "checkpoint": "pre-master",
        "proofPlanId": plan["proofPlanId"],
        "proofPlanHash": plan["proofPlanHash"],
        "preflightHash": "b" * 64,
        "microproofGateHash": "c" * 64,
        "output": file_fingerprint(candidate),
        "producer": {"name": "avo.ffmpeg-proof-plan", "version": "1"},
        "canonicalInputLock": plan["canonicalInputLock"],
        "renderProfile": "master",
    }
    record = {**body, "materializationHash": content_hash(body)}
    record_path = root / "materialization.json"
    record_path.write_text(json.dumps(record), encoding="utf-8")
    return SimpleNamespace(
        root=root,
        plan=plan,
        candidate=candidate,
        record=record,
        record_path=record_path,
    )


@pytest.fixture
def native_fidelity(native_fidelity_media, monkeypatch):
    import copy

    from avo.adapters.qc import source_fidelity
    from avo.timeline.proof_plan import ProofPlanCompiler

    data = native_fidelity_media
    plan = copy.deepcopy(data.plan)
    workspace = SimpleNamespace(raw_dir=data.root, timeline_dir=data.root / "timeline")
    calls = []

    def verify(actual_workspace, materialization, candidate):
        calls.append((actual_workspace, materialization, candidate))
        return {"proof-plan": plan["proofPlanHash"]}

    monkeypatch.setattr(
        approval_service, "require_native_proof_materialization", verify
    )
    monkeypatch.setattr(ProofPlanCompiler, "load", lambda *_args: plan)
    return SimpleNamespace(
        data=data,
        plan=plan,
        workspace=workspace,
        calls=calls,
        source_fidelity=source_fidelity,
    )


def _native_fidelity(case, checkpoint="pre-master"):
    return case.source_fidelity.source_fidelity_evidence(
        checkpoint=checkpoint,
        candidate={
            "locator": str(case.data.candidate),
            "sha256": case.data.record["output"]["sha256"],
        },
        materialization=case.data.record,
        materialization_path=str(case.data.record_path),
        workspace=case.workspace,
    )


@pytest.mark.parametrize("checkpoint", ["pre-master", "deliver"])
def test_native_fidelity_uses_actual_sdr_media_and_frozen_native_contract(
    native_fidelity,
    checkpoint,
):
    case = native_fidelity
    result = _native_fidelity(case, checkpoint)
    assert result["status"] == "pass", result
    assert result["disposition"] == "pass"
    assert result["findings"] == []
    assert case.calls
    basis = result["details"]["nativeBasis"]
    assert basis["proofPlanHash"] == case.plan["proofPlanHash"]
    assert basis["materializationHash"] == case.data.record["materializationHash"]
    assert basis["microproofGateHash"] == case.data.record["microproofGateHash"]
    assert basis["frameCount"] == 60
    assert basis["scope"] == "8-bit-sdr-native"
    assert "deliveryFidelityPolicy" not in result["details"]
    assert "pictureLineage" not in result["details"]


@pytest.mark.parametrize("mutation", ["codec", "mix", "graph"])
def test_native_fidelity_blocks_unsupported_frozen_contract_features(
    native_fidelity, mutation
):
    case = native_fidelity
    if mutation == "codec":
        case.plan["output"]["videoCodec"] = "hevc"
    elif mutation == "mix":
        case.plan["audioGraph"]["operations"].append({"kind": "mix"})
    else:
        case.plan["videoGraph"]["operations"][0]["kind"] = "reframe"
    result = _native_fidelity(case)
    assert result["status"] == "error"
    assert result["disposition"] == "blocked"
    assert "unsupported" in str(result["findings"]).lower()


def test_native_fidelity_requires_persisted_record_and_current_source_authority(
    native_fidelity,
    monkeypatch,
):
    case = native_fidelity

    def reject(*_args):
        raise ValueError("current generated input or original source is stale")

    monkeypatch.setattr(
        approval_service, "require_native_proof_materialization", reject
    )
    result = _native_fidelity(case)
    assert result["disposition"] == "blocked"
    assert "stale" in str(result["findings"])
    assert result["status"] == "error"


@pytest.mark.parametrize(
    "mutation",
    [
        "width",
        "fps",
        "frames",
        "codec",
        "audio-rate",
        "audio-channels",
        "audio-duration",
        "audio-layout",
        "duration",
        "pixel-depth",
        "hdr-output",
        "hdr-source",
    ],
)
def test_native_fidelity_rejects_incompatible_actual_streams(
    native_fidelity,
    monkeypatch,
    mutation,
):
    import copy

    case = native_fidelity
    probe = case.source_fidelity._native_probe

    def observe(path, *, count_frames=False):
        value = copy.deepcopy(probe(path, count_frames=count_frames))
        video = next(item for item in value["streams"] if item["codec_type"] == "video")
        if Path(path) != case.data.candidate:
            if mutation == "hdr-source":
                video["color_transfer"] = "smpte2084"
            return value
        audio = next(item for item in value["streams"] if item["codec_type"] == "audio")
        if mutation == "width":
            video["width"] += 2
        elif mutation == "fps":
            video["avg_frame_rate"] = "24/1"
        elif mutation == "frames":
            video["nb_read_frames"] = "61"
        elif mutation == "codec":
            video["codec_name"] = "hevc"
        elif mutation == "audio-rate":
            audio["sample_rate"] = "44100"
        elif mutation == "audio-channels":
            audio["channels"] = 6
        elif mutation == "audio-duration":
            audio["duration"] = "1"
        elif mutation == "audio-layout":
            audio["channel_layout"] = "downmix"
        elif mutation == "duration":
            value["format"]["duration"] = "10"
        elif mutation == "pixel-depth":
            video["pix_fmt"] = "yuv420p10le"
        elif mutation == "hdr-output":
            video["color_transfer"] = "arib-std-b67"
        return value

    monkeypatch.setattr(case.source_fidelity, "_native_probe", observe)
    result = _native_fidelity(case)
    assert result["status"] in {"error", "fail"}
    assert result["disposition"] in {"blocked", "fail"}
    assert result["findings"]


def test_native_fidelity_rejects_missing_persisted_materialization(native_fidelity):
    case = native_fidelity
    result = case.source_fidelity.source_fidelity_evidence(
        checkpoint="deliver",
        candidate={"locator": str(case.data.candidate)},
        materialization=case.data.record,
        workspace=case.workspace,
    )
    assert result["disposition"] == "blocked"
    assert "persisted" in str(result["findings"])
