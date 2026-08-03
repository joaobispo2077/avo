"""Platform loudness reference presets and profile resolution for AVO."""

from __future__ import annotations

import json
import subprocess
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Any

PRESET_DISCLAIMER = "reference preset — not an official platform requirement"
CREATIVE_DEVIATION_LU = 3.0
QC_INTEGRATED_TOLERANCE_LU = 1.0
QC_ENCODE_TP_DELTA_DBTp = 0.3

INTENTS = frozenset({"platform_fit", "channel_standard", "creative"})
RANGE_PREFERENCES = frozenset({"tight", "balanced", "preserve_dynamics"})

PROFILE_TO_PRESET: dict[str, str] = {
    "long-form": "youtube_long_form_speech",
    "shorts": "youtube_shorts",
    "tiktok": "tiktok",
    "podcast-clip": "podcast_clip",
    "trailer": "youtube_shorts",
    "music-video": "music_video",
}

LIMITER_FILTER_TEMPLATE = "alimiter=limit={limit:.3f}:level=false:attack=5:release=50"


@dataclass(frozen=True)
class LoudnessPreset:
    preset_id: str
    label: str
    integrated_lufs: float
    true_peak_dbtp: float
    lra_lu: float
    note: str
    last_verified: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ResolvedLoudnessProfile:
    integrated_lufs: float
    true_peak_dbtp: float
    lra_lu: float
    preset_id: str
    preset_label: str
    intent: str
    source: str
    range_preference: str
    loudnorm_enabled: bool = True
    disclaimer: str = PRESET_DISCLAIMER
    legacy_warning: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def log_line(self) -> str:
        return (
            f"{self.integrated_lufs:.1f} LUFS / {self.true_peak_dbtp:.1f} dBTP / "
            f"LRA {self.lra_lu:.1f} ({self.preset_label}; {self.disclaimer})"
        )


LOUDNESS_PRESETS: dict[str, LoudnessPreset] = {
    "youtube_long_form_speech": LoudnessPreset(
        preset_id="youtube_long_form_speech",
        label="YouTube long-form speech",
        integrated_lufs=-16.0,
        true_peak_dbtp=-1.0,
        lra_lu=9.0,
        note="Speech-led long-form; quieter than Shorts for dynamics",
        last_verified="2026-08-02",
    ),
    "youtube_shorts": LoudnessPreset(
        preset_id="youtube_shorts",
        label="YouTube Shorts",
        integrated_lufs=-14.0,
        true_peak_dbtp=-1.0,
        lra_lu=11.0,
        note="Short-form vertical reference",
        last_verified="2026-08-02",
    ),
    "instagram_reels": LoudnessPreset(
        preset_id="instagram_reels",
        label="Instagram Reels",
        integrated_lufs=-14.0,
        true_peak_dbtp=-1.0,
        lra_lu=11.0,
        note="Meta adaptive loudness; no official LUFS publish",
        last_verified="2026-08-02",
    ),
    "tiktok": LoudnessPreset(
        preset_id="tiktok",
        label="TikTok",
        integrated_lufs=-14.0,
        true_peak_dbtp=-1.0,
        lra_lu=11.0,
        note="Short-form feed reference; mono clarity matters",
        last_verified="2026-08-02",
    ),
    "music_video": LoudnessPreset(
        preset_id="music_video",
        label="Music video",
        integrated_lufs=-14.0,
        true_peak_dbtp=-1.0,
        lra_lu=8.0,
        note="Music-forward delivery reference",
        last_verified="2026-08-02",
    ),
    "podcast_clip": LoudnessPreset(
        preset_id="podcast_clip",
        label="Podcast clip",
        integrated_lufs=-16.0,
        true_peak_dbtp=-1.0,
        lra_lu=11.0,
        note="Speech-led clip / podcast highlight reference",
        last_verified="2026-08-02",
    ),
}

DEFAULT_PRESET_ID = "youtube_long_form_speech"
DEFAULT_INTENT = "platform_fit"


def preset_ids() -> list[str]:
    return sorted(LOUDNESS_PRESETS.keys())


