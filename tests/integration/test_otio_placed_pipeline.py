"""Synthetic placed import through the actual canonical proof pipeline."""

import importlib.util
import json
import shutil
import subprocess
from copy import deepcopy
from pathlib import Path

import numpy as np
import pytest
from tests.integration.test_code_drawn_canonical_pipeline import _pixels
from tests.integration.test_ffmpeg_proof_executor import _pcm
from tests.test_proof_plan import regression_contract
from tests.test_timeline_import_service import _approve_fixture_sync

from avo.adapters.media.ffprobe import FfprobeMediaAdapter
from avo.adapters.media.otio_reader import read_otio
from avo.adapters.media.timeline_render import TimelineRenderAdapter
from avo.provider_scaffold import build_manifest
from avo.timeline.cmap_service import CMapService
from avo.timeline.import_service import TimelineImportService
from avo.timeline.initial_cut import initial_cut_proof_request
from avo.timeline.materialize import (
    canonical_proof_media_inputs,
    materialize_proof_plan,
    render_proof_microproofs,
)
from avo.timeline.pipeline import TimelinePipeline
from avo.timeline.proof_plan import ProofPlanCompiler

pytestmark = pytest.mark.integration


def _trial(tmp_path):
    if importlib.util.find_spec("opentimelineio") is None or not shutil.which("ffmpeg"):
        pytest.skip("Optional OTIO and native media tools required")
    raw = tmp_path / "footage"
    raw.mkdir()
    source = raw / "original.mkv"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=s=128x96:r=24:d=3",
            "-f",
            "lavfi",
            "-i",
            "aevalsrc=0.2+0.1*sin(440*2*PI*t)|0.15+0.08*sin(660*2*PI*t):s=48000:d=3",
            "-c:v",
            "ffv1",
            "-c:a",
            "pcm_s16le",
            str(source),
        ],
        capture_output=True,
        check=True,
    )
    project = raw / "avo.project.json"
    project.write_text(
        json.dumps(
            {"provider": "channel", "videoId": "placed-trial", "rawDir": str(raw)}
        )
    )
    provider = tmp_path / "provider"
    provider.mkdir()
    (provider / "avo.provider.json").write_text(
        json.dumps(build_manifest("channel", "youtube", str(raw)))
    )
    export = json.loads(
        (Path(__file__).parents[1] / "fixtures/otio/clip-v1.otio").read_text()
    )
    track = export["tracks"]["children"][0]
    clip = deepcopy(track["children"][0])
    clip["media_reference"]["available_range"]["duration"]["value"] = 72
    clip["source_range"]["start_time"]["value"] = 252
    clip["source_range"]["duration"]["value"] = 24
    gap = {"OTIO_SCHEMA": "Gap.1", "source_range": deepcopy(clip["source_range"])}
    gap["source_range"]["start_time"]["value"] = 0
    gap["source_range"]["duration"]["value"] = 12
    track["children"] = [gap, clip, deepcopy(gap), deepcopy(clip)]
    upper = deepcopy(track)
    upper_clip = deepcopy(clip)
    upper_clip["source_range"]["start_time"]["value"] = 240
    upper_clip["source_range"]["duration"]["value"] = 6
    upper_gap = deepcopy(gap)
    upper_gap["source_range"]["duration"]["value"] = 24
    upper["children"] = [upper_gap, upper_clip]
    audio = deepcopy(track)
    audio["kind"] = "Audio"
    audio["children"] = [deepcopy(gap), deepcopy(clip)]
    audio["children"][0]["source_range"]["duration"]["value"] = 6
    export["tracks"]["children"] = [track, upper, audio]
    path = raw / "export.otio"
    path.write_text(json.dumps(export))
    mappings = {}
    for ti, tr in enumerate(export["tracks"]["children"]):
        for ci, item in enumerate(tr["children"]):
            if item["OTIO_SCHEMA"] != "Clip.1":
                continue
            selection = (
                {"videoStreamIndex": 0}
                if tr["kind"] == "Video"
                else {
                    "audioSelection": {
                        "streamIndex": 1,
                        "channels": [0, 1],
                        "sourceLayout": "stereo",
                        "outputLayout": "stereo",
                    }
                }
            )
            mappings[f"/tracks/children/{ti}/children/{ci}/media_reference"] = {
                "path": str(source),
                "identityConfirmed": True,
                **selection,
            }
    service = TimelineImportService(
        project,
        provider_root=provider,
        reader=read_otio,
        probe=FfprobeMediaAdapter().inventory,
    )
    prepared = service.prepare(
        path,
        mappings=mappings,
        declarations={
            "sourceOnly": True,
            "layoutMode": "placed",
            "output": {
                "width": 128,
                "height": 96,
                "frameRate": {"num": 24, "den": 1},
                "audioSampleRate": 48000,
                "channelLayout": "stereo",
            },
        },
        actor="fixture",
        reason="Placed native handoff",
    )
    waiting = service.validate(prepared["importId"])
    assert waiting["status"] == "awaiting-sync", waiting
    _approve_fixture_sync(service, waiting["proposal"])
    ready = service.validate(prepared["importId"])
    activated = service.activate(
        prepared["importId"],
        validation_hash=ready["validationHash"],
        expected_head="empty",
        actor="fixture",
        reason="Select placed draft",
    )
    return service, source, activated["revision"]


