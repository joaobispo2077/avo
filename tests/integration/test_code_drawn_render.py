"""Physical browser/encoder evidence for the framework-free motion path."""

from __future__ import annotations

import importlib
import io
import json
import os
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from fractions import Fraction
from pathlib import Path

import pytest
from PIL import Image

from avo import motion
from avo.timeline.contracts import file_fingerprint

pytestmark = pytest.mark.integration

FIXTURES = Path(__file__).parents[1] / "fixtures" / "code_drawn"
WIDTH, HEIGHT, FRAMES = 128, 96, 12
MOMENTS = [0, 1, 2, 3, 4, 5, 6, 8, 10, 11]
ENVELOPE_FIELDS = {
    "operation",
    "status",
    "selection",
    "savedPreferences",
    "runSelection",
    "recordedAnimation",
    "readiness",
    "artifacts",
    "checks",
    "errors",
}


def _runtime_missing(reason: str) -> None:
    if os.environ.get("AVO_REQUIRE_CODE_DRAWN_RUNTIME") == "1":
        pytest.fail(reason)
    pytest.skip(reason)


@pytest.fixture(scope="module")
def adapter_type():
    module = importlib.import_module("avo.adapters.motion.code_drawn")
    adapter = module.CodeDrawnAdapter
    readiness = module.runtime_readiness()
    if not readiness["ready"]:
        _runtime_missing("; ".join(readiness["blockers"]))
    return adapter


def _ok(result: dict) -> None:
    assert set(result) == ENVELOPE_FIELDS
    assert result["status"] == "ok", result
    assert not result["errors"], result


def _failure(operation) -> dict:
    with pytest.raises(motion.MotionError) as caught:
        operation()
    return caught.value.to_dict()


def _save_manifest(composition: Path, manifest: dict) -> None:
    composition.write_text(
        json.dumps(motion.seal_composition(manifest), indent=2) + "\n",
        encoding="utf-8",
    )


def _replace_source(composition: Path, source: str) -> None:
    manifest = json.loads(composition.read_text(encoding="utf-8"))
    entry = composition.parent / manifest["entry"]
    entry.write_text(source, encoding="utf-8")
    fingerprint = file_fingerprint(entry)
    manifest["files"] = [
        {
            "path": manifest["entry"],
            "sha256": fingerprint["sha256"],
            "sizeBytes": fingerprint["sizeBytes"],
            "role": "source",
        }
    ]
    manifest["sourceRevision"] = "integration-source-r0001"
    _save_manifest(composition, manifest)


def _composition(
    tmp_path: Path,
    route: str = "canvas",
    *,
    background: str = "transparent",
    frames: int = FRAMES,
) -> Path:
    destination = tmp_path / "composition"
    result = motion.scaffold_code_drawn(
        destination=destination,
        route=route,
        width=WIDTH,
        height=HEIGHT,
        fps="30000/1001",
        frames=frames,
        background=background,
        background_color="#14202a" if background == "opaque" else None,
    )
    _ok(result)
    composition = destination / "composition.json"
    manifest = json.loads(composition.read_text(encoding="utf-8"))
    assert manifest["drawingRoute"] == route
    if route != "brush":
        source = (FIXTURES / f"{route}.html").read_text(encoding="utf-8")
        source = source.replace(
            "__AVO_TEST_BACKGROUND__",
            json.dumps("#14202a" if background == "opaque" else None),
        )
        _replace_source(composition, source)
    return composition


def _rgba(png: bytes) -> bytes:
    with Image.open(io.BytesIO(png)) as image:
        assert image.size == (WIDTH, HEIGHT)
        return image.convert("RGBA").tobytes()


def _freeze(adapter, composition: Path, tmp_path: Path) -> Path:
    lock = tmp_path / "input-lock.json"
    result = adapter.check(composition, output_lock=lock)
    _ok(result)
    assert result["readiness"]["ready"] is True
    assert result["checks"]
    binding = json.loads(lock.read_text(encoding="utf-8"))
    assert binding["bindingMode"] == "standalone"
    assert "canonicalInputLock" not in binding
    return lock


