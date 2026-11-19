"""Reference measurements separate display-wide movement from local residuals."""

import hashlib
import json
import os
import subprocess
from copy import deepcopy
from pathlib import Path

import numpy as np
import pytest

from avo.editing_craft import resolve_editing_craft_selection
from avo.reference_analysis import freeze_reference_motion
from avo.timeline.contracts import file_fingerprint
from avo.timeline.motion_review import MotionReviewService
from avo.visual_motion_runtime import measure_reference_proxy
from tests.test_timeline_bmap_service import approved_workspace


@pytest.fixture
def reference_runtime():
    pin = os.environ.get("AVO_TEST_VISUAL_MOTION_PIN")
    if not pin:
        pytest.skip("Explicit prepared OpenCV runtime required")
    return Path(
        json.loads(Path(pin).read_text(encoding="utf-8"))["model"]["runtime"][
            "pythonEnv"
        ]
    )


def reference_frames():
    rng = np.random.default_rng(488)
    canvas = rng.integers(48, 180, (96, 128), dtype=np.uint8)
    canvas[16:24, [10, 28, 61, 83, 94, 115]] = 215
    moved = np.roll(canvas, (2, 5), axis=(0, 1))
    local = moved.copy()
    local[32:52, 60:86] = np.roll(moved[32:52, 60:86], 4, axis=1)
    frames = [canvas, local, np.zeros_like(canvas)]
    return np.repeat(np.stack(frames)[..., np.newaxis], 3, axis=-1)


def reference_request(workspace, source, python):
    fingerprint = file_fingerprint(source)
    return {
        "contractVersion": "1.0.0",
        "operation": "reference-analyze",
        "actor": "creator",
        "reason": "Review only the selected movement and brightness",
        "expectedBasis": MotionReviewService(workspace).project()["basisHeads"],
        "selection": resolve_editing_craft_selection(
            invocation={"referenceAnalysis": {"enabled": True}}
        ),
        "runtimePython": str(python),
        "clips": [
            {
                "clipId": "selected-reference",
                "locator": str(source),
                "source": {
                    "sourceId": "source-reference",
                    "sha256": fingerprint["sha256"],
                    "sizeBytes": fingerprint["sizeBytes"],
                },
                "streamIndex": 0,
                "sampleEvery": 1,
                "sourceRange": {
                    "startTicks": 0,
                    "endTicks": 120,
                    "timebase": {"num": 1, "den": 1000},
                },
                "aspects": ["global-motion", "brightness", "audio-word-timing"],
            }
        ],
    }


def source_movie(tmp_path):
    source = tmp_path / "reference.mkv"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "rawvideo",
            "-pixel_format",
            "bgr24",
            "-video_size",
            "128x96",
            "-framerate",
            "25",
            "-i",
            "pipe:0",
            "-f",
            "lavfi",
            "-i",
            r"aevalsrc=if(gte(t\,0.046)\,0.7*sin(2*PI*1000*t)\,0):s=48000:d=0.12",
            "-vf",
            "setsar=1",
            "-c:v",
            "ffv1",
            "-c:a",
            "pcm_f32le",
            str(source),
        ],
        input=reference_frames().tobytes(),
        check=True,
        timeout=30,
    )
    return source


def test_reference_motion_uses_actual_proxy_and_abstains_in_darkness(
    tmp_path, reference_runtime
):
    frames = reference_frames()
    proxy = tmp_path / "reference.bgr"
    proxy.write_bytes(frames.tobytes())
    result = measure_reference_proxy(
        reference_runtime,
        proxy,
        width=128,
        height=96,
        frame_count=3,
        sha256=hashlib.sha256(frames.tobytes()).hexdigest(),
    )
    motion, dark = result["pairs"]
    assert motion["status"] == "measured"
    assert motion["global"]["scale"] == pytest.approx(1, abs=0.02)
    assert motion["global"]["translateX"] == pytest.approx(5 / 128, abs=0.008)
    assert motion["global"]["translateY"] == pytest.approx(2 / 96, abs=0.008)
    assert motion["coverage"]["inliers"] >= 12
    assert motion["residual"]["movingPoints"] > 0
    assert dark["status"] == "unmeasurable"
    assert dark["reason"] == "dark-frame"
    assert dark["brightness"]["after"] == 0
    assert result["versions"]["opencv-python-headless"] == "4.12.0.88"
    assert "modelSha256" not in result


