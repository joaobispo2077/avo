"""Explicit original authorial data generates a deterministic title overlay."""

import json
import shutil
from fractions import Fraction
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from tests.integration.test_otio_placed_render_runtime import _decoded
from tests.test_import_title import title_snapshot

from avo.adapters.media.proof_placed import execute_placed_proof
from avo.capabilities import default_proof_capability_registry
from avo.timeline.contracts import file_fingerprint
from avo.timeline.initial_cut_placed import placed_cut_proof_request

FONT = next(
    (
        p
        for p in [
            Path("C:/Windows/Fonts/seguisb.ttf"),
            Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
        ]
        if p.is_file()
    ),
    None,
)
pytestmark = pytest.mark.skipif(
    FONT is None or not shutil.which("ffmpeg") or not shutil.which("ffprobe"),
    reason="Installed font and native FFmpeg required",
)


def test_title_uses_locked_font_and_microproof_matches_full(tmp_path, monkeypatch):
    snapshot = title_snapshot()
    project = tmp_path / "original-title.json"
    project.write_text('{"text":"2026"}')
    font_copy = tmp_path / "original-font.ttf"
    shutil.copyfile(FONT, font_copy)
    for source, path in zip(snapshot["sources"], [project, font_copy], strict=True):
        source.update(locator=str(path), fingerprint=file_fingerprint(path))
    item = snapshot["layout"]["placements"][0]
    item["pictureFade"] = {"inFrames": 0, "outFrames": 6}
    request = placed_cut_proof_request(
        SimpleNamespace(raw_dir=tmp_path),
        snapshot,
        iteration_id="title",
        output=tmp_path / "full.mkv",
        frame_rate={"num": 24, "den": 1},
        width=64,
        height=48,
        sample_rate=48000,
        sample_rate_probe=None,
    )
    impl = default_proof_capability_registry().resolve("source-layout")
    request["videoGraph"]["operations"][0]["implementationId"] = impl.implementation_id
    request.update(
        window=None,
        sourceAssemblyPolicy="preserve-import",
        implementationRefs=[impl.proof_reference()],
        canonicalInputLock={
            f"source:{s['sourceId']}": s["fingerprint"]["sha256"]
            for s in snapshot["sources"]
        },
    )
    request["output"].update(
        videoCodec="ffv1", audioCodec="pcm_s32le", conformance=True
    )
    full = tmp_path / "full.mkv"
    execute_placed_proof(request, full, request["output"], Fraction(24), 48000)
    frames = _decoded(full)
    assert (
        len(frames) == 96
        and np.count_nonzero(frames[:24]) == 0
        and np.count_nonzero(frames[48:]) == 0
    )
    assert np.count_nonzero(frames[24]) > 0
    assert np.array_equal(frames[24], frames[40])
    assert np.sum(frames[47]) < np.sum(frames[24])
    request["window"] = {"startFrame": 42, "endFrameExclusive": 48}
    micro = tmp_path / "micro.mkv"
    execute_placed_proof(request, micro, request["output"], Fraction(24), 48000)
    assert np.array_equal(_decoded(micro), frames[42:48])
    request["canonicalInputLock"]["source:font"] = "0" * 64
    with pytest.raises(RuntimeError, match="lock mismatch"):
        execute_placed_proof(
            request, tmp_path / "wrong-font.mkv", request["output"], Fraction(24), 48000
        )
    request["canonicalInputLock"]["source:font"] = file_fingerprint(font_copy)["sha256"]
    from avo.adapters.media import proof_title

    render = proof_title.render_title

    def changed_after_render(*args, **kwargs):
        render(*args, **kwargs)
        font_copy.write_bytes(b"changed original font")

    monkeypatch.setattr(proof_title, "render_title", changed_after_render)
    with pytest.raises(RuntimeError, match="changed|fingerprint|lock"):
        execute_placed_proof(
            request,
            tmp_path / "changed-font.mkv",
            request["output"],
            Fraction(24),
            48000,
        )
    assert not (tmp_path / "changed-font.mkv").exists()


def test_title_survives_import_activation_and_canonical_proof_pipeline(tmp_path):
    from tests.integration.test_code_drawn_canonical_pipeline import _pixels
    from tests.integration.test_ffmpeg_proof_executor import _pcm
    from tests.integration.test_otio_placed_pipeline import _render, _trial
    from tests.test_timeline_import_service import _approve_fixture_sync

    service, _original, revision = _trial(tmp_path)
    baseline = _render(service, "baseline-reference")
    raw = service.workspace.raw_dir
    export_path = raw / "export.otio"
    export = json.loads(export_path.read_text())
    clip = export["tracks"]["children"][1]["children"][1]
    clip["media_reference"] = {"OTIO_SCHEMA": "MissingReference.1"}
    clip["source_range"]["start_time"]["value"] = 0
    export_path.write_text(json.dumps(export))
    reference = "/tracks/children/1/children/1/media_reference"
    document = raw / "original-title.json"
    document.write_text('{"text":"2026"}')
    font = raw / "original-font.ttf"
    shutil.copyfile(FONT, font)
    options = service.load(revision["snapshot"]["originRef"]["importId"])["options"]
    title = title_snapshot()["layout"]["placements"][0]["title"]
    options["mappings"][reference] = {
        "path": str(document),
        "identityConfirmed": True,
        "mediaKind": "title",
        "title": title,
        "font": {"path": str(font), "fingerprint": file_fingerprint(font)},
    }
    options["declarations"].update(
        sourceOnly=False,
        reconstructionMode="declared-treatments",
        generatedTitles=[reference],
        mediaOrigins={reference: {"value": "0", "rate": "24"}},
    )
    prepared = service.prepare(
        export_path,
        mappings=options["mappings"],
        declarations=options["declarations"],
        actor="fixture",
        reason="Canonical title pipeline qualification",
    )
    waiting = service.validate(prepared["importId"])
    assert waiting["status"] == "awaiting-sync", waiting.get("findings")
    _approve_fixture_sync(service, waiting["proposal"])
    ready = service.validate(prepared["importId"])
    service.activate(
        prepared["importId"],
        validation_hash=ready["validationHash"],
        expected_head=revision["contentHash"],
        actor="fixture",
        reason="Fixture title",
    )
    output = _render(service, "canonical-title")
    before, after = _pixels(baseline), _pixels(output)
    assert np.array_equal(before[:24], after[:24])
    assert np.array_equal(before[30:], after[30:])
    assert not np.array_equal(before[24:30], after[24:30])
    assert np.array_equal(_pcm(baseline), _pcm(output))