def _decoded(path: Path) -> tuple[dict, list[bytes]]:
    probe = json.loads(
        subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-count_frames",
                "-show_streams",
                "-show_format",
                "-of",
                "json",
                str(path),
            ],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    )
    streams = probe["streams"]
    assert len(streams) == 1 and streams[0]["codec_type"] == "video"
    video = streams[0]
    assert video["codec_name"] == "ffv1"
    assert video["pix_fmt"] == "bgra"
    assert (video["width"], video["height"]) == (WIDTH, HEIGHT)
    assert Fraction(video["r_frame_rate"]) == Fraction(30000, 1001)
    raw = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            str(path),
            "-map",
            "0:v:0",
            "-fps_mode",
            "passthrough",
            "-pix_fmt",
            "rgba",
            "-f",
            "rawvideo",
            "pipe:1",
        ],
        capture_output=True,
        check=True,
    ).stdout
    frame_size = WIDTH * HEIGHT * 4
    assert len(raw) % frame_size == 0
    return video, [
        raw[offset : offset + frame_size] for offset in range(0, len(raw), frame_size)
    ]


@pytest.mark.parametrize(
    "route,software",
    [("canvas", False), ("svg", False), ("brush", False), ("brush", True)],
)
@pytest.mark.parametrize("background", ["opaque", "transparent"])
def test_packaged_starters_preserve_exact_rgba(
    tmp_path, adapter_type, route, software, background, monkeypatch
):
    if software:
        from playwright.sync_api import BrowserType

        original = BrowserType.launch

        def launch(browser_type, *args, **kwargs):
            kwargs["args"] = [*kwargs.get("args", []), "--use-angle=swiftshader"]
            return original(browser_type, *args, **kwargs)

        monkeypatch.setattr(BrowserType, "launch", launch)
    destination = tmp_path / route
    _ok(
        motion.scaffold_code_drawn(
            destination=destination,
            route=route,
            width=WIDTH,
            height=HEIGHT,
            fps="30/1",
            frames=3,
            background=background,
            background_color="#121212" if background == "opaque" else None,
        )
    )
    composition = destination / "composition.json"
    adapter = adapter_type()
    lock = _freeze(adapter, composition, tmp_path)
    _ok(adapter.render(composition, input_lock=lock, output=tmp_path / "asset.mkv"))


