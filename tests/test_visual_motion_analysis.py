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