def _render(service, name):
    workspace = service.workspace
    request = initial_cut_proof_request(
        workspace,
        iteration_id="iteration-0001",
        output=workspace.raw_dir / f"edit/preview/{name}.mkv",
        frame_rate={"num": 24, "den": 1},
        width=128,
        height=96,
    )
    request["output"].update(
        conformance=True, videoCodec="ffv1", audioCodec="pcm_s32le"
    )
    plan = ProofPlanCompiler(workspace).compile(
        request, regression_contract=regression_contract()
    )
    inputs = canonical_proof_media_inputs(workspace, plan)
    gate = render_proof_microproofs(
        workspace=workspace,
        proof_plan=plan,
        media_inputs=inputs,
        render_port=TimelineRenderAdapter(),
    )
    assert gate["status"] == "pass", gate
    materialize_proof_plan(
        workspace=workspace,
        proof_plan=plan,
        media_inputs=inputs,
        microproof_gate=gate["path"],
        render_port=TimelineRenderAdapter(),
    )
    return Path(plan["output"]["path"])


def test_native_placed_import_and_scoped_occurrence_edit_survive_restart(tmp_path):
    service, source, initial = _trial(tmp_path)
    original = _pixels(source)
    expected = np.zeros((72, *original.shape[1:]), dtype=original.dtype)
    expected[:, :, :, 3] = 255
    expected[12:36] = original[12:36]
    expected[48:72] = original[12:36]
    expected[24:30] = original[0:6]
    audio = _pcm(source)
    expected_audio = np.zeros((144000, 2), dtype=audio.dtype)
    expected_audio[12000:60000] = audio[24000:72000]
    output = _render(service, "placed")
    assert np.array_equal(_pixels(output), expected)
    assert np.array_equal(_pcm(output), expected_audio)
    revised = deepcopy(initial["snapshot"])
    # Exact clocks may use different rational bases. Move only one source start,
    # and shorten that occurrence by one program frame without touching others.
    item = revised["layout"]["placements"][0]
    item["in"] = {**item["in"], "ticks": 13, "timebase": {"num": 1, "den": 24}}
    item["start"]["ticks"] += 1
    changed = CMapService(service.workspace).author(
        revised,
        expected_head_hash=initial["contentHash"],
        actor="fixture",
        reason="Trim one selected placement",
    )
    assert (
        changed["snapshot"]["layout"]["placements"][1:]
        == initial["snapshot"]["layout"]["placements"][1:]
    )
    status = TimelinePipeline(service.workspace).initialize()
    assert status["timelineImport"]["originRef"] == initial["snapshot"]["originRef"]
    assert service.workspace.store("cmap").head_hash() == changed["contentHash"]
    assert service.workspace.store("cmap").effective_approval() is None
    expected[12] = np.zeros_like(expected[12])
    expected[12, :, :, 3] = 255
    scoped = _render(service, "scoped")
    assert np.array_equal(_pixels(scoped), expected)
    assert np.array_equal(_pcm(scoped), expected_audio)
