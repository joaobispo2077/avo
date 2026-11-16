"""Original placed media plus admitted generated overlays share one frozen clock."""

import json
import shutil
import subprocess
from copy import deepcopy
from types import SimpleNamespace

import numpy as np
import pytest
from tests.integration import test_code_drawn_proof_executor as generated_fixture
from tests.integration.test_otio_placed_render_runtime import (
    _decoded,
    _execution,
    _fractional_execution,
)

from avo.adapters.media.proof_executor import execute_ffmpeg_proof
from avo.timeline.contracts import document_hash_excluding
from avo.timeline.generated_assets import GeneratedAssetService

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not shutil.which("ffmpeg") or not shutil.which("ffprobe"),
        reason="Actual FFmpeg required",
    ),
]


@pytest.fixture
def placed_assets(tmp_path, monkeypatch, request):
    if getattr(request, "param", None) == "fractional":
        execution = _fractional_execution(tmp_path)
    else:
        execution, _ = _execution(tmp_path)
    rate = execution["output"]["frameRate"]
    fps = str(rate["num"]) + "/" + str(rate["den"])

    def encode(path, *, opaque):
        frames = np.zeros((72, 48, 64, 4), dtype=np.uint8)
        for frame in range(72):
            if opaque:
                frames[frame] = [40 + 2 * frame, 180, 35, 255]
            else:
                frames[frame, 6:18, 8:24] = [180, 40, 210, 128]
                frames[frame, 10:14, 12:16] = [40 + 2 * frame, 200, 35, 255]
        subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-nostdin",
                "-f",
                "rawvideo",
                "-pix_fmt",
                "rgba",
                "-s",
                "64x48",
                "-r",
                fps,
                "-i",
                "-",
                "-an",
                "-c:v",
                "ffv1",
                "-pix_fmt",
                "bgra",
                str(path),
            ],
            input=frames.tobytes(),
            capture_output=True,
            check=True,
        )

    monkeypatch.setattr(generated_fixture, "_encode_generated", encode)
    service = GeneratedAssetService(
        SimpleNamespace(timeline_dir=tmp_path / "edit/timeline")
    )
    assets = {
        key: generated_fixture._generated(
            tmp_path, service, asset_id="placed-" + key, opaque=opaque
        )
        for key, opaque in (("opaque", True), ("alpha", False))
    }
    return execution, assets


def add_overlay(request, asset, start=24, end=48, **kwargs):
    operation = generated_fixture._add_generated(
        request, asset, kind="overlay-video", start=start, end=end, **kwargs
    )
    operation["parameters"]["placement"] = {"x": 0, "y": 0, "width": 64, "height": 48}
    return operation


@pytest.mark.parametrize("asset_kind", ["opaque", "alpha"])
def test_placed_overlay_preserves_raw_audio_and_outside_picture(
    placed_assets, tmp_path, asset_kind
):
    request, assets = placed_assets
    base = tmp_path / "base.mkv"
    execute_ffmpeg_proof(request, base)
    add_overlay(request, assets[asset_kind])
    # Graph declaration order does not control the frozen layer order.
    request["videoGraph"]["operations"].reverse()
    original = deepcopy(request)
    full = tmp_path / "overlaid.mkv"
    result = execute_ffmpeg_proof(request, full)
    picture, baseline = _decoded(full), _decoded(base)
    assert np.array_equal(picture[:24], baseline[:24])
    assert np.array_equal(picture[48:], baseline[48:])
    if asset_kind == "opaque":
        expected = _decoded(assets[asset_kind]["path"])[7:31]
        assert np.array_equal(picture[24:48], expected)
    else:
        assert np.array_equal(picture[24:48, :6], baseline[24:48, :6])
        assert np.array_equal(picture[24:48, 18:], baseline[24:48, 18:])
        assert np.all(picture[24:48, 11, 13, 1] == 200)
        expected = (
            np.array([180, 40, 210]) * 128 + baseline[24:48, 7, 9].astype(int) * 127
        ) / 255
        np.testing.assert_allclose(picture[24:48, 7, 9], expected, atol=2)
    assert np.array_equal(_decoded(full, audio=True), _decoded(base, audio=True))
    assert result["audioEncodeCount"] == 1
    assert len(result["generatedOperations"]) == 1
    assert len(result["overlayOperations"]) == 1
    assert request == original


