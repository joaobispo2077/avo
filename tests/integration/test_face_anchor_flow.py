"""Explicitly provisioned detector execution on prepared display proxy frames."""

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
from PIL import Image

from avo.model_sources import resolve_job
from avo.reference_analysis import freeze_face_observation


@pytest.fixture
def provisioned():
    path = os.environ.get("AVO_TEST_VISUAL_MOTION_PIN")
    if not path:
        pytest.skip("Explicit prepared visual runtime pin required")
    pin = json.loads(Path(path).read_text(encoding="utf-8"))
    resolved = resolve_job("face_detect", invocation=pin["model"], state={})
    image = Path(pin["fixture"])
    assert hashlib.sha256(image.read_bytes()).hexdigest() == pin["fixtureSha256"]
    return resolved, image


def test_actual_detector_preserves_source_sample_identity_and_marks_disappearance(
    tmp_path, provisioned
):
    from avo.visual_motion_runtime import detect_proxy_faces

    resolved, image = provisioned
    proxy = tmp_path / "display-proxy.bgr"
    with Image.open(image) as original:
        rgb = original.convert("RGB")
        width, height = rgb.size
        visible = rgb.tobytes("raw", "BGR")
    raw = visible + visible + bytes(len(visible))
    proxy.write_bytes(raw)
    digest = hashlib.sha256(raw).hexdigest()
    response = detect_proxy_faces(
        resolved, proxy, width=width, height=height, frame_count=3, sha256=digest
    )
    assert response["proxySha256"] == digest
    assert [len(rows) for rows in response["detections"]] == [1, 1, 0]
    request = {
        "contractVersion": "1.0.0",
        "source": {
            "sourceId": "sample-reference",
            "sha256": hashlib.sha256(image.read_bytes()).hexdigest(),
            "sizeBytes": image.stat().st_size,
        },
        "sourceRange": {
            "startTicks": 24000,
            "endTicks": 26880,
            "timebase": {"num": 1, "den": 48000},
        },
        "geometry": {
            "width": width,
            "height": height,
            "rotation": 0,
            "sampleAspectRatio": {"num": 1, "den": 1},
        },
        "proxy": {
            "sha256": digest,
            "width": width,
            "height": height,
            "content": {"x": 0, "y": 0, "width": width, "height": height},
            "sourceTicks": [24000, 24960, 25920],
        },
        "seed": {"sourceTick": 24000, "detectionIndex": 0},
        "minimumOverlap": 0.3,
        "maximumGapTicks": 960,
    }
    observation = freeze_face_observation(request, response)
    association = observation["association"]
    assert observation["coverage"] == {"observedFrames": 3, "selectedFrames": 2}
    assert [item["sourceTick"] for item in association] == [24000, 24960, 25920]
    assert [item["status"] for item in association] == ["selected", "selected", "lost"]


def test_prepared_proxy_cannot_use_unverified_bytes(tmp_path, provisioned):
    from avo.visual_motion_runtime import detect_proxy_faces

    resolved, _ = provisioned
    proxy = tmp_path / "wrong.bgr"
    proxy.write_bytes(bytes(320 * 320 * 3))
    with pytest.raises(ValueError, match="proxy bytes differ"):
        detect_proxy_faces(
            resolved, proxy, width=320, height=320, frame_count=1, sha256="f" * 64
        )