def test_reference_motion_discloses_cut_and_untrackable_blur(
    tmp_path, reference_runtime
):
    import numpy as np

    random = np.random.default_rng(7)
    shape = (96, 128, 1)
    first = random.integers(16, 80, size=shape, dtype=np.uint8).repeat(3, axis=2)
    second = random.integers(165, 240, size=shape, dtype=np.uint8).repeat(3, axis=2)
    blurred = np.full_like(second, 195)
    frames = np.stack([first, second, blurred])
    proxy = tmp_path / "cut-and-blur.bgr"
    proxy.write_bytes(frames.tobytes())
    result = measure_reference_proxy(
        reference_runtime,
        proxy,
        width=128,
        height=96,
        frame_count=len(frames),
        sha256=file_fingerprint(proxy)["sha256"],
    )
    cut, soft = result["pairs"]
    assert cut["status"] == "cut-candidate"
    assert cut["reason"] == "tracking-break-and-histogram-change"
    assert cut["brightness"]["after"] > cut["brightness"]["before"]
    assert soft["status"] == "unmeasurable"
    assert soft["reason"] == "insufficient-detail"
    assert "global" not in cut and "global" not in soft


def test_motion_in_one_subject_area_does_not_establish_camera_movement(
    tmp_path, reference_runtime
):
    import numpy as np

    random = np.random.default_rng(9)
    subject = random.integers(35, 220, size=(22, 26, 3), dtype=np.uint8)
    frames = np.full((2, 96, 128, 3), 105, dtype=np.uint8)
    frames[0, 38:60, 45:71] = subject
    frames[1, 38:60, 49:75] = subject
    proxy = tmp_path / "subject-only.bgr"
    proxy.write_bytes(frames.tobytes())
    result = measure_reference_proxy(
        reference_runtime,
        proxy,
        width=128,
        height=96,
        frame_count=len(frames),
        sha256=file_fingerprint(proxy)["sha256"],
    )
    (pair,) = result["pairs"]
    assert pair["status"] == "unmeasurable"
    assert pair["reason"] == "unqualified-global-motion"
    assert "global" not in pair


def test_freeze_preserves_exact_native_grid_and_requested_aspects_only():
    request = {
        "source": {"sourceId": "reference", "sha256": "a" * 64, "sizeBytes": 800},
        "sourceRange": {
            "startTicks": 4000,
            "endTicks": 4200,
            "timebase": {"num": 1, "den": 1000},
        },
        "geometry": {
            "width": 128,
            "height": 96,
            "rotation": 0,
            "sampleAspectRatio": {"num": 1, "den": 1},
        },
        "proxy": {
            "sha256": "b" * 64,
            "width": 128,
            "height": 96,
            "content": {"x": 0, "y": 0, "width": 128, "height": 96},
            "sourceTicks": [4001, 4020, 4070],
        },
        "aspects": ["brightness", "audio-word-timing"],
    }
    measured = {
        "isolated": True,
        "device": "cpu",
        "versions": {"opencv-python-headless": "4.12.0.88", "numpy": "2.2.6"},
        "method": "pyramidal-lk-partial-affine-v1",
        "proxySha256": "b" * 64,
        "pairs": [
            {
                "status": "cut-candidate",
                "reason": "tracking-break-and-histogram-change",
                "brightness": {"before": 0.6, "after": 0.3},
            },
            {
                "status": "unmeasurable",
                "reason": "dark-frame",
                "brightness": {"before": 0.3, "after": 0.0},
            },
        ],
    }
    result = freeze_reference_motion(request, measured)
    assert result["coverage"] == {
        "sampledFrames": 3,
        "pairCount": 2,
        "minimumGapTicks": 19,
        "maximumGapTicks": 50,
    }
    assert result["intervals"][0] == {
        "startTicks": 4001,
        "endTicks": 4020,
        "brightness": {"before": 0.6, "after": 0.3},
    }
    assert result["interpretation"] == {
        "easing": "uninterpreted",
        "availableEvidence": {
            "audio-word-timing": "unavailable",
            "prepared-words": "not-selected",
        },
    }
    stale = deepcopy(request)
    stale["proxy"]["sourceTicks"] = [4001, 4020, 4020]
    with pytest.raises(ValueError, match="increasing sampled frame grid"):
        freeze_reference_motion(stale, measured)


