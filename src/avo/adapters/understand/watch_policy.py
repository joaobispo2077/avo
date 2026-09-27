"""Pure configuration and prompt policy for the Watch adapter boundary."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from avo.settings import (
    ResolvedSettings,
    redact_path,
    resolve_path_setting,
    resolve_scoped_settings,
    stable_settings_hash,
)


class WatchPolicyError(ValueError):
    pass


DEFAULT_WATCH_SETTINGS: dict[str, Any] = {
    "whisperModel": "inherit",
    "device": "auto",
    "maxFrames": 18,
    "repairMaxFrames": 8,
    "analysisAttempts": 2,
    "toolAttempts": 3,
    "workingDirectory": None,
    "format": None,
    "language": None,
    "acceptanceCriteria": [],
    "riskNotes": [],
    "sections": [],
    "pacingMetrics": {},
}

_DEVICE = re.compile(r"^(?:auto|cpu|cuda(?::[0-9]+)?)$")


@dataclass(frozen=True)
class WatchPolicy:
    whisper_model: str
    device: str
    max_frames: int
    repair_max_frames: int
    analysis_attempts: int
    tool_attempts: int
    working_directory: Path | None
    context: dict[str, Any]
    effective: dict[str, Any]
    sources: dict[str, str]
    policy_hash: str
    raw_dir: Path | None = None

    def payload(self, *, redact_working_directory: bool = False) -> dict[str, Any]:
        effective = dict(self.effective)
        if redact_working_directory and effective.get("workingDirectory"):
            effective["workingDirectory"] = redact_path(
                self.working_directory,
                base=self.raw_dir or self.working_directory or Path.cwd(),
            )
        effective["repairMaxFrames"] = self.repair_max_frames
        return {
            "effective": effective,
            "sources": dict(self.sources),
            "policyHash": self.policy_hash,
        }


def _bounded(name: str, value: Any, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise WatchPolicyError(f"watch.{name} must be an integer")
    if not minimum <= value <= maximum:
        raise WatchPolicyError(f"watch.{name} must be between {minimum} and {maximum}")
    return value


def _resolved_model(resolved: ResolvedSettings, transcription_model: str) -> str:
    requested = str(resolved.setting("whisperModel").value or "inherit").strip()
    if not requested:
        raise WatchPolicyError("watch.whisperModel must be 'inherit' or a model id")
    model = transcription_model if requested == "inherit" else requested
    if not model:
        raise WatchPolicyError(
            "watch.whisperModel=inherit requires a transcription model"
        )
    return model


def _resolved_device(values: Mapping[str, Any]) -> str:
    device = str(values.get("device") or "auto").lower()
    if not _DEVICE.fullmatch(device):
        raise WatchPolicyError("watch.device must be auto, cpu, cuda, or cuda:N")
    return device


def _resolved_frame_limits(values: Mapping[str, Any]) -> tuple[int, int]:
    maximum = _bounded("maxFrames", values.get("maxFrames"), 1, 64)
    repair = _bounded("repairMaxFrames", values.get("repairMaxFrames"), 1, 64)
    if repair > maximum:
        raise WatchPolicyError("watch.repairMaxFrames cannot exceed watch.maxFrames")
    return maximum, repair


def _resolved_working_directory(
    values: Mapping[str, Any], raw_dir: Path | None
) -> Path | None:
    configured = values.get("workingDirectory")
    if configured is None:
        return None
    if raw_dir is None:
        raise WatchPolicyError("watch.workingDirectory requires a rawDir")
    return resolve_path_setting(str(configured), base=Path(raw_dir), contain=True)


def _validated_context(values: Mapping[str, Any]) -> dict[str, Any]:
    for name in ("acceptanceCriteria", "riskNotes"):
        value = values.get(name)
        if not isinstance(value, list) or not all(
            isinstance(item, str) and item.strip() for item in value
        ):
            raise WatchPolicyError(f"watch.{name} must be a list of non-empty strings")
    sections = values.get("sections")
    if not isinstance(sections, list):
        raise WatchPolicyError("watch.sections must be a list")
    required_section_fields = {
        "sectionId",
        "formatRole",
        "purpose",
        "payoff",
        "targetDensity",
        "protectedPauses",
        "riskClasses",
    }
    for section in sections:
        if not isinstance(section, dict) or not required_section_fields.issubset(
            section
        ):
            raise WatchPolicyError(
                "watch.sections entries require format, purpose, payoff, density, pauses, and risks"
            )
        density = section.get("targetDensity")
        if (
            isinstance(density, bool)
            or not isinstance(density, int)
            or not 0 <= density <= 5
        ):
            raise WatchPolicyError(
                "watch section targetDensity must be between 0 and 5"
            )
        if not isinstance(section.get("protectedPauses"), list) or not isinstance(
            section.get("riskClasses"), list
        ):
            raise WatchPolicyError("watch section pauses and risks must be lists")
    pacing_metrics = values.get("pacingMetrics")
    if not isinstance(pacing_metrics, dict) or not all(
        isinstance(key, str) and isinstance(value, dict)
        for key, value in pacing_metrics.items()
    ):
        raise WatchPolicyError(
            "watch.pacingMetrics must map section IDs to metric objects"
        )
    return {
        key: values[key]
        for key in (
            "format",
            "language",
            "acceptanceCriteria",
            "riskNotes",
            "sections",
            "pacingMetrics",
        )
        if values.get(key) not in (None, [], "", {})
    }


def resolve_watch_policy(
    *,
    transcription_model: str = "small",
    raw_dir: Path | None = None,
    scopes: Iterable[tuple[str, Mapping[str, Any] | None]] = (),
) -> WatchPolicy:
    resolved: ResolvedSettings = resolve_scoped_settings(
        defaults=DEFAULT_WATCH_SETTINGS,
        scopes=scopes,
    )
    values = dict(resolved.values)
    model = _resolved_model(resolved, transcription_model)
    device = _resolved_device(values)
    max_frames, repair_frames = _resolved_frame_limits(values)
    analysis_attempts = _bounded(
        "analysisAttempts", values.get("analysisAttempts"), 1, 3
    )
    tool_attempts = _bounded("toolAttempts", values.get("toolAttempts"), 1, 3)
    working_directory = _resolved_working_directory(values, raw_dir)
    context = _validated_context(values)
    effective = {
        **values,
        "whisperModel": model,
        "workingDirectory": str(working_directory) if working_directory else None,
    }
    return WatchPolicy(
        whisper_model=model,
        device=device,
        max_frames=max_frames,
        repair_max_frames=repair_frames,
        analysis_attempts=analysis_attempts,
        tool_attempts=tool_attempts,
        working_directory=working_directory,
        context=context,
        effective=effective,
        sources=resolved.sources,
        policy_hash=stable_settings_hash(
            {"effective": effective, "sources": resolved.sources}
        ),
        raw_dir=Path(raw_dir).resolve() if raw_dir is not None else None,
    )


_PROMPT_WINDOW_CAP = 8


def _window_prompt_lines(windows: list[dict[str, Any]]) -> list[str]:
    if not windows:
        return []
    editorial: list[dict[str, Any]] = []
    joins = 0
    cues = 0
    for window in windows:
        reason = str(window.get("reason") or "")
        if reason.startswith("join:"):
            joins += 1
        elif reason.startswith("cue:"):
            cues += 1
        else:
            editorial.append(window)
    listed = editorial[:_PROMPT_WINDOW_CAP]
    lines = ["Required windows:"]
    lines.extend(
        f"- {float(window['start']):.3f}–{float(window['end']):.3f} seconds: "
        f"{window['reason']}"
        for window in listed
    )
    extras: list[str] = []
    omitted = len(editorial) - len(listed)
    if omitted:
        extras.append(f"{omitted} more editorial windows")
    if joins:
        extras.append(f"{joins} cut joins")
    if cues:
        extras.append(f"{cues} overlay cues")
    if extras:
        lines.append(
            "Sampled frames also cover "
            + ", ".join(extras)
            + ". Judge those frames. Do not repeat this list."
        )
    return lines


def _context_prompt_lines(context: Mapping[str, Any]) -> list[str]:
    declared = [
        ("Declared format", context.get("format")),
        ("Declared language", context.get("language")),
    ]
    lines = [f"{label}: {value}" for label, value in declared if value]
    lines.extend(
        f"Acceptance criterion: {item}"
        for item in context.get("acceptanceCriteria") or []
    )
    lines.extend(f"Declared risk: {item}" for item in context.get("riskNotes") or [])
    for section in context.get("sections") or []:
        lines.append(
            "Section "
            f"{section['sectionId']}: format={section['formatRole']}; "
            f"purpose={section['purpose']}; payoff={section['payoff']}; "
            f"target-density={section['targetDensity']}; "
            f"protected-pauses={len(section['protectedPauses'])}; "
            f"risks={','.join(section['riskClasses']) or 'none'}"
        )
    for section_id, metrics in sorted((context.get("pacingMetrics") or {}).items()):
        lines.append(f"Deterministic pacing metrics for {section_id}: {metrics}")
    return lines


def _reference_prompt_lines(
    transcript_ref: str | Path | None,
    terms: list[str] | None,
    names: list[str] | None,
) -> list[str]:
    lines: list[str] = []
    if transcript_ref:
        lines.append(f"Candidate transcript reference: {Path(transcript_ref).name}")
    if terms:
        lines.append("Validated terms: " + ", ".join(terms))
    if names:
        lines.append("Validated names: " + ", ".join(names))
    return lines


def build_watch_prompt(
    *,
    checkpoint: str,
    scope: str,
    windows: list[dict[str, Any]],
    context: Mapping[str, Any] | None = None,
    transcript_ref: str | Path | None = None,
    terms: list[str] | None = None,
    names: list[str] | None = None,
    repair: bool = False,
) -> str:
    context = dict(context or {})
    lines = [
        f"Review the exact candidate for checkpoint '{checkpoint}' with {scope} coverage.",
        "Inspect continuity, sync, cut edges, overlays, text readability, privacy, safety, accessibility, and preserved meaning.",
    ]
    lines.extend(_window_prompt_lines(windows))
    lines.extend(_context_prompt_lines(context))
    lines.extend(_reference_prompt_lines(transcript_ref, terms, names))
    if repair:
        lines.append(
            "Repair the prior answer into the required structured result only."
        )
    lines.extend(
        [
            "Answer with one JSON object only. Do not describe frames in prose.",
            'Required shape: {"status":"pass"|"fail"|"needs-human-judgment","confidence":0.0,"findings":[]}',
            "status must be pass, fail, or needs-human-judgment; confidence must be numeric; findings must be a list.",
            "Use pass only when no blocker exists. Never invent unseen evidence.",
        ]
    )
    return "\n".join(lines)
