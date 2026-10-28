"""The native batch routes original picture, graphics alpha and independent audio."""

from pathlib import Path
from unittest.mock import patch

import pytest

from avo import shorts, shorts_contract, shorts_delivery, shorts_fidelity, shorts_qc
from avo.adapters.base import JobResult
from avo.adapters.motion.hyperframes import _ratio_lock_markup


def test_batch_fidelity_uses_original_picture_and_graphics_only(tmp_path):
    source = tmp_path / "camera.mp4"
    source.write_bytes(b"original")
    voice = tmp_path / "voice.wav"
    voice.write_bytes(b"voice")
    work = tmp_path / "work"
    work.mkdir()
    output = work / "candidate.mp4"
    item = {
        "layout": {"mode": "full-frame"},
        "sourceSegments": [{"startSec": 3, "endSec": 5, "sourceFingerprint": "a" * 64}],
        "inputFingerprint": "b" * 64,
        "speed": 1,
    }
    spec = {
        "assets": {
            "dialogueAudio": {"path": str(voice), "hash": "c" * 64, "durationSec": 2}
        }
    }
    seen = {}

    def compile_overlay(value, path):
        seen["spec"] = value
        return path

    class Adapter:
        def execute(self, action, project, *args, **kwargs):
            destination = Path(args[args.index("--output") + 1])
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(b"alpha")
            return JobResult(exit_code=0)

    def mix(prepared, selected, path, **kwargs):
        assert selected is item
        assert kwargs["channels"] == 1
        assert prepared["dialogueAudio"]["path"] == str(voice)
        return {"path": str(voice), "sha256": "c" * 64}

    def render(original, destination, **kwargs):
        seen["original"] = original
        seen["render"] = kwargs
        return {
            "path": str(destination),
            "canonicalInputLock": kwargs["canonical_lock"],
        }

    with (
        patch.object(shorts, "compile_project", side_effect=compile_overlay),
        patch("avo.shorts_fidelity_audio.mix_short_audio", side_effect=mix),
        patch(
            "avo.shorts_fidelity.build_microproofs",
            return_value={"sha256": "e" * 64},
            create=True,
        ),
        patch("avo.shorts_fidelity.render_fidelity", side_effect=render),
    ):
        shorts._render_source_fidelity(
            {"planHash": "d" * 64},
            item,
            source,
            {
                "width": 720,
                "height": 1280,
                "fps": 30000 / 1001,
                "frameRateRational": "30000/1001",
                "audioChannels": 1,
                "preview": True,
            },
            spec,
            work,
            output,
            Adapter(),
        )
    assert seen["spec"]["renderLayers"] == "graphics-only"
    assert seen["original"] == source
    assert seen["render"]["fps"] == "30000/1001"
    assert seen["render"]["mixed_audio_path"] == voice
    assert (work / "source-fidelity.json").is_file()


def test_qc_rejects_silent_fidelity_and_channel_downgrades():
    probe = {
        "streams": [
            {
                "codec_type": "video",
                "width": 720,
                "height": 1280,
                "pix_fmt": "yuv420p",
                "r_frame_rate": "30/1",
            },
            {"codec_type": "audio", "channels": 2, "sample_rate": "44100"},
        ],
        "format": {"duration": 2},
    }
    findings = shorts_qc.evaluate_probe(
        probe,
        {
            "width": 720,
            "height": 1280,
            "durationSec": 2,
            "pixelFormat": "yuv420p10le",
            "frameRateRational": "30000/1001",
            "colorSpace": "bt709",
            "audioSampleRateHz": 48000,
            "audioChannels": 1,
        },
    )
    assert {row["code"] for row in findings} == {
        "wrong-pixel-format",
        "wrong-frame-rate",
        "wrong-color-space",
        "wrong-audio-rate",
        "wrong-audio-channels",
    }


