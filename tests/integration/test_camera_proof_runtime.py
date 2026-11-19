"""Actual original-picture resampling, separate from declared camera readiness."""

import hashlib
import json
import subprocess
from copy import deepcopy
from fractions import Fraction
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from tests.editing_craft_fixtures import channel_impulses, labeled_video

from avo.timeline.camera import evaluate_camera
from avo.timeline.contracts import content_hash

pytestmark = pytest.mark.integration


def probe(path):
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(path)],
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(result.stdout)["streams"][0]


def pixels(path, width, height):
    result = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-nostdin",
            "-noautorotate",
            "-i",
            str(path),
            "-map",
            "0:v:0",
            "-an",
            "-pix_fmt",
            "rgb48le",
            "-f",
            "rawvideo",
            "pipe:1",
        ],
        capture_output=True,
        check=True,
    )
    return np.frombuffer(result.stdout, dtype="<u2").reshape(-1, height, width, 3)


def operation(
    path,
    *,
    size=(160, 90),
    sar=Fraction(1),
    rotation=0,
    scale=1.25,
    curve="quadratic-in-out",
):
    display = (size[0] * sar, size[1])
    if rotation % 180:
        display = display[::-1]
    geometry = {
        "codedWidth": size[0],
        "codedHeight": size[1],
        "sampleAspectRatio": {"num": sar.numerator, "den": sar.denominator},
        "rotationDegrees": rotation,
        "baselineCrop": {
            "x": 0,
            "y": 0,
            "width": int(display[0]),
            "height": int(display[1]),
        },
    }
    behavior = {
        "contractVersion": "1.0.0",
        "targetLayerId": "presenter",
        "sourceId": "camera-main",
        "nodes": [
            {"phase": 0, "scale": 1, "center": {"x": 0.5, "y": 0.5}, "curve": curve},
            {
                "phase": 1,
                "scale": scale,
                "center": {"x": 0.5, "y": 0.5},
                "curve": "hold",
            },
        ],
    }
    interval = {"firstFrame": 0, "endFrameExclusive": 24}
    source_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    return {
        "operationId": "camera-original",
        "kind": "camera-transform",
        "implementationId": "impl-camera-transform",
        "inputs": ["camera-main"],
        "outputRange": {"startFrame": 0, "endFrameExclusive": 24},
        "parameters": {
            "componentId": "camera-push",
            "cueId": "cue-push",
            "targetLayerId": "presenter",
            "sourceId": "camera-main",
            "sourceOccurrenceId": "trim-original",
            "sourceSha256": source_hash,
            "behavior": behavior,
            "geometry": geometry,
            "originalFrameRange": interval,
            "entryState": evaluate_camera(
                behavior, frame=0, frame_range=interval, geometry=geometry
            ),
            "pathHash": content_hash({"behavior": behavior, "geometry": geometry}),
            "optionsHash": "a" * 64,
        },
    }


def render(path, destination, selected, *, first=0, last=24, width=160, height=90):
    from avo.adapters.media.camera import camera_filter, camera_input_arguments

    metadata = probe(path)
    specification = {"width": width, "height": height, "pixelFormat": "gbrp16le"}
    chain = camera_filter(
        [selected],
        metadata=metadata,
        output=specification,
        source_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        first_frame=first,
        end_frame=last,
    )
    assert isinstance(chain, str)
    result = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-nostdin",
            "-n",
            *camera_input_arguments(0),
            "-i",
            str(path),
            "-map",
            "0:v:0",
            "-an",
            "-vf",
            f"trim=start_frame={first}:end_frame={last},setpts=PTS-STARTPTS," + chain,
            "-frames:v",
            str(last - first),
            "-c:v",
            "ffv1",
            "-pix_fmt",
            "+gbrp16le",
            str(destination),
        ],
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    return pixels(destination, width, height)


def test_identity_camera_preserves_real_sixteen_bit_picture_and_original_bytes(
    tmp_path,
):
    source = labeled_video(tmp_path / "original.mkv", bit_depth=16)
    before = source.read_bytes()
    actual = render(source, tmp_path / "identity.mkv", operation(source, scale=1))
    np.testing.assert_array_equal(actual, pixels(source, 160, 90))
    assert np.any(actual % 257 != 0), (
        "An 8-bit staging conversion discarded source detail"
    )
    assert source.read_bytes() == before
    assert probe(tmp_path / "identity.mkv")["pix_fmt"] == "gbrp16le"