def test_actual_face_measurements_drive_encoded_window_and_hold_after_loss(
    tmp_path, provisioned
):
    import numpy as np
    from tests.integration.test_camera_proof_runtime import operation, pixels, render

    from avo.adapters.understand.visual_motion import observe_selected_face
    from avo.reference_analysis import freeze_face_trajectory
    from avo.timeline.camera import evaluate_camera, reframe_face_camera
    from avo.timeline.contracts import content_hash

    resolved, image = provisioned
    size = 160
    with Image.open(image) as original:
        face = original.convert("RGB").resize((size, size)).tobytes("raw", "BGR")
    source = tmp_path / "presenter.mkv"
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
            f"{size}x{size}",
            "-framerate",
            "25",
            "-i",
            "pipe:0",
            "-vf",
            "setsar=1",
            "-c:v",
            "ffv1",
            "-pix_fmt",
            "gbrp16le",
            str(source),
        ],
        input=face * 18 + bytes([96, 50, 100]) * size * size * 6,
        check=True,
        timeout=25,
    )
    original = source.read_bytes()
    selected = operation(source, size=(size, size))
    parameters = selected["parameters"]
    observation = observe_selected_face(
        resolved,
        source,
        {
            "sourceId": parameters["sourceId"],
            "sourceSha256": parameters["sourceSha256"],
            "sourceRange": {
                "startTicks": 0,
                "endTicks": 960,
                "timebase": {"num": 1, "den": 1000},
            },
            "streamIndex": 0,
            "sampleEvery": 2,
            "seed": {"sourceTick": 0, "detectionIndex": 0},
            "minimumOverlap": 0.3,
            "maximumGapTicks": 80,
        },
    )
    assert observation["coverage"] == {"observedFrames": 12, "selectedFrames": 9}
    assert observation["association"][9]["status"] == "lost"
    trajectory = freeze_face_trajectory(observation)
    frame_range, geometry = parameters["originalFrameRange"], parameters["geometry"]
    behavior = reframe_face_camera(
        parameters["behavior"],
        frame_range=frame_range,
        geometry=geometry,
        points=trajectory["points"],
        source_ticks=range(0, 960, 40),
        transition_frames=4,
        fallback="hold",
    )
    parameters["behavior"] = behavior
    parameters["pathHash"] = content_hash({"behavior": behavior, "geometry": geometry})

    def crop(frame):
        return evaluate_camera(
            behavior, frame=frame, frame_range=frame_range, geometry=geometry
        )["crop"]

    assert crop(16) == crop(23)
    full = render(source, tmp_path / "full.mkv", selected, width=size, height=size)
    window = render(
        source,
        tmp_path / "window.mkv",
        selected,
        first=15,
        last=20,
        width=size,
        height=size,
    )
    comparison = pixels(source, size, size)
    np.testing.assert_array_equal(full[0], comparison[0])
    assert not np.array_equal(full[16], comparison[16])
    assert np.all(full[23] > 0)
    np.testing.assert_array_equal(window, full[15:20])
    assert source.read_bytes() == original


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="FFmpeg required for decode")
@pytest.mark.parametrize("offset_seconds", [0, 5])
def test_original_source_decoder_keeps_native_frames_and_range(
    tmp_path, provisioned, offset_seconds
):
    from avo.adapters.understand.visual_motion import capture_display_proxy
    from avo.visual_motion_runtime import detect_proxy_faces

    resolved, image = provisioned
    source = tmp_path / "source.mkv"
    with Image.open(image) as original:
        rgb = original.convert("RGB")
        width, height = rgb.size
        visible = rgb.tobytes("raw", "BGR")
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
            f"{width}x{height}",
            "-framerate",
            "25",
            "-i",
            "-",
            "-vf",
            f"setsar=1,setpts=PTS+{offset_seconds}/TB",
            "-c:v",
            "ffv1",
            str(source),
        ],
        input=visible * 3 + bytes(len(visible)),
        check=True,
        timeout=20,
    )
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    proxy_path = tmp_path / "captured.bgr"
    offset = 1000 * offset_seconds
    scope = {
        "startTicks": offset + 40,
        "endTicks": offset + 140,
        "timebase": {"num": 1, "den": 1000},
    }
    measured = capture_display_proxy(
        source,
        proxy_path,
        stream_index=0,
        expected_sha256=source_hash,
        source_range=scope,
        sample_every=2,
    )
    proxy = measured["proxy"]
    assert measured["streamOriginTicks"] == offset
    assert proxy["sourceTicks"] == [offset + 40, offset + 120]
    assert measured["geometry"]["width"] == width
    assert hashlib.sha256(source.read_bytes()).hexdigest() == source_hash
    detections = detect_proxy_faces(
        resolved,
        proxy_path,
        width=proxy["width"],
        height=proxy["height"],
        frame_count=len(proxy["sourceTicks"]),
        sha256=proxy["sha256"],
    )
    assert [len(rows) for rows in detections["detections"]] == [1, 0]