def test_ratio_comparison_changes_geometry_as_well_as_its_label():
    common = {"id": "ratio", "widget": "ratio-lock", "corner": "bl"}
    narrow = _ratio_lock_markup({**common, "params": {"ratio": "4:3"}})
    wide = _ratio_lock_markup({**common, "params": {"ratio": "16:9"}})
    assert "aspect-ratio:4/3" in narrow
    assert "aspect-ratio:16/9" in wide
    assert "height:auto" in narrow and "height:auto" in wide


def test_preview_cannot_be_copied_into_a_source_resolution_master():
    with pytest.raises(shorts_delivery.DeliveryError, match="preview"):
        shorts_delivery._require_delivery_profile(
            {"output": {"width": 1728, "height": 3072}},
            {
                "shortId": "01",
                "renderProfile": {"preview": True, "width": 720, "height": 1280},
            },
        )


def _fidelity_status(tmp_path):
    proof = tmp_path / "proof.mp4"
    proof.write_bytes(b"proof")
    implementations = shorts._fidelity_implementation_hashes()
    implementations["implementation:registered-source-fidelity"] = (
        shorts_fidelity.registered_implementation()["sha256"]
    )
    report = {
        "path": str(proof),
        "sha256": shorts.shorts_media.sha256_file(proof),
        "canonicalInputLock": implementations,
        "implementationRef": {
            "sha256": implementations["implementation:registered-source-fidelity"]
        },
    }
    report_path = tmp_path / "source-fidelity.json"
    shorts_contract.atomic_write_json(report_path, report)
    row = {
        "shortId": "01",
        "proofArtifactRevision": 1,
        "proofRevision": 1,
        "dirty": False,
        "dirtyReasons": [],
        "artifacts": [
            shorts._artifact("proof", proof, 1),
            shorts._artifact("source-fidelity", report_path, 1),
        ],
    }
    return {"items": [row]}, report, report_path


def test_unchanged_fidelity_proof_is_not_marked_dirty(tmp_path):
    status, _, _ = _fidelity_status(tmp_path)
    shorts._mark_stale_fidelity_proofs(
        {"output": {"pixelFormat": "yuv420p10le"}}, status
    )
    assert status["items"][0]["dirty"] is False
    assert status["items"][0]["dirtyReasons"] == []


@pytest.mark.parametrize(
    "changed",
    [
        "implementation:shorts.py",
        "implementation:shorts_fidelity.py",
        "implementation:shorts_fidelity_audio.py",
        "implementation:registered-source-fidelity",
    ],
)
def test_changed_declared_implementation_marks_fidelity_dirty(tmp_path, changed):
    status, report, path = _fidelity_status(tmp_path)
    report["canonicalInputLock"][changed] = "0" * 64
    shorts_contract.atomic_write_json(path, report)
    status["items"][0]["artifacts"][-1] = shorts._artifact("source-fidelity", path, 1)
    plan = {"output": {"pixelFormat": "yuv420p10le"}}
    shorts._mark_stale_fidelity_proofs(plan, status)
    shorts._mark_stale_fidelity_proofs(plan, status)
    assert status["items"][0]["dirty"] is True
    assert status["items"][0]["dirtyReasons"] == ["render-implementation-changed"]


@pytest.mark.parametrize(
    "invalid", ["report-bytes", "missing-report", "proof-bytes", "registered-ref"]
)
def test_invalid_fidelity_artifact_marks_dirty(tmp_path, invalid):
    status, report, path = _fidelity_status(tmp_path)
    if invalid == "report-bytes":
        path.write_text("{}", encoding="utf-8")
    elif invalid == "missing-report":
        status["items"][0]["artifacts"].pop()
    elif invalid == "proof-bytes":
        Path(report["path"]).write_bytes(b"corrupted")
    else:
        report["implementationRef"]["sha256"] = "0" * 64
        shorts_contract.atomic_write_json(path, report)
        status["items"][0]["artifacts"][-1] = shorts._artifact(
            "source-fidelity", path, 1
        )
    shorts._mark_stale_fidelity_proofs(
        {"output": {"pixelFormat": "yuv420p10le"}}, status
    )
    assert status["items"][0]["dirtyReasons"] == ["render-implementation-changed"]