def test_boundary_zoom_preserves_the_final_original_pixel_without_a_dark_border(
    tmp_path,
):
    source = labeled_video(tmp_path / "original.mkv", bit_depth=16)
    selected = operation(source)
    parameters = selected["parameters"]
    parameters["behavior"]["nodes"][-1]["center"] = {"x": 0.6, "y": 0.6}
    parameters["pathHash"] = content_hash(
        {key: parameters[key] for key in ("behavior", "geometry")}
    )
    full = render(source, tmp_path / "boundary.mkv", selected)
    np.testing.assert_array_equal(full[-1, -1, -1], pixels(source, 160, 90)[-1, -1, -1])
    window = render(source, tmp_path / "last-frame.mkv", selected, first=23, last=24)
    np.testing.assert_array_equal(window, full[23:24])


@pytest.mark.parametrize(
    "curve",
    [
        "hold",
        "linear",
        "quadratic-in",
        "quadratic-out",
        "quadratic-in-out",
        "quartic-in",
        "exponential-out",
    ],
)
def test_encoded_windows_use_the_original_path_interval_in_any_seek_order(
    tmp_path, curve
):
    source = labeled_video(
        tmp_path / "original.mkv", bit_depth=16, fps=Fraction(30000, 1001)
    )
    selected = operation(source, curve=curve)
    full = render(source, tmp_path / "full.mkv", selected)
    original = pixels(source, 160, 90)
    np.testing.assert_array_equal(full[0], original[0])
    np.testing.assert_array_equal(full[-1, 70, 0], original[-1, 65, 16])
    parameters = selected["parameters"]
    crop = evaluate_camera(
        parameters["behavior"],
        frame=11,
        frame_range=parameters["originalFrameRange"],
        geometry=parameters["geometry"],
    )["crop"]
    x, y = crop["x"], crop["y"] + 70 * crop["height"] / 90
    ix, iy = int(x), int(y)
    dx, dy = x - ix, y - iy
    expected = (
        original[11, iy, ix].astype(float) * (1 - dx) * (1 - dy)
        + original[11, iy, ix + 1].astype(float) * dx * (1 - dy)
        + original[11, iy + 1, ix].astype(float) * (1 - dx) * dy
        + original[11, iy + 1, ix + 1].astype(float) * dx * dy
    )
    # Independently sample the original at the pure evaluator's crop position.
    # One integer level covers interpolation rounding; window comparisons below
    # still require exact pixels and detect a restarted or stateful native path.
    np.testing.assert_allclose(full[11, 70, 0], expected, rtol=0, atol=1)
    for first, last in ((13, 24), (0, 3), (4, 9), (23, 24), (9, 10)):
        actual = render(
            source, tmp_path / f"window-{first}.mkv", selected, first=first, last=last
        )
        np.testing.assert_array_equal(actual, full[first:last])


def test_single_frame_camera_hold_keeps_its_selected_state(tmp_path):
    source = labeled_video(tmp_path / "original.mkv", bit_depth=16)
    selected = operation(source)
    parameters = selected["parameters"]
    for node in parameters["behavior"]["nodes"]:
        node.update(scale=1.25, curve="hold")
    selected["outputRange"] = {"startFrame": 23, "endFrameExclusive": 24}
    parameters["originalFrameRange"] = {"firstFrame": 23, "endFrameExclusive": 24}
    parameters["pathHash"] = content_hash(
        {key: parameters[key] for key in ("behavior", "geometry")}
    )
    parameters["entryState"] = evaluate_camera(
        parameters["behavior"],
        frame=23,
        frame_range=parameters["originalFrameRange"],
        geometry=parameters["geometry"],
    )
    full = render(source, tmp_path / "full.mkv", selected)
    last = render(source, tmp_path / "last.mkv", selected, first=23, last=24)
    np.testing.assert_array_equal(last, full[23:24])
    np.testing.assert_array_equal(full[:23], pixels(source, 160, 90)[:23])
    assert not np.array_equal(last[0], pixels(source, 160, 90)[23])


