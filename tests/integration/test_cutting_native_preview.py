"""Real native previews of synthetic originals; injected alignment is explicit."""

import shutil
import subprocess

import numpy as np
import pytest
from scipy.io import wavfile

from avo.adapters.media.cutting_preview import CuttingPreviewAdapter
from avo.timeline.cmap_service import CMapService
from avo.timeline.contracts import file_fingerprint
from avo.timeline.cutting_audit import audit_joins
from avo.timeline.cutting_policy import resolve_cutting_policy
from avo.timeline.cutting_service import CuttingService
from avo.timeline.sync_service import SyncService
from cutting_fixtures import cutting_workspace, source_snapshot


class SuppliedAlignedEvidence:
    """Synthetic fixture labels only; no model inference or listening claim."""

    def analyze(self, source, **request):
        gap = {
            **request["source_range"],
            "startTicks": 36000,
            "endTicksExclusive": 103200,
        }
        return {
            "sourceRef": {
                "locator": str(source),
                "sha256": request["fingerprint"]["sha256"],
            },
            "syncRef": request["sync_ref"],
            "routing": request["selection"],
            "preprocessing": {"sourceRange": request["source_range"]},
            "status": "pass",
            "coverage": {"observed": True},
            "words": [
                {"text": "before", "start": 0.25, "end": 0.65, "eligibleEdge": True},
                {"text": "after", "start": 2.25, "end": 2.65, "eligibleEdge": True},
            ],
            "pauseCandidates": [
                {
                    "sourceRange": gap,
                    "evidence": {
                        "quietRanges": [gap],
                        "speechRanges": [],
                        "acousticObserved": True,
                        "wordEdges": {
                            "status": "observed",
                            "beforeEndTicks": 31200,
                            "afterStartTicks": 108000,
                        },
                        "context": {"dispensable": True, "intentionalPause": False},
                        "adjacentWords": {"before": "before", "after": "after"},
                    },
                }
            ],
        }


def native_workspace(tmp_path, noise):
    workspace, wav = cutting_workspace(tmp_path)
    clock = np.arange(144000) / 48000
    signal = np.sin(clock * 2 * np.pi * 220) * 0.25
    signal[
        ~(((clock >= 0.25) & (clock < 0.65)) | ((clock >= 2.25) & (clock < 2.65)))
    ] = 0
    wavfile.write(wav, 48000, (signal * 32767).astype("int16"))
    source = workspace.raw_dir / "original.mkv"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=320x180:r=30:d=3",
            "-i",
            str(wav),
            "-map",
            "0:v",
            "-map",
            "1:a",
            "-af",
            "pan=stereo|c0=c0|c1=c0",
            "-c:v",
            "ffv1",
            "-c:a",
            "pcm_s16le",
            "-t",
            "3",
            str(source),
        ],
        check=True,
    )
    sync = SyncService(workspace)
    revision = sync.author_not_applicable(
        raw_fingerprints={"dialogue": file_fingerprint(source)["sha256"]},
        actor="fixture",
        reason="generated original has muxed clock",
    )
    evidence = sync.validate_current()
    sync.decide(
        decision="approved",
        candidate_hash=revision["contentHash"],
        evidence_bundle_hash=evidence["sha256"],
        actor="fixture",
        reason="synthetic source",
    )
    snapshot = source_snapshot(source)
    snapshot["segments"][0]["out"]["ticks"] = 144000
    metadata = snapshot["sources"][0]["streamMetadata"]
    metadata["audioSelection"].update(streamIndex=1, sourceLayout="stereo")
    if noise:
        metadata["dialogueNoiseReductionPolicy"] = {
            "mode": "afftdn",
            "role": "presenter-dialogue",
            "strengthPercent": 40,
            "streamIndex": 1,
            "channelIndex": 0,
            "approvedByUser": True,
        }
    canonical = CMapService(workspace).author(
        snapshot, actor="fixture", reason="generated original"
    )
    return workspace, canonical


@pytest.mark.integration
@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="FFmpeg required")
@pytest.mark.parametrize("noise", [False, True])
def test_real_native_preview_verifies_then_applies_original_selection(tmp_path, noise):
    workspace, canonical = native_workspace(tmp_path, noise)
    preview = CuttingPreviewAdapter(workspace)
    service = CuttingService(
        workspace,
        policy=resolve_cutting_policy(
            project_settings={"enabled": True, "family": "analysis-review"}
        ),
        analysis_port=SuppliedAlignedEvidence(),
        preview_port=preview,
        verification_port=preview,
    )
    proposal_ref = service.analyze()["proposalRef"]
    proposal = service.status(proposal_ref)["proposal"]
    assert len(proposal["edits"]) == 1
    rendered = service.preview(proposal_ref)
    report = service.store.load_document(rendered["verificationRef"])["payload"]
    assert rendered["status"] == "pass", report["checks"]
    assert workspace.store("cmap").head_hash() == canonical["contentHash"]
    assert report["claims"]["fullProgramReviewed"] is False
    identity = proposal["edits"][0]["occurrenceId"]
    assert identity in report["occurrenceCoverage"]
    assert all(check["status"] == "pass" for check in report["checks"])
    service.decide(
        proposal_ref,
        {
            "previewRef": rendered["verificationRef"],
            "decisions": [
                {
                    "occurrenceId": identity,
                    "disposition": "shorten",
                    "reason": "fixture-approved choice",
                }
            ],
        },
    )
    applied = service.apply(proposal_ref)
    assert applied["status"] == "applied"
    snapshot = applied["revision"]["snapshot"]
    assert snapshot["cuttingRef"] == rendered["verificationRef"]
    assert len(snapshot["segments"]) == 2
    joins = audit_joins(snapshot, {"num": 30, "den": 1})
    assert {join["joinId"] for join in joins} <= set(report["occurrenceCoverage"])
    assert all(source["kind"] == "raw" for source in snapshot["sources"])