def test_eight_bit_route_does_not_require_fidelity_reports():
    status = {
        "items": [{"proofArtifactRevision": 1, "dirty": False, "dirtyReasons": []}]
    }
    shorts._mark_stale_fidelity_proofs({"output": {"pixelFormat": "yuv420p"}}, status)
    assert status["items"][0]["dirty"] is False


def _code_drawn_fidelity_context(tmp_path, *, caption_plan_hash=None):
    from copy import deepcopy

    from avo.timeline.contracts import content_hash, file_fingerprint
    from avo.timeline.generated_assets import GeneratedAssetService
    from tests.code_drawn_asset_fixture import canonical_asset

    if caption_plan_hash is None:
        asset = canonical_asset(tmp_path)
    else:
        from tests import code_drawn_asset_fixture

        write = code_drawn_asset_fixture.write_manifest

        def declared_manifest(path, value):
            value = deepcopy(value)
            value["extensions"] = {"shortsCaptionPlanHash": caption_plan_hash}
            write(path, value)

        with patch.object(
            code_drawn_asset_fixture, "write_manifest", side_effect=declared_manifest
        ):
            asset = canonical_asset(tmp_path)
    workspace = asset.workspace
    service = GeneratedAssetService(workspace)
    receipt = service.register(asset.record, code_drawn_environment=asset.environment)
    voice = workspace.raw_dir / "prepared-voice.wav"
    voice.write_bytes(b"unit-transport-existing-canonical-audio")
    source = workspace.raw_dir / "raw.bin"
    item = {
        "layout": {"mode": "full-frame"},
        "sourceSegments": [
            {
                "startSec": 0.1,
                "endSec": 0.4,
                "sourceFingerprint": file_fingerprint(source)["sha256"],
            }
        ],
        "inputFingerprint": content_hash("bound-short"),
        "speed": 1,
        "editedDurationSec": 0.3,
    }
    spec = {
        "motionEngine": "code-drawn",
        "codeDrawn": {
            **deepcopy(asset.reference),
            "inputLockRef": deepcopy(
                receipt["parameters"]["codeDrawn"]["inputLockRef"]
            ),
            "generatedAssetRef": {
                "assetId": receipt["assetId"],
                "recordHash": receipt["recordHash"],
                "locator": str(service.path(receipt["assetId"])),
            },
        },
        "assets": {
            "dialogueAudio": {
                "path": str(voice),
                "hash": file_fingerprint(voice)["sha256"],
                "durationSec": 0.3,
            }
        },
    }
    return workspace, source, voice, item, spec, receipt


