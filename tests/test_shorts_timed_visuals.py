"""Timed inserts must remain bound to exact media and the edited clock."""

import hashlib
import json
from copy import deepcopy
from pathlib import Path

import pytest

from avo import shorts_contract, shorts_plan
from avo.adapters.motion.hyperframes import build_composition_spec, compile_project
from avo.shorts_visuals import (
    prepare_visual_inserts,
    validate_visual_inserts,
)


@pytest.fixture
def insert(tmp_path):
    path = tmp_path / "source.png"
    path.write_bytes(b"original image")
    return {
        "id": "detail",
        "kind": "image",
        "path": str(path),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "rightsReference": "user-supplied://image",
        "startSec": 0.5,
        "endSec": 1.5,
        "rect": {"x": 0, "y": 0, "width": 1, "height": 1 / 3},
        "baseRegion": {"x": 0, "y": 1 / 3, "width": 1, "height": 2 / 3},
        "fit": "contain",
        "label": "Official footage",
    }


def test_validation_rejects_stale_media_clock_crop_and_derived_ancestry(
    insert, tmp_path
):
    for patch, match in [
        ({"sha256": "f" * 64}, "fingerprint"),
        ({"endSec": 4}, "duration"),
        ({"rect": {"x": 0.8, "y": 0, "width": 1, "height": 1}}, "rectangle"),
    ]:
        with pytest.raises(shorts_contract.ContractValidationError, match=match):
            validate_visual_inserts([{**insert, **patch}], 2)
    derived = tmp_path / "renders" / "source.png"
    derived.parent.mkdir()
    derived.write_bytes(b"original image")
    with pytest.raises(shorts_contract.ContractValidationError, match="prohibited"):
        validate_visual_inserts([{**insert, "path": str(derived)}], 2)


def test_video_cannot_silently_loop_and_base_windows_cannot_conflict(insert):
    video = {
        **insert,
        "kind": "video",
        "sourceStartSec": 5,
        "sourceEndSec": 5.5,
        "videoStreamIndex": 0,
    }
    with pytest.raises(
        shorts_contract.ContractValidationError, match="without looping"
    ):
        validate_visual_inserts([video], 2)
    with pytest.raises(shorts_contract.ContractValidationError, match="cannot overlap"):
        validate_visual_inserts([insert, {**insert, "id": "other"}], 2)


def test_preparation_preserves_source_bytes_and_windows(insert, tmp_path):
    rows = prepare_visual_inserts([insert], tmp_path / "assets", duration=2)
    assert Path(rows[0]["path"]).read_bytes() == b"original image"
    assert rows[0]["sha256"] == insert["sha256"]
    assert rows[0]["startSec"] == 0.5


def test_plan_freezes_insert_and_hash_invalidates_on_content_change(insert):
    fixtures = Path(__file__).parent / "fixtures" / "shorts" / "planning"
    request = json.loads((fixtures / "shorts.request.json").read_text(encoding="utf8"))
    transcript = json.loads((fixtures / "transcript.json").read_text(encoding="utf8"))
    request["candidates"][0]["visualInserts"] = [insert]

    def resolve():
        return shorts_plan.resolve_batch(
            request,
            transcript,
            request_path=fixtures / "shorts.request.json",
            source_fingerprint="a" * 64,
            provider_tokens={},
        )

    first = resolve()
    assert first["items"][0]["visualInserts"] == [insert]
    request["candidates"][0]["visualInserts"][0]["label"] = "Changed label"
    assert (
        resolve()["items"][0]["inputFingerprint"]
        != first["items"][0]["inputFingerprint"]
    )


def test_generated_media_is_framework_timed_and_captions_last(insert, tmp_path):
    assets = {}
    for key, name in (("baseVideo", "camera.mp4"), ("dialogueAudio", "voice.m4a")):
        path = tmp_path / name
        path.write_bytes(name.encode())
        assets[key] = {
            "path": str(path),
            "hash": hashlib.sha256(path.read_bytes()).hexdigest(),
            "durationSec": 2,
            "muted": key == "baseVideo",
        }
    item = {
        "id": "01",
        "editedDurationSec": 2,
        "layout": {"mode": "full-frame", "captionAnchor": "bottom"},
        "captions": [],
        "visualInserts": [insert],
    }
    spec = build_composition_spec(
        batch_id="batch",
        item=item,
        output={"width": 720, "height": 1280, "fps": 30},
        assets=assets,
        proof_revision=1,
        expected_output_path=tmp_path / "out.mp4",
    )
    project = compile_project(spec, tmp_path / "composition")
    page = (project / "index.html").read_text(encoding="utf8")
    assert 'id="visual-detail"' in page and 'data-start="0.500000"' in page
    assert "object-fit:contain" in page
    assert (
        page.index('id="visual-detail"')
        < page.index('id="graphic-layer"')
        < page.index('id="caption-rail"')
    )
    assert 'data-media-start="0.500000"' in page
    assert "__VISUAL_JSON__" not in (project / "runtime.js").read_text(encoding="utf8")
    alpha_spec = deepcopy(spec)
    alpha_spec["renderLayers"] = "graphics-only"
    alpha = compile_project(alpha_spec, tmp_path / "alpha")
    alpha_page = (alpha / "index.html").read_text(encoding="utf8")
    assert (
        "<video" not in alpha_page
        and "<audio" not in alpha_page
        and "<img" not in alpha_page
    )
    assert 'id="caption-rail"' in alpha_page
    assert 'id="visual-detail-label"' in alpha_page
    assert not (alpha / "assets" / "base-video.mp4").exists()
    styles = (project / "styles.css").read_text(encoding="utf8")
    assert "--short-overlay-gap:" in styles
    assert (
        "bottom: calc(var(--short-safe-bottom) + var(--short-overlay-gap));" in styles
    )
    assert '#short-root[data-layout="full-frame"] .callout.corner-br' in styles
    assert '#short-root[data-layout="full-frame"] .graphic.corner-br' in styles
    assert "top: var(--short-safe-top);" in styles
    assert "bottom: auto;" in styles
    assert ".meter-label {" in styles
    assert "background: rgba(14, 12, 18, 0.92);" in styles


def test_preview_profile_honors_requested_long_side():
    plan = {"output": {"width": 1728, "height": 3072, "previewLongSide": 1280}}
    assert shorts_plan.target_render_profile(plan, preview=True) == {
        "preview": True,
        "width": 720,
        "height": 1280,
    }


def test_explicit_sfx_can_silence_or_replace_automatic_hits():
    from avo.shorts_plan import _sfx_from_motion

    automatic = {
        "short_id": "01",
        "callouts": [],
        "punch_ins": [{"id": "zoom", "startSec": 0, "endSec": 1, "scale": 1.08}],
        "layout": {"mode": "full-frame"},
        "sfx": {"library": {"price": "cash.wav"}},
        "edited_duration": 2,
    }
    assert _sfx_from_motion(**automatic, explicit_hits=[]) == []
    hit = {"id": "price-hit", "kind": "price", "startSec": 0.5}
    assert _sfx_from_motion(**automatic, explicit_hits=[hit]) == [hit]
    with pytest.raises(shorts_plan.PlanningError, match="unique"):
        _sfx_from_motion(**automatic, explicit_hits=[hit, hit])
    with pytest.raises(shorts_plan.PlanningError, match="duration"):
        _sfx_from_motion(**automatic, explicit_hits=[{**hit, "startSec": 2}])
