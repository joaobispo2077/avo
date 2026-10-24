from __future__ import annotations

import array
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from avo.shorts_fidelity import build_fidelity_command, render_fidelity
from avo.shorts_media import sha256_file
from avo.shorts_rules import MediaPreparationError


def _source(tmp_path):
    source = tmp_path / "original.mkv"
    source.write_bytes(b"original")
    fingerprint = sha256_file(source)
    return source, {
        "source_segments": [{"startSec": 0, "endSec": 1}],
        "source_sha256": fingerprint,
        "canonical_lock": {"source": fingerprint},
    }


def _probe_runner(argv):
    return subprocess.CompletedProcess(
        argv,
        0,
        json.dumps(
            {
                "streams": [
                    {
                        "codec_type": "video",
                        "pix_fmt": "yuv420p10le",
                        "color_space": "bt709",
                        "color_transfer": "bt709",
                        "color_primaries": "bt709",
                    }
                ]
            }
        ),
        "",
    )


def test_original_lock_and_recursive_forbidden_ancestry_fail_closed(tmp_path):
    source, kwargs = _source(tmp_path)
    with pytest.raises(MediaPreparationError, match="fingerprint"):
        build_fidelity_command(
            source,
            tmp_path / "out.mp4",
            **{**kwargs, "canonical_lock": {"source": "0" * 64}},
            runner=_probe_runner,
        )
    with pytest.raises(MediaPreparationError, match="forbidden.*original"):
        build_fidelity_command(
            source,
            tmp_path / "out.mp4",
            **kwargs,
            source_ancestry=[
                {"mediaClass": "source", "ancestry": [{"mediaClass": "proof"}]}
            ],
            runner=_probe_runner,
        )
    with pytest.raises(MediaPreparationError, match="aliases"):
        build_fidelity_command(source, source, **kwargs, runner=_probe_runner)


def test_graph_preserves_ten_bits_and_timed_base_region(tmp_path):
    source, kwargs = _source(tmp_path)
    image = tmp_path / "insert.png"
    image.write_bytes(b"image")
    kwargs["canonical_lock"]["image"] = sha256_file(image)
    insert = {
        "kind": "image",
        "path": str(image),
        "sha256": sha256_file(image),
        "startSec": 0.2,
        "endSec": 0.8,
        "fit": "contain",
        "rect": {"x": 0, "y": 0.68, "width": 1, "height": 0.32},
        "baseRegion": {"x": 0, "y": 0, "width": 1, "height": 0.68},
    }
    command = build_fidelity_command(
        source,
        tmp_path / "out.mp4",
        **kwargs,
        visual_inserts=[insert],
        runner=_probe_runner,
    )
    graph = command[command.index("-filter_complex") + 1]
    assert "format=yuv420p10le" in graph
    assert "format=yuv420p," not in graph
    assert "overlay=x=0:y=0:format=yuv420p10" in graph
    assert "gte(t,0.2)*lt(t,0.8)" in graph
    assert command[command.index("-c:v") + 1] == "libx265"
    assert command[command.index("-r") + 1] == "30000/1001"


def test_eight_bit_source_is_rejected(tmp_path):
    source, kwargs = _source(tmp_path)

    def runner(argv):
        result = _probe_runner(argv)
        result.stdout = result.stdout.replace("yuv420p10le", "yuv420p")
        return result

    with pytest.raises(MediaPreparationError, match="original yuv420p10le"):
        build_fidelity_command(source, tmp_path / "out.mp4", **kwargs, runner=runner)


def test_original_named_preview_is_rejected_but_generated_overlay_is_allowed(tmp_path):
    source, kwargs = _source(tmp_path)
    preview = source.with_name("clip-preview-v001.mkv")
    preview.write_bytes(source.read_bytes())
    with pytest.raises(MediaPreparationError, match="forbidden original"):
        build_fidelity_command(
            preview, tmp_path / "out.mp4", **kwargs, runner=_probe_runner
        )