def test_code_drawn_shorts_transport_uses_admitted_alpha_without_hyperframes(
    tmp_path, monkeypatch
):
    from avo.timeline.contracts import content_hash, file_fingerprint
    from avo.timeline.generated_assets import GeneratedAssetService

    workspace, source, voice, item, spec, receipt = _code_drawn_fidelity_context(
        tmp_path
    )
    seen = {}

    def admit(service, asset_id, **kwargs):
        assert service.workspace is workspace
        assert asset_id == receipt["assetId"]
        assert kwargs, (
            "Code-drawn admission must receive current freshness observations."
        )
        seen["admission"] = kwargs
        return receipt

    def forbidden(*args, **kwargs):
        pytest.fail("Bound code-drawn Shorts invoked a HyperFrames compile or render.")

    class NoFrameworkAdapter:
        execute = forbidden
        render = forbidden

    def render(original, destination, **kwargs):
        seen["source"] = original
        seen["render"] = kwargs
        return {
            "path": str(destination),
            "canonicalInputLock": kwargs["canonical_lock"],
        }

    from tests.code_drawn_asset_fixture import synthetic_environment

    def observe(composition, **kwargs):
        seen["observedComposition"] = composition
        return synthetic_environment()

    monkeypatch.setattr("avo.proof_composition.observe_code_drawn_environment", observe)
    monkeypatch.setattr(GeneratedAssetService, "admit", admit)
    monkeypatch.setattr(shorts, "compile_project", forbidden, raising=False)
    monkeypatch.setattr(
        "avo.shorts_fidelity_audio.mix_short_audio",
        lambda *a, **k: {
            "path": str(voice),
            "sha256": file_fingerprint(voice)["sha256"],
        },
    )
    monkeypatch.setattr(
        shorts_fidelity,
        "build_microproofs",
        lambda *a, **k: {"sha256": content_hash("microproof")},
    )
    monkeypatch.setattr(shorts_fidelity, "render_fidelity", render)
    work = workspace.raw_dir / "short-work"
    work.mkdir()
    shorts._render_source_fidelity(
        {"planHash": content_hash("plan")},
        item,
        source,
        {
            "width": 128,
            "height": 96,
            "fps": 30,
            "frameRateRational": "30/1",
            "audioChannels": 2,
            "preview": True,
        },
        spec,
        work,
        work / "candidate.mp4",
        NoFrameworkAdapter(),
        workspace=workspace,
    )
    assert seen["admission"] == {"code_drawn_environment": synthetic_environment()}
    assert seen["observedComposition"].name == "composition.json"
    assert seen["source"] == source
    assert seen["render"]["overlay_path"] == Path(receipt["output"]["locator"])
    assert seen["render"]["overlay_sha256"] == receipt["output"]["sha256"]
    assert seen["render"]["mixed_audio_path"] == voice
    assert seen["render"]["fps"] == "30/1"


def test_code_drawn_shorts_requires_real_canonical_context_before_media_work(
    tmp_path, monkeypatch
):
    def forbidden(*args, **kwargs):
        pytest.fail("An unbound request reached media work.")

    monkeypatch.setattr(shorts, "compile_project", forbidden, raising=False)
    monkeypatch.setattr("avo.shorts_fidelity_audio.mix_short_audio", forbidden)
    with pytest.raises(RuntimeError, match="canonical|workspace|context"):
        shorts._render_source_fidelity(
            {"planHash": "a" * 64},
            {
                "layout": {"mode": "full-frame"},
                "sourceSegments": [
                    {"startSec": 0, "endSec": 1, "sourceFingerprint": "b" * 64}
                ],
                "speed": 1,
            },
            tmp_path / "source.mkv",
            {"width": 128, "height": 96, "fps": 30},
            {"motionEngine": "code-drawn", "codeDrawn": {}, "assets": {}},
            tmp_path,
            tmp_path / "candidate.mp4",
            object(),
        )
    assert not (tmp_path / "candidate.mp4").exists()


def test_unported_shorts_style_cannot_trigger_implicit_hyperframes_generation(
    tmp_path, monkeypatch
):
    def forbidden(*args, **kwargs):
        pytest.fail("Unsupported style reached a HyperFrames loader.")

    monkeypatch.setattr(shorts, "compile_project", forbidden, raising=False)
    with pytest.raises(
        RuntimeError, match="code-drawn|bound|unsupported|capability|context"
    ):
        shorts._render_graphics_alpha(
            {
                "motionEngine": "code-drawn",
                "assets": {},
                "captions": [],
                "identity": "embedded",
            },
            tmp_path,
            tmp_path / "alpha.webm",
            "30/1",
            object(),
        )
    assert not (tmp_path / "alpha.webm").exists()


