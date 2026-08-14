"""Runtime command registry and mutation permissions for every /avo.* surface."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class CommandPermissionError(RuntimeError):
    pass


@dataclass(frozen=True)
class CommandSpec:
    name: str
    mode: str
    owns: frozenset[str] = frozenset()
    secondary_evidence: frozenset[str] = frozenset()


_MODES = {"Owns", "Evidence", "Consumes", "Profile", "Admin"}
_MATRIX = {
    "animation-qc": ("Evidence", ()),
    "audio-qc": ("Evidence", ()),
    "audit": ("Evidence", ()),
    "captions": ("Owns", ("bmap", "tracks")),
    "changelog-video": ("Profile", ()),
    "chapters": ("Consumes", ()),
    "cleanup": ("Admin", ()),
    "color": ("Owns", ("tracks",)),
    "creators": ("Admin", ()),
    "deliver": ("Consumes", ()),
    "docs": ("Admin", ()),
    "end-screen": ("Owns", ("bmap", "tracks")),
    "explainer": ("Profile", ()),
    "figma": ("Owns", ("animation", "tracks")),
    "format": ("Consumes", ()),
    "framework": ("Owns", ("animation",)),
    "general": ("Profile", ()),
    "grade": ("Owns", ("tracks",)),
    "guidelines": ("Consumes", ()),
    "help": ("Admin", ()),
    "issues": ("Admin", ()),
    "launch": ("Profile", ()),
    "learndown": ("Admin", ()),
    "media": ("Owns", ("bmap", "tracks")),
    "motion": ("Owns", ("bmap", "tracks", "animation")),
    "motion-graphics": ("Profile", ()),
    "music-video": ("Profile", ()),
    "pipeline": ("Owns", ("sync-map", "cmap", "bmap", "tracks", "animation")),
    "podcast-clip": ("Profile", ()),
    "pr-video": ("Profile", ()),
    "provider": ("Owns", ("provider-animation",)),
    "reframe": ("Profile", ()),
    "remotion-port": ("Owns", ("animation", "tracks")),
    "retention": ("Consumes", ()),
    "rights": ("Evidence", ()),
    "screencast": ("Profile", ()),
    "shorts": ("Profile", ()),
    "slideshow": ("Profile", ()),
    "sound": ("Owns", ("bmap", "tracks")),
    "stats": ("Admin", ()),
    "supporters": ("Admin", ()),
    "sync": ("Owns", ("sync-map",)),
    "talking-head": ("Profile", ()),
    "telemetry": ("Admin", ()),
    "thumbnail": ("Consumes", ()),
    "trailer": ("Profile", ()),
    "transcribe": ("Evidence", ()),
    "trim": ("Owns", ("cmap",)),
    "update": ("Admin", ()),
    "voiceover": ("Profile", ()),
    "watch": ("Evidence", ()),
}
COMMANDS = {
    name: CommandSpec(name=name, mode=mode, owns=frozenset(owns))
    for name, (mode, owns) in _MATRIX.items()
}


def command_spec(name: str) -> CommandSpec:
    try:
        return COMMANDS[name]
    except KeyError as exc:
        raise CommandPermissionError(f"unknown AVO command: {name}") from exc


def authorize(
    name: str,
    *,
    mutation: str | None = None,
    writes_evidence: bool = False,
    target_scope: str = "current",
    parent_timeline_ref: str | None = None,
) -> CommandSpec:
    spec = command_spec(name)
    if spec.mode not in _MODES:
        raise CommandPermissionError(f"invalid command mode: {spec.mode}")
    if mutation is not None and mutation not in spec.owns:
        raise CommandPermissionError(
            f"{name} ({spec.mode}) cannot mutate canonical artifact {mutation}"
        )
    if writes_evidence and spec.mode not in {"Evidence", "Owns"}:
        raise CommandPermissionError(f"{name} ({spec.mode}) cannot write review evidence")
    if spec.mode == "Profile":
        if target_scope != "child" or not parent_timeline_ref:
            raise CommandPermissionError(
                f"{name} profile must create an isolated child timeline with parent lineage"
            )
    elif target_scope == "child" and spec.mode != "Profile":
        raise CommandPermissionError(f"{name} is not a derivative profile command")
    return spec


def registry_document() -> dict[str, Any]:
    return {
        "schemaVersion": "1.0.0",
        "commands": [
            {
                "name": spec.name,
                "mode": spec.mode,
                "owns": sorted(spec.owns),
                "secondaryEvidence": sorted(spec.secondary_evidence),
            }
            for spec in sorted(COMMANDS.values(), key=lambda item: item.name)
        ],
    }