def get_preset(preset_id: str) -> LoudnessPreset:
    if preset_id not in LOUDNESS_PRESETS:
        valid = ", ".join(preset_ids())
        raise ValueError(f"Unknown loudness preset: {preset_id}. Valid: {valid}")
    return LOUDNESS_PRESETS[preset_id]


def preset_stale_advisory(preset: LoudnessPreset, *, today: date | None = None) -> str | None:
    today = today or date.today()
    verified = date.fromisoformat(preset.last_verified)
    age_days = (today - verified).days
    if age_days >= 180:
        return (
            f"Preset '{preset.label}' last verified {preset.last_verified} "
            f"({age_days} days ago); re-check platform docs (non-blocking)."
        )
    return None


def apply_range_preference(base_lra: float, preference: str) -> float:
    if preference == "tight":
        return float(min(base_lra, 7.0))
    if preference == "preserve_dynamics":
        return float(min(base_lra + 2.0, 15.0))
    return float(base_lra)


def _audio_block(*sources: dict[str, Any] | None) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for src in sources:
        if not src:
            continue
        audio = src.get("audio")
        if isinstance(audio, dict):
            merged.update(audio)
    return merged


def _deliverable_profile(project: dict[str, Any] | None) -> str:
    if not project:
        return "long-form"
    deliverable = project.get("deliverable") or {}
    profile = str(deliverable.get("profile") or "long-form").strip().lower()
    return profile or "long-form"


def preset_for_deliverable_profile(profile: str) -> str:
    return PROFILE_TO_PRESET.get(profile, DEFAULT_PRESET_ID)


def nearest_preset_id(integrated_lufs: float) -> str:
    best_id = DEFAULT_PRESET_ID
    best_dist = float("inf")
    for preset in LOUDNESS_PRESETS.values():
        dist = abs(preset.integrated_lufs - integrated_lufs)
        if dist < best_dist:
            best_dist = dist
            best_id = preset.preset_id
    return best_id