@pytest.mark.parametrize("declared", [None, "0" * 64])
def test_code_drawn_captions_require_exact_authored_plan_before_observation(
    tmp_path, monkeypatch, declared
):
    from avo import shorts_motion

    workspace, _, _, item, spec, _ = _code_drawn_fidelity_context(
        tmp_path, caption_plan_hash=declared
    )
    spec["captions"] = [
        {"id": "caption-one", "text": "Source meaning", "startSec": 0, "endSec": 0.3}
    ]

    def forbidden(*args, **kwargs):
        pytest.fail("Undeclared captions reached a browser or audio operation")

    monkeypatch.setattr(
        "avo.proof_composition.observe_code_drawn_environment", forbidden
    )
    with pytest.raises(RuntimeError, match="caption.*plan|caption.*source"):
        shorts_motion.admitted_alpha(
            spec, workspace, item, {"width": 128, "height": 96, "fps": 30}
        )


def test_code_drawn_declared_caption_plan_is_bound_but_requires_visual_review(tmp_path):
    from avo import shorts_motion

    captions = [
        {"id": "caption-one", "text": "Source meaning", "startSec": 0, "endSec": 0.3}
    ]
    workspace, _, _, item, spec, receipt = _code_drawn_fidelity_context(
        tmp_path, caption_plan_hash=shorts_contract.content_hash(captions)
    )
    spec["captions"] = captions
    _, actual, _ = shorts_motion.preflight_alpha(
        spec, workspace, item, {"width": 128, "height": 96, "fps": 30}
    )
    assert actual["recordHash"] == receipt["recordHash"]
    assert "semanticReview" not in actual


@pytest.mark.parametrize(
    "changed", ["range", "speed", "size", "rate", "duration", "noncontiguous"]
)
def test_code_drawn_short_contract_mismatch_blocks_before_current_observation(
    tmp_path, monkeypatch, changed
):
    from copy import deepcopy

    from avo import shorts_motion

    workspace, _, _, item, spec, _ = _code_drawn_fidelity_context(tmp_path)
    output = {"width": 128, "height": 96, "fps": 30, "frameRateRational": "30/1"}
    if changed == "range":
        item["sourceSegments"][0]["startSec"] = 0.2
    elif changed == "speed":
        item["speed"] = 1.25
    elif changed == "size":
        output["width"] = 256
    elif changed == "rate":
        output["fps"], output["frameRateRational"] = 60, "60/1"
    elif changed == "duration":
        item["editedDurationSec"] = 0.6
    else:
        item["sourceSegments"].append(deepcopy(item["sourceSegments"][0]))

    def forbidden(*args, **kwargs):
        pytest.fail("Incompatible selected content reached current browser observation")

    monkeypatch.setattr(
        "avo.proof_composition.observe_code_drawn_environment", forbidden
    )
    with pytest.raises(RuntimeError, match="code-drawn"):
        shorts_motion.admitted_alpha(spec, workspace, item, output)


def test_code_drawn_source_changed_during_fidelity_cannot_publish_report(
    tmp_path, monkeypatch
):
    from avo import motion
    from tests.code_drawn_asset_fixture import synthetic_environment

    workspace, source, voice, item, spec, _ = _code_drawn_fidelity_context(tmp_path)
    manifest_path = workspace.raw_dir / spec["codeDrawn"]["manifestRef"]["path"]
    manifest = motion.load_composition(manifest_path)
    entry = manifest_path.parent / manifest["entry"]
    work = workspace.raw_dir / "fidelity-attempt"
    work.mkdir()
    monkeypatch.setattr(
        "avo.proof_composition.observe_code_drawn_environment",
        lambda _, **kwargs: synthetic_environment(),
    )
    monkeypatch.setattr(
        "avo.shorts_fidelity_audio.mix_short_audio",
        lambda *a, **k: {
            "path": str(voice),
            "sha256": shorts.shorts_media.sha256_file(voice),
        },
    )
    monkeypatch.setattr(
        shorts_fidelity, "build_microproofs", lambda *a, **k: {"sha256": "e" * 64}
    )

    def render(original, destination, **kwargs):
        entry.write_bytes(entry.read_bytes() + b"\n<!-- changed while encoding -->")
        return {
            "path": str(destination),
            "canonicalInputLock": kwargs["canonical_lock"],
        }

    monkeypatch.setattr(shorts_fidelity, "render_fidelity", render)
    with pytest.raises(motion.MotionError, match="fingerprint|changed"):
        shorts._render_source_fidelity(
            {"planHash": "d" * 64},
            item,
            source,
            {"width": 128, "height": 96, "fps": 30},
            spec,
            work,
            work / "proof.mp4",
            None,
            workspace=workspace,
        )
    assert not (work / "source-fidelity.json").exists()