def test_placed_overlay_full_and_micro_are_identical_with_inactive_layers(
    placed_assets, tmp_path
):
    request, assets = placed_assets
    add_overlay(request, assets["opaque"], 12, 24, operation_id="early")
    add_overlay(request, assets["alpha"], 60, 84, operation_id="late", local_start=31)
    full = tmp_path / "full.mkv"
    execute_ffmpeg_proof(request, full)
    for start, end in ((4, 20), (30, 40), (66, 90)):
        request["window"] = {"startFrame": start, "endFrameExclusive": end}
        micro = tmp_path / f"micro-{start}.mkv"
        result = execute_ffmpeg_proof(request, micro)
        assert np.array_equal(_decoded(micro), _decoded(full)[start:end])
        assert np.array_equal(
            _decoded(micro, audio=True),
            _decoded(full, audio=True)[start * 2000 : end * 2000],
        )
        assert len(result["overlayOperations"]) == 2


@pytest.mark.parametrize(
    "fault",
    [
        "unknown-operation",
        "extra-base",
        "second-layout",
        "duplicate-overlay",
        "stale-implementation",
        "source-range",
        "source-eof",
        "asset-lock",
        "input-lock",
        "beyond-program",
        "caption-under-graphic",
    ],
)
def test_placed_overlay_invalid_graph_cannot_publish(placed_assets, tmp_path, fault):
    request, assets = placed_assets
    op = add_overlay(request, assets["alpha"])
    operations = request["videoGraph"]["operations"]
    if fault == "unknown-operation":
        op["kind"] = "unregistered-effect"
    elif fault == "extra-base":
        op["kind"] = "generated-clip"
    elif fault == "second-layout":
        operations.append(deepcopy(operations[0]))
    elif fault == "duplicate-overlay":
        operations.append(deepcopy(op))
    elif fault == "stale-implementation":
        op["implementationId"] = "invalid"
    elif fault == "source-range":
        op["parameters"]["sourceRange"]["endFrameExclusive"] -= 1
    elif fault == "source-eof":
        op["parameters"]["sourceRange"] = {"startFrame": 60, "endFrameExclusive": 84}
    elif fault == "asset-lock":
        request["canonicalInputLock"]["generated:placed-alpha"] = "f" * 64
    elif fault == "input-lock":
        op["parameters"]["inputLockRef"]["sha256"] = "f" * 64
    elif fault == "beyond-program":
        op["outputRange"] = {"startFrame": 84, "endFrameExclusive": 108}
    elif fault == "caption-under-graphic":
        op["parameters"]["layerRole"] = "caption"
        op["parameters"]["zOrder"] = 5
        add_overlay(request, assets["opaque"], operation_id="graphic", z_order=10)
    output = tmp_path / "must-not-publish.mkv"
    with pytest.raises(RuntimeError):
        execute_ffmpeg_proof(request, output)
    assert not output.exists()


def test_placed_overlay_rechecks_admission_before_publication(placed_assets, tmp_path):
    request, assets = placed_assets
    asset = assets["alpha"]
    add_overlay(request, asset)
    calls = []

    def admission(reference, lock, canonical):
        calls.append(reference)
        if len(calls) == 2:
            asset["lock_path"].write_text("changed during render", encoding="utf-8")
        return deepcopy(asset["record"])

    output = tmp_path / "must-not-publish.mkv"
    with pytest.raises(RuntimeError, match="changed|mismatch"):
        execute_ffmpeg_proof(request, output, generated_asset_validator=admission)
    assert len(calls) == 2
    assert not output.exists()