@pytest.mark.parametrize("route", ["canvas", "svg", "brush"])
def test_real_routes_seek_repeat_reverse_fresh_and_lossless_encode(
    tmp_path: Path, adapter_type, route: str, monkeypatch
) -> None:
    composition = _composition(tmp_path, route)
    if route == "brush":
        # A portable authored project needs only its declared local brush bytes.
        empty_home = tmp_path / "empty-home"
        empty_home.mkdir()
        from avo.templates.code_drawn import brush_cache_paths

        monkeypatch.setattr(
            "avo.adapters.motion.code_drawn.brush_cache_paths",
            lambda: brush_cache_paths(empty_home),
        )
        monkeypatch.setattr(
            "avo.motion_runtime.brush_cache_paths",
            lambda: brush_cache_paths(empty_home),
        )
    adapter = adapter_type()
    sequence = MOMENTS + MOMENTS + list(reversed(MOMENTS))
    captured = [_rgba(png) for png in adapter.capture_frames(composition, sequence)]
    fresh = [_rgba(png) for png in adapter_type().capture_frames(composition, MOMENTS)]
    assert len(captured) == len(sequence)
    assert len(fresh) == len(MOMENTS)
    for index, reference in enumerate(captured[:10]):
        assert reference == captured[index + 10]
        assert reference == captured[29 - index]
        assert reference == fresh[index]
    assert len(set(fresh)) > 1, "The fixture must exercise actual motion."
    assert min(fresh[0][3::4]) == 0
    assert max(fresh[0][3::4]) > 0
    assert any(0 < alpha < 255 for alpha in fresh[0][3::4])

    lock = _freeze(adapter, composition, tmp_path)
    snapshot = tmp_path / "frame-five.png"
    _ok(adapter.snapshot(composition, frame=5, output=snapshot, input_lock=lock))
    assert _rgba(snapshot.read_bytes()) == fresh[MOMENTS.index(5)]

    output = tmp_path / "asset.mkv"
    result = adapter.render(composition, input_lock=lock, output=output)
    _ok(result)
    video, decoded = _decoded(output)
    assert int(video["nb_read_frames"]) == FRAMES
    assert len(decoded) == FRAMES
    for index, frame in enumerate(MOMENTS):
        assert decoded[frame] == fresh[index]

    receipt = json.loads(
        output.with_suffix(".generated-asset.json").read_text(encoding="utf-8")
    )
    binding = json.loads(lock.read_text(encoding="utf-8"))
    extension = receipt["parameters"]["codeDrawn"]
    assert receipt["generator"]["adapterId"] == "code-drawn"
    assert receipt["reproducibility"] == "verified"
    assert receipt["approvalReference"] is None
    assert extension["drawingRoute"] == route
    assert extension["inputLockHash"] == binding["inputLockHash"]
    assert extension["inputLockRef"]["sha256"] == file_fingerprint(lock)["sha256"]
    assert extension["captureEvidence"]
    assert extension["outputVerification"]
    assert "canonicalInputLock" not in extension
    assert receipt["output"]["sha256"] == file_fingerprint(output)["sha256"]


def test_real_opaque_asset_preserves_declared_background(tmp_path, adapter_type):
    composition = _composition(tmp_path, background="opaque")
    adapter = adapter_type()
    lock = _freeze(adapter, composition, tmp_path)
    output = tmp_path / "opaque.mkv"
    _ok(adapter.render(composition, input_lock=lock, output=output))
    _video, frames = _decoded(output)
    assert len(frames) == FRAMES
    assert all(alpha == 255 for frame in frames for alpha in frame[3::4])
    assert frames[0][:4] == bytes((20, 32, 42, 255))


@pytest.mark.parametrize("kind", ["font", "image"])
def test_declared_corrupt_assets_are_readiness_failures(tmp_path, adapter_type, kind):
    composition = _composition(tmp_path)
    manifest = json.loads(composition.read_text(encoding="utf-8"))
    asset = composition.parent / ("broken.woff2" if kind == "font" else "broken.png")
    asset.write_bytes(b"Deliberately invalid synthetic test asset")
    fingerprint = file_fingerprint(asset)
    declared = {
        "path": asset.name,
        "sha256": fingerprint["sha256"],
        "sizeBytes": fingerprint["sizeBytes"],
        "id": "broken-asset",
        "kind": kind,
        "rightsRef": "ANIMATION-SOURCE-LOG.md",
    }
    if kind == "font":
        declared.update(family="InvalidFixtureFace", style="normal", weight=400)
    else:
        declared.update(width=1, height=1)
    manifest["assets"] = [declared]
    _save_manifest(composition, manifest)
    lock = tmp_path / "must-not-exist.json"
    error = _failure(lambda: adapter_type().check(composition, output_lock=lock))
    assert error["code"] == "CODE_DRAWN_ASSET_NOT_READY"
    assert not lock.exists()


