"""Placed source geometry preserves lower layers and fades on absolute clocks."""

import shutil
from copy import deepcopy
from fractions import Fraction

import numpy as np
import pytest
from tests.integration.test_otio_placed_render_runtime import _decoded, _execution

from avo.adapters.media.proof_placed import execute_placed_proof

pytestmark = pytest.mark.skipif(
    not shutil.which("ffmpeg") or not shutil.which("ffprobe"),
    reason="Native FFmpeg required",
)


def test_transform_alpha_fade_and_microproof_use_the_same_source_graph(tmp_path):
    request, _ = _execution(tmp_path)
    item = next(
        i
        for i in request["videoGraph"]["operations"][0]["parameters"]["placements"]
        if i["placementId"] == "still"
    )
    item["pictureTransform"] = {
        "canvasWidth": 64,
        "canvasHeight": 48,
        "x": 4,
        "y": 7,
        "width": 16,
        "height": 12,
    }
    item["pictureFade"] = {"inFrames": 0, "outFrames": 6}
    base = deepcopy(request)
    op = base["videoGraph"]["operations"][0]
    op["parameters"]["placements"] = [
        i for i in op["parameters"]["placements"] if i["placementId"] != "still"
    ]
    op["inputs"] = sorted({i["sourceId"] for i in op["parameters"]["placements"]})
    baseline = tmp_path / "baseline.mkv"
    execute_placed_proof(base, baseline, base["output"], Fraction(24), 48000)
    full = tmp_path / "treated.mkv"
    execute_placed_proof(request, full, request["output"], Fraction(24), 48000)
    expected = _decoded(baseline)
    actual = _decoded(full)
    assert np.array_equal(actual[:54], expected[:54])
    assert np.array_equal(actual[66:], expected[66:])
    assert np.array_equal(actual[54:66, :, :4], expected[54:66, :, :4])
    assert np.array_equal(actual[54:66, :7], expected[54:66, :7])
    assert np.array_equal(
        actual[54, 7:19, 4:20],
        np.tile(np.array([0, 180, 0], dtype=np.uint8), (12, 16, 1)),
    )
    assert np.all(
        np.abs(
            actual[65, 8, 5].astype(float)
            - (np.array([0, 180, 0]) / 6 + expected[65, 8, 5] * 5 / 6)
        )
        <= 2
    )
    assert np.array_equal(_decoded(full, audio=True), _decoded(baseline, audio=True))
    request["window"] = {"startFrame": 60, "endFrameExclusive": 66}
    micro = tmp_path / "micro-treated.mkv"
    execute_placed_proof(request, micro, request["output"], Fraction(24), 48000)
    assert np.array_equal(_decoded(micro), actual[60:66])
