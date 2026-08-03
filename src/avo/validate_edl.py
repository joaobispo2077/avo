"""Validate AVO EDL files against the feature schema and media semantics."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

try:
    from jsonschema import Draft202012Validator
except ImportError:  # Older distro jsonschema; schema uses only supported basics here.
    from jsonschema import Draft7Validator as Draft202012Validator


from avo.paths import schema_path as resolve_schema_path

SLOT_IDS = (
    "transfer-direction",
    "move-not-copy-warning",
    "two-game-verification",
)
PURPOSE_BY_SLOT = {
    "transfer-direction": "transfer_whoosh",
    "move-not-copy-warning": "warning_hit",
    "two-game-verification": "verification_chime",
}
DEFAULT_SCHEMA = resolve_schema_path("edl.schema.json")
BLURAY_PS5_FEATURE_ID = "005-bluray-ps5-gamevlog"


class EdlValidationError(ValueError):
    """Raised when an EDL violates schema or timeline semantics."""


def _resolve(path_value: str, edit_dir: Path) -> Path:
    path = Path(path_value)
    return path if path.is_absolute() else (edit_dir / path).resolve()


def _format_schema_error(error: Any) -> str:
    location = ".".join(str(item) for item in error.absolute_path) or "<root>"
    return f"{location}: {error.message}"


def _item_id(item: dict) -> str:
    return str(item.get("motion_brief_id") or item.get("source_log_id") or item.get("file") or "<unknown>")


def _check_non_overlapping(items: list[dict], label: str, errors: list[str]) -> None:
    ordered = sorted(
        items,
        key=lambda item: (
            float(item["start_in_output"]),
            float(item["duration"]),
        ),
    )
    for previous, current in zip(ordered, ordered[1:]):
        previous_end = float(previous["start_in_output"]) + float(previous["duration"])
        current_start = float(current["start_in_output"])
        if current_start < previous_end - 1e-6:
            errors.append(
                f"{label} overlap: {_item_id(previous)} ends at "
                f"{previous_end:.3f}, after {_item_id(current)} starts "
                f"at {current_start:.3f}"
            )


def _check_item_windows(
    items: list[dict],
    label: str,
    output_duration: float,
    errors: list[str],
) -> None:
    _check_non_overlapping(items, label, errors)
    for item in items:
        try:
            end = float(item["start_in_output"]) + float(item["duration"])
        except (KeyError, TypeError, ValueError):
            continue
        if end > output_duration + 1e-6:
            errors.append(
                f"{label} {_item_id(item)} ends at {end:.3f}, "
                f"beyond output duration {output_duration:.3f}"
            )


def _check_assets(asset_fields: list[tuple[str, Any]], edit_dir: Path) -> list[str]:
    errors: list[str] = []
    for field, value in asset_fields:
        if not value:
            continue
        if not _resolve(str(value), edit_dir).exists():
            errors.append(f"{field} does not exist: {value}")
    return errors



def _is_bluray_ps5_edl(edl: dict) -> bool:
    return edl.get("feature_id") == BLURAY_PS5_FEATURE_ID


def _bluray_ps5_semantic_errors(
    edl: dict,
    edit_dir: Path,
    output_duration: float,
) -> list[str]:
    errors: list[str] = []
    sources = edl.get("sources") or {}
    overlays = edl.get("overlays") or []
    effects = edl.get("sound_effects") or []
    caption_policy = edl.get("caption_policy") or {}
    motion_policy = edl.get("motion_policy") or {}
    render_gate = edl.get("render_gate") or {}

    for source_id, source in sources.items():
        role = source.get("role")
        path_value = str(source.get("path") or "")
        if role == "authoritative_master" and path_value.lower().endswith(".lrf"):
            errors.append(f"source {source_id} uses LRF proxy as authoritative_master")
        if role == "authoritative_master" and "DJI_20260506201325_0444_D.MP4" not in Path(path_value).name:
            errors.append(f"source {source_id} authoritative_master must resolve to the MP4 finishing source")

    for index, item in enumerate(edl.get("ranges") or []):
        source = sources.get(item.get("source")) or {}
        if source.get("role") != "authoritative_master":
            errors.append(f"ranges[{index}].source must resolve to an authoritative_master source")

    if caption_policy.get("language") != "pt-BR":
        errors.append("caption_policy.language must be pt-BR")
    if caption_policy.get("selectable") is not True:
        errors.append("caption_policy.selectable must be true")
    if caption_policy.get("visual_subtitles") is not False:
        errors.append("caption_policy.visual_subtitles must be false unless explicitly approved outside feature 005")

    if motion_policy.get("framework") != "hyperframes":
        errors.append("motion_policy.framework must be hyperframes")
    if motion_policy.get("timeline_owner") != "edl":
        errors.append("motion_policy.timeline_owner must be edl")
    density_levels = set(motion_policy.get("density_levels") or [])
    if not density_levels:
        errors.append("motion_policy.density_levels must include approved Level 1-2 values")
    elif not density_levels.issubset({1, 2}):
        errors.append("motion_policy.density_levels must stay within selective Level 1-2")

    if overlays and not motion_policy.get("review_package_approval"):
        errors.append("overlays require motion_policy.review_package_approval")

    _check_item_windows(overlays, "overlay", output_duration, errors)
    _check_item_windows(effects, "sound effect", output_duration, errors)

    overlay_ids = Counter(item.get("motion_brief_id") for item in overlays)
    for slot_id, count in overlay_ids.items():
        if count > 1:
            errors.append(f"duplicate overlay motion_brief_id: {slot_id}")

    for item in effects:
        try:
            if float(item["gain_db"]) >= 0:
                errors.append(f"sound effect {_item_id(item)} gain_db must be negative")
        except (KeyError, TypeError, ValueError):
            pass

    stage = render_gate.get("stage")
    approvals = render_gate.get("approval_references") or []
    if stage == "rough":
        if len(approvals) < 1:
            errors.append("rough render requires diagnosis/story approval reference")
    elif stage == "overlay_package":
        if len(approvals) < 1:
            errors.append("overlay package render requires story approval reference")
    elif stage == "fine":
        if len(approvals) < 1:
            errors.append("fine render requires rough approval reference")
    elif stage == "picture_lock":
        if len(approvals) < 2:
            errors.append("picture lock requires editorial and release approval references")
    elif stage == "master":
        if len(approvals) < 5:
            errors.append("master render requires picture-lock, audio/color, captions, rights/privacy, and policy approvals")
        if not motion_policy.get("review_package_approval") and overlays:
            errors.append("master render requires approved motion package reference")
    else:
        errors.append("render_gate.stage must be rough, overlay_package, fine, picture_lock, or master")

    asset_fields = []
    if caption_policy.get("caption_path"):
        asset_fields.append(("caption_policy.caption_path", caption_policy.get("caption_path")))
    asset_fields.extend((f"overlays[{index}].file", item.get("file")) for index, item in enumerate(overlays))
    asset_fields.extend((f"sound_effects[{index}].file", item.get("file")) for index, item in enumerate(effects))
    errors.extend(_check_assets(asset_fields, edit_dir))
    return errors


def _is_comparison_edl(edl: dict) -> bool:
    return int(edl.get("version", 1)) >= 4 or "caption_policy" in edl


def _comparison_semantic_errors(
    edl: dict,
    edit_dir: Path,
    output_duration: float,
) -> list[str]:
    errors: list[str] = []
    overlays = edl.get("overlays") or []
    effects = edl.get("sound_effects") or []
    caption_policy = edl.get("caption_policy") or {}
    motion_policy = edl.get("motion_policy") or {}

    if caption_policy.get("visual_subtitles") is not False:
        errors.append("caption_policy.visual_subtitles must be false")
    if motion_policy.get("visual_subtitles_allowed") is not False:
        errors.append("motion_policy.visual_subtitles_allowed must be false")
    if edl.get("caption_burn_in") is not None:
        errors.append("caption_burn_in must be null for comparison EDLs")

    if int(edl.get("version", 1)) >= 4:
        render_gate = edl.get("render_gate") or {}
        review_package = edl.get("review_package") or {}
        audio = edl.get("audio") or {}
        if motion_policy.get("rebuild_scope") != "rebuilt_v004_hyperframes":
            errors.append("motion_policy.rebuild_scope must be rebuilt_v004_hyperframes")
        if motion_policy.get("review_package_required") is not True:
            errors.append("motion_policy.review_package_required must be true")
        if audio.get("noise_reduction_policy") != "conservative_speech_first":
            errors.append("audio.noise_reduction_policy must be conservative_speech_first")
        if audio.get("channel_qc") not in {"pending", "passed_left_right_dialogue_audible"}:
            errors.append("audio.channel_qc must record stereo dialogue QC status")
        from avo import audio_restoration

        errors.extend(audio_restoration.validate_restoration_segments(audio))
        if render_gate.get("stage") == "v004_review_package":
            if render_gate.get("full_render_allowed") is not False:
                errors.append("v004 review package gate must set full_render_allowed false")
        elif render_gate.get("stage") == "full_render_after_creator_approval":
            if render_gate.get("full_render_allowed") is not True:
                errors.append("full render gate must set full_render_allowed true")
            if not render_gate.get("creator_approval_reference"):
                errors.append("full render requires creator approval reference")
            if review_package.get("approval_status") != "approved":
                errors.append("full render requires review package approval")
        else:
            errors.append("render_gate.stage must be v004_review_package or full_render_after_creator_approval")

        for index, item in enumerate(edl.get("blocked_source_ranges") or []):
            source = item.get("source")
            if source not in edl.get("sources", {}):
                errors.append(f"blocked_source_ranges[{index}].source does not resolve in sources")
            min_start = item.get("minimum_excluded_start")
            min_end = item.get("minimum_excluded_end")
            cut_start = item.get("final_cut_start")
            cut_end = item.get("final_cut_end")
            if cut_start is not None and cut_end is not None:
                if float(cut_start) > float(min_start) + 1e-6 or float(cut_end) < float(min_end) - 1e-6:
                    errors.append(f"blocked_source_ranges[{index}] final cut must cover minimum excluded range")

    overlay_ids = Counter(item.get("motion_brief_id") for item in overlays)
    for slot_id, count in overlay_ids.items():
        if count > 1:
            errors.append(f"duplicate overlay motion_brief_id: {slot_id}")

    effect_ids = Counter(item.get("motion_brief_id") for item in effects)
    for slot_id, count in effect_ids.items():
        if count > 1:
            errors.append(f"duplicate sound effect motion_brief_id: {slot_id}")
        if slot_id not in overlay_ids:
            errors.append(f"sound effect {slot_id} has no matching overlay")

    _check_item_windows(overlays, "overlay", output_duration, errors)
    _check_item_windows(effects, "sound effect", output_duration, errors)

    for item in effects:
        slot_id = item.get("motion_brief_id")
        try:
            if float(item["gain_db"]) >= 0:
                errors.append(f"sound effect {slot_id} gain_db must be negative")
        except (KeyError, TypeError, ValueError):
            pass

    asset_fields = [
        ("subtitles", edl.get("subtitles")),
        (
            "ad_segment.approved_asset",
            (edl.get("ad_segment") or {}).get("approved_asset"),
        ),
    ]
    asset_fields.extend(
        (f"overlays[{index}].file", item.get("file"))
        for index, item in enumerate(overlays)
    )
    asset_fields.extend(
        (f"sound_effects[{index}].file", item.get("file"))
        for index, item in enumerate(effects)
    )
    errors.extend(_check_assets(asset_fields, edit_dir))
    return errors


def _semantic_errors(edl: dict, edit_dir: Path) -> list[str]:
    errors: list[str] = []
    ranges = edl.get("ranges") or []
    sources = edl.get("sources") or {}

    output_duration = 0.0
    for index, item in enumerate(ranges):
        source = item.get("source")
        if source not in sources:
            errors.append(f"ranges[{index}].source does not resolve in sources")
        try:
            start = float(item["start"])
            end = float(item["end"])
        except (KeyError, TypeError, ValueError):
            continue
        if end <= start:
            errors.append(f"ranges[{index}] must have end > start")
        else:
            output_duration += end - start

    if int(edl.get("version", 1)) < 3:
        return errors

    if _is_bluray_ps5_edl(edl):
        errors.extend(_bluray_ps5_semantic_errors(edl, edit_dir, output_duration))
        return errors

    if _is_comparison_edl(edl):
        errors.extend(_comparison_semantic_errors(edl, edit_dir, output_duration))
        return errors

    overlays = edl.get("overlays") or []
    effects = edl.get("sound_effects") or []

    for label, items in (("overlay", overlays), ("sound effect", effects)):
        counts = Counter(item.get("motion_brief_id") for item in items)
        for slot_id in SLOT_IDS:
            if counts[slot_id] != 1:
                errors.append(
                    f"{label} motion_brief_id {slot_id} must appear exactly once"
                )
        unexpected = sorted(
            str(slot_id)
            for slot_id in counts
            if slot_id not in SLOT_IDS
        )
        if unexpected:
            errors.append(f"{label} contains unapproved slot IDs: {unexpected}")
        _check_item_windows(items, label, output_duration, errors)

    overlay_ids = Counter(item.get("motion_brief_id") for item in overlays)
    effect_ids = Counter(item.get("motion_brief_id") for item in effects)
    if overlay_ids != effect_ids:
        errors.append("overlay and sound effect IDs must map one-to-one")

    for item in effects:
        slot_id = item.get("motion_brief_id")
        expected_purpose = PURPOSE_BY_SLOT.get(slot_id)
        if expected_purpose and item.get("purpose") != expected_purpose:
            errors.append(
                f"sound effect {slot_id} must use purpose {expected_purpose}"
            )
        try:
            if float(item["gain_db"]) >= 0:
                errors.append(f"sound effect {slot_id} gain_db must be negative")
        except (KeyError, TypeError, ValueError):
            pass

    asset_fields = [
        ("subtitles", edl.get("subtitles")),
        (
            "caption_burn_in.file",
            (edl.get("caption_burn_in") or {}).get("file"),
        ),
    ]
    asset_fields.extend(
        (f"overlays[{index}].file", item.get("file"))
        for index, item in enumerate(overlays)
    )
    asset_fields.extend(
        (f"sound_effects[{index}].file", item.get("file"))
        for index, item in enumerate(effects)
    )
    errors.extend(_check_assets(asset_fields, edit_dir))

    audio = edl.get("audio") or {}
    if audio.get("restoration_default_pct") is not None or audio.get("restoration_segments"):
        from avo import audio_restoration

        errors.extend(audio_restoration.validate_restoration_segments(audio))
    if (
        audio.get("gain_default_pct") is not None
        or audio.get("gain_segments")
        or audio.get("gain_policy") == "level_match_speech"
    ):
        from avo import audio_gain

        errors.extend(audio_gain.validate_gain_segments(audio))

    return errors


def validate_edl(
    edl: dict,
    edit_dir: Path,
    schema_path: Path = DEFAULT_SCHEMA,
) -> None:
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)
    errors = [
        _format_schema_error(error)
        for error in sorted(validator.iter_errors(edl), key=str)
    ]
    errors.extend(_semantic_errors(edl, edit_dir))
    if errors:
        raise EdlValidationError("EDL validation failed:\n- " + "\n- ".join(errors))


def load_and_validate(
    edl_path: Path,
    schema_path: Path = DEFAULT_SCHEMA,
) -> dict:
    path = edl_path.resolve()
    edl = json.loads(path.read_text(encoding="utf-8"))
    validate_edl(edl, path.parent, schema_path=schema_path)
    return edl


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("edl", type=Path)
    parser.add_argument("--schema", type=Path, default=DEFAULT_SCHEMA)
    args = parser.parse_args()
    edl = load_and_validate(args.edl, args.schema)
    print(
        f"valid EDL v{edl.get('version', 1)}: "
        f"{len(edl.get('ranges', []))} ranges"
    )


if __name__ == "__main__":
    main()