def test_vp9_overlay_accepts_uppercase_ffprobe_alpha_mode_tag(tmp_path):
    source, kwargs = _source(tmp_path)
    overlay = tmp_path / "graphics-alpha.webm"
    overlay.write_bytes(b"overlay")
    overlay_hash = sha256_file(overlay)
    kwargs["canonical_lock"]["overlay"] = overlay_hash

    def runner(argv):
        if str(overlay) in argv:
            return subprocess.CompletedProcess(
                argv,
                0,
                json.dumps(
                    {
                        "streams": [
                            {
                                "codec_type": "video",
                                "codec_name": "vp9",
                                "pix_fmt": "yuv420p",
                                "tags": {"ALPHA_MODE": "1"},
                            }
                        ]
                    }
                ),
                "",
            )
        return _probe_runner(argv)

    command = build_fidelity_command(
        source,
        tmp_path / "out.mp4",
        **kwargs,
        overlay_path=overlay,
        overlay_sha256=overlay_hash,
        runner=runner,
    )
    assert command[command.index("-c:v") + 1] == "libvpx-vp9"


def test_split_fidelity_requires_timed_visual_inserts():
    from avo.shorts import _fidelity_segments

    item = {
        "layout": {"mode": "split"},
        "insertion": None,
        "sourceSegments": [{"sourceFingerprint": "a" * 64}],
        "visualInserts": [],
    }
    with pytest.raises(RuntimeError, match="timed visualInserts"):
        _fidelity_segments(item)

    item["visualInserts"] = [{"id": "gameplay"}]
    assert _fidelity_segments(item) == item["sourceSegments"]


def test_only_slow_media_warning_can_retry_without_strict_mode():
    from avo.shorts import _only_slow_media_warning

    slow = subprocess.CompletedProcess([], 1, "⚠ clip_media_fit: delayed\n", "")
    overlap = subprocess.CompletedProcess([], 1, "✗ content_overlap: captions\n", "")
    assert _only_slow_media_warning(slow) is True
    assert _only_slow_media_warning(overlap) is False


def test_fidelity_lock_tracks_hyperframes_implementation_and_templates():
    from avo.shorts import _fidelity_implementation_hashes

    hashes = _fidelity_implementation_hashes()
    assert "implementation:hyperframes.py" in hashes
    for name in ("index.html", "runtime.js", "styles.css", "hyperframes.json"):
        assert f"implementation:{name}" in hashes


def test_microproof_window_preserves_whole_picture_graph(tmp_path):
    source, kwargs = _source(tmp_path)
    full = build_fidelity_command(
        source, tmp_path / "full.mp4", **kwargs, runner=_probe_runner
    )
    micro = build_fidelity_command(
        source,
        tmp_path / "micro.mp4",
        **kwargs,
        window={"startSec": 0.2, "endSec": 0.6},
        runner=_probe_runner,
    )
    assert (
        full[full.index("-filter_complex") + 1]
        == micro[micro.index("-filter_complex") + 1]
    )
    assert (
        micro[micro.index("-filter_complex") + 1 :]
        != full[full.index("-filter_complex") + 1 :]
    )
    assert micro[-micro[::-1].index("-t")] == "0.400000"


def test_dialogue_tail_gap_is_measured_and_large_missing_audio_fails(tmp_path):
    from avo.shorts_fidelity_audio import _dialogue_clock
    from avo.shorts_media import PreparedAsset

    def probe_runner(duration):
        return lambda argv: subprocess.CompletedProcess(
            argv,
            0,
            json.dumps(
                {
                    "streams": [
                        {
                            "codec_type": "audio",
                            "sample_rate": "48000",
                            "duration": duration,
                        }
                    ]
                }
            ),
            "",
        )

    asset = PreparedAsset(tmp_path / "dialogue.wav", "0" * 64, 25.01)
    clock = _dialogue_clock(asset, 25.01, probe_runner("25.002417"))
    assert clock["trailingPaddingSamples"] == 364
    with pytest.raises(MediaPreparationError, match="sample count"):
        _dialogue_clock(asset, 25.01, probe_runner("24.91"))


