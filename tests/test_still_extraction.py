from __future__ import annotations

from fractions import Fraction
from types import SimpleNamespace

import pytest

from avo.adapters.media.still_extract import (
    StillExtractionError,
    media_metadata,
    select_frame,
)
from avo.cli import build_parser
from avo.timeline.command_handlers import CommandHandlers
from avo.timeline.media_admission import validate_still_admission
from avo.timeline.stills import resolve_program_frame


def _probe(pts, *, rate="30/1", duration=1, **stream):
    return {
        "stream": {
            "time_base": "1/1000",
            "avg_frame_rate": rate,
            "r_frame_rate": rate,
            "start_pts": 100,
            "width": 720,
            "height": 480,
            "pix_fmt": "yuv420p",
            "sample_aspect_ratio": "4:3",
            "color_primaries": "bt709",
            "color_transfer": "bt709",
            "color_space": "bt709",
            "color_range": "tv",
            **stream,
        },
        "frames": [
            {"best_effort_timestamp": value, "pkt_duration": duration} for value in pts
        ],
    }


def test_cfr_and_vfr_selection_use_half_open_pts_intervals():
    cfr = _probe([100, 133, 166], rate="30000/1001", duration=33)
    selected = select_frame(cfr, Fraction(33, 1000))
    assert selected["decodedFrameIndex"] == 1
    assert selected["selectionMethod"] == "cfr-frame-map"

    vfr = _probe([100, 140, 240], rate="0/0", duration=40)
    within = select_frame(vfr, Fraction(139, 1000))
    boundary = select_frame(vfr, Fraction(140, 1000))
    assert within["decodedFrameIndex"] == 1
    assert boundary["decodedFrameIndex"] == 2
    assert boundary["boundaryDecision"] == "incoming"


@pytest.mark.parametrize("pts", [[100, 100, 200], [100, 90, 200], [100, None, 200]])
def test_pts_anomalies_block_time_selection_but_explicit_index_is_allowed(pts):
    probe = _probe(pts, rate="0/0")
    with pytest.raises(StillExtractionError, match="PTS"):
        select_frame(probe, Fraction(0, 1))
    selected = select_frame(probe, None, decoded_frame_index=2)
    assert selected["decodedFrameIndex"] == 2
    assert selected["selectionMethod"] == "decoded-frame-index"


def _segment(source_id, start, end):
    return {
        "sourceId": source_id,
        "in": {
            "ticks": start,
            "timebase": {"num": 1, "den": 24},
            "domain": "raw-source",
            "sourceId": source_id,
        },
        "out": {
            "ticks": end,
            "timebase": {"num": 1, "den": 24},
            "domain": "raw-source",
            "sourceId": source_id,
        },
    }


def test_program_cut_boundary_requires_side_and_resolves_exact_adjacent_frames():
    snapshot = {"segments": [_segment("a", 0, 24), _segment("b", 48, 72)]}
    rate = {"num": 24, "den": 1}
    with pytest.raises(ValueError, match="cut boundary"):
        resolve_program_frame(snapshot, 24, rate)
    outgoing = resolve_program_frame(snapshot, 24, rate, side="outgoing")
    incoming = resolve_program_frame(snapshot, 24, rate, side="incoming")
    assert (outgoing["sourceId"], outgoing["sourceFrame"]) == ("a", 23)
    assert (incoming["sourceId"], incoming["sourceFrame"]) == ("b", 48)
    assert outgoing["boundaryDecision"] == "outgoing"
    assert incoming["boundaryDecision"] == "incoming"


def test_rotation_sar_and_color_policy_are_explicit_and_hdr_fails_closed():
    probe = _probe(
        [100, 133],
        side_data_list=[{"rotation": -90}],
    )
    media, policy = media_metadata(probe)
    assert (media["displayWidth"], media["displayHeight"]) == (480, 960)
    assert media["rotationDegrees"] == 270
    assert policy["policyId"] == "sdr-srgb-v1"

    hdr = _probe([100, 133], color_transfer="smpte2084", color_primaries="bt2020")
    with pytest.raises(StillExtractionError, match="HDR"):
        media_metadata(hdr)
    media, policy = media_metadata(hdr, color_policy="hdr-tone-map-hable-v1")
    assert media["hdrState"] == "hdr-tone-mapped"
    assert policy["policyId"] == "hdr-tone-map-hable-v1"


def test_candidate_stills_are_delivery_reference_only_and_thumbnail_is_approved():
    validate_still_admission(purpose="reference", input_kind="current-candidate")
    validate_still_admission(purpose="thumbnail", input_kind="approved-candidate")
    with pytest.raises(ValueError, match="approved-candidate"):
        validate_still_admission(purpose="thumbnail", input_kind="current-candidate")
    with pytest.raises(ValueError, match="cannot enter a proof"):
        validate_still_admission(
            purpose="canonical-generated-asset", input_kind="approved-candidate"
        )


def test_still_cli_parses_exact_candidate_request(tmp_path):
    args = build_parser().parse_args(
        [
            "still",
            "extract",
            "--project",
            str(tmp_path / "avo.project.json"),
            "--purpose",
            "thumbnail",
            "--candidate",
            str(tmp_path / "candidate.mp4"),
            "--candidate-frame",
            "42",
            "--candidate-state",
            "approved",
            "--candidate-sha256",
            "a" * 64,
        ]
    )
    assert (args.command, args.still_command, args.candidate_frame) == (
        "still",
        "extract",
        42,
    )


def test_thumbnail_command_handler_routes_read_only_extraction(monkeypatch):
    expected = {"extractionId": "video-thumbnail-f42-v001"}
    calls = []

    def extract(_service, **payload):
        calls.append(payload)
        return expected

    monkeypatch.setattr("avo.timeline.stills.StillExtractionService.extract", extract)
    pipeline = SimpleNamespace(workspace=object())
    result = CommandHandlers(pipeline).execute(
        "thumbnail", "extract", {"purpose": "thumbnail"}
    )
    assert result == {
        "command": "thumbnail",
        "mode": "Consumes",
        "operation": "extract",
        "mutated": False,
        "result": expected,
    }
    assert calls == [{"purpose": "thumbnail"}]
