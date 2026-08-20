"""Footage-root EDITLOG.md: digest projection plus append-only Human notes."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
from uuid import uuid4

from avo.timeline.store import StoreError, now_iso
from avo.timeline.workspace import (
    TimelineWorkspace,
    WorkspaceError,
    resolve_project_raw_dir,
)

DIGEST_START = "<!-- avo:editlog-digest:start -->"
DIGEST_END = "<!-- avo:editlog-digest:end -->"
HUMAN_NOTES_HEADING = "## Human notes"
RECENT_EVENTS_CAP = 20
PLACEHOLDER_PICTURE = "Picture: not yet authored"
PLACEHOLDER_AUDIO = "Audio: not yet authored"
PLACEHOLDER_MOTION = "Motion: not yet authored"
PLACEHOLDER_APPROVALS = "Approvals: none recorded yet"
EXPORT_NAME_RE = re.compile(
    r"\d{8}-[a-z0-9]+(?:-[a-z0-9]+)*-v\d{3}",
    re.IGNORECASE,
)
_AUDIO_CUE_KINDS = frozenset({"sfx", "music", "dialogue", "ambience", "voice"})
_MOTION_CUE_KINDS = frozenset({"animation", "motion", "overlay"})


class EditlogError(RuntimeError):
    """Fail-closed EDITLOG refresh (markers, rawDir, unreadable index)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _repo_template_path() -> Path:
    return (
        Path(__file__).resolve().parents[2]
        / "docs"
        / "templates"
        / "logs"
        / "EDITLOG.md"
    )


def template_text() -> str:
    path = _repo_template_path()
    if path.is_file():
        return path.read_text(encoding="utf-8")
    return (
        f"# EDITLOG\n\n{DIGEST_START}\n_Generated: <ISO-8601 Z>_\n\n"
        f"## Picture\n\n{PLACEHOLDER_PICTURE}\n\n## Audio\n\n{PLACEHOLDER_AUDIO}\n\n"
        f"## Motion\n\n{PLACEHOLDER_MOTION}\n\n## Approvals\n\n"
        f"{PLACEHOLDER_APPROVALS}\n\n{DIGEST_END}\n\n{HUMAN_NOTES_HEADING}\n\n"
        "AVO never overwrites this region.\n"
    )