def selected_face_request(workspace, *, stream_origin=None):
    from tests.test_visual_motion_analysis import observation_inputs

    from avo.editing_craft import resolve_editing_craft_selection
    from avo.timeline.motion_review import MotionReviewService

    fixture, detection = observation_inputs()
    if stream_origin is not None:
        fixture["streamOriginTicks"] = stream_origin
    cmap = workspace.store("cmap").load()["revisions"][-1]["snapshot"]
    raw = cmap["sources"][0]
    fixture["source"] = {
        "sourceId": raw["sourceId"],
        "sha256": raw["fingerprint"]["sha256"],
        "sizeBytes": raw["fingerprint"]["sizeBytes"],
    }
    request = {
        "contractVersion": "1.0.0",
        "operation": "face-analyze",
        "actor": "creator",
        "reason": "Review the selected presenter in this range",
        "expectedBasis": MotionReviewService(workspace).project()["basisHeads"],
        "selection": resolve_editing_craft_selection(
            invocation={"camera": {"enabled": True, "faceAnchor": "selected-subject"}}
        ),
        "sourceId": fixture["source"]["sourceId"],
        "sourceSha256": fixture["source"]["sha256"],
        "streamIndex": 0,
        "sampleEvery": 2,
        **{
            key: fixture[key]
            for key in ("sourceRange", "seed", "minimumOverlap", "maximumGapTicks")
        },
    }
    return request, freeze_face_observation(fixture, detection)


def test_selected_analysis_publishes_observation_without_applying_camera(tmp_path):
    from tests.test_timeline_bmap_service import approved_workspace

    from avo.timeline.face_analysis import analyze_face

    workspace, _, _ = approved_workspace(tmp_path)
    request, observed = selected_face_request(workspace)
    before = {
        path: path.read_bytes()
        for path in workspace.timeline_dir.rglob("*")
        if path.is_file()
    }
    result = analyze_face(workspace, request, lambda path, value: observed)
    assert result["status"] == "observed"
    ref = result["observationRef"]
    output = workspace.raw_dir / ref["locator"]
    assert hashlib.sha256(output.read_bytes()).hexdigest() == ref["sha256"]
    evidence = json.loads(output.read_bytes())
    assert evidence["observation"] == observed
    assert evidence["request"] == request
    trajectory = evidence["trajectory"]
    assert result["trajectoryHash"] == trajectory["trajectoryHash"]
    assert result["uncertainIntervals"] == trajectory["uncertainIntervals"]
    assert trajectory["uncertainIntervals"][-1]["reason"] == "lost"
    assert {path: path.read_bytes() for path in before} == before


def test_frozen_face_reader_requires_exact_saved_bytes(tmp_path):
    from tests.test_timeline_bmap_service import approved_workspace

    from avo.timeline.face_analysis import analyze_face, read_face_anchor

    workspace, _, _ = approved_workspace(tmp_path)
    request, observed = selected_face_request(workspace, stream_origin=23040)
    result = analyze_face(workspace, request, lambda path, value: observed)
    binding = {
        "observationRef": result["observationRef"],
        "trajectoryHash": result["trajectoryHash"],
        "transitionFrames": 4,
    }
    trajectory, stream_index = read_face_anchor(workspace, binding)
    assert trajectory["streamOriginTicks"] == 23040
    assert stream_index == request["streamIndex"]
    path = workspace.raw_dir / result["observationRef"]["locator"]
    path.write_bytes(path.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="observation bytes changed"):
        read_face_anchor(workspace, binding)


def test_face_analysis_fails_before_capture_when_current_source_differs(tmp_path):
    from tests.test_timeline_bmap_service import approved_workspace

    from avo.timeline.face_analysis import analyze_face

    workspace, _, _ = approved_workspace(tmp_path)
    request, _ = selected_face_request(workspace)
    request["sourceSha256"] = "f" * 64

    def forbidden(*args):
        pytest.fail("Stale source selection reached capture")

    with pytest.raises(ValueError, match="current original"):
        analyze_face(workspace, request, forbidden)
    assert not (workspace.raw_dir / "edit/motion/face").exists()


def test_source_change_during_face_analysis_prevents_publication(tmp_path):
    from tests.test_timeline_bmap_service import approved_workspace

    from avo.timeline.face_analysis import analyze_face

    workspace, _, _ = approved_workspace(tmp_path)
    request, observed = selected_face_request(workspace)

    def changed(source, value):
        source.write_bytes(b"changed original fixture")
        return observed

    with pytest.raises(ValueError, match="bytes changed during face analysis"):
        analyze_face(workspace, request, changed)
    assert not (workspace.raw_dir / "edit/motion/face").exists()