@pytest.mark.parametrize(
    "fault",
    [
        "rejected-ready",
        "throwing-seek",
        "undeclared-input",
        "external-input",
        "history-dependent",
    ],
)
def test_real_bridge_rejects_unready_unregistered_or_order_dependent_source(
    tmp_path, adapter_type, fault
):
    composition = _composition(tmp_path)
    entry = composition.parent / "index.html"
    source = entry.read_text(encoding="utf-8")
    additions = {
        "rejected-ready": "window.avoReady=Promise.reject(new Error('fixture ready'));",
        "throwing-seek": "window.seek=()=>{throw new Error('fixture seek');};",
        "undeclared-input": (
            "window.avoReady=fetch('undeclared.json').then(r=>{"
            "if(!r.ok)throw new Error('undeclared fixture');});"
        ),
        "external-input": (
            "window.avoReady=fetch(['https:','','avo-runtime-test.invalid',"
            "'remote.svg'].join('/'));"
        ),
        "history-dependent": (
            "const previousSeek=window.seek;let calls=0;"
            "window.seek=async(t)=>{await previousSeek(t);calls++;"
            "context.fillStyle='rgb('+calls+',0,0)';context.fillRect(0,0,2,2);};"
        ),
    }
    if fault == "undeclared-input":
        (composition.parent / "undeclared.json").write_text("{}", encoding="utf-8")
    _replace_source(
        composition, source.replace("</script>", additions[fault] + "</script>")
    )
    error = _failure(lambda: adapter_type(timeout_ms=3000).check(composition))
    if fault == "history-dependent":
        assert error["code"] == "CODE_DRAWN_SEEK_MISMATCH"


def test_real_render_rejects_stale_original_lock_without_rewriting_it(
    tmp_path, adapter_type
):
    composition = _composition(tmp_path)
    adapter = adapter_type()
    lock = _freeze(adapter, composition, tmp_path)
    original_lock = lock.read_bytes()
    entry = composition.parent / "index.html"
    _replace_source(
        composition, entry.read_text(encoding="utf-8") + "\n<!-- revision -->"
    )
    output = tmp_path / "stale.mkv"
    error = _failure(
        lambda: adapter.render(composition, input_lock=lock, output=output)
    )
    assert error["code"] == "CODE_DRAWN_LOCK_STALE"
    assert lock.read_bytes() == original_lock
    assert not output.exists()
    assert not output.with_suffix(".generated-asset.json").exists()


@pytest.mark.parametrize("frame", [-1, FRAMES])
def test_snapshot_rejects_nonexistent_endpoint_frame(tmp_path, adapter_type, frame):
    composition = _composition(tmp_path)
    output = tmp_path / "invalid.png"
    _failure(lambda: adapter_type().snapshot(composition, frame=frame, output=output))
    assert not output.exists()


def test_successful_output_and_receipt_are_not_overwritten(tmp_path, adapter_type):
    composition = _composition(tmp_path)
    adapter = adapter_type()
    lock = _freeze(adapter, composition, tmp_path)
    output = tmp_path / "immutable.mkv"
    _ok(adapter.render(composition, input_lock=lock, output=output))
    receipt = output.with_suffix(".generated-asset.json")
    before = output.read_bytes(), receipt.read_bytes()
    _failure(lambda: adapter.render(composition, input_lock=lock, output=output))
    assert (output.read_bytes(), receipt.read_bytes()) == before


def test_real_encoder_nonzero_exit_cannot_register_success(
    tmp_path, adapter_type, monkeypatch
):
    composition = _composition(tmp_path)
    adapter = adapter_type()
    lock = _freeze(adapter, composition, tmp_path)
    original_popen = subprocess.Popen
    failed_launches = []

    def fail_encoding_only(arguments, *args, **kwargs):
        command = [str(value) for value in arguments]
        if "ffv1" in command and any(value in command for value in ("pipe:0", "-")):
            command.insert(1, "-avo-test-invalid-encoding-option")
            failed_launches.append(command)
        return original_popen(command, *args, **kwargs)

    monkeypatch.setattr(subprocess, "Popen", fail_encoding_only)
    output = tmp_path / "failed.mkv"
    error = _failure(
        lambda: adapter.render(composition, input_lock=lock, output=output)
    )
    assert error["code"] == "CODE_DRAWN_RENDER_FAILED"
    assert failed_launches, "The real encoder launch must have been exercised."
    assert not output.exists()
    assert not output.with_suffix(".generated-asset.json").exists()