def validate_creative_custom(custom: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    try:
        integrated = float(custom["integrated_lufs"])
        true_peak = float(custom["true_peak_dbtp"])
    except (KeyError, TypeError, ValueError):
        return ["audio.loudness_custom requires integrated_lufs and true_peak_dbtp numbers"]

    if true_peak > -0.5:
        errors.append("audio.loudness_custom.true_peak_dbtp must be <= -0.5 dBTP for lossy encode safety")

    nearest = get_preset(nearest_preset_id(integrated))
    deviation = abs(integrated - nearest.integrated_lufs)
    if deviation > CREATIVE_DEVIATION_LU and not custom.get("approved_by_user"):
        errors.append(
            "Creative loudness deviates >3 LU from nearest preset; set approved_by_user: true"
        )

    if integrated > -10.0 and not custom.get("approved_by_user"):
        errors.append(
            "Creative integrated loudness hotter than -10 LUFS requires approved_by_user: true"
        )

    return errors


def resolve_loudness_profile(
    edl: dict[str, Any] | None = None,
    project: dict[str, Any] | None = None,
    provider: dict[str, Any] | None = None,
    *,
    preset_override: str | None = None,
) -> ResolvedLoudnessProfile:
    """Resolve loudness targets from EDL → project → provider → deliverable default."""
    edl = edl or {}
    project = project or {}
    provider = provider or {}

    audio = _audio_block(edl, project)
    provider_loudness = provider.get("loudness") or {}

    intent = str(
        audio.get("loudness_intent")
        or provider_loudness.get("default_intent")
        or DEFAULT_INTENT
    )
    if intent not in INTENTS:
        raise ValueError(f"Unknown loudness_intent: {intent}. Valid: {', '.join(sorted(INTENTS))}")

    range_preference = str(audio.get("loudness_range_preference") or "balanced")
    if range_preference not in RANGE_PREFERENCES:
        raise ValueError(
            f"Unknown loudness_range_preference: {range_preference}. "
            f"Valid: {', '.join(sorted(RANGE_PREFERENCES))}"
        )

    loudnorm_enabled = audio.get("loudnorm_enabled", True)
    if loudnorm_enabled is False:
        loudnorm_enabled = False
    else:
        loudnorm_enabled = bool(loudnorm_enabled)

    legacy_warning = not audio and not provider_loudness.get("channel_standard")

    if preset_override:
        preset = get_preset(preset_override)
        source = "cli_override"
        integrated = preset.integrated_lufs
        true_peak = preset.true_peak_dbtp
        base_lra = preset.lra_lu
    elif intent == "creative":
        custom = audio.get("loudness_custom") or {}
        errors = validate_creative_custom(custom)
        if errors:
            raise ValueError("; ".join(errors))
        integrated = float(custom["integrated_lufs"])
        true_peak = float(custom["true_peak_dbtp"])
        base_lra = float(custom.get("lra_lu") or get_preset(nearest_preset_id(integrated)).lra_lu)
        preset = get_preset(nearest_preset_id(integrated))
        source = "edl" if edl.get("audio") else "project"
    elif intent == "channel_standard":
        channel = provider_loudness.get("channel_standard") or {}
        if channel.get("integrated_lufs") is not None:
            integrated = float(channel["integrated_lufs"])
            true_peak = float(channel.get("true_peak_dbtp", -1.0))
            base_lra = float(channel.get("lra_lu", 9.0))
            preset_id = str(audio.get("loudness_preset") or nearest_preset_id(integrated))
            preset = get_preset(preset_id)
            source = "provider.channel_standard"
        else:
            intent = "platform_fit"
            preset_id = str(
                audio.get("loudness_preset")
                or preset_for_deliverable_profile(_deliverable_profile(project))
            )
            preset = get_preset(preset_id)
            integrated = preset.integrated_lufs
            true_peak = preset.true_peak_dbtp
            base_lra = preset.lra_lu
            source = "provider_fallback_platform_fit"
    else:
        preset_id = str(
            audio.get("loudness_preset")
            or preset_for_deliverable_profile(_deliverable_profile(project))
        )
        preset = get_preset(preset_id)
        integrated = preset.integrated_lufs
        true_peak = preset.true_peak_dbtp
        base_lra = preset.lra_lu
        if edl.get("audio"):
            source = "edl"
        elif project.get("audio"):
            source = "project"
        else:
            source = "deliverable_default"

    if intent == "creative" and audio.get("loudness_custom", {}).get("lra_lu") is not None:
        lra = float(audio["loudness_custom"]["lra_lu"])
    else:
        lra = apply_range_preference(base_lra, range_preference)

    return ResolvedLoudnessProfile(
        integrated_lufs=integrated,
        true_peak_dbtp=true_peak,
        lra_lu=lra,
        preset_id=preset.preset_id,
        preset_label=preset.label,
        intent=intent,
        source=source,
        range_preference=range_preference,
        loudnorm_enabled=loudnorm_enabled,
        legacy_warning=legacy_warning,
    )


def limiter_filter_for(true_peak_dbtp: float) -> str:
    """Map true-peak ceiling to alimiter linear limit (approximate)."""
    limit = 10 ** (true_peak_dbtp / 20.0)
    return LIMITER_FILTER_TEMPLATE.format(limit=limit)


def loudnorm_measure_filter(profile: ResolvedLoudnessProfile) -> str:
    return (
        f"loudnorm=I={profile.integrated_lufs}:TP={profile.true_peak_dbtp}:"
        f"LRA={profile.lra_lu}:print_format=json"
    )


def measure_loudness(
    media_path: Path,
    profile: ResolvedLoudnessProfile,
) -> dict[str, str] | None:
    """Run ffmpeg loudnorm first pass and parse JSON measurement."""
    filter_str = loudnorm_measure_filter(profile)
    cmd = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-nostats",
        "-i",
        str(media_path),
        "-af",
        filter_str,
        "-vn",
        "-f",
        "null",
        "-",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    stderr = proc.stderr
    start = stderr.rfind("{")
    end = stderr.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        data = json.loads(stderr[start : end + 1])
    except json.JSONDecodeError:
        return None
    needed = {"input_i", "input_tp", "input_lra", "input_thresh", "target_offset"}
    if not needed.issubset(data.keys()):
        return None
    return data


def compare_measurement(
    measurement: dict[str, str],
    profile: ResolvedLoudnessProfile,
) -> dict[str, Any]:
    measured_i = float(measurement["input_i"])
    measured_tp = float(measurement["input_tp"])
    measured_lra = float(measurement["input_lra"])
    delta_i = measured_i - profile.integrated_lufs
    warnings: list[str] = []
    if delta_i > 2.0:
        warnings.append(
            "Measured integrated loudness is >2 LU above target; YouTube only turns loud content down."
        )
    if delta_i < -2.0:
        warnings.append(
            "Measured integrated loudness is >2 LU below target; YouTube does not boost quiet uploads."
        )
    return {
        "measured_i": measured_i,
        "measured_tp": measured_tp,
        "measured_lra": measured_lra,
        "target_i": profile.integrated_lufs,
        "target_tp": profile.true_peak_dbtp,
        "target_lra": profile.lra_lu,
        "delta_i": round(delta_i, 2),
        "warnings": warnings,
        "profile": profile.to_dict(),
    }


def evaluate_qc(
    measurement: dict[str, str],
    profile: ResolvedLoudnessProfile,
    *,
    upload_measurement: dict[str, str] | None = None,
) -> dict[str, Any]:
    measured_i = float(measurement["input_i"])
    measured_tp = float(measurement["input_tp"])
    integrated_pass = abs(measured_i - profile.integrated_lufs) <= QC_INTEGRATED_TOLERANCE_LU
    tp_pass = measured_tp <= profile.true_peak_dbtp + 0.05

    encode_delta: float | None = None
    encode_pass = True
    if upload_measurement:
        upload_tp = float(upload_measurement["input_tp"])
        encode_delta = round(upload_tp - measured_tp, 2)
        encode_pass = encode_delta <= QC_ENCODE_TP_DELTA_DBTp

    status = "PASS" if integrated_pass and tp_pass and encode_pass else "FAIL"
    blockers: list[str] = []
    if not integrated_pass:
        blockers.append(
            f"Integrated loudness {measured_i:.1f} LUFS outside "
            f"{profile.integrated_lufs:.1f} ± {QC_INTEGRATED_TOLERANCE_LU} LU"
        )
    if not tp_pass:
        blockers.append(
            f"True peak {measured_tp:.1f} dBTP exceeds ceiling {profile.true_peak_dbtp:.1f} dBTP"
        )
    if not encode_pass and encode_delta is not None:
        blockers.append(
            f"Upload candidate true peak delta {encode_delta:.2f} dBTP exceeds {QC_ENCODE_TP_DELTA_DBTp}"
        )

    return {
        "status": status,
        "integrated_pass": integrated_pass,
        "true_peak_pass": tp_pass,
        "encode_pass": encode_pass,
        "encode_delta_dbtp": encode_delta,
        "blockers": blockers,
        "measurement": compare_measurement(measurement, profile),
    }


def nr_loudness_warning(edl: dict[str, Any], profile: ResolvedLoudnessProfile) -> str | None:
    audio = edl.get("audio") or {}
    hot_segments = [
        seg
        for seg in (audio.get("restoration_segments") or [])
        if int(seg.get("strength_pct", 0)) > 50
    ]
    if hot_segments and profile.integrated_lufs >= -14.0:
        return (
            "Warning: aggressive noise reduction (>50%) combined with a hot loudness target "
            f"({profile.integrated_lufs:.1f} LUFS) may cause artifacts."
        )
    return None


def load_project_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def load_context_for_edit_dir(edit_dir: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    """Load avo.project.json and provider manifest from an edit/ directory."""
    project_path = edit_dir.parent / "avo.project.json"
    project = load_project_json(project_path)
    provider: dict[str, Any] = {}
    provider_slug = str(project.get("provider") or "").strip()
    if provider_slug:
        from avo.init_project import load_provider

        try:
            provider = load_provider(provider_slug)
        except FileNotFoundError:
            provider = {}
    return project, provider
