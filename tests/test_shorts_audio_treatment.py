from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from avo import shorts_media


@pytest.fixture
def treatment():
    return {
        "stream": "0:a:1",
        "channel": "mono",
        "eqProfile": "bishop-dialogue-v1",
        "noiseReduction": {
            "mode": "afftdn",
            "strengthPercent": 30,
            "nrDb": 6.0,
            "noiseFloorDb": -37.5,
        },
        "approval": {
            "abRequired": True,
            "removedSignalReviewRequired": True,
            "reference": "user://approved",
        },
    }


@pytest.mark.parametrize("profile", ["dialogue-v1", "another-provider-dialogue-v1"])
def test_generic_dialogue_profile_uses_same_calibration(treatment, profile):
    treatment["eqProfile"] = profile
    command = shorts_media.dialogue_treatment_command(
        Path("raw.wav"), Path("out.wav"), treatment=treatment
    )
    assert "afftdn=nr=6.00:nf=-37.5:tn=1" in command[command.index("-af") + 1]


@pytest.mark.parametrize(
    "field,value", [("nrDb", 8), ("noiseFloorDb", -35), ("strengthPercent", True)]
)
def test_rejects_uncalibrated_noise_parameters(treatment, field, value):
    treatment["noiseReduction"][field] = value
    with pytest.raises(shorts_media.MediaPreparationError):
        shorts_media.dialogue_treatment_command(
            Path("raw.wav"), Path("out.wav"), treatment=treatment
        )


def test_protection_bypasses_all_repair_filters_without_breath_processing(treatment):
    treatment["protectedWindows"] = [
        {"startSec": 1, "endSec": 2, "reason": "page turn"}
    ]
    command = shorts_media.dialogue_treatment_command(
        Path("raw.wav"), Path("out.wav"), treatment=treatment
    )
    chain = command[command.index("-filter_complex") + 1]
    assert "aeval='val(ch)*gt(between(t,1.000000,2.000000),0)'" in chain
    assert "afftdn=nr=6.00:nf=-37.5:tn=1" in chain
    assert "silenceremove" not in chain
    assert command[command.index("-c:a") + 1] == "pcm_s24le"


def test_ordered_preparation_preserves_selected_stream_and_only_repairs_once(
    tmp_path, treatment
):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"source")
    commands = []

    def runner(argv):
        commands.append(list(argv))
        if argv[0] == "ffprobe":
            return subprocess.CompletedProcess(
                argv,
                0,
                json.dumps(
                    {
                        "streams": [
                            {"codec_type": "audio", "channels": 2},
                            {"codec_type": "audio", "channels": 1},
                        ]
                    }
                ),
                "",
            )
        Path(argv[-1]).write_bytes(str(len(commands)).encode())
        return subprocess.CompletedProcess(argv, 0, "", "")

    result = shorts_media.prepare_ordered_base_assets(
        source,
        tmp_path / "prepared",
        source_segments=[
            {"order": 1, "startSec": 1, "endSec": 3},
            {"order": 2, "startSec": 8, "endSec": 9},
        ],
        speed=1,
        audio_treatment=treatment,
        runner=runner,
    )
    extracts = [c for c in commands if "-ss" in c and "-af" in c]
    assert len(extracts) == 2
    assert all(c[c.index("-map") + 1] == "0:a:1" for c in extracts)
    assert all(c[c.index("-ac") + 1] == "1" for c in extracts)
    assert all(c[c.index("-c:a") + 1] == "pcm_s24le" for c in extracts)
    repairs = [c for c in commands if "afftdn=" in " ".join(c)]
    assert len(repairs) == 1
    assert result["dialogueAudio"].path.suffix == ".wav"
    assert result["dialogueUntreated"].duration_sec == 3
    assert result["dialogueRemovedSignal"].path.is_file()


def test_rejects_source_channel_conversion_before_render(tmp_path, treatment):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"source")
    treatment["stream"] = "0:a:0"

    def runner(argv):
        assert argv[0] == "ffprobe"
        return subprocess.CompletedProcess(
            argv,
            0,
            json.dumps({"streams": [{"codec_type": "audio", "channels": 2}]}),
            "",
        )

    with pytest.raises(shorts_media.MediaPreparationError, match="channel layout"):
        shorts_media.prepare_base_assets(
            source,
            tmp_path / "out",
            start_sec=0,
            end_sec=1,
            speed=1,
            audio_treatment=treatment,
            runner=runner,
        )


@pytest.mark.parametrize(
    "suffix,channels,codec", [(".wav", 1, "pcm_s24le"), (".m4a", 2, "aac")]
)
def test_gain_and_normalization_preserve_requested_channels_and_codec(
    tmp_path, monkeypatch, suffix, channels, codec
):
    source = tmp_path / "raw.wav"
    source.write_bytes(b"raw")
    measurements = iter(
        [
            {"integratedLufs": -30, "truePeakDbtp": -10},
            {"integratedLufs": -25, "truePeakDbtp": -5},
        ]
    )
    monkeypatch.setattr(
        shorts_media, "measure_audio_loudness", lambda *a, **k: next(measurements)
    )
    commands = []

    def runner(argv):
        commands.append(argv)
        Path(argv[-1]).write_bytes(b"processed")
        return subprocess.CompletedProcess(argv, 0, "", "")

    result = shorts_media.apply_dialogue_gain_if_needed(
        shorts_media.PreparedAsset(source, "sourcehash", 2),
        tmp_path / f"gain{suffix}",
        channels=channels,
        runner=runner,
    )
    assert len(commands) == 2
    assert all(c[c.index("-ac") + 1] == str(channels) for c in commands)
    assert all(c[c.index("-c:a") + 1] == codec for c in commands)
    assert result.path.name == f"dialogue-loudnorm{suffix}"


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg required")
def test_real_ffmpeg_protected_event_is_lossless(treatment, tmp_path):
    source = tmp_path / "raw.wav"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=250:duration=2:sample_rate=48000",
            "-c:a",
            "pcm_s24le",
            str(source),
        ],
        check=True,
        capture_output=True,
    )
    treatment["stream"] = "0:a:0"
    treatment["protectedWindows"] = [
        {"startSec": 0.5, "endSec": 1.5, "reason": "handling"}
    ]
    output = tmp_path / "treated.wav"
    command = shorts_media.dialogue_treatment_command(
        source, output, treatment=treatment
    )
    subprocess.run(command, check=True, capture_output=True)

    def samples(path):
        return subprocess.run(
            ["ffmpeg", "-v", "error", "-i", str(path), "-f", "s24le", "-"],
            check=True,
            capture_output=True,
        ).stdout

    original, repaired = samples(source), samples(output)
    assert len(original) == len(repaired)
    assert (
        original[48000 * 3 // 2 : 48000 * 3 * 3 // 2]
        == repaired[48000 * 3 // 2 : 48000 * 3 * 3 // 2]
    )
    assert original[:48000] != repaired[:48000]
