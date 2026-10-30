"""The native full-node dialogue recipe survives exact microproof seeking."""

from copy import deepcopy
from fractions import Fraction

import numpy as np
import pytest
from tests.integration.test_ffmpeg_proof_executor import _execution, _pcm
from tests.integration.test_proof_audio_mix_executor import _with_music

from avo.adapters.media.proof_executor import execute_ffmpeg_proof
from avo.audio_restoration import validate_dialogue_treatment_policy


def _policy():
    return {
        "mode": "clarity-v1",
        "role": "presenter-dialogue",
        "approvedByUser": True,
        "highpassHz": 80,
        "compression": {
            "thresholdDb": -26,
            "ratio": 3,
            "attackMs": 15,
            "releaseMs": 100,
        },
        "makeupGainDb": 6,
        "limiter": {
            "ceilingDbfs": -3,
            "attackMs": 5,
            "releaseMs": 50,
            "latencyCompensated": True,
        },
    }


def test_native_dialogue_treatment_is_identical_in_full_and_window(tmp_path):
    execution = _execution(tmp_path)
    execution["output"].update(
        conformance=True, videoCodec="ffv1", audioCodec="pcm_s32le"
    )
    execution["audioGraph"]["operations"][0]["parameters"][
        "dialogueTreatmentPolicy"
    ] = _policy()
    full = tmp_path / "full.mkv"
    result = execute_ffmpeg_proof(execution, full)
    assert len(result["sourceDialogueTreatmentPolicies"]) == 1
    execution["window"] = {"startFrame": 12, "endFrameExclusive": 33}
    micro = tmp_path / "micro.mkv"
    execute_ffmpeg_proof(execution, micro)
    start, end = [round(Fraction(frame * 1001 * 48000, 30000)) for frame in (12, 33)]
    np.testing.assert_allclose(_pcm(micro), _pcm(full)[start:end], atol=2e-7)


def test_dialogue_policy_is_not_silently_ignored_on_music(tmp_path):
    execution = _with_music(_execution(tmp_path))
    for operation in execution["audioGraph"]["operations"]:
        if operation["operationId"] == "music-trim":
            operation["parameters"]["dialogueTreatmentPolicy"] = deepcopy(_policy())
    target = tmp_path / "must-not-exist.mp4"
    with pytest.raises(ValueError, match="Dialogue"):
        execute_ffmpeg_proof(execution, target)
    assert not target.exists()


def test_policy_used_by_native_kernel_is_valid():
    assert validate_dialogue_treatment_policy(_policy()) == _policy()