def test_baseline_uses_measured_sar_and_rotation_without_changing_orientation_twice(
    tmp_path,
    monkeypatch,
):
    from avo.adapters.media.proof_executor import execute_ffmpeg_proof

    source = labeled_video(tmp_path / "original.mp4", sar=Fraction(2), rotation=90)
    selected = operation(source, sar=Fraction(2), rotation=90, scale=1)
    actual = render(source, tmp_path / "display.mkv", selected, width=90, height=320)
    expected = tmp_path / "expected.mkv"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-nostdin",
            "-n",
            "-noautorotate",
            "-i",
            str(source),
            "-an",
            "-vf",
            # Reference display conversion preserves precision before resizing.
            # It intentionally contains no camera sampler or path expressions.
            (
                "transpose=cclock,scale=iw:ih:flags=bilinear,format=gbrp16le,"
                "scale=90:320:flags=bilinear,setsar=1"
            ),
            "-c:v",
            "ffv1",
            str(expected),
        ],
        capture_output=True,
        check=True,
    )
    np.testing.assert_array_equal(actual, pixels(expected, 90, 320))
    observed = probe(tmp_path / "display.mkv")
    assert observed["sample_aspect_ratio"] == "1:1"
    assert int(observed.get("tags", {}).get("rotate", 0)) % 360 == 0
    assert all(
        item.get("rotation", 0) % 360 == 0
        for item in observed.get("side_data_list", [])
    )
    execution, _, _, _ = native_execution(tmp_path, monkeypatch)
    execution["output"].update(width=90, height=320)
    camera = operation(source, sar=Fraction(2), rotation=90, scale=1)
    execution["videoGraph"]["operations"][1] = camera
    execution["videoGraph"]["operations"][0]["parameters"]["source"].update(
        locator=str(source), sha256=camera["parameters"]["sourceSha256"]
    )
    execution["canonicalInputLock"]["source:camera-main"] = camera["parameters"][
        "sourceSha256"
    ]
    native = tmp_path / "native-display.mkv"
    execute_ffmpeg_proof(execution, native)
    np.testing.assert_array_equal(pixels(native, 90, 320), actual)
    assert all(
        item.get("rotation", 0) % 360 == 0
        for item in probe(native).get("side_data_list", [])
    )
    execution["window"] = {"startFrame": 9, "endFrameExclusive": 17}
    window = tmp_path / "native-display-window.mkv"
    execute_ffmpeg_proof(execution, window)
    np.testing.assert_array_equal(pixels(window, 90, 320), actual[9:17])


@pytest.mark.parametrize(
    "change", ["geometry", "source", "expression", "path-hash", "input"]
)
def test_unverified_source_or_executable_parameters_are_rejected_before_render(
    tmp_path, change
):
    from avo.adapters.media.camera import CameraRenderError, camera_filter

    source = labeled_video(tmp_path / "original.mkv", bit_depth=16)
    selected = operation(source)
    altered = deepcopy(selected)
    if change == "geometry":
        altered["parameters"]["geometry"]["codedWidth"] += 1
        altered["parameters"]["pathHash"] = content_hash(
            {key: altered["parameters"][key] for key in ("behavior", "geometry")}
        )
    elif change == "source":
        altered["parameters"]["sourceSha256"] = "b" * 64
    elif change == "expression":
        altered["parameters"]["expression"] = "untrusted filter"
    elif change == "input":
        altered["inputs"] = ["another-source"]
    else:
        altered["parameters"]["pathHash"] = "b" * 64
    with pytest.raises(CameraRenderError):
        camera_filter(
            [altered],
            metadata=probe(source),
            output={"width": 160, "height": 90, "pixelFormat": "gbrp16le"},
            source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
            first_frame=0,
            end_frame=24,
        )