def test_inflight_cancellation_closes_real_attempt_without_success(
    tmp_path, adapter_type
):
    composition = _composition(tmp_path, frames=300)
    lock = _freeze(adapter_type(), composition, tmp_path)
    cancelled = threading.Event()
    adapter = adapter_type(timeout_ms=2000, cancel_event=cancelled)
    output = tmp_path / "cancelled.mkv"
    timer = threading.Timer(0.5, cancelled.set)
    with ThreadPoolExecutor(max_workers=1) as pool:
        attempt = pool.submit(
            adapter.render, composition, input_lock=lock, output=output
        )
        timer.start()
        try:
            with pytest.raises(motion.MotionError) as caught:
                attempt.result(timeout=12)
        finally:
            cancelled.set()
            timer.cancel()
    assert caught.value.code == "CODE_DRAWN_CANCELLED"
    assert not output.exists()
    assert not output.with_suffix(".generated-asset.json").exists()
    assert not list(tmp_path.glob(".avo-drawing-*"))


LAYOUTS = [
    pytest.param("horizontal", 1280, 720, id="horizontal-hd"),
    pytest.param("vertical", 720, 1280, id="vertical-hd"),
    pytest.param("square", 1080, 1080, id="square-hd"),
]


def _starter(tmp_path, route, width, height):
    result = motion.scaffold_code_drawn(
        destination=tmp_path / route,
        route=route,
        width=width,
        height=height,
        fps="6/1",
        frames=6,
        background="transparent",
    )
    _ok(result)
    return tmp_path / route / "composition.json"


def _text_bounds(adapter, composition, frame):
    manifest = motion.load_composition(composition)
    with adapter._session(composition, manifest) as (page, failures, _environment):
        result = page.evaluate(
            """async seconds => {
              const labels = [];
              const original = CanvasRenderingContext2D.prototype.fillText;
              CanvasRenderingContext2D.prototype.fillText = function(text, x, y, ...rest) {
                const metrics = this.measureText(text);
                const matrix = this.getTransform();
                const bounds = [
                  matrix.transformPoint(new DOMPoint(
                    x - metrics.actualBoundingBoxLeft,
                    y - metrics.actualBoundingBoxAscent)),
                  matrix.transformPoint(new DOMPoint(
                    x + metrics.actualBoundingBoxRight,
                    y + metrics.actualBoundingBoxDescent))
                ];
                labels.push({text, left:bounds[0].x, top:bounds[0].y,
                  right:bounds[1].x, bottom:bounds[1].y, font:this.font});
                return original.call(this, text, x, y, ...rest);
              };
              try { await window.seek(seconds); }
              finally { CanvasRenderingContext2D.prototype.fillText = original; }
              for (const text of document.querySelectorAll('#avo-stage text')) {
                if (!text.textContent.trim()) continue;
                const bounds = text.getBoundingClientRect();
                labels.push({text:text.textContent, left:bounds.left, top:bounds.top,
                  right:bounds.right, bottom:bounds.bottom,
                  font:getComputedStyle(text).font});
              }
              return labels;
            }""",
            adapter._frame(manifest, frame),
        )
        adapter._failures(failures)
    return result


