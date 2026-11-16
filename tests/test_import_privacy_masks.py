"""Opaque privacy regions remain canonical, bounded and frame addressed."""

from copy import deepcopy
from fractions import Fraction
from types import SimpleNamespace

import pytest

from avo.timeline.import_layout import LayoutError, validate_layout
from avo.timeline.initial_cut_placed import _picture
from tests.test_automatic_timeline_import import _export, _service, fixtures
from tests.test_timeline_import_layout import placed_snapshot

project_fixture = pytest.fixture(name="import_project")(
    fixtures.import_project.__wrapped__
)


def privacy_masks():
    return {
        "canvasWidth": 128,
        "canvasHeight": 96,
        "regions": [
            {
                "maskId": "account-name",
                "startFrame": 12,
                "endFrameExclusive": 48,
                "x": 9,
                "y": 11,
                "width": 21,
                "height": 13,
            }
        ],
    }


def test_privacy_regions_are_frozen_in_the_canonical_source_graph(tmp_path):
    snapshot = placed_snapshot()
    snapshot["layout"]["privacyMasks"] = privacy_masks()
    validate_layout(snapshot)
    graph = _picture(
        snapshot,
        {"camera": {**snapshot["sources"][0], "locator": str(tmp_path / "raw.mkv")}},
        {t["trackId"]: t for t in snapshot["layout"]["tracks"]},
        SimpleNamespace(raw_dir=tmp_path),
        Fraction(24),
        96,
    )
    frozen = graph["operations"][0]["parameters"]["privacyMasks"]
    assert frozen == snapshot["layout"]["privacyMasks"]
    snapshot["layout"]["privacyMasks"]["regions"][0]["x"] = 0
    assert frozen["regions"][0]["x"] == 9


@pytest.mark.parametrize(
    "defect",
    [
        "canvas",
        "outside",
        "duration",
        "reversed",
        "duplicate",
        "opacity",
        "fraction",
        "boolean",
        "empty",
    ],
)
def test_privacy_masks_reject_ambiguous_or_incomplete_coverage(defect):
    snapshot = placed_snapshot()
    masks = privacy_masks()
    region = masks["regions"][0]
    if defect == "canvas":
        masks["canvasWidth"] = 256
    elif defect == "outside":
        region["x"] = 120
    elif defect == "duration":
        region["endFrameExclusive"] = 97
    elif defect == "reversed":
        region["endFrameExclusive"] = region["startFrame"]
    elif defect == "duplicate":
        masks["regions"].append(deepcopy(region))
    elif defect == "opacity":
        region["opacity"] = 0.5
    elif defect == "fraction":
        region["startFrame"] = 1.5
    elif defect == "boolean":
        region["width"] = True
    else:
        masks["regions"] = []
    snapshot["layout"]["privacyMasks"] = masks
    with pytest.raises(LayoutError):
        validate_layout(snapshot)


def test_compiler_refuses_to_drop_or_move_a_canonical_privacy_mask(
    import_project, tmp_path
):
    from avo.timeline.cmap_service import CMapService
    from avo.timeline.initial_cut import initial_cut_proof_request
    from avo.timeline.proof_plan import ProofPlanCompiler, ProofPlanError
    from tests.test_proof_plan import regression_contract

    service = _service(import_project)
    prepared = service.prepare_automatic(
        _export(tmp_path, import_project[2]), actor="fixture", reason="Import edit"
    )
    prepared = service.validate(prepared["importId"])
    fixtures._approve_fixture_sync(service, prepared["proposal"])
    ready = service.validate(prepared["importId"])
    selected = service.activate(
        prepared["importId"],
        validation_hash=ready["validationHash"],
        expected_head="empty",
        actor="fixture",
        reason="Select draft",
    )
    snapshot = deepcopy(selected["revision"]["snapshot"])
    masks = privacy_masks()
    masks.update(canvasWidth=640, canvasHeight=360)
    snapshot["layout"]["privacyMasks"] = masks
    CMapService(service.workspace).author(
        snapshot, actor="fixture", reason="Cover account"
    )
    request = initial_cut_proof_request(
        service.workspace,
        iteration_id="privacy",
        output=tmp_path / "proof.mp4",
        frame_rate={"num": 24, "den": 1},
        width=640,
        height=360,
    )
    compiler = ProofPlanCompiler(service.workspace)
    compiler.compile(request, regression_contract=regression_contract("privacy"))
    for change in ("drop", "move"):
        altered = deepcopy(request)
        parameters = altered["videoGraph"]["operations"][0]["parameters"]
        if change == "drop":
            del parameters["privacyMasks"]
        else:
            parameters["privacyMasks"]["regions"][0]["x"] += 1
        with pytest.raises(ProofPlanError, match="canonical imported source assembly"):
            compiler.compile(
                altered, regression_contract=regression_contract("privacy")
            )
