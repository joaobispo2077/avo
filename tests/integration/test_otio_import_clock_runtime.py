"""Native admission rejects false constant-rate headers before canonical writes."""

import importlib.util
import json
import shutil
import subprocess
from fractions import Fraction

import pytest
from tests.test_timeline_import_service import FIXTURE, REFERENCE
from tests.test_timeline_import_service import import_project as _project
from tests.test_video_clock import _recording

from avo.adapters.media import proof_executor, proof_placed
from avo.adapters.media.ffprobe import FfprobeMediaAdapter
from avo.adapters.media.otio_reader import read_otio
from avo.timeline.contracts import file_fingerprint
from avo.timeline.import_service import TimelineImportService

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        importlib.util.find_spec("opentimelineio") is None
        or not shutil.which("ffmpeg")
        or not shutil.which("ffprobe"),
        reason="Optional OTIO and native FFmpeg tools required",
    ),
]


@pytest.fixture(name="import_project")
def project_fixture(tmp_path):
    return _project.__wrapped__(tmp_path)


@pytest.mark.parametrize(
    "container,irregular,extra_frame",
    [
        ("mov", False, False),
        ("mov", True, False),
        ("mkv", False, False),
        ("mkv", True, False),
        ("mkv", False, True),
    ],
)
def test_native_clock_admission_and_preflight(
    import_project, tmp_path, container, irregular, extra_frame
):
    project, provider, _ = import_project
    original = tmp_path / ("original." + container)
    _recording(original, container=container, irregular=irregular)
    if extra_frame:
        extended = tmp_path / "extended.mkv"
        subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-nostdin",
                "-i",
                str(original),
                "-map",
                "0:v",
                "-c",
                "copy",
                "-bsf:v",
                "setts=duration=if(eq(N\\,11)\\,84\\,42)",
                str(extended),
            ],
            check=True,
            capture_output=True,
        )
        original = extended
        stream = FfprobeMediaAdapter().inventory([original])["sources"][0]["streams"][
            "video"
        ][0]
        assert stream["frameRate"] == stream["averageFrameRate"] == "24/1"
        assert stream["durationSeconds"] > 13 / 24
    count = 13 if extra_frame else 12
    if irregular:
        # Leave headroom so Matroska extent rounding cannot mask the bad packet clock.
        count -= 1
    blocked = irregular or extra_frame
    export = tmp_path / "handoff.otio"
    data = json.loads(FIXTURE.read_text())
    clip = data["tracks"]["children"][0]["children"][0]
    clip["source_range"]["start_time"]["value"] = 240
    clip["source_range"]["duration"]["value"] = count
    clip["media_reference"]["available_range"]["duration"]["value"] = count
    export.write_text(json.dumps(data))
    service = TimelineImportService(
        project,
        provider_root=provider,
        reader=read_otio,
        probe=FfprobeMediaAdapter().inventory,
    )
    prepared = service.prepare(
        export,
        media_roots=[str(tmp_path)],
        mappings={
            REFERENCE: {
                "path": str(original),
                "identityConfirmed": True,
                "videoStreamIndex": 0,
            }
        },
        declarations={
            "sourceOnly": True,
            "layoutMode": "placed",
            "output": {
                "width": 64,
                "height": 48,
                "frameRate": {"num": 24, "den": 1},
                "audioSampleRate": 48000,
                "channelLayout": "stereo",
            },
        },
        actor="fixture",
        reason="Synthetic timing regression",
    )
    result = service.validate(prepared["importId"])
    assert result["status"] == ("blocked" if blocked else "awaiting-sync"), result[
        "findings"
    ]
    assert not service.workspace.artifact_path("cmap").exists()
    if blocked:
        assert any(
            row["code"] == "OTIO_RATE_UNVERIFIED" for row in result["findings"]
        ), result["findings"]
    else:
        source = result["proposal"]["snapshot"]["sources"][0]
        assert source["streamMetadata"]["videoClock"]["packetCount"] == 12

    # Construct an adversarial graph directly, bypassing staged admission.
    sha = file_fingerprint(original)["sha256"]
    item = {
        "placementId": "p",
        "trackId": "v",
        "sourceId": "original",
        "mediaKind": "video",
        "source": {
            "locator": str(original),
            "sha256": sha,
            "mediaClass": "source",
            "streamIndex": 0,
        },
        "sourceRange": {
            "startTicks": 0,
            "endTicks": count,
            "timebase": {"num": 1, "den": 24},
        },
        "outputRange": {"startFrame": 0, "endFrameExclusive": count},
        "zOrder": 0,
        "enabled": True,
    }
    execution = {
        "canonicalInputLock": {"source:original": sha},
        "sourceAssemblyPolicy": "preserve-import",
    }
    operation = {"kind": "trim", "parameters": item, "outputRange": item["outputRange"]}
    if blocked:
        with pytest.raises(RuntimeError, match="clock.*unverified|available.*frames"):
            proof_placed._admit_picture(execution, [item], count, Fraction(24), {})
        with pytest.raises(RuntimeError, match="clock.*unverified|available.*frames"):
            proof_executor._picture_source(operation, {}, execution, {}, Fraction(24))
    else:
        assert (
            len(proof_placed._admit_picture(execution, [item], count, Fraction(24), {}))
            == 1
        )
