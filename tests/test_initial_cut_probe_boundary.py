from copy import deepcopy

import pytest

from avo.timeline.initial_cut import initial_cut_proof_request
from test_initial_cut_request import workspace


def test_sample_rate_probe_is_injected_cached_and_skipped_for_declared_rate(tmp_path):
    project, snapshot = workspace(tmp_path)
    snapshot["protectedQuizWindows"] = []
    del snapshot["sources"][0]["streamMetadata"]["audioSelection"]["sourceSampleRate"]
    snapshot["segments"].insert(1, deepcopy(snapshot["segments"][0]))
    calls = []

    def probe(selection, locator):
        calls.append((selection["streamIndex"], locator.name))
        return 44100

    result = initial_cut_proof_request(
        project,
        iteration_id="probe-boundary",
        output=tmp_path / "proof.mp4",
        frame_rate={"num": 30, "den": 1},
        sample_rate_probe=probe,
    )
    assert calls == [(2, "camera-1.mkv")]
    assert [node["sourceSampleRate"] for node in result["audioGraph"]["nodes"]] == [
        44100,
        44100,
        48000,
    ]


def test_sample_rate_probe_failure_is_not_hidden(tmp_path):
    project, snapshot = workspace(tmp_path)
    del snapshot["sources"][0]["streamMetadata"]["audioSelection"]["sourceSampleRate"]

    def probe(selection, locator):
        raise ValueError("canonical selected stream must contain audio")

    with pytest.raises(ValueError, match="selected stream must contain audio"):
        initial_cut_proof_request(
            project,
            iteration_id="probe-boundary",
            output=tmp_path / "proof.mp4",
            frame_rate={"num": 30, "den": 1},
            sample_rate_probe=probe,
        )