@pytest.mark.parametrize("route", ["canvas", "svg", "brush"])
@pytest.mark.parametrize("aspect,width,height", LAYOUTS)
def test_actual_starters_relayout_text_inside_each_aspect(
    tmp_path, adapter_type, route, aspect, width, height
):
    composition = _starter(tmp_path, route, width, height)
    labels = _text_bounds(adapter_type(), composition, 3)
    assert labels, "Every drawing starter needs an actual title."
    title = [
        item
        for item in labels
        if item["text"] in {"Code-drawn motion", "Code-drawn", "motion"}
    ]
    assert " ".join(item["text"] for item in title) == "Code-drawn motion"
    assert len(title) == (2 if width <= height else 1)
    for label in labels:
        assert width * 0.03 <= label["left"] < label["right"] <= width * 0.97
        assert height * 0.03 <= label["top"] < label["bottom"] <= height * 0.97
    (tmp_path / "actual-text-bounds.json").write_text(
        json.dumps(
            {"aspect": aspect, "width": width, "height": height, "labels": labels},
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


@pytest.mark.parametrize("route", ["canvas", "svg", "brush"])
@pytest.mark.parametrize("aspect,width,height", LAYOUTS)
def test_actual_hd_routes_produce_candidate_bound_review_artifacts(
    tmp_path, adapter_type, route, aspect, width, height
):
    from avo.adapters.qc.code_drawn_review import CodeDrawnReviewProducer

    composition = _starter(tmp_path, route, width, height)
    adapter = adapter_type()
    samples = [0, 1, 3, 5]  # First, reveal, dense/settled, final actual sample.
    reference = adapter.capture_frames(composition, samples)
    lock = _freeze(adapter, composition, tmp_path)
    output = tmp_path / "actual-source-asset.mkv"
    _ok(adapter.render(composition, input_lock=lock, output=output))
    contract = {
        "width": width,
        "height": height,
        "frameRate": {"num": 6, "den": 1},
        "frameCount": 6,
    }
    fingerprint = file_fingerprint(output)
    loop_requested = aspect == "square"
    producer = CodeDrawnReviewProducer()
    result = producer(
        candidate=output,
        output_dir=tmp_path / "review",
        candidate_contract=contract,
        sample_frames=samples,
        transition_ranges=[{"startFrame": 1, "endFrameExclusive": 4}],
        loop_requested=loop_requested,
    )
    assert result["status"] == "needs-human-judgment"
    assert result["findings"] == [], "The producer cannot invent visual approval."
    artifacts = result["artifacts"]
    frames = [item for item in artifacts if item["kind"] == "frame"]
    small = [item for item in artifacts if item["kind"] == "small-display"]
    assert [item["frame"] for item in frames] == samples
    assert [item["frame"] for item in small] == samples
    for artifact, png in zip(frames, reference, strict=True):
        with (
            Image.open(artifact["path"]) as actual,
            Image.open(io.BytesIO(png)) as expected,
        ):
            assert actual.size == expected.size == (width, height)
            ink = actual.getchannel("A").getbbox()
            if ink is not None:
                assert 1 < ink[0] < ink[2] < width - 1
                assert 1 < ink[1] < ink[3] < height - 1
            assert (
                actual.convert("RGBA").tobytes() == expected.convert("RGBA").tobytes()
            )
    for artifact in small:
        with Image.open(artifact["path"]) as image:
            assert image.size == (360, round(height * 360 / width))
    sheets = [item for item in artifacts if item["kind"] == "contact-sheet"]
    strips = [item for item in artifacts if item["kind"] == "transition-strip"]
    loops = [item for item in artifacts if item["kind"] == "loop-strip"]
    assert len(sheets) == len(strips) == 1
    assert strips[0]["frames"] == [1, 2, 3]
    assert bool(loops) is loop_requested
    if loop_requested:
        assert loops[0]["frames"] == [5, 0]
        assert loops[0]["range"] == {"startFrame": 0, "endFrameExclusive": 6}
        # The generic reveal is not an authored seamless loop. Preserve evidence.
        assert (
            producer._frame(output, 5).tobytes() != producer._frame(output, 0).tobytes()
        )
    assert file_fingerprint(output) == fingerprint
    evidence = {
        "route": route,
        "aspect": aspect,
        "candidate": {"path": str(output), **fingerprint},
        "contract": contract,
        "samples": {"first": 0, "reveal": 1, "dense": 3, "final": 5},
        "loopRequested": loop_requested,
        "visualReview": "pending-human",
        "result": result,
    }
    (tmp_path / "physical-review-evidence.json").write_text(
        json.dumps(evidence, indent=2) + "\n", encoding="utf-8"
    )