def native_execution(tmp_path, monkeypatch, *, fps=Fraction(24), bit_depth=16):
    from avo.adapters.media import proof_executor
    from avo.capabilities import default_proof_capability_registry

    source = labeled_video(
        tmp_path / ("raw-picture.mov" if bit_depth == 8 else "raw-picture.mkv"),
        bit_depth=bit_depth,
        fps=fps,
    )
    sample_count = round(Fraction(24 * 48000, 1) / fps)
    dialogue = channel_impulses(tmp_path / "dialogue.wav", sample_count=sample_count)
    camera = operation(source)
    candidate = default_proof_capability_registry()
    # Exercise the shipped implementation rather than declaring readiness here.
    assert candidate.resolve("camera-transform-v1") is not None
    monkeypatch.setattr(
        proof_executor, "default_proof_capability_registry", lambda: candidate
    )
    audio_hash = hashlib.sha256(dialogue.read_bytes()).hexdigest()
    source_hash = camera["parameters"]["sourceSha256"]
    region = {"startSample": 0, "endSampleExclusive": sample_count}
    execution = {
        "schemaVersion": "2.0.0",
        "requiredReaderCapabilities": ["camera-transform-v1"],
        "output": {
            "width": 160,
            "height": 90,
            "frameRate": {"num": fps.numerator, "den": fps.denominator},
            "audioSampleRate": 48000,
            "channelLayout": "stereo",
            "videoCodec": "ffv1",
            "audioCodec": "pcm_s32le",
            "conformance": True,
            "pixelFormat": "gbrp16le",
        },
        "canonicalInputLock": {
            "source:camera-main": source_hash,
            "source:dialogue": audio_hash,
        },
        "implementationRefs": [
            candidate.resolve("trim").proof_reference(),
            candidate.resolve("camera-transform-v1").proof_reference(),
        ],
        "videoGraph": {
            "operations": [
                {
                    "operationId": "trim-original",
                    "kind": "trim",
                    "implementationId": "impl-trim",
                    "inputs": ["camera-main"],
                    "outputRange": {"startFrame": 0, "endFrameExclusive": 24},
                    "parameters": {
                        "sourceId": "camera-main",
                        "source": {
                            "locator": str(source),
                            "sha256": source_hash,
                            "mediaClass": "source",
                            "streamIndex": 0,
                        },
                        "sourceRange": {
                            "startTicks": 0,
                            "endTicks": 24,
                            "timebase": {"num": fps.denominator, "den": fps.numerator},
                        },
                    },
                },
                camera,
            ]
        },
        "audioGraph": {
            "sampleRate": 48000,
            "singleFinalEncode": True,
            "nodes": [
                {
                    "nodeId": "dialogue-node",
                    "kind": "source",
                    "sourceSampleRate": 48000,
                    "targetSampleRate": 48000,
                    "sourceLayout": "stereo",
                    "targetLayout": "stereo",
                    "channelMap": [0, 1],
                    "latencyCompensationSamples": 0,
                    "sourceRange": dict(region),
                    "outputRange": dict(region),
                }
            ],
            "operations": [
                {
                    "operationId": "audio-original",
                    "kind": "trim",
                    "range": dict(region),
                    "parameters": {
                        "nodeId": "dialogue-node",
                        "sourceId": "dialogue",
                        "source": {
                            "locator": str(dialogue),
                            "sha256": audio_hash,
                            "mediaClass": "source",
                            "streamIndex": 0,
                        },
                        "fadeInSamples": 0,
                        "fadeOutSamples": 0,
                    },
                },
                {
                    "operationId": "encode",
                    "kind": "encode",
                    "range": dict(region),
                    "parameters": {},
                },
            ],
        },
        "events": [],
        "window": None,
    }
    return execution, source, dialogue, camera


def audio_samples(path):
    result = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            str(path),
            "-map",
            "0:a:0",
            "-f",
            "f32le",
            "pipe:1",
        ],
        capture_output=True,
        check=True,
    )
    return np.frombuffer(result.stdout, dtype="<f4").reshape(-1, 2)


