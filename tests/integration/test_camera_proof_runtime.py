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
    from avo.adapters.media.camera import camera_filter

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
            "-noautorotate",
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
    assert not np.array_equal(full[-1], pixels(source, 160, 90)[-1])
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
):
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


def native_execution(tmp_path, monkeypatch, *, fps=Fraction(24)):
    from avo.adapters.media import proof_executor
    from avo.capabilities import (
        CapabilityImplementation,
        default_proof_capability_registry,
    )

    source = labeled_video(tmp_path / "raw-picture.mkv", bit_depth=16, fps=fps)
    sample_count = round(Fraction(24 * 48000, 1) / fps)
    dialogue = channel_impulses(tmp_path / "dialogue.wav", sample_count=sample_count)
    camera = operation(source)
    candidate = default_proof_capability_registry()
    # Qualification candidate only; the shipped registry stays unavailable until
    # the complete native composition/profile tests qualify its execution.
    candidate.register(
        CapabilityImplementation(
            implementation_id="impl-camera-transform",
            capability="camera-transform-v1",
            kind="built-in",
            adapter_id="ffmpeg.camera-transform",
            version="1.0.0",
            sha256="c" * 64,
        )
    )
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


def placed_execution(tmp_path, monkeypatch):
    from avo.capabilities import default_proof_capability_registry

    execution, source, dialogue, camera = native_execution(tmp_path, monkeypatch)
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
