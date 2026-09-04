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
    return {
        key: values[key]
        for key in ("format", "language", "acceptanceCriteria", "riskNotes")
        if values.get(key) not in (None, [], "")
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


def _window_prompt_lines(windows: list[dict[str, Any]]) -> list[str]:
    if not windows:
        return []
    return [
        "Required windows:",
        *[
            f"- {float(window['start']):.3f}–{float(window['end']):.3f} seconds: "
            f"{window['reason']}"
            for window in windows
        ],
    ]


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
            "Return one JSON object with keys status, confidence, and findings.",
            "status must be pass, fail, or needs-human-judgment; confidence must be numeric; findings must be a list.",
            "Use pass only when no blocker exists. Never invent unseen evidence.",
        ]
    )
    return "\n".join(lines)