@pytest.mark.parametrize(
    "field", ["sourceRange", "seed", "minimumOverlap", "maximumGapTicks"]
)
def test_face_capture_cannot_publish_evidence_from_another_request(tmp_path, field):
    from tests.test_timeline_bmap_service import approved_workspace

    from avo.timeline.face_analysis import analyze_face

    workspace, _, _ = approved_workspace(tmp_path)
    request, observation = selected_face_request(workspace)
    changed = {
        "sourceRange": {**request["sourceRange"], "endTicks": 27_840},
        "seed": {**request["seed"], "detectionIndex": 1},
        "minimumOverlap": 0.45,
        "maximumGapTicks": 1920,
    }
    request[field] = changed[field]
    with pytest.raises(ValueError, match="analysis parameters"):
        analyze_face(workspace, request, lambda *_: observation)
    assert not (workspace.raw_dir / "edit/motion/face").exists()


def test_frozen_treatment_requires_matching_display_geometry_without_inference(
    tmp_path, monkeypatch
):
    from tests.test_timeline_bmap_service import approved_workspace

    from avo.timeline.face_analysis import analyze_face, read_face_treatment

    workspace, _, _ = approved_workspace(tmp_path)
    request, observation = selected_face_request(workspace, stream_origin=23040)
    result = analyze_face(workspace, request, lambda *_: observation)
    geometry = observation["request"]["geometry"]
    treatment = {
        "faceAnchor": {
            "observationRef": result["observationRef"],
            "trajectoryHash": result["trajectoryHash"],
            "transitionFrames": 4,
        },
        "sourceGeometry": {
            "codedWidth": geometry["width"],
            "codedHeight": geometry["height"],
            "rotationDegrees": geometry["rotation"],
            "sampleAspectRatio": geometry["sampleAspectRatio"],
        },
        "camera": {"sourceId": request["sourceId"]},
        "sourceSha256": request["sourceSha256"],
    }

    def forbidden(*args, **kwargs):
        pytest.fail("Frozen camera treatment started vision inference")

    monkeypatch.setattr("avo.visual_motion_runtime._run_worker", forbidden)
    trajectory, stream = read_face_treatment(workspace, treatment)
    assert trajectory["trajectoryHash"] == result["trajectoryHash"]
    assert stream == request["streamIndex"]
    treatment["sourceGeometry"]["rotationDegrees"] = 180
    with pytest.raises(ValueError, match="display geometry"):
        read_face_treatment(workspace, treatment)


@pytest.mark.parametrize("wrong_hash", [False, True])
def test_face_analysis_command_checks_request_bytes_before_adapter(
    tmp_path, capsys, monkeypatch, wrong_hash
):
    from tests.test_timeline_bmap_service import approved_workspace

    from avo.cli import main

    workspace, _, _ = approved_workspace(tmp_path)
    request, observed = selected_face_request(workspace)
    document = tmp_path / "face-request.json"
    document.write_text(json.dumps(request), encoding="utf-8")
    digest = hashlib.sha256(document.read_bytes()).hexdigest()
    calls = []

    def adapter(resolved, source, actual):
        calls.append(source)
        assert resolved.job == "face_detect"
        assert actual == request
        return observed

    monkeypatch.setattr(
        "avo.adapters.understand.visual_motion.observe_selected_face", adapter
    )
    code = main(
        [
            "animation",
            "face-analyze",
            "--project",
            str(workspace.project_path),
            "--video-id",
            workspace.video_id,
            "--request",
            str(document),
            "--request-sha256",
            "f" * 64 if wrong_hash else digest,
            "--json",
        ]
    )
    if wrong_hash:
        assert code == 2
        assert calls == []
        assert "changed" in capsys.readouterr().err.lower()
    else:
        assert code == 0
        assert len(calls) == 1
        assert json.loads(capsys.readouterr().out)["review"] == "required"


def test_mcp_face_analysis_requires_confirmation_of_exact_request(tmp_path):
    from avo.mcp.tools.cli_tools import _all_bridge_defs, _decision_gate_args

    operation = next(
        entry
        for entry in _all_bridge_defs()
        if entry.cli_prefix == ("animation", "face-analyze")
    )
    document = tmp_path / "request.json"
    document.write_bytes(b'{"operation":"face-analyze"}')
    assert operation.spec.destructive
    checked = _decision_gate_args(operation, {"request": str(document)})
    assert (
        checked["_decisionDocumentSha256"]
        == hashlib.sha256(document.read_bytes()).hexdigest()
    )