@pytest.mark.parametrize("fps", [Fraction(24), Fraction(30000, 1001)])
def test_normal_native_proof_applies_camera_and_preserves_independent_audio(
    tmp_path, monkeypatch, fps
):
    from avo.adapters.media.proof_executor import execute_ffmpeg_proof

    execution, source, dialogue, camera = native_execution(
        tmp_path, monkeypatch, fps=fps
    )
    before = deepcopy(execution)
    original_bytes = source.read_bytes(), dialogue.read_bytes()
    expected = render(source, tmp_path / "kernel-reference.mkv", camera)
    from avo.adapters.media import proof_executor

    pieces = []
    original_piece = proof_executor._render_piece

    def observe_piece(*args, **kwargs):
        original_piece(*args, **kwargs)
        pieces.append(pixels(args[6], 160, 90))

    monkeypatch.setattr(proof_executor, "_render_piece", observe_piece)
    from avo.adapters.media.timeline_render import TimelineRenderAdapter

    readiness = TimelineRenderAdapter().proof_tool_readiness(execution)
    full_path = tmp_path / "native.mkv"
    result = execute_ffmpeg_proof(execution, full_path)
    provenance = result["producer"]["camera"]
    assert provenance["runtime"]["ffmpeg"]["version"].startswith("ffmpeg version ")
    assert len(provenance["runtime"]["ffprobe"]["sha256"]) == 64
    assert provenance["window"] is None
    assert provenance["environmentHash"] == readiness["cameraEnvironmentHash"]
    np.testing.assert_array_equal(pieces[0], expected)
    np.testing.assert_array_equal(pixels(full_path, 160, 90), expected)
    np.testing.assert_array_equal(audio_samples(full_path), audio_samples(dialogue))
    assert result["audioEncodeCount"] == 1
    assert probe(full_path)["pix_fmt"] == "gbrp16le"
    execution["window"] = {"startFrame": 7, "endFrameExclusive": 18}
    window_path = tmp_path / "native-window.mkv"
    execute_ffmpeg_proof(execution, window_path)
    np.testing.assert_array_equal(pixels(window_path, 160, 90), expected[7:18])
    np.testing.assert_array_equal(
        audio_samples(window_path),
        audio_samples(dialogue)[round(7 * 48000 / fps) : round(18 * 48000 / fps)],
    )
    execution["window"] = None
    assert execution == before
    assert (source.read_bytes(), dialogue.read_bytes()) == original_bytes


@pytest.mark.parametrize(
    "profile",
    ["retimed", "past-eof", "fractional-frame", "reduced-depth", "baseline-aspect"],
)
def test_camera_rejects_unqualified_profiles_before_creating_outputs(
    tmp_path, monkeypatch, profile
):
    from avo.adapters.media.proof_executor import execute_ffmpeg_proof

    execution, _, _, _ = native_execution(tmp_path, monkeypatch)
    source_range = execution["videoGraph"]["operations"][0]["parameters"]["sourceRange"]
    if profile == "retimed":
        source_range["endTicks"] = 23
    elif profile == "past-eof":
        source_range.update(startTicks=1, endTicks=25)
    elif profile == "fractional-frame":
        source_range.update(startTicks=1, endTicks=49, timebase={"num": 1, "den": 48})
    elif profile == "baseline-aspect":
        execution["output"]["height"] = 160
    else:
        execution["output"]["pixelFormat"] = "yuv420p"
    destination = tmp_path / "uncreated" / "proof.mkv"
    with pytest.raises((RuntimeError, ValueError)):
        execute_ffmpeg_proof(execution, destination)
    assert not destination.parent.exists()


@pytest.mark.parametrize("tags", [("smpte2084", "bt2020"), ("bt709", "smpte432")])
def test_actual_hdr_or_wide_gamut_source_tags_fail_preflight(
    tmp_path, monkeypatch, tags
):
    from avo.adapters.media.proof_executor import execute_ffmpeg_proof

    execution, source, _, camera = native_execution(tmp_path, monkeypatch)
    tagged = tmp_path / "tagged-original.mkv"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-nostdin",
            "-n",
            "-i",
            str(source),
            "-c",
            "copy",
            "-color_trc",
            tags[0],
            "-color_primaries",
            tags[1],
            str(tagged),
        ],
        capture_output=True,
        check=True,
    )
    assert probe(tagged)["color_transfer"] == tags[0]
    digest = hashlib.sha256(tagged.read_bytes()).hexdigest()
    original = execution["videoGraph"]["operations"][0]["parameters"]["source"]
    original.update(locator=str(tagged), sha256=digest)
    camera["parameters"]["sourceSha256"] = digest
    execution["canonicalInputLock"]["source:camera-main"] = digest
    destination = tmp_path / "uncreated" / "proof.mkv"
    with pytest.raises(ValueError, match="HDR/wide-gamut"):
        execute_ffmpeg_proof(execution, destination)
    assert not destination.parent.exists()