def test_code_drawn_fidelity_reuse_requires_current_observed_browser_environment(
    tmp_path, monkeypatch
):
    from types import SimpleNamespace

    from avo import shorts_motion
    from tests.code_drawn_asset_fixture import synthetic_environment

    workspace, _, _, item, spec, receipt = _code_drawn_fidelity_context(tmp_path)
    item.update(id="01", **shorts_motion.pinned_fields(spec))
    output = {"width": 128, "height": 96, "fps": 30, "pixelFormat": "yuv420p10le"}
    plan = {"items": [item], "output": output}
    paths = SimpleNamespace(raw_dir=workspace.raw_dir)
    observed = synthetic_environment()
    monkeypatch.setattr(
        "avo.proof_composition.observe_code_drawn_environment",
        lambda _, **kwargs: dict(observed),
    )
    implementations = shorts._current_fidelity_implementations(plan, item, paths)
    proof = workspace.raw_dir / "short-proof.mp4"
    proof.write_bytes(b"synthetic unit proof")
    report = {
        "path": str(proof),
        "sha256": shorts.shorts_media.sha256_file(proof),
        "canonicalInputLock": implementations,
        "implementationRef": {
            "sha256": implementations["implementation:registered-source-fidelity"]
        },
    }
    report_path = workspace.raw_dir / "source-fidelity.json"
    shorts_contract.atomic_write_json(report_path, report)
    row = {
        "shortId": "01",
        "proofRevision": 1,
        "dirty": False,
        "dirtyReasons": [],
        "artifacts": [
            shorts._artifact("proof", proof, 1),
            shorts._artifact("source-fidelity", report_path, 1),
        ],
    }
    status = {"items": [row]}
    shorts._mark_stale_fidelity_proofs(plan, status, paths=paths)
    assert row["dirty"] is False
    observed["browserVersion"] = "different-current-browser"
    shorts._mark_stale_fidelity_proofs(plan, status, paths=paths)
    assert row["dirty"] is True
    assert row["dirtyReasons"] == ["render-implementation-changed"]
    assert implementations["generated:" + receipt["assetId"]] == receipt["recordHash"]


def test_code_drawn_short_rejects_changed_fresh_pixels_before_admission(
    tmp_path, monkeypatch
):
    from copy import deepcopy

    from avo import motion, shorts_motion
    from avo.adapters.motion.code_drawn import CodeDrawnAdapter
    from avo.timeline.generated_assets import GeneratedAssetService
    from tests.code_drawn_asset_fixture import synthetic_environment

    workspace, _, _, item, spec, receipt = _code_drawn_fidelity_context(tmp_path)
    fresh = deepcopy(receipt["parameters"]["codeDrawn"]["captureEvidence"])
    fresh["rgbaSha256"][0] = "f" * 64
    fresh["environment"] = synthetic_environment()
    monkeypatch.setattr(
        CodeDrawnAdapter,
        "check",
        lambda self, composition: {"checks": [{"evidence": fresh}]},
    )

    def forbidden(*args, **kwargs):
        pytest.fail("Changed fresh pixels reached generated alpha admission")

    monkeypatch.setattr(GeneratedAssetService, "admit", forbidden)
    with pytest.raises(motion.MotionError, match="RGBA|pixels"):
        shorts_motion.admitted_alpha(
            spec, workspace, item, {"width": 128, "height": 96, "fps": 30}
        )