def test_placed_overlay_reference_proof_ancestor_cannot_publish(
    placed_assets, tmp_path
):
    request, assets = placed_assets
    op = add_overlay(request, assets["alpha"])
    # A generated asset cannot embed a previous preview as its picture source.
    record = deepcopy(assets["alpha"]["record"])
    original = assets["alpha"]["path"]
    forbidden = tmp_path / "preview" / original.name
    forbidden.parent.mkdir()
    forbidden.write_bytes(original.read_bytes())
    record["output"]["locator"] = str(forbidden)
    record["recordHash"] = document_hash_excluding(record, "recordHash")
    assets["alpha"]["receipt"].write_text(json.dumps(record), encoding="utf-8")
    op["parameters"]["sourceFingerprint"] = deepcopy(record["output"])
    op["parameters"]["generatedAssetRef"]["recordHash"] = record["recordHash"]
    request["canonicalInputLock"]["generated:placed-alpha"] = record["recordHash"]
    output = tmp_path / "must-not-publish.mkv"
    with pytest.raises(RuntimeError, match="Prohibited"):
        execute_ffmpeg_proof(request, output)
    assert not output.exists()


def test_placed_translucent_overlay_preserves_privacy_with_reordered_base(
    placed_assets, tmp_path
):
    from tests.test_import_privacy_masks import privacy_masks

    request, assets = placed_assets
    masks = privacy_masks()
    masks["regions"][0].update(startFrame=53, endFrameExclusive=67)
    request["videoGraph"]["operations"][0]["parameters"]["privacyMasks"] = masks
    baseline = tmp_path / "privacy-base.mkv"
    execute_ffmpeg_proof(request, baseline)
    add_overlay(request, assets["alpha"], 50, 70)
    request["videoGraph"]["operations"].reverse()
    full = tmp_path / "privacy-overlay.mkv"
    execute_ffmpeg_proof(request, full)
    picture = _decoded(full)
    assert np.all(picture[53:67, 5:12, 4:8] == 0)
    np.testing.assert_allclose(
        picture[53:67, 7, 9],
        np.tile(np.array([180, 40, 210]) * 128 / 255, (14, 1)),
        atol=2,
    )
    assert np.array_equal(_decoded(full, audio=True), _decoded(baseline, audio=True))
    request["window"] = {"startFrame": 52, "endFrameExclusive": 68}
    micro = tmp_path / "privacy-micro.mkv"
    execute_ffmpeg_proof(request, micro)
    assert np.array_equal(_decoded(micro), picture[52:68])
    assert np.array_equal(
        _decoded(micro, audio=True), _decoded(full, audio=True)[104000:136000]
    )


@pytest.mark.parametrize("placed_assets", ["fractional"], indirect=True)
def test_fractional_placed_overlay_keeps_phase_and_half_up_pcm_windows(
    placed_assets, tmp_path
):
    request, assets = placed_assets
    add_overlay(request, assets["opaque"], 1, 11, operation_id="early")
    add_overlay(request, assets["alpha"], 20, 26, operation_id="late", local_start=31)
    full = tmp_path / "fractional-overlays.mkv"
    execute_ffmpeg_proof(request, full)
    assert np.array_equal(
        _decoded(full)[1:11], _decoded(assets["opaque"]["path"])[7:17]
    )
    assert len(_decoded(full, audio=True)) == 48048
    for start, end in ((1, 3), (10, 22), (27, 30)):
        request["window"] = {"startFrame": start, "endFrameExclusive": end}
        micro = tmp_path / f"fractional-micro-{start}.mkv"
        execute_ffmpeg_proof(request, micro)
        assert np.array_equal(_decoded(micro), _decoded(full)[start:end])
        first_sample = (start * 1001 * 48000 + 15000) // 30000
        last_sample = (end * 1001 * 48000 + 15000) // 30000
        assert np.array_equal(
            _decoded(micro, audio=True),
            _decoded(full, audio=True)[first_sample:last_sample],
        )