def test_camera_phase_survives_an_exact_source_cut(tmp_path, monkeypatch):
    from avo.adapters.media.proof_executor import execute_ffmpeg_proof

    execution, source, dialogue, camera = native_execution(tmp_path, monkeypatch)
    trim = execution["videoGraph"]["operations"][0]
    right = deepcopy(trim)
    trim["outputRange"]["endFrameExclusive"] = 12
    trim["parameters"]["sourceRange"]["endTicks"] = 12
    right["operationId"] = "trim-second"
    right["outputRange"]["startFrame"] = 12
    right["parameters"]["sourceRange"]["startTicks"] = 12
    following = deepcopy(camera)
    camera["outputRange"]["endFrameExclusive"] = 12
    following["operationId"] = "camera-second"
    following["outputRange"]["startFrame"] = 12
    following["parameters"]["sourceOccurrenceId"] = "trim-second"
    execution["videoGraph"]["operations"] = [trim, right, camera, following]
    reference = deepcopy(following)
    reference["outputRange"]["startFrame"] = 0
    expected = render(source, tmp_path / "unsplit-reference.mkv", reference)
    full = tmp_path / "split.mkv"
    execute_ffmpeg_proof(execution, full)
    np.testing.assert_array_equal(pixels(full, 160, 90), expected)
    np.testing.assert_array_equal(audio_samples(full), audio_samples(dialogue))
    execution["window"] = {"startFrame": 9, "endFrameExclusive": 16}
    window = tmp_path / "cross-cut.mkv"
    execute_ffmpeg_proof(execution, window)
    np.testing.assert_array_equal(pixels(window, 160, 90), expected[9:16])


def admitted_overlay(tmp_path):
    from avo.timeline.contracts import file_fingerprint
    from avo.timeline.generated_assets import GeneratedAssetService

    path = labeled_video(tmp_path / "graphic.mkv", size=(40, 32), alpha=True)
    lock = {"instanceId": "fixed-graphic", "generator": "fixture.ffmpeg", "seed": 7}
    lock["inputLockHash"] = content_hash(lock)
    lock_path = tmp_path / "graphic.input-lock.json"
    lock_path.write_text(json.dumps(lock), encoding="utf-8")
    service = GeneratedAssetService(
        SimpleNamespace(timeline_dir=tmp_path / "edit/timeline")
    )
    import shutil

    record = service.register(
        {
            "assetId": "fixed-graphic",
            "role": "overlay",
            "generator": {
                "adapterId": "fixture.ffmpeg",
                "version": "1",
                "executableSha256": file_fingerprint(Path(shutil.which("ffmpeg")))[
                    "sha256"
                ],
            },
            "parameters": {
                "instanceId": "fixed-graphic",
                "inputLockHash": lock["inputLockHash"],
            },
            "inputs": [
                {
                    "artifactId": "fixture-input-lock",
                    "fingerprint": file_fingerprint(lock_path),
                    "ancestryRole": "dependency",
                }
            ],
            "sourceFree": True,
            "environment": {
                "platform": "test",
                "dependencies": {"encoder": "actual-ffmpeg"},
            },
            "output": file_fingerprint(path),
            "reproducibility": "verified",
            "approvalReference": None,
        }
    )
    service.admit("fixed-graphic")
    return {
        "record": record,
        "receipt": service.path("fixed-graphic"),
        "lock": lock,
        "lock_path": lock_path,
        "path": path,
    }


