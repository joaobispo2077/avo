"""Face association follows only the creator's selected geometric seed."""

import pytest

from avo.model_sources import PreflightError, preflight, resolve_job
from avo.reference_analysis import associate_selected_face


def sample(tick, *boxes):
    return {
        "sourceTick": tick,
        "detections": [{"box": box, "score": 0.95} for box in boxes],
    }


def track(frames, *, seed=(0, 1), max_gap=2):
    return associate_selected_face(
        {
            "frames": frames,
            "seed": {"sourceTick": seed[0], "detectionIndex": seed[1]},
            "minimumOverlap": 0.3,
            "maximumGapTicks": max_gap,
        }
    )


LEFT = [0.1, 0.2, 0.2, 0.3]
RIGHT = [0.65, 0.2, 0.2, 0.3]
MOVED = [0.63, 0.2, 0.2, 0.3]


def test_selected_subject_follows_overlap_when_detection_order_changes():
    result = track([sample(0, LEFT, RIGHT), sample(1, MOVED, LEFT)])
    assert [entry["status"] for entry in result] == ["selected", "selected"]
    assert [entry["detectionIndex"] for entry in result] == [1, 0]
    assert result[1]["overlap"] == pytest.approx(0.18 / 0.22)


def test_two_plausible_faces_abstain_and_require_a_new_seed():
    result = track(
        [
            sample(0, LEFT, RIGHT),
            sample(1, MOVED, [0.68, 0.2, 0.2, 0.3]),
            sample(2, MOVED),
        ]
    )
    assert [entry["status"] for entry in result] == [
        "selected",
        "ambiguous",
        "reseed-required",
    ]
    assert result[1]["detectionIndex"] is None
    assert result[2]["detectionIndex"] is None


def test_missing_face_does_not_switch_to_a_different_subject():
    result = track([sample(0, LEFT, RIGHT), sample(1, LEFT), sample(2, MOVED)])
    assert [entry["status"] for entry in result] == [
        "selected",
        "lost",
        "reseed-required",
    ]
    assert result[1]["overlap"] is None


def test_unobserved_interval_and_preseed_samples_remain_explicit():
    result = track([sample(0, LEFT), sample(1, RIGHT), sample(4, MOVED)], seed=(1, 0))
    assert [entry["status"] for entry in result] == ["unselected", "selected", "gap"]
    assert [entry["sourceTick"] for entry in result] == [0, 1, 4]


@pytest.mark.parametrize(
    ("frames", "seed", "message"),
    [
        ([sample(0, RIGHT)], (0, 1), "exact sampled detection"),
        ([sample(0, RIGHT), sample(0, MOVED)], (0, 0), "increasing source ticks"),
        ([sample(0, [0.9, 0.2, 0.2, 0.3])], (0, 0), "display bounds"),
        ([sample(0, [0.0, 0.0, 1e-200, 1e-200])], (0, 0), "display bounds"),
    ],
)
def test_invalid_seed_clock_or_geometry_cannot_anchor_a_face(frames, seed, message):
    with pytest.raises(ValueError, match=message):
        track(frames, seed=seed)


def test_face_model_pin_reports_unavailable_without_a_local_runtime(monkeypatch):
    monkeypatch.setattr("avo.models.load_config", lambda root: {})
    selected = resolve_job("face_detect", state={})
    assert selected.id == "yunet-2023mar"
    with pytest.raises(PreflightError) as error:
        preflight(selected)
    assert error.value.code == "face_runtime_unavailable"


def test_face_model_preflight_checks_bytes_before_running_an_interpreter(
    tmp_path, monkeypatch
):
    artifact = tmp_path / "unverified.onnx"
    artifact.write_bytes(b"not the pinned model")
    python = tmp_path / "separate-python.exe"
    python.write_bytes(b"interpreter fixture")
    selected = resolve_job(
        "face_detect",
        invocation={
            "id": "yunet-2023mar",
            "source": {"kind": "artifact", "artifactPath": str(artifact)},
            "runtime": {"device": "cpu", "pythonEnv": str(python)},
        },
    )

    def forbidden(*args, **kwargs):
        pytest.fail("Unverified model bytes reached the optional runtime")

    monkeypatch.setattr("subprocess.run", forbidden)
    with pytest.raises(PreflightError, match="exact pinned YuNet 2023 model bytes"):
        preflight(selected)


