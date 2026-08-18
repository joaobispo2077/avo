"""Preserved-set resolution, delete candidates, and cleanup safety for AVO projects.

Local-only: no network I/O. Delete execution uses ``npx rimraf`` via subprocess.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from avo import avo_state
from avo.session import diff_inventories as _session_diff_inventories
from avo.session import scan_inventory as _session_scan_inventory
from avo.telemetry import dir_size

FINAL_TRANSCRIPT_SUFFIXES = (".json", ".txt", ".md", ".srt")
RAW_SUBDIR = "raw"
TOP_LEVEL_EXCLUDE_NAMES = frozenset(
    {
        "edit",
        "avo.project.json",
        "EDITLOG.md",
        "SOURCE-LOG.md",
    }
)
TOP_LEVEL_EXCLUDE_PREFIXES = ("avo.wrap.",)
CANONICAL_INDEX_NAMES = ("cmap", "bmap", "tracks", "animation", "sync-map")
# Names under edit/ for promote-legacy when the five canonical indexes are
# absent. EDITLOG.md here means edit/EDITLOG.md — not footage-root EDITLOG.md.
# When the five indexes exist, promote is a no-op: the root file is a living
# parallel audit (not obsolete-legacy-only). Canonical cleanup walks only
# edit/, so <rawDir>/EDITLOG.md is never a delete candidate.
LEGACY_NAMED_SOURCES = (
    "edl.json",
    "EDITLOG.md",
    "AUDIO-EDITLOG.md",
    "cut-map.md",
    "takes_packed.md",
    "project.md",
)
CLEANUP_SAMPLE_DEFAULT = 50


class PreservedSetViolation(Exception):
    """Raised when a delete list intersects the preserved set."""


@dataclass(frozen=True)
class FileEntry:
    path: str
    bytes: int


@dataclass
class FileDiff:
    added: list[FileEntry] = field(default_factory=list)
    removed: list[FileEntry] = field(default_factory=list)
    modified: list[FileEntry] = field(default_factory=list)
    unchanged: list[FileEntry] = field(default_factory=list)


@dataclass
class PreservedSetResult:
    raw_sources: list[Path]
    initial_transcript: Path | None
    final_transcripts: list[Path]
    final_master: list[Path]
    reconstruction_metadata: list[Path] = field(default_factory=list)

    @property
    def all_paths(self) -> list[Path]:
        paths: list[Path] = []
        paths.extend(self.raw_sources)
        if self.initial_transcript is not None:
            paths.append(self.initial_transcript)
        paths.extend(self.final_transcripts)
        paths.extend(self.final_master)
        paths.extend(self.reconstruction_metadata)
        return paths


@dataclass
class InventoryReport:
    raw_dir: Path
    master_basename: str
    preserved: PreservedSetResult
    delete_candidates: list[Path]
    verify_errors: list[str]
    degraded_mode: bool
    pre_cleanup_project_bytes: int
    delete_candidate_bytes: int
    preserved_bytes: int
    leftover_candidates: int = 0
    file_diff: FileDiff | None = None

    def to_dict(self) -> dict[str, Any]:
        preserved_entries = [
            {"path": _relative_posix(self.raw_dir, path), "bytes": _file_size(path)}
            for path in self.preserved.all_paths
            if path.exists()
        ]
        delete_entries = [
            {"path": _relative_posix(self.raw_dir, path), "bytes": _file_size(path)}
            for path in self.delete_candidates
            if path.exists()
        ]
        files: dict[str, Any] = {
            "scheduledForDeletion": delete_entries,
            "preserved": preserved_entries,
            "degradedMode": self.degraded_mode,
        }
        if self.file_diff is not None:
            files["addedThenRemoved"] = [
                entry.__dict__ for entry in self.file_diff.added
            ]
            files["modified"] = [entry.__dict__ for entry in self.file_diff.modified]
            files["removed"] = [entry.__dict__ for entry in self.file_diff.removed]
        else:
            files["addedThenRemoved"] = []
            files["modified"] = []
            files["removed"] = []

        return {
            "rawDir": str(self.raw_dir.resolve()),
            "masterBasename": self.master_basename,
            "generatedAt": avo_state.now_iso(),
            "verifyErrors": self.verify_errors,
            "space": {
                "preCleanupProjectBytes": self.pre_cleanup_project_bytes,
                "deleteCandidateBytes": self.delete_candidate_bytes,
                "preservedBytes": self.preserved_bytes,
            },
            "files": files,
        }


def _relative_posix(raw_dir: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(raw_dir.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _cleanup_sample_limit() -> int:
    try:
        from avo.stats import load_stats_config

        return int(load_stats_config().deleted_path_sample_limit)
    except Exception:
        return CLEANUP_SAMPLE_DEFAULT


def _as_rel_path(item: Path | str, raw_dir: Path | None) -> str:
    if isinstance(item, Path):
        if raw_dir is not None:
            return _relative_posix(raw_dir, item)
        return item.as_posix()
    return str(item)


def _count_or_len(value: int | None, items: list[str]) -> int:
    return len(items) if value is None else int(value)


def _space_out(space: dict[str, Any] | None) -> dict[str, Any]:
    data = space or {}
    return {
        "preCleanupProjectBytes": int(data.get("preCleanupProjectBytes", 0)),
        "deleteCandidateBytes": int(data.get("deleteCandidateBytes", 0)),
        "preservedBytes": int(data.get("preservedBytes", 0)),
        "freedBytes": data.get("freedBytes"),
    }


def compact_cleanup_result(
    *,
    status: str,
    candidates: Sequence[Path | str] = (),
    deleted: Sequence[Path | str] = (),
    preserved_count: int = 0,
    leftover_candidates: int = 0,
    space: dict[str, Any] | None = None,
    verify_errors: list[str] | None = None,
    session_id: str | None = None,
    scratch_report: str | None = None,
    scratch_meta: str | None = None,
    full_paths: bool = False,
    raw_dir: Path | None = None,
    candidate_count: int | None = None,
    deleted_count: int | None = None,
) -> dict[str, Any]:
    """Bounded JSON for inventory/cleanup stdout. Full path arrays only with ``full_paths``."""
    limit = _cleanup_sample_limit()
    rel_candidates = [_as_rel_path(item, raw_dir) for item in candidates]
    rel_deleted = [_as_rel_path(item, raw_dir) for item in deleted]
    payload: dict[str, Any] = {
        "status": status,
        "candidateCount": _count_or_len(candidate_count, rel_candidates),
        "deletedCount": _count_or_len(deleted_count, rel_deleted),
        "preservedCount": int(preserved_count),
        "leftoverCandidates": int(leftover_candidates),
        "space": _space_out(space),
        "verifyErrors": list(verify_errors or []),
        "candidateSample": rel_candidates[:limit],
        "deletedSample": rel_deleted[:limit],
        "sessionId": session_id,
        "scratchReport": scratch_report,
        "scratchMeta": scratch_meta,
    }
    if full_paths:
        payload["deleteCandidates"] = rel_candidates
        payload["deleted"] = rel_deleted
    return payload


def _file_size(path: Path) -> int:
    try:
        if path.is_file():
            return path.stat().st_size
        if path.is_dir():
            return dir_size(path)
    except OSError:
        return 0
    return 0


def _is_hidden(name: str) -> bool:
    return name.startswith(".")


def _matches_wrap_sidecar(name: str) -> bool:
    return any(name.startswith(prefix) for prefix in TOP_LEVEL_EXCLUDE_PREFIXES)


def load_project(raw_dir: Path) -> dict[str, Any]:
    project_path = raw_dir / "avo.project.json"
    if not project_path.is_file():
        return {}
    return json.loads(project_path.read_text(encoding="utf-8-sig"))


def scan_inventory(root: Path, *, relative_to: Path | None = None) -> dict[str, int]:
    if _session_scan_inventory is not None:
        return _session_scan_inventory(root, relative_to=relative_to or root)

    root = root.resolve()
    base = (relative_to or root).resolve()
    inventory: dict[str, int] = {}
    if not root.exists():
        return inventory

    for path in root.rglob("*"):
        try:
            if not path.is_file() or path.is_symlink():
                continue
            rel = path.resolve().relative_to(base).as_posix()
            inventory[rel] = path.stat().st_size
        except (OSError, ValueError):
            continue
    return inventory


def diff_inventories(pre: dict[str, int], post: dict[str, int]) -> FileDiff:
    if _session_diff_inventories is not None:
        return _session_diff_inventories(pre, post)

    pre_keys = set(pre)
    post_keys = set(post)
    added = [
        FileEntry(path=path, bytes=post[path]) for path in sorted(post_keys - pre_keys)
    ]
    removed = [
        FileEntry(path=path, bytes=pre[path]) for path in sorted(pre_keys - post_keys)
    ]
    modified: list[FileEntry] = []
    unchanged: list[FileEntry] = []
    for path in sorted(pre_keys & post_keys):
        if pre[path] != post[path]:
            modified.append(FileEntry(path=path, bytes=post[path]))
        else:
            unchanged.append(FileEntry(path=path, bytes=post[path]))
    return FileDiff(
        added=added, removed=removed, modified=modified, unchanged=unchanged
    )


def _resolve_raw_sources(raw_dir: Path) -> list[Path]:
    raw_subdir = raw_dir / RAW_SUBDIR
    if raw_subdir.is_dir():
        return sorted(
            path
            for path in raw_subdir.rglob("*")
            if path.is_file() and not path.is_symlink() and not _is_hidden(path.name)
        )

    sources: list[Path] = []
    if not raw_dir.is_dir():
        return sources
    for entry in raw_dir.iterdir():
        if not entry.is_file() or entry.is_symlink():
            continue
        name = entry.name
        if _is_hidden(name):
            continue
        if name in TOP_LEVEL_EXCLUDE_NAMES or _matches_wrap_sidecar(name):
            continue
        sources.append(entry)
    return sorted(sources)


def _resolve_initial_transcript(
    raw_dir: Path,
    master_basename: str,
    *,
    override: Path | None = None,
) -> Path | None:
    if override is not None:
        override = override.resolve()
        if override.is_file():
            return override
        return None

    transcripts_dir = raw_dir / "edit" / "transcripts"
    if not transcripts_dir.is_dir():
        return None

    candidates: list[Path] = []
    for path in transcripts_dir.glob("*.json"):
        if path.stem == master_basename:
            continue
        if path.is_file() and not path.is_symlink():
            candidates.append(path)

    if not candidates:
        return None

    return min(candidates, key=lambda path: path.stat().st_mtime)


def _resolve_final_transcripts(raw_dir: Path, master_basename: str) -> list[Path]:
    transcripts_dir = raw_dir / "edit" / "transcripts"
    if not transcripts_dir.is_dir():
        return []

    paths: list[Path] = []
    for suffix in FINAL_TRANSCRIPT_SUFFIXES:
        path = transcripts_dir / f"{master_basename}{suffix}"
        if path.is_file() and not path.is_symlink():
            paths.append(path)
    return sorted(paths)


def _resolve_final_master(raw_dir: Path, master_basename: str) -> list[Path]:
    masters_dir = raw_dir / "edit" / "masters"
    if not masters_dir.is_dir():
        return []

    paths = sorted(
        path
        for path in masters_dir.glob(f"{master_basename}.*")
        if path.is_file() and not path.is_symlink()
    )
    return paths


def _resolve_reconstruction_metadata(raw_dir: Path) -> list[Path]:
    bundle_path = raw_dir / "edit" / "timeline" / "reconstruction-bundle.json"
    if bundle_path.is_file():
        try:
            from avo.timeline.reconstruction import verify_reconstruction_bundle

            bundle = verify_reconstruction_bundle(raw_dir, bundle_path)
            return sorted(
                {
                    bundle_path,
                    *(raw_dir / item["path"] for item in bundle["files"]),
                }
            )
        except Exception:
            return [bundle_path]
    roots = (raw_dir / "edit" / "timeline", raw_dir / "edit" / "review")
    paths: list[Path] = []
    for root in roots:
        if root.is_dir():
            paths.extend(
                path
                for path in root.rglob("*")
                if path.is_file()
                and not path.is_symlink()
                and path.suffix.lower() in {".json", ".md"}
            )
    # Living footage-root audits (not reconstruction-bundle graph members).
    # Listed as preserved metadata when no verified bundle is present so a
    # later edit/-only cleanup cannot treat them as skippable leftovers.
    for name in (
        "EDITLOG.md",
        "SOURCE-LOG.md",
        "AUDIO-EDITLOG.md",
        "AUDIO-SOURCE-LOG.md",
        "ANIMATION-EDITLOG.md",
        "ANIMATION-SOURCE-LOG.md",
    ):
        path = raw_dir / name
        if path.is_file() and not path.is_symlink():
            paths.append(path)
    return sorted(set(paths))


def resolve_preserved_set(
    raw_dir: Path,
    master_basename: str,
    *,
    initial_transcript: Path | None = None,
) -> PreservedSetResult:
    raw_dir = raw_dir.resolve()
    return PreservedSetResult(
        raw_sources=_resolve_raw_sources(raw_dir),
        initial_transcript=_resolve_initial_transcript(
            raw_dir, master_basename, override=initial_transcript
        ),
        final_transcripts=_resolve_final_transcripts(raw_dir, master_basename),
        final_master=_resolve_final_master(raw_dir, master_basename),
        reconstruction_metadata=_resolve_reconstruction_metadata(raw_dir),
    )


def verify_preserved_complete(
    raw_dir: Path,
    master_basename: str,
    *,
    initial_transcript: Path | None = None,
) -> list[str]:
    raw_dir = raw_dir.resolve()
    if not raw_dir.is_dir():
        return [f"rawDir does not exist: {raw_dir}"]

    preserved = resolve_preserved_set(
        raw_dir, master_basename, initial_transcript=initial_transcript
    )
    errors: list[str] = []

    if not preserved.raw_sources:
        errors.append("missing raw source file(s)")

    if preserved.initial_transcript is None:
        errors.append("missing initial transcript under edit/transcripts/")
    elif not preserved.initial_transcript.is_file():
        errors.append(
            f"missing initial transcript: "
            f"{_relative_posix(raw_dir, preserved.initial_transcript)}"
        )

    if not preserved.final_transcripts:
        errors.append(
            f"missing final transcript artifact(s) for master basename {master_basename!r}"
        )
    else:
        for path in preserved.final_transcripts:
            if not path.is_file():
                errors.append(
                    f"missing final transcript: {_relative_posix(raw_dir, path)}"
                )

    if not preserved.final_master:
        errors.append(
            f"missing final master under edit/masters/ for basename {master_basename!r}"
        )
    else:
        for path in preserved.final_master:
            if not path.is_file():
                errors.append(f"missing final master: {_relative_posix(raw_dir, path)}")

    timeline = raw_dir / "edit" / "timeline"
    canonical = [timeline / f"{name}.json" for name in CANONICAL_INDEX_NAMES]
    if all(path.is_file() for path in canonical):
        try:
            from avo.timeline.reconstruction import verify_reconstruction_bundle

            verify_reconstruction_bundle(raw_dir)
        except Exception as error:
            errors.append(f"invalid or missing reconstruction bundle: {error}")

    return errors


def _normalized_path_set(paths: list[Path]) -> set[str]:
    return {str(path.resolve()) for path in paths}


def scan_delete_candidates(
    raw_dir: Path, preserved: PreservedSetResult
) -> tuple[list[Path], int]:
    """Walk ``edit/`` for delete candidates. ``OSError`` skips increment leftover.

    Do not extend this walker to the footage root. ``EDITLOG.md`` at
    ``<rawDir>/`` is a living audit (and is in ``TOP_LEVEL_EXCLUDE_NAMES``);
    ``edit/EDITLOG.md`` may still be disposable after migration.
    """
    raw_dir = raw_dir.resolve()
    edit_dir = raw_dir / "edit"
    if not edit_dir.is_dir():
        return [], 0

    preserved_set = _normalized_path_set(preserved.all_paths)
    candidates: list[Path] = []
    leftover = 0

    for path in sorted(edit_dir.rglob("*")):
        try:
            resolved = str(path.resolve())
            if resolved in preserved_set:
                continue
            if path.is_file() and not path.is_symlink():
                candidates.append(path)
        except OSError:
            leftover += 1
            continue

    return candidates, leftover


def list_delete_candidates(raw_dir: Path, preserved: PreservedSetResult) -> list[Path]:
    candidates, _leftover = scan_delete_candidates(raw_dir, preserved)
    return candidates


def assert_no_preserved_in_delete_list(
    preserved: PreservedSetResult,
    delete_list: list[Path],
) -> None:
    preserved_set = _normalized_path_set(preserved.all_paths)
    for path in delete_list:
        resolved = str(path.resolve())
        if resolved in preserved_set:
            rel = path.as_posix()
            raise PreservedSetViolation(
                f"Cleanup refused: delete list includes preserved file: {rel}"
            )


def measure_footprint(paths: list[Path]) -> int:
    total = 0
    for path in paths:
        total += _file_size(path)
    return total


def _load_pre_inventory(
    pre_json_path: Path | None,
) -> tuple[dict[str, int] | None, bool]:
    if pre_json_path is None or not pre_json_path.is_file():
        return None, True

    payload = json.loads(pre_json_path.read_text(encoding="utf-8"))
    files = payload.get("files")
    if not isinstance(files, dict):
        return None, True
    inventory = {str(key): int(value) for key, value in files.items()}
    return inventory, False


def build_inventory_report(
    raw_dir: Path,
    master_basename: str,
    *,
    pre_json_path: Path | None = None,
    initial_transcript: Path | None = None,
) -> InventoryReport:
    raw_dir = raw_dir.resolve()
    preserved = resolve_preserved_set(
        raw_dir, master_basename, initial_transcript=initial_transcript
    )
    verify_errors = verify_preserved_complete(
        raw_dir, master_basename, initial_transcript=initial_transcript
    )
    delete_candidates, leftover = scan_delete_candidates(raw_dir, preserved)

    pre_inventory, degraded_mode = _load_pre_inventory(pre_json_path)
    current_inventory = scan_inventory(raw_dir, relative_to=raw_dir)
    file_diff = (
        diff_inventories(pre_inventory, current_inventory)
        if pre_inventory is not None
        else None
    )

    pre_cleanup_bytes = (
        sum(pre_inventory.values()) if pre_inventory is not None else dir_size(raw_dir)
    )

    return InventoryReport(
        raw_dir=raw_dir,
        master_basename=master_basename,
        preserved=preserved,
        delete_candidates=delete_candidates,
        verify_errors=verify_errors,
        degraded_mode=degraded_mode,
        pre_cleanup_project_bytes=pre_cleanup_bytes,
        delete_candidate_bytes=measure_footprint(delete_candidates),
        preserved_bytes=measure_footprint(preserved.all_paths),
        leftover_candidates=leftover,
        file_diff=file_diff,
    )


def _canonical_indexes_complete(raw_dir: Path) -> bool:
    timeline = Path(raw_dir) / "edit" / "timeline"
    return all((timeline / f"{name}.json").is_file() for name in CANONICAL_INDEX_NAMES)


def _legacy_source_files(raw_dir: Path) -> list[Path]:
    edit = Path(raw_dir) / "edit"
    if not edit.is_dir():
        return []
    found: list[Path] = []
    for name in LEGACY_NAMED_SOURCES:
        path = edit / name
        if path.is_file() and not path.is_symlink():
            found.append(path)
    found.extend(
        sorted(
            path
            for path in edit.glob("edl-v*.json")
            if path.is_file() and not path.is_symlink()
        )
    )
    # Keep stable unique order
    seen: set[str] = set()
    unique: list[Path] = []
    for path in found:
        key = str(path.resolve())
        if key in seen:
            continue
        seen.add(key)
        unique.append(path)
    return unique


def _legacy_destinations(raw_dir: Path, source: Path) -> list[Path]:
    raw_dir = Path(raw_dir)
    name = source.name
    dests = [raw_dir / "edit" / "review" / "legacy-reconstruction" / name]
    if name == "EDITLOG.md":
        dests.append(raw_dir / "EDITLOG.md")
    elif name == "AUDIO-EDITLOG.md":
        dests.append(raw_dir / "AUDIO-EDITLOG.md")
    return dests


def promote_legacy_reconstruction(raw_dir: Path, *, apply: bool) -> list[Path]:
    """Copy legacy EDL/log files from ``edit/`` into reconstruction locations.

    ``apply=False`` (dry-run) writes nothing. Skip when all five canonical
    indexes exist — footage-root ``EDITLOG.md`` is then a living parallel
    audit, not obsolete-legacy-only. Destinations are returned so callers
    can treat them as preserved for listing.
    """
    raw_dir = Path(raw_dir)
    if _canonical_indexes_complete(raw_dir):
        return []
    sources = _legacy_source_files(raw_dir)
    dests: list[Path] = []
    for source in sources:
        dests.extend(_legacy_destinations(raw_dir, source))
    if apply:
        for source in sources:
            for dest in _legacy_destinations(raw_dir, source):
                dest.parent.mkdir(parents=True, exist_ok=True)
                try:
                    if dest.resolve() == source.resolve():
                        continue
                except OSError:
                    continue
                shutil.copy2(source, dest)
    return sorted(set(dests))


@dataclass
class CleanupRunResult:
    paths: list[Path]
    leftover: int
    preserved: PreservedSetResult
    pre_cleanup_project_bytes: int
    delete_candidate_bytes: int
    preserved_bytes: int


def _safe_rimraf(runner: Any, path: Path) -> None:
    try:
        runner(path)
    except OSError:
        return


def _path_still_present(path: Path) -> bool:
    try:
        return path.exists()
    except OSError:
        return True


def _merge_legacy_dests(
    preserved: PreservedSetResult, dests: list[Path]
) -> PreservedSetResult:
    if not dests:
        return preserved
    return replace(
        preserved,
        reconstruction_metadata=list(preserved.reconstruction_metadata) + list(dests),
    )


def _execute_deletes(delete_list: list[Path], runner: Any) -> int:
    unlink_skip = 0
    for path in delete_list:
        _safe_rimraf(runner, path)
        if _path_still_present(path):
            unlink_skip += 1
    return unlink_skip


def _maybe_purge_session(session_id: str | None, *, purge_session: bool) -> None:
    if not session_id or not purge_session:
        return
    from avo.scratch import ScratchError, purge_session_tmp

    try:
        purged = purge_session_tmp(session_id)
    except ScratchError:
        purged = False
    if purged:
        print(f"scratch purged: session {session_id}")


def run_cleanup(
    raw_dir: Path,
    master_basename: str,
    *,
    dry_run: bool = False,
    initial_transcript: Path | None = None,
    rimraf_runner: Any | None = None,
    session_id: str | None = None,
    purge_session: bool = True,
) -> CleanupRunResult:
    raw_dir = Path(raw_dir).resolve()
    errors = verify_preserved_complete(
        raw_dir, master_basename, initial_transcript=initial_transcript
    )
    if errors:
        raise SystemExit("\n".join(errors))

    dests = promote_legacy_reconstruction(raw_dir, apply=not dry_run)
    preserved = _merge_legacy_dests(
        resolve_preserved_set(
            raw_dir, master_basename, initial_transcript=initial_transcript
        ),
        dests,
    )
    delete_list, leftover = scan_delete_candidates(raw_dir, preserved)
    assert_no_preserved_in_delete_list(preserved, delete_list)

    result = CleanupRunResult(
        paths=delete_list,
        leftover=leftover,
        preserved=preserved,
        pre_cleanup_project_bytes=dir_size(raw_dir),
        delete_candidate_bytes=measure_footprint(delete_list),
        preserved_bytes=measure_footprint(preserved.all_paths),
    )
    if dry_run:
        return result

    result.leftover += _execute_deletes(
        delete_list, rimraf_runner or _default_rimraf_runner
    )
    _maybe_purge_session(session_id, purge_session=purge_session)
    return result


def execute_cleanup(
    raw_dir: Path,
    master_basename: str,
    *,
    dry_run: bool = False,
    initial_transcript: Path | None = None,
    rimraf_runner: Any | None = None,
    session_id: str | None = None,
) -> list[Path]:
    return run_cleanup(
        raw_dir,
        master_basename,
        dry_run=dry_run,
        initial_transcript=initial_transcript,
        rimraf_runner=rimraf_runner,
        session_id=session_id,
        purge_session=True,
    ).paths


def _default_rimraf_runner(path: Path) -> None:
    import shutil

    try:
        if path.is_file() or path.is_symlink():
            path.unlink(missing_ok=True)
            return
        if path.is_dir():
            npx = "npx.cmd" if sys.platform == "win32" else "npx"
            try:
                subprocess.run([npx, "rimraf", str(path)], check=True)
            except (FileNotFoundError, subprocess.CalledProcessError):
                shutil.rmtree(path, ignore_errors=True)
    except OSError:
        return


def _print_json(payload: Any) -> None:
    print(json.dumps(payload, indent=2))


def _cmd_verify(args: argparse.Namespace) -> int:
    errors = verify_preserved_complete(
        Path(args.raw_dir),
        args.master_basename,
        initial_transcript=args.initial_transcript,
    )
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    print("Preserved set complete.")
    return 0


def _cmd_delete_list(args: argparse.Namespace) -> int:
    raw_dir = Path(args.raw_dir)
    preserved = resolve_preserved_set(
        raw_dir,
        args.master_basename,
        initial_transcript=args.initial_transcript,
    )
    delete_list, leftover = scan_delete_candidates(raw_dir, preserved)
    assert_no_preserved_in_delete_list(preserved, delete_list)

    rel_paths = [_relative_posix(raw_dir, path) for path in delete_list]
    if args.json:
        _print_json(
            compact_cleanup_result(
                status="dry-run",
                candidates=delete_list,
                preserved_count=len(preserved.all_paths),
                leftover_candidates=leftover,
                raw_dir=raw_dir,
                full_paths=bool(getattr(args, "full_paths", False)),
            )
        )
    else:
        for rel in rel_paths:
            print(rel)
    return 0


def _cmd_report(args: argparse.Namespace) -> int:
    report = build_inventory_report(
        Path(args.raw_dir),
        args.master_basename,
        pre_json_path=args.pre,
        initial_transcript=args.initial_transcript,
    )
    payload = report.to_dict()
    scratch_report = None
    scratch_meta = None
    if args.scratch_out:
        if not args.session_id:
            print("error: --session-id required with --scratch-out", file=sys.stderr)
            return 1
        from avo.scratch import write_inventory_scratch

        report_path, meta_path = write_inventory_scratch(args.session_id, payload)
        scratch_report = str(report_path)
        scratch_meta = str(meta_path)
        print(f"scratch report: {report_path}")
        print(f"scratch meta: {meta_path}")
        if not args.json:
            print(f"rawDir: {payload['rawDir']}")
            print(f"masterBasename: {payload['masterBasename']}")
            print(f"deleteCandidates: {len(payload['files']['scheduledForDeletion'])}")
            return 0
    if args.json:
        _print_json(
            compact_cleanup_result(
                status="blocked" if report.verify_errors else "dry-run",
                candidates=report.delete_candidates,
                preserved_count=len(report.preserved.all_paths),
                leftover_candidates=report.leftover_candidates,
                space={
                    "preCleanupProjectBytes": report.pre_cleanup_project_bytes,
                    "deleteCandidateBytes": report.delete_candidate_bytes,
                    "preservedBytes": report.preserved_bytes,
                    "freedBytes": None,
                },
                verify_errors=report.verify_errors,
                session_id=args.session_id,
                scratch_report=scratch_report,
                scratch_meta=scratch_meta,
                full_paths=bool(getattr(args, "full_paths", False)),
                raw_dir=report.raw_dir,
            )
        )
    else:
        print(f"rawDir: {payload['rawDir']}")
        print(f"masterBasename: {payload['masterBasename']}")
        print(f"degradedMode: {payload['files']['degradedMode']}")
        print(f"deleteCandidates: {len(payload['files']['scheduledForDeletion'])}")
        print(f"preserved: {len(payload['files']['preserved'])}")
        if report.verify_errors:
            print("verifyErrors:")
            for error in report.verify_errors:
                print(f"  - {error}")
    return 0


def _print_inventory_cleanup_json(
    args: argparse.Namespace, outcome: CleanupRunResult
) -> None:
    dry = args.dry_run
    raw_dir = Path(args.raw_dir)
    _print_json(
        compact_cleanup_result(
            status="dry-run" if dry else "executed",
            candidates=outcome.paths if dry else (),
            deleted=() if dry else outcome.paths,
            preserved_count=len(outcome.preserved.all_paths),
            leftover_candidates=outcome.leftover,
            space={
                "preCleanupProjectBytes": outcome.pre_cleanup_project_bytes,
                "deleteCandidateBytes": outcome.delete_candidate_bytes,
                "preservedBytes": outcome.preserved_bytes,
                "freedBytes": None if dry else outcome.delete_candidate_bytes,
            },
            session_id=args.session_id,
            full_paths=bool(getattr(args, "full_paths", False)),
            raw_dir=raw_dir,
        )
    )


def _cmd_cleanup(args: argparse.Namespace) -> int:
    try:
        outcome = run_cleanup(
            Path(args.raw_dir),
            args.master_basename,
            dry_run=args.dry_run,
            initial_transcript=args.initial_transcript,
            session_id=args.session_id,
            purge_session=not args.dry_run,
        )
    except PreservedSetViolation as exc:
        print(str(exc), file=sys.stderr)
        return 1

    raw_dir = Path(args.raw_dir)
    rel_paths = [_relative_posix(raw_dir, path) for path in outcome.paths]
    if getattr(args, "json", False):
        _print_inventory_cleanup_json(args, outcome)
        if not args.dry_run:
            print(f"Deleted {len(rel_paths)} path(s).")
        return 0
    if args.dry_run:
        for rel in rel_paths:
            print(rel)
        return 0
    print(f"Deleted {len(rel_paths)} path(s).")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    parent = argparse.ArgumentParser(add_help=False)
    parent.add_argument("--raw-dir", type=Path, required=True)
    parent.add_argument("--master-basename", required=True)
    parent.add_argument(
        "--initial-transcript",
        type=Path,
        default=None,
        help="Override initial transcript detection.",
    )

    p_verify = sub.add_parser("verify", parents=[parent], help="Check preserved set.")
    p_verify.set_defaults(func=_cmd_verify)

    p_delete = sub.add_parser(
        "delete-list", parents=[parent], help="List safe delete candidates."
    )
    p_delete.add_argument("--json", action="store_true")
    p_delete.add_argument(
        "--full-paths",
        action="store_true",
        help="Include the full relative path list (debug).",
    )
    p_delete.set_defaults(func=_cmd_delete_list)

    p_report = sub.add_parser(
        "report", parents=[parent], help="Build inventory report."
    )
    p_report.add_argument("--pre", type=Path, default=None, help="Path to pre.json.")
    p_report.add_argument("--json", action="store_true")
    p_report.add_argument(
        "--full-paths",
        action="store_true",
        help="Include the full relative path list in JSON (debug).",
    )
    p_report.add_argument(
        "--scratch-out",
        action="store_true",
        help="Write full report under .avo/tmp/learndown/<session-id>/.",
    )
    p_report.add_argument(
        "--session-id",
        default=None,
        help="Session id for scratch-out paths.",
    )
    p_report.set_defaults(func=_cmd_report)

    p_cleanup = sub.add_parser("cleanup", parents=[parent], help="Verify and delete.")
    p_cleanup.add_argument(
        "--dry-run",
        action="store_true",
        help="List delete candidates without calling rimraf.",
    )
    p_cleanup.add_argument("--json", action="store_true")
    p_cleanup.add_argument(
        "--full-paths",
        action="store_true",
        help="Include the full relative path list in JSON (debug).",
    )
    p_cleanup.add_argument(
        "--session-id",
        default=None,
        help=(
            "After successful cleanup, purge all .avo/tmp/<kind>/<session-id>/ "
            "kinds (not dry-run)."
        ),
    )
    p_cleanup.set_defaults(func=_cmd_cleanup)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