def test_fixed_caption_and_credit_layers_preserve_camera_precision_and_window_phase(
    tmp_path, monkeypatch
):
    from tests.integration.test_code_drawn_proof_executor import _add_generated

    from avo.adapters.media.proof_executor import execute_ffmpeg_proof

    execution, source, dialogue, camera = native_execution(tmp_path, monkeypatch)
    asset = admitted_overlay(tmp_path)
    for identity, role, first, last, x, y, order in (
        ("credit", "overlay", 3, 20, 7, 5, 10),
        ("caption", "caption", 6, 18, 30, 60, 20),
    ):
        selected = _add_generated(
            execution,
            asset,
            kind="overlay-video",
            start=first,
            end=last,
            local_start=0,
            operation_id=identity,
            role=role,
            z_order=order,
        )
        selected["parameters"]["placement"].update(x=x, y=y)
    expected = render(source, tmp_path / "camera-reference.mkv", camera)
    full = tmp_path / "layered.mkv"
    execute_ffmpeg_proof(execution, full)
    actual = pixels(full, 160, 90)
    # Camera sampling cannot touch fixed output-space graphics. Outside their
    # rectangles the original 16-bit values must remain exact, including low bits.
    mask = np.ones((90, 160), dtype=bool)
    mask[5:29, 7:47] = False
    mask[60:84, 30:70] = False
    np.testing.assert_array_equal(actual[:, mask], expected[:, mask])
    np.testing.assert_array_equal(actual[:3], expected[:3])
    np.testing.assert_array_equal(actual[20:], expected[20:])
    assert not np.array_equal(actual[10], expected[10])
    np.testing.assert_array_equal(audio_samples(full), audio_samples(dialogue))
    for first, last in ((13, 24), (0, 3), (4, 9)):
        execution["window"] = {"startFrame": first, "endFrameExclusive": last}
        window = tmp_path / f"layered-{first}.mkv"
        execute_ffmpeg_proof(execution, window)
        np.testing.assert_array_equal(pixels(window, 160, 90), actual[first:last])


def placed_execution(tmp_path, monkeypatch, *, fps=Fraction(24), bit_depth=16):
    from avo.capabilities import default_proof_capability_registry

    execution, source, dialogue, camera = native_execution(
        tmp_path, monkeypatch, fps=fps, bit_depth=bit_depth
    )
    original = execution["videoGraph"]["operations"][0]
    implementation = default_proof_capability_registry().resolve("source-layout")
    execution["implementationRefs"].append(implementation.proof_reference())
    placement = {
        "placementId": "trim-original",
        "trackId": "presenter",
        "mediaKind": "video",
        "outputRange": deepcopy(original["outputRange"]),
        "enabled": True,
        "zOrder": 0,
        **deepcopy(original["parameters"]),
    }
    execution["videoGraph"]["operations"][0] = {
        "operationId": "placed-picture",
        "kind": "source-layout",
        "implementationId": implementation.implementation_id,
        "inputs": ["camera-main"],
        "outputRange": deepcopy(original["outputRange"]),
        "parameters": {"background": "black", "placements": [placement]},
    }
    return execution, source, dialogue, camera


def test_placed_camera_preserves_sixteen_bit_layers_audio_and_bounded_window_frames(
    tmp_path, monkeypatch
):
    from tests.integration.test_code_drawn_proof_executor import _add_generated

    from avo.adapters.media import proof_bounded
    from avo.adapters.media.proof_executor import execute_ffmpeg_proof

    monkeypatch.setattr(proof_bounded, "MAX_CHUNK_FRAMES", 7)
    execution, source, dialogue, camera = placed_execution(tmp_path, monkeypatch)
    asset = admitted_overlay(tmp_path)
    caption = _add_generated(
        execution,
        asset,
        kind="overlay-video",
        start=3,
        end=20,
        local_start=0,
        role="caption",
    )
    caption["parameters"]["placement"].update(x=7, y=5)
    expected = render(source, tmp_path / "original-only-reference.mkv", camera)
    full = tmp_path / "placed.mkv"
    execute_ffmpeg_proof(execution, full)
    actual = pixels(full, 160, 90)
    mask = np.ones((90, 160), dtype=bool)
    mask[5:29, 7:47] = False
    np.testing.assert_array_equal(actual[:, mask], expected[:, mask])
    assert not np.array_equal(actual[10], expected[10])
    np.testing.assert_array_equal(audio_samples(full), audio_samples(dialogue))
    for first, last in ((13, 24), (0, 3), (4, 9)):
        execution["window"] = {"startFrame": first, "endFrameExclusive": last}
        window = tmp_path / f"placed-{first}.mkv"
        execute_ffmpeg_proof(execution, window)
        np.testing.assert_array_equal(pixels(window, 160, 90), actual[first:last])


