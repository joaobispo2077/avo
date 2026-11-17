"""Privacy remains opaque above imported fades at exact micro/full frames."""

import shutil
from copy import deepcopy
from fractions import Fraction

import numpy as np
import pytest
from tests.integration.test_otio_placed_render_runtime import _decoded, _execution
from tests.test_import_privacy_masks import privacy_masks

from avo.adapters.media.proof_placed import execute_placed_proof

pytestmark = pytest.mark.skipif(
    not shutil.which("ffmpeg") or not shutil.which("ffprobe"),
    reason="Native FFmpeg required",
)


def test_privacy_is_opaque_through_fades_without_touching_other_picture_or_pcm(
    tmp_path,
):
    request, _ = _execution(tmp_path)
    still = next(
        p
        for p in request["videoGraph"]["operations"][0]["parameters"]["placements"]
        if p["placementId"] == "still"
    )
    still["pictureFade"] = {"inFrames": 0, "outFrames": 6}
    baseline = tmp_path / "baseline.mkv"
    execute_placed_proof(request, baseline, request["output"], Fraction(24), 48000)
    masked = deepcopy(request)
    masks = privacy_masks()
    masks["regions"][0].update(startFrame=53, endFrameExclusive=67)
    masked["videoGraph"]["operations"][0]["parameters"]["privacyMasks"] = masks
    output = tmp_path / "masked.mkv"
    execute_placed_proof(masked, output, masked["output"], Fraction(24), 48000)
    before, after = _decoded(baseline), _decoded(output)
    assert np.all(after[53:67, 5:12, 4:15] == 0)
    expected = before.copy()
    expected[53:67, 5:12, 4:15] = 0
    assert np.array_equal(after, expected)
    assert np.array_equal(_decoded(output, audio=True), _decoded(baseline, audio=True))
    masked["window"] = {"startFrame": 52, "endFrameExclusive": 68}
    micro = tmp_path / "masked-micro.mkv"
    execute_placed_proof(masked, micro, masked["output"], Fraction(24), 48000)
    assert np.array_equal(_decoded(micro), after[52:68])