def test_microproof_gate_locks_inputs_and_reuses_full_picture_graph(
    tmp_path, monkeypatch
):
    from avo import shorts_fidelity

    source, kwargs = _source(tmp_path)
    image, video = tmp_path / "image.png", tmp_path / "gameplay.mp4"
    image.write_bytes(b"image")
    video.write_bytes(b"video")
    item = {
        "id": "05",
        "speed": 1,
        "sourceSegments": [{"startSec": 0, "endSec": 4}],
        "punchIns": [{"startSec": 3, "endSec": 4, "scale": 1.1}],
        "visualInserts": [],
    }
    for index, path in enumerate((image, video), 1):
        item["visualInserts"].append(
            {
                "id": f"insert-{index}",
                "kind": "image" if index == 1 else "video",
                "path": str(path),
                "sha256": sha256_file(path),
                "startSec": index,
                "endSec": index + 1,
                "rect": {"x": 0, "y": 0, "width": 1, "height": 0.25},
                "sourceStartSec": 0,
                "sourceEndSec": 1,
                "videoStreamIndex": 0,
            }
        )
    graphs = []

    def render(source_arg, output, **options):
        command = build_fidelity_command(
            source_arg, output, **{**options, "runner": _probe_runner}
        )
        full = build_fidelity_command(
            source_arg, output, **{**options, "window": None, "runner": _probe_runner}
        )
        graph = command[command.index("-filter_complex") + 1]
        assert graph == full[full.index("-filter_complex") + 1]
        assert source_arg == source
        assert options.get("overlay_path") is None
        graphs.append(graph)
        output.write_bytes(b"microproof")
        return {"path": str(output), "sha256": sha256_file(output)}

    monkeypatch.setattr(shorts_fidelity, "render_fidelity", render)
    gate = shorts_fidelity.build_microproofs(
        source,
        tmp_path / "micro",
        plan_hash="a" * 64,
        item=item,
        source_sha256=kwargs["source_sha256"],
        width=64,
        height=96,
        fps="30000/1001",
    )
    assert len(graphs) == 4
    assert len(set(graphs)) == 1
    assert gate["status"] == "passed"
    assert gate["sha256"] == sha256_file(Path(gate["path"]))
    assert gate["canonicalInputLock"]["insert:insert-1"] == sha256_file(image)
    assert gate["scope"] == "original-picture-and-mixed-audio-only"
    assert "separate" in gate["graphicsReview"]