def test_placed_foreground_retains_original_rgb_detail_and_independent_source_alpha(
    tmp_path, monkeypatch
):
    from tests.integration.test_code_drawn_proof_executor import _frames

    from avo.adapters.media import proof_bounded
    from avo.adapters.media.proof_executor import execute_ffmpeg_proof
    from avo.timeline.import_layout import picture_input_ids

    monkeypatch.setattr(proof_bounded, "MAX_CHUNK_FRAMES", 7)
    execution, source, dialogue, camera = placed_execution(tmp_path, monkeypatch)
    layout = execution["videoGraph"]["operations"][0]
    foreground = labeled_video(
        tmp_path / "raw-foreground.mkv", size=(48, 32), bit_depth=16
    )
    alpha = labeled_video(tmp_path / "raw-alpha.mkv", size=(32, 32), alpha=True)
    for identity, path, x, y, width, height, order in (
        ("foreground", foreground, 110, 10, 48, 32, 1),
        ("alpha-picture", alpha, 70, 50, 32, 32, 2),
    ):
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        placement = deepcopy(layout["parameters"]["placements"][0])
        placement.update(
            placementId=identity,
            trackId=identity,
            sourceId=identity,
            zOrder=order,
            source={
                "locator": str(path),
                "sha256": digest,
                "mediaClass": "source",
                "streamIndex": 0,
            },
            pictureTransform={
                "canvasWidth": 160,
                "canvasHeight": 90,
                "x": x,
                "y": y,
                "width": width,
                "height": height,
            },
        )
        layout["parameters"]["placements"].append(placement)
        execution["canonicalInputLock"][f"source:{identity}"] = digest
    layout["inputs"] = picture_input_ids(layout["parameters"]["placements"])
    expected = render(source, tmp_path / "camera-reference.mkv", camera)
    output = tmp_path / "source-layers.mkv"
    execute_ffmpeg_proof(execution, output)
    actual = pixels(output, 160, 90)
    np.testing.assert_array_equal(actual[:, 10:42, 110:158], pixels(foreground, 48, 32))
    rgba = _frames(alpha, width=32, height=32)
    layer = actual[:, 50:82, 70:102]
    transparent, opaque = rgba[..., 3] == 0, rgba[..., 3] == 255
    np.testing.assert_array_equal(
        layer[transparent], expected[:, 50:82, 70:102][transparent]
    )
    # Independent eight-bit alpha remains at its declared precision. Original
    # sixteen-bit opaque picture outside it must retain every low bit exactly.
    np.testing.assert_array_equal(
        np.rint(layer[opaque] / 257).astype(np.uint8), rgba[..., :3][opaque]
    )
    np.testing.assert_array_equal(audio_samples(output), audio_samples(dialogue))
    execution["window"] = {"startFrame": 9, "endFrameExclusive": 17}
    window = tmp_path / "source-layer-window.mkv"
    execute_ffmpeg_proof(execution, window)
    np.testing.assert_array_equal(pixels(window, 160, 90), actual[9:17])


def test_placed_camera_keeps_the_closed_original_input_policy_after_admission(
    tmp_path, monkeypatch
):
    from avo.adapters.media.proof_placed import (
        _admit_picture,
        _admit_precision_picture,
        _stage_picture,
    )

    execution, original, _, _ = placed_execution(tmp_path, monkeypatch)
    cache = {}
    admitted = _admit_picture(
        execution,
        execution["videoGraph"]["operations"][0]["parameters"]["placements"],
        24,
        Fraction(24),
        cache,
    )
    _admit_precision_picture(
        execution, admitted, cache, execution["output"], Fraction(24)
    )
    before = original.read_bytes()
    (tmp_path / "unadmitted.mkv").write_bytes(before)
    try:
        # Fault injection after successful admission: a replacement container
        # must not redirect the decoder to an unconsumed child media file.
        original.write_text(
            "ffconcat version 1.0\nfile 'unadmitted.mkv'\n", encoding="utf-8"
        )
        output = tmp_path / "must-not-exist.mkv"
        with pytest.raises(RuntimeError, match="whitelist"):
            _stage_picture(admitted[0], output, execution["output"], Fraction(24))
        assert not output.exists()
    finally:
        original.write_bytes(before)