def format_clock(ticks: int, timebase: dict[str, Any] | None) -> str:
    """Render ticks + timebase as mm:ss or h:mm:ss (never ticks-only)."""
    num = int((timebase or {}).get("num") or 1)
    den = int((timebase or {}).get("den") or 1)
    if den <= 0:
        den = 1
    seconds = max(int(ticks) * num / den, 0)
    whole = round(seconds)
    hours, rem = divmod(whole, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def resolve_editlog_raw_dir(
    *,
    project: Path | None = None,
    raw_dir: Path | None = None,
) -> Path:
    if project is None and raw_dir is None:
        raise EditlogError("AVO-EL-002", "require --project and/or --raw-dir")
    try:
        if project is not None:
            resolved = Path(TimelineWorkspace.from_project(project).raw_dir)
            if raw_dir is not None:
                mapped = Path(resolve_project_raw_dir(project, raw_dir))
                if resolved.resolve() != mapped.resolve():
                    raise EditlogError(
                        "AVO-EL-002",
                        "project rawDir does not match --raw-dir",
                    )
            return resolved
        return Path(resolve_project_raw_dir(None, raw_dir))
    except EditlogError:
        raise
    except (WorkspaceError, OSError, TypeError, ValueError) as exc:
        raise EditlogError("AVO-EL-002", str(exc)) from exc


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        with temp.open("w", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
        temp.replace(path)
    except Exception:
        temp.unlink(missing_ok=True)
        raise


def _split_hybrid(text: str) -> tuple[str, str]:
    starts = list(re.finditer(re.escape(DIGEST_START), text))
    ends = list(re.finditer(re.escape(DIGEST_END), text))
    conflict = (
        "EDITLOG digest markers missing or conflicting — Human notes not "
        "overwritten. Fix markers or restore from template."
    )
    if len(starts) != 1 or len(ends) != 1:
        raise EditlogError("AVO-EL-001", conflict)
    start = starts[0]
    end = ends[0]
    if start.start() >= end.start():
        raise EditlogError("AVO-EL-001", conflict)
    notes_at = text.find(HUMAN_NOTES_HEADING)
    if notes_at < 0 or notes_at < end.end():
        raise EditlogError("AVO-EL-001", conflict)
    return text[: start.start()], text[notes_at:]


def _clock_span(point: dict[str, Any] | None) -> str:
    if not isinstance(point, dict) or point.get("ticks") is None:
        return "??:??"
    return format_clock(int(point["ticks"]), point.get("timebase"))


def _head_revision(
    workspace: TimelineWorkspace, artifact: str
) -> dict[str, Any] | None:
    path = workspace.artifact_path(artifact)
    if not path.is_file():
        return None
    try:
        store = workspace.store(artifact)
        index = store.load_index()
    except (StoreError, OSError, KeyError, ValueError) as exc:
        raise EditlogError(
            "AVO-EL-003",
            f"Cannot refresh EDITLOG digest — canonical index unreadable: {artifact}",
        ) from exc
    revision_id = index.get("approvedRevisionId") or index.get("headRevisionId")
    if not revision_id:
        return None
    try:
        return store.revision(str(revision_id))
    except (StoreError, KeyError, OSError) as exc:
        raise EditlogError(
            "AVO-EL-003",
            f"Cannot refresh EDITLOG digest — canonical index unreadable: {artifact}",
        ) from exc


def _head_snapshot(
    workspace: TimelineWorkspace, artifact: str
) -> dict[str, Any] | None:
    revision = _head_revision(workspace, artifact)
    if revision is None:
        return None
    return revision.get("snapshot") or {}


def _first_text(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _append_picture_offset(
    bits: list[str], transform: dict[str, Any], sync: dict[str, Any], where: str
) -> None:
    offset = transform.get("offsetTicks", sync.get("offsetTicks"))
    if offset is None or where != "picture":
        return
    timebase = transform.get("timebase") or sync.get("timebase")
    bits.append(f"offset {format_clock(int(offset), timebase)}")
    bits.append(str(int(offset)))


def _sync_bits(sync: dict[str, Any], where: str) -> list[str]:
    transform = sync.get("transform") or {}
    kind = _first_text(transform.get("kind"), sync.get("kind"), sync.get("mode"))
    rationale = _first_text(sync.get("rationale"), sync.get("reason"))
    bits = [kind] if kind else []
    _append_picture_offset(bits, transform, sync, where)
    if rationale:
        bits.append(rationale)
    return bits


def _fold_sync(lines: list[str], sync: dict[str, Any] | None, where: str) -> list[str]:
    if not sync:
        return lines
    bits = _sync_bits(sync, where)
    if bits:
        lines.append("- Sync: " + "; ".join(bits))
        lines.append("")
    return lines


def _keep_segment_line(segment: dict[str, Any]) -> str:
    start = _clock_span(segment.get("in"))
    end = _clock_span(segment.get("out"))
    sid = segment.get("segmentId") or "segment"
    source = segment.get("sourceId") or ""
    reason = (segment.get("reason") or "").strip()
    extra = f" ({reason})" if reason else ""
    return f"- Keep `{sid}` {start}–{end} {source}{extra}".rstrip()


def _snapshot_removal_line(removal: dict[str, Any]) -> str:
    start = _clock_span(removal.get("in") or removal.get("start"))
    end = _clock_span(removal.get("out") or removal.get("end"))
    reason = (removal.get("reason") or "removed").strip()
    return f"- Remove {start}–{end} ({reason})"


def _diff_removal_lines(diffs: list[dict[str, Any]] | None) -> list[str]:
    lines: list[str] = []
    for item in diffs or []:
        if item.get("op") != "remove":
            continue
        sid = (item.get("target") or {}).get("stableId") or ""
        reason = (item.get("reason") or "removed").strip()
        lines.append(f"- Remove `{sid}` ({reason})".rstrip())
    return lines


def _picture_lines(
    snapshot: dict[str, Any] | None,
    sync: dict[str, Any] | None,
    diffs: list[dict[str, Any]] | None = None,
) -> list[str]:
    lines = ["## Picture", ""]
    if not snapshot or not snapshot.get("segments"):
        lines.append(PLACEHOLDER_PICTURE)
        lines.append("")
        return _fold_sync(lines, sync, "picture")
    lines.extend(_keep_segment_line(s) for s in snapshot.get("segments") or [])
    lines.extend(_snapshot_removal_line(r) for r in snapshot.get("removals") or [])
    lines.extend(_diff_removal_lines(diffs))
    lines.append("")
    return _fold_sync(lines, sync, "picture")


def _cues_with_kinds(
    bmap: dict[str, Any] | None, kinds: frozenset[str]
) -> list[dict[str, Any]]:
    return [
        cue
        for cue in (bmap or {}).get("cues") or []
        if str(cue.get("kind") or "").lower() in kinds
    ]


def _layer_line(layer: dict[str, Any]) -> str:
    role = layer.get("role") or "layer"
    layer_id = layer.get("layerId") or ""
    mute = " (muted)" if layer.get("mute") else ""
    return f"- `{layer_id}` role={role}{mute}"


def _audio_cue_line(cue: dict[str, Any]) -> str:
    start = _clock_span(cue.get("start"))
    end = _clock_span(cue.get("end"))
    intent = (cue.get("intent") or cue.get("reason") or "").strip()
    extra = f" — {intent}" if intent else ""
    cue_id = cue.get("cueId")
    kind = cue.get("kind")
    return f"- Cue `{cue_id}` {start}–{end} ({kind}){extra}"


def _audio_lines(
    tracks: dict[str, Any] | None,
    bmap: dict[str, Any] | None,
    sync: dict[str, Any] | None,
) -> list[str]:
    lines = ["## Audio", ""]
    layers = (tracks or {}).get("audioTracks", {}).get("layers") or []
    cues = _cues_with_kinds(bmap, _AUDIO_CUE_KINDS)
    if not layers and not cues:
        lines.append(PLACEHOLDER_AUDIO)
        lines.append("")
        return _fold_sync(lines, sync, "audio")
    lines.extend(_layer_line(layer) for layer in layers)
    lines.extend(_audio_cue_line(cue) for cue in cues)
    lines.append("")
    return _fold_sync(lines, sync, "audio")


def _animation_parts(
    animation: dict[str, Any] | None,
) -> tuple[dict[str, Any], list[Any], dict[str, Any]]:
    strategy = (animation or {}).get("strategy") or animation or {}
    components = strategy.get("components") or (animation or {}).get("components") or []
    diagnosis = (
        strategy.get("formatDiagnosis")
        or (animation or {}).get("formatDiagnosis")
        or {}
    )
    return strategy, components, diagnosis


def _density_of(strategy: dict[str, Any], animation: dict[str, Any] | None) -> Any:
    density = strategy.get("density")
    if density is None and animation:
        return animation.get("density")
    return density


def _framework_of(strategy: dict[str, Any], animation: dict[str, Any] | None) -> Any:
    return strategy.get("framework") or (animation or {}).get("framework")


def _strategy_line(
    strategy: dict[str, Any],
    animation: dict[str, Any] | None,
    diagnosis: dict[str, Any],
) -> str | None:
    bits = [
        part
        for part in (
            diagnosis.get("format") or "",
            diagnosis.get("viewerIntent") or "",
            _framework_of(strategy, animation),
        )
        if part
    ]
    density = _density_of(strategy, animation)
    if density is not None:
        bits.append(f"density {density}")
    if not bits:
        return None
    return "- Strategy: " + "; ".join(bits)


def _component_line(component: dict[str, Any]) -> str:
    cid = component.get("componentId") or component.get("id") or "component"
    return f"- Component `{cid}`"


def _motion_cue_line(cue: dict[str, Any]) -> str:
    start = _clock_span(cue.get("start"))
    end = _clock_span(cue.get("end"))
    cue_id = cue.get("cueId")
    kind = cue.get("kind")
    return f"- Motion cue `{cue_id}` {start}–{end} ({kind})"


def _motion_lines(
    animation: dict[str, Any] | None, bmap: dict[str, Any] | None
) -> list[str]:
    lines = ["## Motion", ""]
    strategy, components, diagnosis = _animation_parts(animation)
    cues = _cues_with_kinds(bmap, _MOTION_CUE_KINDS)
    if not (components or diagnosis or cues):
        lines.append(PLACEHOLDER_MOTION)
        lines.append("")
        return lines
    strategy_line = _strategy_line(strategy, animation, diagnosis)
    if strategy_line:
        lines.append(strategy_line)
    lines.extend(_component_line(component) for component in components)
    lines.extend(_motion_cue_line(cue) for cue in cues)
    lines.append("")
    return lines


def _decision_event(artifact: str, decision: dict[str, Any]) -> dict[str, Any]:
    return {
        "occurredAt": str(decision.get("decidedAt") or ""),
        "decision": decision.get("decision"),
        "actor": decision.get("actor"),
        "reason": decision.get("reason"),
        "artifact": artifact,
    }


def _collect_events(workspace: TimelineWorkspace) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for artifact in ("cmap", "bmap", "tracks", "animation", "sync-map"):
        path = workspace.artifact_path(artifact)
        if not path.is_file():
            continue
        try:
            loaded = workspace.store(artifact).load()
        except (StoreError, OSError, KeyError, ValueError):
            continue
        events.extend(
            _decision_event(artifact, decision)
            for decision in loaded.get("decisions") or []
        )
    events.sort(key=lambda item: item.get("occurredAt") or "", reverse=True)
    return events[:RECENT_EVENTS_CAP]


def _export_names(raw_dir: Path) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()
    for root in (
        raw_dir / "edit" / "masters",
        raw_dir / "edit" / "preview",
        raw_dir / "edit" / "review",
    ):
        if not root.is_dir():
            continue
        try:
            for path in root.rglob("*"):
                if EXPORT_NAME_RE.search(path.name) and path.name not in seen:
                    seen.add(path.name)
                    names.append(path.name)
        except OSError:
            continue
    return names[:20]


def _risk_notes(payload: dict[str, Any]) -> list[str]:
    notes: list[str] = []
    for risk in payload.get("unresolvedRisks") or []:
        message = str(risk.get("message") or "").strip()
        if message:
            notes.append(f"- Risk: {message}")
    return notes


def _notes_from_review_json(review_json: Path) -> list[str]:
    notes = [f"- Evidence `{review_json.parent.name}/review.json`"]
    try:
        payload = json.loads(review_json.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return notes
    reviewer = str(payload.get("reviewer") or "").strip()
    state = str(payload.get("state") or "").strip()
    extra = " ".join(
        part for part in (state, f"by {reviewer}" if reviewer else "") if part
    )
    if extra:
        notes.append(f"- Review `{review_json.parent.name}` {extra}")
    notes.extend(_risk_notes(payload))
    return notes


def _review_package_notes(workspace: TimelineWorkspace) -> list[str]:
    notes: list[str] = []
    if not workspace.review_dir.is_dir():
        return notes
    for gate in sorted(workspace.review_dir.glob("*/approval-gate.md")):
        notes.append(f"- Review gate `{gate.parent.name}`")
    for review_json in sorted(workspace.review_dir.glob("*/review.json")):
        notes.extend(_notes_from_review_json(review_json))
    return notes


def _sibling_logs(raw_dir: Path) -> list[str]:
    return [
        name
        for name in ("AUDIO-EDITLOG.md", "ANIMATION-EDITLOG.md")
        if (raw_dir / name).is_file()
    ]


def _event_line(event: dict[str, Any]) -> str:
    actor = event.get("actor") or "unknown"
    decision = event.get("decision") or "event"
    when = event.get("occurredAt") or ""
    reason = (event.get("reason") or "").strip()
    extra = f" — {reason}" if reason else ""
    artifact = event.get("artifact")
    return f"- {when} `{artifact}` {decision} by {actor}{extra}".rstrip()


def _append_siblings(lines: list[str], siblings: list[str]) -> None:
    if siblings:
        lines.append("- Optional sibling logs: " + ", ".join(siblings))


def _approval_lines(workspace: TimelineWorkspace, raw_dir: Path) -> list[str]:
    lines = ["## Approvals", ""]
    events = _collect_events(workspace)
    review_notes = _review_package_notes(workspace)
    exports = _export_names(raw_dir)
    siblings = _sibling_logs(raw_dir)
    empty = not events and not review_notes and not exports
    if empty:
        lines.append(PLACEHOLDER_APPROVALS)
        lines.append("")
        _append_siblings(lines, siblings)
        if siblings:
            lines.append("")
        return lines
    lines.extend(_event_line(event) for event in events)
    lines.extend(review_notes)
    lines.extend(f"- Export `{name}`" for name in exports)
    _append_siblings(lines, siblings)
    lines.append("")
    return lines


def _workspace_for(raw_dir: Path) -> TimelineWorkspace | None:
    project = raw_dir / "avo.project.json"
    if not project.is_file():
        return None
    try:
        return TimelineWorkspace.from_project(project)
    except (WorkspaceError, OSError, ValueError):
        return None


def render_digest(raw_dir: Path, *, generated_at: str | None = None) -> str:
    """Pure projection. Placeholders for missing indexes. Never invent cuts."""
    stamp = generated_at or now_iso()
    workspace = _workspace_for(raw_dir)
    picture = audio_snap = motion = sync = bmap = None
    picture_diffs: list[dict[str, Any]] = []
    if workspace is not None:
        cmap_revision = _head_revision(workspace, "cmap")
        picture = (cmap_revision or {}).get("snapshot") if cmap_revision else None
        picture_diffs = list((cmap_revision or {}).get("diff") or [])
        audio_snap = _head_snapshot(workspace, "tracks")
        motion = _head_snapshot(workspace, "animation")
        sync = _head_snapshot(workspace, "sync-map")
        bmap = _head_snapshot(workspace, "bmap")
    parts = [DIGEST_START, f"_Generated: {stamp}_", ""]
    parts.extend(_picture_lines(picture, sync, picture_diffs))
    parts.extend(_audio_lines(audio_snap, bmap, sync))
    parts.extend(_motion_lines(motion, bmap))
    if workspace is None:
        parts.extend(["## Approvals", "", PLACEHOLDER_APPROVALS, ""])
    else:
        parts.extend(_approval_lines(workspace, raw_dir))
    parts.append(DIGEST_END)
    return "\n".join(parts) + "\n"


def _compose(prefix: str, digest: str, notes_section: str) -> str:
    head = prefix.rstrip() + "\n\n" if prefix.strip() else ""
    return f"{head}{digest.rstrip()}\n\n{notes_section.rstrip()}\n"


def _migrate_edit_copy(raw_dir: Path, notes_section: str) -> tuple[str, bool]:
    edit_copy = raw_dir / "edit" / "EDITLOG.md"
    if not edit_copy.is_file():
        return notes_section, False
    try:
        body = edit_copy.read_text(encoding="utf-8")
    except OSError:
        return notes_section, False
    if not body.strip() or body.strip() in notes_section:
        return notes_section, False
    block = "### Migrated from edit/EDITLOG.md\n\n" + body.rstrip() + "\n"
    return notes_section.rstrip() + "\n\n" + block, True


def refresh_editlog(
    raw_dir: Path, *, generated_at: str | None = None
) -> dict[str, Any]:
    """Migrate if needed; rewrite digest region only; preserve Human notes."""
    raw_dir = Path(raw_dir)
    path = raw_dir / "EDITLOG.md"
    created = False
    if not path.is_file():
        text = template_text()
        created = True
    else:
        text = path.read_text(encoding="utf-8")
        if DIGEST_START not in text or DIGEST_END not in text:
            notes = f"{HUMAN_NOTES_HEADING}\n\n{text.rstrip()}\n"
            text = _compose("# EDITLOG\n", f"{DIGEST_START}\n{DIGEST_END}", notes)
    prefix, notes = _split_hybrid(text)
    notes, migrated = _migrate_edit_copy(raw_dir, notes)
    digest = render_digest(raw_dir, generated_at=generated_at)
    _atomic_write_text(path, _compose(prefix, digest, notes))
    return {
        "ok": True,
        "path": str(path),
        "created": created,
        "migratedEditCopy": migrated,
        "generatedAt": generated_at or now_iso(),
    }


def after_canonical_write(raw_dir: Path) -> dict[str, Any]:
    """Stage hook. Never raises into the mutator."""
    path = Path(raw_dir) / "EDITLOG.md"
    try:
        return refresh_editlog(Path(raw_dir))
    except EditlogError as exc:
        return {
            "ok": False,
            "path": str(path),
            "code": exc.code,
            "message": exc.message,
        }
    except Exception as exc:
        return {
            "ok": False,
            "path": str(path),
            "code": "AVO-EL-HOOK",
            "message": str(exc),
        }