def test_microproof_gate_deduplicates_windows_and_never_writes_pass_after_failure(
    tmp_path, monkeypatch
):
    from avo import shorts_fidelity

    item = {
        "id": "01",
        "sourceSegments": [{"startSec": 0, "endSec": 0.5}],
        "punchIns": [{"startSec": 0, "endSec": 0.5, "scale": 1.1}],
    }
    windows = shorts_fidelity._microproof_windows(item, 0.5)
    assert len(windows) == 1
    assert windows[0]["cases"] == ["opening", "punch"]

    def fail(*args, **kwargs):
        raise MediaPreparationError("render failed")

    monkeypatch.setattr(shorts_fidelity, "render_fidelity", fail)
    with pytest.raises(MediaPreparationError, match="render failed"):
        shorts_fidelity.build_microproofs(
            tmp_path / "original.mkv",
            tmp_path / "micro",
            plan_hash="a" * 64,
            item=item,
            source_sha256="b" * 64,
            width=64,
            height=96,
            fps="30",
        )
    assert not (tmp_path / "micro" / "microproof-gate.json").exists()


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="FFmpeg not installed")
def test_real_audio_mix_uses_two_pass_loudness_and_pcm48k(tmp_path):
    from avo.shorts_fidelity_audio import mix_short_audio
    from avo.shorts_media import PreparedAsset, probe_media

    source = tmp_path / "dialogue.wav"
    effect = tmp_path / "effect.wav"
    for path, frequency, duration in ((source, 220, 1), (effect, 900, 0.1)):
        subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-f",
                "lavfi",
                "-i",
                f"sine=frequency={frequency}:sample_rate=48000:duration={duration}",
                "-c:a",
                "pcm_s24le",
                str(path),
            ],
            check=True,
        )
    result = mix_short_audio(
        {
            "dialogueAudio": PreparedAsset(source, sha256_file(source), 1),
            "sfxPrice": PreparedAsset(effect, sha256_file(effect), 0.1).as_contract(),
        },
        {"sfxHits": [{"kind": "price", "startSec": 0.25}]},
        tmp_path / "mixed.wav",
    )
    probe = probe_media(Path(result["path"]))
    assert probe["streams"][0]["sample_rate"] == "48000"
    assert probe["streams"][0]["channels"] == 1
    assert abs(float(probe["format"]["duration"]) - 1) < 1 / 48000


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="FFmpeg not installed")
def test_dynamic_loudnorm_preserves_nonround_25_second_sample_clock(tmp_path):
    from avo.shorts_fidelity_audio import mix_short_audio
    from avo.shorts_media import PreparedAsset, probe_media

    source = tmp_path / "dynamic-dialogue.wav"
    output = tmp_path / "mixed.wav"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            (
                "aevalsrc='(if(lt(mod(t,8),4),0.025,0.06)+if(lt(mod(t,8),0.02),0.7,0))*(sin(2*PI*223*t)+"
                "0.25*sin(2*PI*871*t))':s=48000:d=25.01"
            ),
            "-c:a",
            "pcm_s24le",
            str(source),
        ],
        check=True,
    )
    result = mix_short_audio(
        {"dialogueAudio": PreparedAsset(source, sha256_file(source), 25.01)}, {}, output
    )
    probe = probe_media(output)
    assert probe["streams"][0]["duration_ts"] == round(25.01 * 48000)
    assert result["sourceClock"]["trailingPaddingSamples"] == 0
    values = result["measurements"]
    assert values["input_tp"] + (-16 - values["input_i"]) > -1

    def waveform(path):
        raw = subprocess.run(
            ["ffmpeg", "-v", "error", "-i", str(path), "-f", "f32le", "-"],
            capture_output=True,
            check=True,
        ).stdout
        return array.array("f", raw)

    original, mixed = waveform(source), waveform(output)
    # A duration-only pad could hide a cut tail. Both ends must still contain
    # the same signal at the same sample, allowing loudnorm's varying gain.
    for first, last in ((24000, 28800), (-4800, -1)):
        a, b = original[first:last], mixed[first:last]
        correlation = (
            sum(x * y for x, y in zip(a, b))
            / (sum(x * x for x in a) * sum(y * y for y in b)) ** 0.5
        )
        assert correlation > 0.99


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="FFmpeg not installed")
def test_real_ten_bit_ramp_survives_concat_and_alpha_composite(tmp_path):
    """More than 256 decoded luma values catches an 8-bit picture round trip."""
    source, overlay, output, insert_path = (
        tmp_path / name
        for name in ("original.mkv", "graphics.mov", "out.mp4", "image.png")
    )
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            (
                "nullsrc=s=512x32:r=30000/1001,format=yuv420p10le,"
                "geq=lum='64+X*1.75':cb=512:cr=512"
            ),
            "-t",
            "0.3",
            "-c:v",
            "ffv1",
            "-pix_fmt",
            "yuv420p10le",
            str(source),
        ],
        check=True,
    )
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            (
                "color=red@0:s=512x32:r=30000/1001,format=argb,"
                "drawbox=x=0:y=0:w=8:h=8:color=white@1:t=fill"
            ),
            "-t",
            "0.3",
            "-c:v",
            "qtrle",
            str(overlay),
        ],
        check=True,
    )
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=blue:s=64x32",
            "-frames:v",
            "1",
            str(insert_path),
        ],
        check=True,
    )
    source_hash, overlay_hash = sha256_file(source), sha256_file(overlay)
    image_hash = sha256_file(insert_path)
    result = render_fidelity(
        source,
        output,
        source_segments=[
            {"startSec": 0, "endSec": 0.1},
            {"startSec": 0.15, "endSec": 0.25},
        ],
        source_sha256=source_hash,
        canonical_lock={
            "source": source_hash,
            "overlay": overlay_hash,
            "image": image_hash,
        },
        overlay_path=overlay,
        overlay_sha256=overlay_hash,
        visual_inserts=[
            {
                "kind": "image",
                "path": str(insert_path),
                "sha256": image_hash,
                "startSec": 0.1,
                "endSec": 0.18,
                "fit": "contain",
                "rect": {"x": 0, "y": 0.75, "width": 1, "height": 0.25},
                "baseRegion": {"x": 0, "y": 0, "width": 1, "height": 0.75},
            }
        ],
        punch_ins=[{"startSec": 0.1, "endSec": 0.18, "scale": 1.1}],
        width=512,
        height=32,
        preset="ultrafast",
        crf=0,
    )
    assert result["video"]["pix_fmt"] == "yuv420p10le"
    decoded = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            str(output),
            "-frames:v",
            "1",
            "-pix_fmt",
            "yuv420p10le",
            "-f",
            "rawvideo",
            "-",
        ],
        check=True,
        capture_output=True,
    ).stdout
    luma = array.array("H", decoded[: 512 * 32 * 2])
    assert len(set(luma[16 * 512 : 17 * 512])) > 256