def test_proxy_boxes_map_to_original_display_fractions_at_original_ticks():
    from avo.reference_analysis import map_proxy_face_samples

    rect = {"x": 0, "y": 40, "width": 320, "height": 240}
    responses = [
        [{"box": [32, 88, 64, 72], "score": 0.95}],
        [{"box": [290, 22, 70, 78], "score": 0.93}],
        [{"box": [0, 0, 30, 20], "score": 0.91}],
    ]
    frames = map_proxy_face_samples(responses, [7250, 7500, 7900], rect)
    assert frames == [
        sample(7250, [0.1, 0.2, 0.2, 0.3]),
        {
            "sourceTick": 7500,
            "detections": [{"box": [0.90625, 0.0, 0.09375, 0.25], "score": 0.93}],
        },
        sample(7900),
    ]


def test_proxy_frame_responses_cannot_use_inferred_or_repeated_source_ticks():
    from avo.reference_analysis import map_proxy_face_samples

    rect = {"x": 0, "y": 0, "width": 320, "height": 240}
    with pytest.raises(ValueError, match="exact source ticks"):
        map_proxy_face_samples([[], []], [20], rect)
    with pytest.raises(ValueError, match="increasing source ticks"):
        map_proxy_face_samples([[], []], [20, 20], rect)


def observation_inputs():
    from avo.visual_motion_runtime import VERSIONS, YUNET_SHA256

    request = {
        "contractVersion": "1.0.0",
        "source": {"sourceId": "camera", "sha256": "a" * 64, "sizeBytes": 1000},
        "sourceRange": {
            "startTicks": 24000,
            "endTicks": 25920,
            "timebase": {"num": 1, "den": 48000},
        },
        "geometry": {
            "width": 1080,
            "height": 1920,
            "rotation": 90,
            "sampleAspectRatio": {"num": 1, "den": 1},
        },
        "proxy": {
            "sha256": "b" * 64,
            "width": 320,
            "height": 240,
            "content": {"x": 0, "y": 30, "width": 320, "height": 180},
            "sourceTicks": [24000, 24960],
        },
        "seed": {"sourceTick": 24000, "detectionIndex": 0},
        "minimumOverlap": 0.3,
        "maximumGapTicks": 960,
    }
    observed = {
        "device": "cpu",
        "isolated": True,
        "modelSha256": YUNET_SHA256,
        "versions": VERSIONS,
        "proxySha256": "b" * 64,
        "detections": [[{"box": [32, 48, 40, 50], "score": 0.95}], []],
    }
    return request, observed


def test_frozen_face_observation_contains_exact_source_proxy_and_measurement():
    from avo.reference_analysis import freeze_face_observation

    request, observations = observation_inputs()
    result = freeze_face_observation(request, observations)
    assert result["request"] == request
    assert result["detector"]["modelSha256"] == observations["modelSha256"]
    assert result["coverage"] == {"observedFrames": 2, "selectedFrames": 1}
    assert result["association"][1]["status"] == "lost"
    changed = {**request, "source": {**request["source"], "sha256": "c" * 64}}
    assert (
        freeze_face_observation(changed, observations)["analysisHash"]
        != result["analysisHash"]
    )


@pytest.mark.parametrize(
    ("field", "message"),
    [
        ("geometry", "display aspect"),
        ("range", "source range"),
        ("proxy", "proxy identity"),
    ],
)
def test_face_observation_rejects_inconsistent_observed_scope(field, message):
    from avo.reference_analysis import freeze_face_observation

    request, observations = observation_inputs()
    if field == "geometry":
        request["geometry"]["rotation"] = 0
    elif field == "range":
        request["sourceRange"]["endTicks"] = 24960
    else:
        observations["proxySha256"] = "c" * 64
    with pytest.raises(ValueError, match=message):
        freeze_face_observation(request, observations)
