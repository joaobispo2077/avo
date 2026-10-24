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
