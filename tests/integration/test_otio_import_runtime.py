"""Native synthetic handoffs; fixture Sync decisions are not creator approvals."""

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
from avo.timeline.proof_plan import ProofPlanCompiler, ProofPlanError

pytestmark = pytest.mark.integration


def _native_trial(tmp_path, *, provider_name="channel"):
    if importlib.util.find_spec("opentimelineio") is None:
        pytest.skip("Optional pinned native reader required")
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("FFmpeg and FFprobe are required for native fidelity")
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
            {"provider": provider_name, "videoId": "native-trial", "rawDir": str(raw)}
        )
    )
    provider = tmp_path / "provider"
    provider.mkdir()
    (provider / "avo.provider.json").write_text(
        json.dumps(build_manifest(provider_name, "youtube", str(raw)))
    )
    export = json.loads(
        (Path(__file__).parents[1] / "fixtures/otio/clip-v1.otio").read_text()
    )
    clip = export["tracks"]["children"][0]["children"][0]
    clip["media_reference"]["available_range"]["duration"]["value"] = 72
    clip["source_range"]["start_time"]["value"] = 252
    clip["source_range"]["duration"]["value"] = 12
    second = deepcopy(clip)
    second["source_range"]["start_time"]["value"] = 288
    export["tracks"]["children"][0]["children"].append(second)
    path = raw / "export.otio"
    path.write_text(json.dumps(export))
    mappings = {
        f"/tracks/children/0/children/{index}/media_reference": {
            "path": str(source),
            "identityConfirmed": True,
            "videoStreamIndex": 0,
            "audioSelection": {
                "streamIndex": 1,
                "channels": [0, 1],
                "sourceLayout": "stereo",
                "outputLayout": "stereo",
            },
        }
        for index in range(2)
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
            "output": {
                "width": 128,
                "height": 96,
                "frameRate": {"num": 24, "den": 1},
                "audioSampleRate": 48000,
                "channelLayout": "stereo",
            },
        },
        actor="fixture",
        reason="Native synthetic handoff",
    )
    waiting = service.validate(prepared["importId"])
    _approve_fixture_sync(service, waiting["proposal"])
    ready = service.validate(prepared["importId"])
    assert ready["status"] == "ready-to-activate", ready
    service.activate(
        prepared["importId"],
        validation_hash=ready["validationHash"],
        expected_head="empty",
        actor="fixture",
        reason="Select synthetic draft",
    )
    return service, source


def _render_import(service, name):
    workspace = service.workspace
    request = initial_cut_proof_request(
        workspace,
        iteration_id="iteration-0001",
        output=workspace.raw_dir / f"edit/preview/{name}.mkv",
        frame_rate={"num": 24, "den": 1},
        width=128,
        height=96,
    )
    trims = [op for op in request["audioGraph"]["operations"] if op["kind"] == "trim"]
    assert all(
        op["parameters"]["fadeInSamples"] == op["parameters"]["fadeOutSamples"] == 0
        for op in trims
    )
    assert all("dialogueNoiseReductionPolicy" not in op["parameters"] for op in trims)
    request["output"].update(
        conformance=True, videoCodec="ffv1", audioCodec="pcm_s32le"
    )
    altered = deepcopy(request)
    altered["audioGraph"]["operations"][0]["parameters"]["fadeInSamples"] = 1
    with pytest.raises(ProofPlanError):
        ProofPlanCompiler(workspace).compile(
            altered, regression_contract=regression_contract()
        )
    wrong_rate = initial_cut_proof_request(
        workspace,
        iteration_id="iteration-0001",
        output=workspace.raw_dir / "edit/preview/wrong-rate.mkv",
        frame_rate={"num": 30, "den": 1},
        width=128,
        height=96,
    )
    with pytest.raises(ProofPlanError):
        ProofPlanCompiler(workspace).compile(
            wrong_rate, regression_contract=regression_contract()
        )
    plan = ProofPlanCompiler(workspace).compile(
        request, regression_contract=regression_contract()
    )
    media = canonical_proof_media_inputs(workspace, plan)
    gate = render_proof_microproofs(
        workspace=workspace,
        proof_plan=plan,
        media_inputs=media,
        render_port=TimelineRenderAdapter(),
    )
    assert gate["status"] == "pass"
    materialize_proof_plan(
        workspace=workspace,
        proof_plan=plan,
        media_inputs=media,
        microproof_gate=gate["path"],
        render_port=TimelineRenderAdapter(),
    )
    return Path(plan["output"]["path"])


def test_native_import_reconstructs_every_frame_and_sample_without_treatment(tmp_path):
    service, source = _native_trial(tmp_path)
    output = _render_import(service, "import")
    original_frames, original_audio = _pixels(source), _pcm(source)
    assert np.array_equal(
        _pixels(output),
        np.concatenate([original_frames[12:24], original_frames[48:60]]),
    )
    assert np.array_equal(
        _pcm(output),
        np.concatenate([original_audio[24000:48000], original_audio[96000:120000]]),
    )


def test_scoped_trim_and_restart_retain_other_imported_decisions(tmp_path):
    service, source = _native_trial(tmp_path)
    store = service.workspace.store("cmap")
    initial = store.revision(store.load_index()["headRevisionId"])
    revised = deepcopy(initial["snapshot"])
    revised["segments"][0]["in"]["ticks"] += 1
    changed = CMapService(service.workspace).author(
        revised,
        expected_head_hash=initial["contentHash"],
        actor="fixture-editor",
        reason="Requested one-frame trim of the first occurrence only",
    )
    assert changed["snapshot"]["segments"][1] == initial["snapshot"]["segments"][1]
    assert changed["snapshot"]["originRef"] == initial["snapshot"]["originRef"]
    restarted = TimelinePipeline(service.workspace)
    status = restarted.initialize()
    assert (
        status["timelineImport"]["originRef"]["importId"]
        == initial["snapshot"]["originRef"]["importId"]
    )
    assert store.head_hash() == changed["contentHash"]
    with pytest.raises(ValueError):
        restarted.advance("cmap-approved", review={}, approval=None)
    assert store.effective_approval() is None
    output = _render_import(service, "trimmed")
    frames, audio = _pixels(source), _pcm(source)
    assert np.array_equal(
        _pixels(output), np.concatenate([frames[13:24], frames[48:60]])
    )
    assert np.array_equal(
        _pcm(output), np.concatenate([audio[26000:48000], audio[96000:120000]])
    )