def test_reference_budget_and_exact_request_are_checked_before_analysis(
    tmp_path, monkeypatch
):
    from avo.cli import main
    from avo.timeline.reference_observation import analyze_reference

    workspace, _, _ = approved_workspace(tmp_path)
    source = tmp_path / "reference.bin"
    source.write_bytes(b"explicit fixture")
    request = reference_request(workspace, source, tmp_path / "cpu-python.exe")
    request["clips"][0]["sourceRange"]["endTicks"] = 31000

    def forbidden(*args):
        pytest.fail("Unqualified reference selection ran the analyzer")

    with pytest.raises(ValueError, match="up to 30 seconds"):
        analyze_reference(workspace, request, forbidden)
    monkeypatch.setattr("avo.adapters.registry.build_reference_analyzer", forbidden)
    path = tmp_path / "reference-request.json"
    path.write_text(json.dumps(request), encoding="utf-8")
    code = main(
        [
            "animation",
            "reference-analyze",
            "--project",
            str(workspace.project_path),
            "--video-id",
            workspace.video_id,
            "--request",
            str(path),
            "--request-sha256",
            "f" * 64,
            "--json",
        ]
    )
    assert code == 2
    assert not (workspace.raw_dir / "edit/motion/references").exists()


def test_reference_mcp_gate_binds_exact_request_bytes(tmp_path):
    from avo.mcp.tools.cli_tools import _all_bridge_defs, _decision_gate_args

    path = tmp_path / "request.json"
    path.write_bytes(b'{"operation":"reference-analyze"}')
    route = next(
        row
        for row in _all_bridge_defs()
        if row.cli_prefix == ("animation", "reference-analyze")
    )
    assert route.spec.destructive
    result = _decision_gate_args(route, {"request": str(path)})
    assert (
        result["_decisionDocumentSha256"]
        == hashlib.sha256(path.read_bytes()).hexdigest()
    )


@pytest.mark.integration
def test_native_reference_analysis_saves_inspection_only_sheet_and_observations(
    tmp_path, reference_runtime, capsys
):
    from avo.cli import main

    workspace, _, _ = approved_workspace(tmp_path)
    source = source_movie(tmp_path)
    request = reference_request(workspace, source, reference_runtime)
    request["clips"][0]["audio"] = {
        "streamIndex": 1,
        "channelIndex": 0,
        "energyThreshold": 0.05,
    }
    request_path = tmp_path / "reference-request.json"
    request_path.write_text(json.dumps(request), encoding="utf-8")
    before = {
        path: path.read_bytes()
        for path in workspace.timeline_dir.rglob("*")
        if path.is_file()
    }
    code = main(
        [
            "animation",
            "reference-analyze",
            "--project",
            str(workspace.project_path),
            "--video-id",
            workspace.video_id,
            "--request",
            str(request_path),
            "--json",
        ]
    )
    result = capsys.readouterr()
    assert code == 0, result.err
    receipt = json.loads(result.out)
    assert receipt["review"] == "required"
    ref = receipt["observationRef"]
    path = workspace.raw_dir / ref["locator"]
    assert file_fingerprint(path)["sha256"] == ref["sha256"]
    record = json.loads(path.read_bytes())
    assert record["use"] == "inspection-only"
    (row,) = record["clips"]
    motion = row["observation"]["intervals"][0]
    assert motion["startTicks"] == 0
    assert motion["endTicks"] == 40
    assert motion["global"]["translateX"] == pytest.approx(5 / 128, abs=0.008)
    audio = row["observation"]["interpretation"]["audioTiming"]
    assert audio["status"] == "observed"
    assert audio["sampleRate"] == 48000
    assert audio["onsetSamples"] == [pytest.approx(2208, abs=96)]
    sheet = workspace.raw_dir / row["contactSheet"]["locator"]
    assert sheet.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    assert file_fingerprint(sheet)["sha256"] == row["contactSheet"]["sha256"]
    assert {path: path.read_bytes() for path in before} == before
