"""Preserved-set resolution, delete candidates, and cleanup safety for AVO projects.

Local-only: no network I/O. Delete execution uses ``npx rimraf`` via subprocess.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

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

    @property
    def all_paths(self) -> list[Path]:
        paths: list[Path] = []
        paths.extend(self.raw_sources)
        if self.initial_transcript is not None:
            paths.append(self.initial_transcript)
        paths.extend(self.final_transcripts)
        paths.extend(self.final_master)
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
            files["addedThenRemoved"] = [entry.__dict__ for entry in self.file_diff.added]
            files["modified"] = [entry.__dict__ for entry in self.file_diff.modified]
            files["removed"] = [entry.__dict__ for entry in self.file_diff.removed]
        else:
            files["addedThenRemoved"] = []
            files["modified"] = []
            files["removed"] = []

        return {
            "rawDir": str(self.raw_dir.resolve()),
            "masterBasename": self.master_basename,
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
    return json.loads(project_path.read_text(encoding="utf-8"))


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
        FileEntry(path=path, bytes=post[path])
        for path in sorted(post_keys - pre_keys)
    ]
    removed = [
        FileEntry(path=path, bytes=pre[path])
        for path in sorted(pre_keys - post_keys)
    ]
    modified: list[FileEntry] = []
    unchanged: list[FileEntry] = []
    for path in sorted(pre_keys & post_keys):
        if pre[path] != post[path]:
            modified.append(FileEntry(path=path, bytes=post[path]))
        else:
            unchanged.append(FileEntry(path=path, bytes=post[path]))
    return FileDiff(added=added, removed=removed, modified=modified, unchanged=unchanged)


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
                errors.append(
                    f"missing final master: {_relative_posix(raw_dir, path)}"
                )

    return errors


def _normalized_path_set(paths: list[Path]) -> set[str]:
    return {str(path.resolve()) for path in paths}


def list_delete_candidates(raw_dir: Path, preserved: PreservedSetResult) -> list[Path]:
    raw_dir = raw_dir.resolve()
    edit_dir = raw_dir / "edit"
    if not edit_dir.is_dir():
        return []

    preserved_set = _normalized_path_set(preserved.all_paths)
    candidates: list[Path] = []

    for path in sorted(edit_dir.rglob("*")):
        try:
            resolved = str(path.resolve())
        except OSError:
            continue
        if resolved in preserved_set:
            continue
        if path.is_file() and not path.is_symlink():
            candidates.append(path)

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


def _load_pre_inventory(pre_json_path: Path | None) -> tuple[dict[str, int] | None, bool]:
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
    delete_candidates = list_delete_candidates(raw_dir, preserved)

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
        file_diff=file_diff,
    )


def execute_cleanup(
    raw_dir: Path,
    master_basename: str,
    *,
    dry_run: bool = False,
    initial_transcript: Path | None = None,
    rimraf_runner: Any | None = None,
) -> list[Path]:
    errors = verify_preserved_complete(
        raw_dir, master_basename, initial_transcript=initial_transcript
    )
    if errors:
        raise SystemExit("\n".join(errors))

    preserved = resolve_preserved_set(
        raw_dir, master_basename, initial_transcript=initial_transcript
    )
    delete_list = list_delete_candidates(raw_dir, preserved)
    assert_no_preserved_in_delete_list(preserved, delete_list)

    if dry_run:
        return delete_list

    runner = rimraf_runner or _default_rimraf_runner
    for path in delete_list:
        runner(path)
    return delete_list


def _default_rimraf_runner(path: Path) -> None:
    subprocess.run(
        ["npx", "rimraf", str(path)],
        check=True,
    )


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
    delete_list = list_delete_candidates(raw_dir, preserved)
    assert_no_preserved_in_delete_list(preserved, delete_list)

    rel_paths = [_relative_posix(raw_dir, path) for path in delete_list]
    if args.json:
        _print_json({"deleteCandidates": rel_paths})
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
    if args.json:
        _print_json(payload)
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


def _cmd_cleanup(args: argparse.Namespace) -> int:
    try:
        delete_list = execute_cleanup(
            Path(args.raw_dir),
            args.master_basename,
            dry_run=args.dry_run,
            initial_transcript=args.initial_transcript,
        )
    except PreservedSetViolation as exc:
        print(str(exc), file=sys.stderr)
        return 1

    raw_dir = Path(args.raw_dir)
    rel_paths = [_relative_posix(raw_dir, path) for path in delete_list]
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
    p_delete.set_defaults(func=_cmd_delete_list)

    p_report = sub.add_parser("report", parents=[parent], help="Build inventory report.")
    p_report.add_argument("--pre", type=Path, default=None, help="Path to pre.json.")
    p_report.add_argument("--json", action="store_true")
    p_report.set_defaults(func=_cmd_report)

    p_cleanup = sub.add_parser("cleanup", parents=[parent], help="Verify and delete.")
    p_cleanup.add_argument(
        "--dry-run",
        action="store_true",
        help="List delete candidates without calling rimraf.",
    )
    p_cleanup.set_defaults(func=_cmd_cleanup)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
