"""Candidate-bound policy tests with synthetic sources/previews, never physical QC."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from avo import motion
from avo.adapters.motion.code_drawn import CodeDrawnAdapter
from avo.motion import MotionError
from avo.timeline import review
from avo.timeline.contracts import content_hash, dependency_lock_hash, file_fingerprint
from avo.timeline.review import GateError, candidate_identity, evidence_is_fresh
from tests.code_drawn_asset_fixture import synthetic_environment
from tests.test_vision_review_evidence import _finding


@pytest.fixture
def subject(tmp_path):
    source = tmp_path / "source-v001"
    motion.scaffold_code_drawn(
        source,
        route="canvas",
        width=128,
        height=96,
        fps="30/1",
        frames=12,
        background="transparent",
    )
    composition = source / "composition.json"
    manifest = motion.load_composition(composition)
    lock = motion.freeze_code_drawn_lock(
        composition, environment=synthetic_environment()
    )
    generated = tmp_path / "generated"
    generated.mkdir()
    lock_path = generated / "input-lock.json"
    lock_path.write_text(json.dumps(lock), encoding="utf-8")
    asset = generated / "asset.mkv"
    asset.write_bytes(b"synthetic source asset; not a physical render")
    capture = {
        "frames": list(range(10)),
        "rgbaSha256": ["a" * 64] * 10,
        "passes": ["repeat", "reverse", "fresh-session"],
        "environment": lock["environment"],
    }
    contract = manifest["renderContract"]
    verification = {
        "width": contract["width"],
        "height": contract["height"],
        "frameRate": contract["frameRate"],
        "frameCount": contract["frameCount"],
        "silent": True,
        "codec": "ffv1",
        "pixelFormat": "bgra",
        "alphaMode": "straight",
        "rgbaRoundTrip": "exact",
        "colorRange": "full",
        "captureColorSpace": "srgb",
        "compositeColorSpace": "sdr-bt709",
        "controlledCompositeChecks": [],
    }
    receipt = CodeDrawnAdapter()._receipt(
        composition, manifest, lock_path, lock, asset, capture, verification
    )
    receipt_path = asset.with_suffix(".generated-asset.json")
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    candidate = tmp_path / "candidate.mp4"
    candidate.write_bytes(
        b"sealed candidate fixture; never decoded by this unit producer"
    )
    dependencies = {
        "cmap": "b" * 64,
        "tracks": "c" * 64,
        "animation": "d" * 64,
        "generated:" + receipt["assetId"]: receipt["recordHash"],
        "input-lock:" + lock["instanceId"]: lock["inputLockHash"],
    }
    return SimpleNamespace(
        root=tmp_path,
        candidate=candidate,
        composition=composition,
        manifest=manifest,
        lock=lock,
        lock_path=lock_path,
        receipt=receipt,
        receipt_path=receipt_path,
        dependencies=dependencies,
        contract={
            key: copy.deepcopy(contract[key])
            for key in ("width", "height", "frameRate", "frameCount")
        },
        render_profile="code-drawn",
        output=tmp_path / "review-v001",
        calls=[],
    )


def _producer(subject):
    def produce(**request):
        subject.calls.append(copy.deepcopy(request))
        output = request["output_dir"]
        output.mkdir(parents=True, exist_ok=True)
        artifacts = []
        for frame in request["sample_frames"]:
            target = output / f"frame-{frame}.png"
            Image.new("RGBA", (128, 96), (frame, 20, 30, 255)).save(target)
            artifacts.append({"kind": "frame", "path": str(target), "frame": frame})
            small = output / f"small-{frame}.png"
            Image.new("RGB", (64, 48), (frame, 20, 30)).save(small)
            artifacts.append(
                {"kind": "small-display", "path": str(small), "frame": frame}
            )
        contact = output / "contact.png"
        Image.new("RGB", (128, 96)).save(contact)
        artifacts.append({"kind": "contact-sheet", "path": str(contact)})
        for index, bounds in enumerate(request["transition_ranges"]):
            strip = output / f"strip-{index}.png"
            Image.new("RGB", (256, 96)).save(strip)
            artifacts.append(
                {"kind": "transition-strip", "path": str(strip), "range": bounds}
            )
        if request["loop_requested"]:
            loop = output / "loop.png"
            Image.new("RGB", (256, 96)).save(loop)
            artifacts.append(
                {
                    "kind": "loop-strip",
                    "path": str(loop),
                    "frames": [11, 0],
                    "range": {"startFrame": 0, "endFrameExclusive": 12},
                }
            )
        return {
            "artifacts": artifacts,
            "findings": [],
            "status": "needs-human-judgment",
        }

    return produce


def _prepare(subject, producer=None, **changes):
    request = {
        "candidate": subject.candidate,
        "dependencies": subject.dependencies,
        "render_profile": subject.render_profile,
        "candidate_contract": subject.contract,
        "source_receipts": [subject.receipt_path],
        "output_dir": subject.output,
        "producer": producer or _producer(subject),
        "sample_frames": [5],
        "transition_ranges": [{"startFrame": 4, "endFrameExclusive": 8}],
        "loop_requested": False,
    }
    request.update(changes)
    return motion.prepare_code_drawn_review(**request)


def _validate(subject, package, **changes):
    request = {
        "candidate": subject.candidate,
        "dependencies": subject.dependencies,
        "render_profile": subject.render_profile,
    }
    request.update(changes)
    return review.validate_code_drawn_review(package, **request)


def _reseal(package):
    value = copy.deepcopy(package)
    value["reviewHash"] = content_hash(
        {key: item for key, item in value.items() if key != "reviewHash"}
    )
    Path(value["packagePath"]).write_text(json.dumps(value), encoding="utf-8")
    return value


def _entry(subject, result, *, status="open"):
    frame = next(
        item
        for item in result["artifacts"]
        if item["kind"] == "frame" and item["frame"] == 5
    )
    finding = _finding(
        programRange={"startFrame": 5, "endFrameExclusive": 6},
        evidenceRefs=[
            {
                "kind": "observed-frame",
                "artifactId": "frame-5",
                "sha256": file_fingerprint(Path(frame["path"]))["sha256"],
            }
        ],
        status=status,
        requiresHuman=True,
    )
    entry = {
        "finding": finding,
        "candidateSha256": file_fingerprint(subject.candidate)["sha256"],
        "observedAt": "2026-10-26T12:00:00Z",
    }
    if status == "resolved":
        finding["requiresHuman"] = False
        finding["humanDisposition"] = {
            "decision": "resolved",
            "actor": "fixture-reviewer",
            "rationale": "Synthetic policy fixture, not a real image inspection",
            "decidedAt": "2026-10-26T12:02:00Z",
            "candidateSha256": entry["candidateSha256"],
        }
        entry.update(
            fixRevisionRef="animation-r0002",
            fixedAt="2026-10-26T12:01:00Z",
            recheck={
                "candidateSha256": entry["candidateSha256"],
                "dependencyLockSha256": dependency_lock_hash(subject.dependencies),
                "observedAt": "2026-10-26T12:02:00Z",
                "programRange": {"startFrame": 5, "endFrameExclusive": 6},
                "evidenceRefs": [
                    {
                        "path": frame["path"],
                        "sha256": file_fingerprint(Path(frame["path"]))["sha256"],
                    }
                ],
                "status": "pass",
            },
        )
    return entry


def test_review_binds_actual_candidate_source_and_hashed_preview_files(subject):
    package = _prepare(subject)
    assert package["candidate"] == candidate_identity(
        subject.candidate, subject.dependencies, subject.render_profile
    )
    assert package["dependencyLockSha256"] == dependency_lock_hash(subject.dependencies)
    assert package["candidateContract"] == subject.contract
    assert package["sampleFrames"] == [0, 5, 11]
    assert package["transitionRanges"] == [{"startFrame": 4, "endFrameExclusive": 8}]
    assert package["approval"] is None
    assert package["state"] == "needs-human-judgment"
    assert package["reviewHash"] == content_hash(
        {key: value for key, value in package.items() if key != "reviewHash"}
    )
    assert Path(package["packagePath"]).name == "code-drawn-review.json"
    assert (
        json.loads(Path(package["packagePath"]).read_text(encoding="utf-8")) == package
    )
    for artifact in package["artifacts"]:
        actual = file_fingerprint(Path(artifact["path"]))
        assert artifact["sha256"] == actual["sha256"]
        assert artifact["sizeBytes"] == actual["sizeBytes"]


def test_review_source_summary_keeps_full_editable_and_runtime_identity(subject):
    source = _prepare(subject)["sources"][0]
    extension = subject.receipt["parameters"]["codeDrawn"]
    assert source["engine"] == "code-drawn"
    assert source["drawingRoute"] == "canvas"
    for field in (
        "instanceId",
        "sourceRevision",
        "manifestRef",
        "inputLockRef",
        "inputLockHash",
        "renderContractHash",
        "inputsHash",
        "outputVerification",
    ):
        assert source[field] == extension[field]
    assert source["receiptRef"] == {
        "path": str(subject.receipt_path),
        "sha256": file_fingerprint(subject.receipt_path)["sha256"],
    }
    assert source["generator"] == subject.lock["generator"]
    assert source["environment"] == subject.lock["environment"]
    assert source["dependencies"] == subject.manifest["dependencies"]
    assert source["output"] == subject.receipt["output"]


def test_prepare_passes_one_exact_decoded_candidate_request_to_injected_port(subject):
    _prepare(subject)
    assert len(subject.calls) == 1
    request = subject.calls[0]
    assert request == {
        "candidate": subject.candidate,
        "output_dir": subject.output,
        "candidate_contract": subject.contract,
        "sample_frames": [0, 5, 11],
        "transition_ranges": [{"startFrame": 4, "endFrameExclusive": 8}],
        "loop_requested": False,
    }


def test_validation_returns_existing_visual_qc_evidence_without_approval(subject):
    package = _prepare(subject)
    evidence = _validate(subject, package)
    assert evidence["kind"] == "visual-qc"
    assert evidence["status"] == "pending"
    assert evidence["candidateHash"] == package["candidate"]["sha256"]
    assert evidence["candidateIdentityHash"] == package["candidate"]["identityHash"]
    assert evidence["dependencyLockSha256"] == package["dependencyLockSha256"]
    reference = evidence["reviewContext"]["codeDrawnReview"]
    assert reference["path"] == package["packagePath"]
    assert reference["sha256"] == file_fingerprint(Path(reference["path"]))["sha256"]
    assert reference["reviewHash"] == package["reviewHash"]
    assert reference["approval"] is None
    assert evidence_is_fresh(
        evidence, package["candidate"]["sha256"], subject.dependencies
    )


@pytest.mark.parametrize(
    "kind", ["frame", "contact-sheet", "small-display", "transition-strip"]
)
def test_missing_required_preview_family_cannot_publish_complete_review(subject, kind):
    normal = _producer(subject)

    def incomplete(**request):
        result = normal(**request)
        result["artifacts"] = [
            item for item in result["artifacts"] if item["kind"] != kind
        ]
        return result

    with pytest.raises((MotionError, GateError)):
        _prepare(subject, producer=incomplete)
    assert not (subject.output / "code-drawn-review.json").exists()


def test_loop_review_is_conditional_and_never_claims_automatic_continuity(subject):
    package = _prepare(subject, loop_requested=True)
    assert package["loopRequested"] is True
    assert any(item["kind"] == "loop-strip" for item in package["artifacts"])
    assert package["state"] == "needs-human-judgment"
    assert package["approval"] is None
    assert subject.calls[0]["loop_requested"] is True


def test_nonloop_brief_has_no_loop_artifact_or_extra_requirement(subject):
    package = _prepare(subject)
    assert package["loopRequested"] is False
    assert not any(item["kind"] == "loop-strip" for item in package["artifacts"])
    assert _validate(subject, package)["status"] == "pending"


@pytest.mark.parametrize("frame", [-1, 12, True, 1.5])
def test_invalid_sample_frame_is_rejected_before_preview_generation(subject, frame):
    with pytest.raises((MotionError, GateError)):
        _prepare(subject, sample_frames=[frame])
    assert not subject.calls


def test_existing_review_destination_is_preserved(subject):
    subject.output.mkdir()
    sentinel = subject.output / "notes.md"
    sentinel.write_text("existing review", encoding="utf-8")
    with pytest.raises((MotionError, GateError)):
        _prepare(subject)
    assert sentinel.read_text(encoding="utf-8") == "existing review"
    assert not subject.calls


def test_candidate_change_during_preview_generation_prevents_package_publication(
    subject,
):
    normal = _producer(subject)

    def changed(**request):
        result = normal(**request)
        subject.candidate.write_bytes(b"changed during preview generation")
        return result

    with pytest.raises((MotionError, GateError)):
        _prepare(subject, producer=changed)
    assert not (subject.output / "code-drawn-review.json").exists()


@pytest.mark.parametrize(
    "target", ["candidate", "source", "lock", "receipt", "artifact"]
)
def test_review_rejects_changed_candidate_or_retained_evidence(subject, target):
    package = _prepare(subject)
    paths = {
        "candidate": subject.candidate,
        "source": subject.composition.parent / subject.manifest["entry"],
        "lock": subject.lock_path,
        "receipt": subject.receipt_path,
        "artifact": Path(package["artifacts"][0]["path"]),
    }
    paths[target].write_bytes(b"changed after review preparation")
    with pytest.raises((GateError, MotionError)):
        _validate(subject, package)


def test_dependency_change_stales_review_even_when_candidate_bytes_match(subject):
    package = _prepare(subject)
    changed = {**subject.dependencies, "animation": "f" * 64}
    with pytest.raises((GateError, MotionError)):
        _validate(subject, package, dependencies=changed)


@pytest.mark.parametrize(
    "field",
    [
        "engine",
        "drawingRoute",
        "sourceRevision",
        "manifestRef",
        "inputLockRef",
        "environment",
        "generator",
        "dependencies",
        "outputVerification",
    ],
)
def test_resealed_package_cannot_omit_required_source_delivery_identity(subject, field):
    package = _prepare(subject)
    package["sources"][0].pop(field)
    with pytest.raises((GateError, MotionError)):
        _validate(subject, _reseal(package))


def test_generated_receipt_or_self_score_never_becomes_creator_approval(subject):
    normal = _producer(subject)

    def scored(**request):
        return {
            **normal(**request),
            "status": "pass",
            "score": 10,
            "approval": {"decision": "approved", "actor": "agent"},
        }

    package = _prepare(subject, producer=scored)
    assert package["approval"] is None
    assert package["state"] == "needs-human-judgment"
    assert _validate(subject, package)["status"] == "pending"
    package["approval"] = {"decision": "approved", "actor": "agent"}
    with pytest.raises((GateError, MotionError)):
        _validate(subject, _reseal(package))


def test_open_finding_retains_exact_range_and_requires_existing_human_review(subject):
    normal = _producer(subject)

    def findings(**request):
        result = normal(**request)
        result["findings"] = [_entry(subject, result)]
        return result

    package = _prepare(subject, producer=findings)
    evidence = _validate(subject, package)
    assert package["findings"][0]["candidateSha256"] == package["candidate"]["sha256"]
    assert evidence["findings"][0]["programRange"] == {
        "startFrame": 5,
        "endFrameExclusive": 6,
    }
    assert evidence["status"] == "pending"
    assert package["approval"] is None


def test_resolved_finding_retains_fix_and_current_recheck_without_granting_approval(
    subject,
):
    normal = _producer(subject)

    def resolved(**request):
        result = normal(**request)
        result["findings"] = [_entry(subject, result, status="resolved")]
        return result

    package = _prepare(subject, producer=resolved)
    evidence = _validate(subject, package)
    assert evidence["findings"][0]["status"] == "resolved"
    assert evidence["fixRevisionRefs"] == ["animation-r0002"]
    assert package["approval"] is None


@pytest.mark.parametrize(
    "mutation",
    [
        "old-candidate",
        "recheck-candidate",
        "recheck-dependencies",
        "recheck-before-fix",
        "range-mismatch",
        "no-recheck",
        "missing-evidence",
        "failed-recheck",
    ],
)
def test_finding_recheck_must_cover_current_candidate_after_the_recorded_fix(
    subject, mutation
):
    normal = _producer(subject)

    def resolved(**request):
        result = normal(**request)
        result["findings"] = [_entry(subject, result, status="resolved")]
        return result

    package = _prepare(subject, producer=resolved)
    entry = package["findings"][0]
    if mutation == "old-candidate":
        entry["candidateSha256"] = "e" * 64
        entry.pop("recheck")
    elif mutation == "recheck-candidate":
        entry["recheck"]["candidateSha256"] = "e" * 64
    elif mutation == "recheck-dependencies":
        entry["recheck"]["dependencyLockSha256"] = "e" * 64
    elif mutation == "recheck-before-fix":
        entry["recheck"]["observedAt"] = "2026-10-26T11:00:00Z"
    elif mutation == "range-mismatch":
        entry["recheck"]["programRange"] = {"startFrame": 0, "endFrameExclusive": 1}
    elif mutation == "no-recheck":
        entry.pop("recheck")
    elif mutation == "failed-recheck":
        entry["recheck"]["status"] = "fail"
    else:
        entry["recheck"]["evidenceRefs"] = []
    with pytest.raises((GateError, MotionError)):
        _validate(subject, _reseal(package))


@pytest.fixture
def delivery_case(subject, monkeypatch):
    from avo.timeline import delivery
    from tests.test_delivery_adoption import adoption as adoption_fixture

    copy_master = delivery._copy_verified_master
    data = adoption_fixture.__wrapped__(subject.root, monkeypatch)
    monkeypatch.setattr(delivery, "_copy_verified_master", copy_master)
    subject.candidate = data.master
    source_dependencies = {
        key: value
        for key, value in subject.dependencies.items()
        if key.startswith(("generated:", "input-lock:"))
    }
    subject.dependencies = {**data.kwargs["dependencies"], **source_dependencies}
    subject.render_profile = "master"
    package = _prepare(subject)
    master = subject.root / "edit" / "masters" / "motion-final.mp4"
    runs = []

    class Runner:
        state = "ai-passed"

        def run(self, **request):
            runs.append(request)
            value = copy.deepcopy(data.review)
            value["candidate"] = candidate_identity(
                request["candidate"], request["dependencies"], request["render_profile"]
            )
            value["dependencyLockSha256"] = dependency_lock_hash(
                request["dependencies"]
            )
            value["state"] = self.state
            for evidence in value["evidence"]:
                evidence["candidateHash"] = value["candidate"]["sha256"]
                evidence["candidateIdentityHash"] = value["candidate"]["identityHash"]
                evidence["dependencyHashes"] = request["dependencies"]
                evidence["dependencyLockSha256"] = value["dependencyLockSha256"]
            data.review_path.write_text(json.dumps(value), encoding="utf-8")
            return {**value, "reviewPath": data.review_path}

    def transcript(candidate, _edit, **_options):
        payload = json.loads(data.sidecars["json"].read_text(encoding="utf-8"))
        payload["source"]["path"] = str(candidate)
        data.sidecars["json"].write_text(json.dumps(payload), encoding="utf-8")
        return data.sidecars

    runner = Runner()
    return SimpleNamespace(
        data=data,
        package=package,
        master=master,
        runner=runner,
        runs=runs,
        kwargs={
            "candidate": subject.candidate,
            "master": master,
            "dependencies": subject.dependencies,
            "materialization": data.kwargs["materialization"],
            "materialization_path": data.kwargs["materialization_path"],
            "review_runner": runner,
            "transcript_generator": transcript,
            "motion_review": package,
        },
    )


def test_delivery_adds_bound_motion_identity_without_skipping_final_review_or_approval(
    delivery_case,
):
    case = delivery_case
    manifest = case.data.service.prepare(**case.kwargs)
    assert manifest["motion"]["engine"] == "code-drawn"
    assert manifest["motion"]["sources"] == case.package["sources"]
    assert manifest["motion"]["output"] == case.package["candidateContract"]
    assert manifest["motion"]["review"]["reviewHash"] == case.package["reviewHash"]
    assert manifest["approval"] is None
    assert manifest["state"] == "review-ready"
    assert len(case.runs) == 1
    assert case.runs[0]["checkpoint"] == "deliver"
    assert case.runs[0]["candidate"] == case.master
    assert manifest["review"]["state"] == "ai-passed"


def test_stale_motion_review_blocks_delivery_before_copying_a_master(delivery_case):
    from avo.timeline.delivery import DeliveryError

    case = delivery_case
    Path(case.package["artifacts"][0]["path"]).write_bytes(b"stale preview")
    with pytest.raises(DeliveryError, match="(?i)motion|code.drawn|review|artifact"):
        case.data.service.prepare(**case.kwargs)
    assert not case.master.exists()
    assert not case.data.service.manifest_path.exists()


def test_motion_review_and_receipt_cannot_replace_required_final_review(delivery_case):
    from avo.timeline.delivery import DeliveryError

    case = delivery_case
    case.runner.state = "blocked"
    with pytest.raises(DeliveryError, match="review"):
        case.data.service.prepare(**case.kwargs)
    assert case.runs
    assert not case.data.service.manifest_path.exists()


@pytest.fixture
def native_delivery_case(delivery_case, subject, monkeypatch):
    """Synthetic persisted native record; native authority is an injected boundary."""
    from avo.timeline import approval_service

    case = delivery_case
    old = case.kwargs["materialization"]
    body = {
        "schemaVersion": "1.0.0",
        "kind": "proof-plan",
        "checkpoint": "pre-master",
        "materializationId": "proof-build-unit",
        "proofPlanId": "proof-plan-" + "a" * 12,
        "proofPlanHash": old["proofPlanHash"],
        "preflightHash": "e" * 64,
        "microproofGateHash": "f" * 64,
        "canonicalInputLock": {
            **copy.deepcopy(old["canonicalInputLock"]),
            "source:camera": "3" * 64,
            **{
                k: v
                for k, v in subject.dependencies.items()
                if k.startswith(("generated:", "input-lock:"))
            },
        },
        "renderProfile": "master",
        "output": copy.deepcopy(old["output"]),
        "producer": {"adapterId": "unit-native-proof"},
        "createdAt": "2026-10-26T12:00:00Z",
    }
    record = {**body, "materializationHash": content_hash(body)}
    record_path = case.kwargs["materialization_path"]
    record_path.write_text(json.dumps(record), encoding="utf-8")
    dependencies = {
        **body["canonicalInputLock"],
        "raw": content_hash({"source:camera": "3" * 64}),
        **{
            k: v
            for k, v in subject.dependencies.items()
            if k.startswith(("generated:", "input-lock:"))
        },
        "proof-plan": record["proofPlanHash"],
        "materialization": record["materializationHash"],
        "microproof-gate": record["microproofGateHash"],
        "preflight": record["preflightHash"],
        "assembly-output": record["output"]["sha256"],
    }
    case.data.snapshot["materialization"]["sha256"] = record["materializationHash"]
    case.data.snapshot["proofPlan"]["sha256"] = record["proofPlanHash"]
    subject.dependencies = dependencies
    subject.output = subject.root / "native-review-v001"
    case.package = _prepare(subject)
    case.kwargs.update(
        materialization=record, dependencies=dependencies, motion_review=case.package
    )
    validations = []

    def verify(workspace, materialization, candidate):
        validations.append((workspace, materialization, candidate))
        assert materialization == record
        assert Path(candidate) == subject.candidate
        return dependencies

    monkeypatch.setattr(
        approval_service, "require_native_proof_materialization", verify, raising=False
    )
    case.validations = validations
    return case


def test_native_proof_delivery_uses_current_native_authority_and_motion_metadata(
    native_delivery_case,
):
    case = native_delivery_case
    manifest = case.data.service.prepare(**case.kwargs)
    assert case.validations
    assert manifest["dependencies"] == case.kwargs["dependencies"]
    assert manifest["materialization"]["kind"] == "proof-plan"
    assert (
        manifest["materialization"]["proofPlanHash"]
        == case.kwargs["materialization"]["proofPlanHash"]
    )
    assert manifest["motion"]["sources"] == case.package["sources"]
    assert manifest["candidateSnapshot"]["sha256"] == case.data.snapshot["snapshotHash"]
    assert manifest["approval"] is None
    assert len(case.runs) == 1


def test_native_proof_delivery_cannot_bypass_stale_native_sources_or_microproofs(
    native_delivery_case,
    monkeypatch,
):
    from avo.timeline import approval_service
    from avo.timeline.delivery import DeliveryError

    case = native_delivery_case

    def reject(*_args):
        raise ValueError("current source or microproof gate is stale")

    monkeypatch.setattr(
        approval_service, "require_native_proof_materialization", reject
    )
    with pytest.raises(DeliveryError, match="source|microproof"):
        case.data.service.prepare(**case.kwargs)
    assert not case.master.exists()


@pytest.mark.parametrize(
    "mutation", ["missing", "materialization", "proof-plan", "approval"]
)
def test_native_proof_delivery_requires_exact_approved_candidate_snapshot(
    native_delivery_case,
    mutation,
    monkeypatch,
):
    from avo.timeline.delivery import DeliveryError

    case = native_delivery_case
    if mutation == "missing":
        monkeypatch.setattr(
            "avo.timeline.pipeline.TimelinePipeline.active_candidate_snapshot",
            lambda _self: None,
        )
    elif mutation in {"materialization", "proof-plan"}:
        key = "proofPlan" if mutation == "proof-plan" else mutation
        case.data.snapshot[key]["sha256"] = "0" * 64
    else:
        case.data.snapshot["approval"] = None
    with pytest.raises(DeliveryError, match="snapshot|candidate"):
        case.data.service.prepare(**case.kwargs)
    assert not case.master.exists()


@pytest.fixture
def native_plan_materialization(tmp_path, monkeypatch):
    """Real plan/store/preflight/gate services with a synthetic media encoder."""
    from avo.timeline import materialize
    from avo.timeline.contracts import document_hash_excluding
    from tests.test_proof_preflight import _plan_fixture

    workspace, compiler, plan, source = _plan_fixture(tmp_path)
    workspace.active_dependency_snapshot = lambda: {
        name: store.head_hash() for name, store in workspace.stores.items()
    }
    inputs = {"camera": source}
    readiness = {"proof-plan-executor": True, "ffmpeg": True}
    monkeypatch.setattr(
        materialize, "canonical_proof_media_inputs", lambda _workspace, _plan: inputs
    )
    monkeypatch.setattr(
        materialize, "default_proof_readiness", lambda _plan, **_kwargs: readiness
    )

    class Encoder:
        def proof_tool_readiness(self, _plan):
            return readiness

        def render_proof_plan(self, _plan, output, *, window):
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(b"synthetic native picture/audio encoder fixture")
            return {"output": file_fingerprint(output), "graphHash": "a" * 64}

    gate = materialize.render_proof_microproofs(
        workspace=workspace, proof_plan=plan, media_inputs=inputs, render_port=Encoder()
    )
    result = materialize.materialize_proof_plan(
        workspace=workspace,
        proof_plan=plan,
        microproof_gate=gate,
        media_inputs=inputs,
        render_port=Encoder(),
    )
    path = Path(result.pop("path"))
    assert result["materializationHash"] == document_hash_excluding(
        result, "materializationHash"
    )
    return SimpleNamespace(
        workspace=workspace,
        compiler=compiler,
        plan=plan,
        source=source,
        gate=gate,
        record=result,
        path=path,
    )


def test_noncut_native_authority_checks_real_plan_source_and_gate(
    native_plan_materialization,
):
    from avo.timeline.approval_service import (
        native_proof_dependencies,
        require_native_proof_materialization,
    )

    case = native_plan_materialization
    dependencies = require_native_proof_materialization(
        case.workspace, case.record, Path(case.plan["output"]["path"])
    )
    assert dependencies == native_proof_dependencies(case.record)
    assert dependencies["microproof-gate"] == case.gate["gateHash"]
    assert dependencies["assembly-output"] == case.record["output"]["sha256"]
    assert dependencies["source:camera"] == file_fingerprint(case.source)["sha256"]


@pytest.mark.parametrize("mutation", ["source", "gate", "record-plan"])
def test_noncut_native_authority_rejects_resealed_stale_inputs(
    native_plan_materialization,
    mutation,
):
    from avo.timeline.approval_service import require_native_proof_materialization

    case = native_plan_materialization
    if mutation == "source":
        case.source.write_bytes(b"changed original")
    elif mutation == "gate":
        gate = copy.deepcopy(case.gate)
        path = Path(gate.pop("path"))
        gate["status"] = "fail"
        gate["gateHash"] = content_hash(
            {k: v for k, v in gate.items() if k != "gateHash"}
        )
        path.write_text(json.dumps(gate), encoding="utf-8")
    else:
        case.record["proofPlanHash"] = "0" * 64
        case.record["materializationHash"] = content_hash(
            {k: v for k, v in case.record.items() if k != "materializationHash"}
        )
    with pytest.raises((ValueError, RuntimeError)):
        require_native_proof_materialization(
            case.workspace, case.record, Path(case.plan["output"]["path"])
        )


def test_native_candidate_approval_reuses_exact_native_lineage(
    native_plan_materialization,
):
    from avo.timeline.approval_service import (
        _candidate_materialization,
        native_proof_dependencies,
    )

    case = native_plan_materialization
    candidate = Path(case.plan["output"]["path"])
    dependencies = native_proof_dependencies(case.record)
    review_record = {"candidate": candidate_identity(candidate, dependencies, "master")}
    actual, fingerprint = _candidate_materialization(
        case.workspace, review_record, case.record
    )
    assert actual == candidate.resolve()
    assert fingerprint == file_fingerprint(candidate)


def test_native_candidate_approval_rejects_added_unfrozen_motion_identity(
    native_plan_materialization,
):
    from avo.timeline.approval_service import (
        _candidate_materialization,
        native_proof_dependencies,
    )

    case = native_plan_materialization
    candidate = Path(case.plan["output"]["path"])
    dependencies = {
        **native_proof_dependencies(case.record),
        "generated:unused": "a" * 64,
    }
    review_record = {"candidate": candidate_identity(candidate, dependencies, "master")}
    with pytest.raises(ValueError, match="dependenc"):
        _candidate_materialization(case.workspace, review_record, case.record)


def test_native_delivery_rejects_motion_sources_absent_from_its_frozen_plan(
    native_delivery_case,
    subject,
):
    from avo.timeline.delivery import DeliveryError

    case = native_delivery_case
    record = case.kwargs["materialization"]
    for key in list(record["canonicalInputLock"]):
        if key.startswith(("generated:", "input-lock:")):
            record["canonicalInputLock"].pop(key)
    record["materializationHash"] = content_hash(
        {k: v for k, v in record.items() if k != "materializationHash"}
    )
    case.kwargs["materialization_path"].write_text(json.dumps(record), encoding="utf-8")
    case.kwargs["dependencies"]["materialization"] = record["materializationHash"]
    case.data.snapshot["materialization"]["sha256"] = record["materializationHash"]
    subject.output = subject.root / "unused-drawing-review"
    case.kwargs["motion_review"] = _prepare(subject)
    with pytest.raises(DeliveryError, match="motion.*source|input lock"):
        case.data.service.prepare(**case.kwargs)
    assert not case.master.exists()
