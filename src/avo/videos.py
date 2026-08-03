"""CLI for provider video registry stubs."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from avo import avo_state, init_project, video_context, video_registry


def _cmd_list(args: argparse.Namespace) -> int:
    entries = video_registry.list_videos(args.provider)
    if args.json:
        sys.stdout.write(json.dumps(entries, indent=2, ensure_ascii=False) + "\n")
        return 0

    if not entries:
        print(f"No videos registered for provider '{args.provider}'.")
        return 0

    print(f"Videos for provider '{args.provider}':")
    for entry in entries:
        title = entry.get("title") or "(untitled)"
        print(
            f"  {entry['id']:30}  {entry.get('status', '?'):12}  {title}\n"
            f"    rawDir: {entry['rawDir']}"
        )
    print()
    print(video_context.work_mode_advisory(args.provider))
    return 0


def _cmd_show(args: argparse.Namespace) -> int:
    try:
        entry = video_registry.load_registry(args.provider, args.video_id)
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except video_registry.VideoRegistryError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if args.json:
        sys.stdout.write(json.dumps(entry, indent=2, ensure_ascii=False) + "\n")
        return 0

    print(f"id       : {entry['id']}")
    print(f"provider : {entry['provider']}")
    print(f"status   : {entry.get('status')}")
    print(f"rawDir   : {entry['rawDir']}")
    if entry.get("title"):
        print(f"title    : {entry['title']}")
    project_path = Path(str(entry["rawDir"])) / str(entry.get("projectFile") or "avo.project.json")
    if project_path.is_file():
        print(f"project  : {project_path} (exists)")
    else:
        print(f"project  : {project_path} (missing)")
    lock = video_context.read_lock(Path(str(entry["rawDir"])))
    if lock:
        print(f"lock     : held since {lock.get('acquiredAt')} (advisory)")
    return 0


def _cmd_resolve(args: argparse.Namespace) -> int:
    try:
        ctx = video_context.resolve_context(
            provider=args.provider,
            video_id=args.video_id,
        )
    except (FileNotFoundError, video_registry.VideoRegistryError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if args.json:
        payload = {
            "provider": ctx.provider,
            "videoId": ctx.video_id,
            "videoKey": ctx.video_key,
            "rawDir": str(ctx.raw_dir),
        }
        if args.verbose:
            payload["mergedConfig"] = video_context.merge_config(ctx)
        sys.stdout.write(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
        return 0

    print(str(ctx.raw_dir))
    if args.verbose and ctx.video_key:
        print(f"videoKey: {ctx.video_key}")
    return 0


def _cmd_reindex(args: argparse.Namespace) -> int:
    try:
        index_path = video_registry.rebuild_index(args.provider)
    except video_registry.VideoRegistryError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"Rebuilt index: {index_path}")
    return 0


def _cmd_context_set(args: argparse.Namespace) -> int:
    try:
        ctx = video_context.resolve_context(provider=args.provider, video_id=args.video_id)
    except (FileNotFoundError, video_registry.VideoRegistryError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    payload = {
        "mode": "concurrency",
        "provider": ctx.provider,
        "videoId": ctx.video_id,
        "videoKey": ctx.video_key,
        "rawDir": str(ctx.raw_dir),
    }
    path = avo_state.save_active_context(payload)
    print(f"Active context set (concurrency mode): {ctx.provider}/{ctx.video_id}")
    print(f"  rawDir: {ctx.raw_dir}")
    print(f"  file  : {path}")
    return 0


def _cmd_context_show(args: argparse.Namespace) -> int:
    active = avo_state.load_active_context()
    if args.json:
        sys.stdout.write(json.dumps(active or {}, indent=2, ensure_ascii=False) + "\n")
        return 0
    if not active:
        print("No active context (concurrency mode). Use: videos context set --provider X --video-id Y")
        return 0
    print(f"mode     : {active.get('mode', 'concurrency')}")
    print(f"provider : {active.get('provider')}")
    print(f"videoId  : {active.get('videoId')}")
    print(f"videoKey : {active.get('videoKey')}")
    print(f"rawDir   : {active.get('rawDir')}")
    print(f"updated  : {active.get('updatedAt')}")
    return 0


def _cmd_context_clear(args: argparse.Namespace) -> int:
    avo_state.clear_active_context()
    print("Active context cleared.")
    return 0


def _cmd_lock_acquire(args: argparse.Namespace) -> int:
    try:
        ctx = video_context.resolve_context(provider=args.provider, video_id=args.video_id)
        path = video_context.acquire_lock(ctx, force=args.force, session_id=args.session_id)
    except video_registry.VideoRegistryError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"Advisory lock acquired: {path}")
    return 0


def _cmd_lock_release(args: argparse.Namespace) -> int:
    raw_dir = Path(args.raw_dir).expanduser()
    if video_context.release_lock(raw_dir):
        print(f"Advisory lock released under {raw_dir / 'edit'}")
        return 0
    print("No advisory lock found.")
    return 0


def _cmd_lock_status(args: argparse.Namespace) -> int:
    raw_dir = Path(args.raw_dir).expanduser()
    lock = video_context.read_lock(raw_dir)
    if args.json:
        sys.stdout.write(json.dumps(lock or {}, indent=2, ensure_ascii=False) + "\n")
        return 0
    if not lock:
        print("No advisory lock.")
        return 0
    print(f"provider  : {lock.get('provider')}")
    print(f"videoId   : {lock.get('videoId')}")
    print(f"videoKey  : {lock.get('videoKey')}")
    print(f"acquired  : {lock.get('acquiredAt')}")
    print(f"host/pid  : {lock.get('host')}/{lock.get('pid')}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_list = sub.add_parser("list", help="List registered videos for a provider.")
    p_list.add_argument("--provider", required=True)
    p_list.add_argument("--json", action="store_true")
    p_list.set_defaults(func=_cmd_list)

    p_show = sub.add_parser("show", help="Show one video registry entry.")
    p_show.add_argument("--provider", required=True)
    p_show.add_argument("--video-id", required=True)
    p_show.add_argument("--json", action="store_true")
    p_show.set_defaults(func=_cmd_show)

    p_resolve = sub.add_parser("resolve", help="Resolve video id to external rawDir.")
    p_resolve.add_argument("--provider", required=True)
    p_resolve.add_argument("--video-id", required=True)
    p_resolve.add_argument("--verbose", action="store_true")
    p_resolve.add_argument("--json", action="store_true")
    p_resolve.set_defaults(func=_cmd_resolve)

    p_reindex = sub.add_parser("reindex", help="Rebuild providers/<slug>/videos.index.json.")
    p_reindex.add_argument("--provider", required=True)
    p_reindex.set_defaults(func=_cmd_reindex)

    p_ctx = sub.add_parser("context", help="Active video context (concurrency mode).")
    ctx_sub = p_ctx.add_subparsers(dest="context_cmd", required=True)

    p_ctx_set = ctx_sub.add_parser("set", help="Set active video for concurrency mode.")
    p_ctx_set.add_argument("--provider", required=True)
    p_ctx_set.add_argument("--video-id", required=True)
    p_ctx_set.set_defaults(func=_cmd_context_set)

    p_ctx_show = ctx_sub.add_parser("show", help="Show active video context.")
    p_ctx_show.add_argument("--json", action="store_true")
    p_ctx_show.set_defaults(func=_cmd_context_show)

    p_ctx_clear = ctx_sub.add_parser("clear", help="Clear active video context.")
    p_ctx_clear.set_defaults(func=_cmd_context_clear)

    p_lock = sub.add_parser("lock", help="Advisory edit/ lock (warn-only).")
    lock_sub = p_lock.add_subparsers(dest="lock_cmd", required=True)

    p_lock_acquire = lock_sub.add_parser("acquire", help="Acquire advisory lock on rawDir/edit/.")
    p_lock_acquire.add_argument("--provider", required=True)
    p_lock_acquire.add_argument("--video-id", required=True)
    p_lock_acquire.add_argument("--force", action="store_true")
    p_lock_acquire.add_argument("--session-id", default="")
    p_lock_acquire.set_defaults(func=_cmd_lock_acquire)

    p_lock_release = lock_sub.add_parser("release", help="Release advisory lock.")
    p_lock_release.add_argument("--raw-dir", required=True)
    p_lock_release.set_defaults(func=_cmd_lock_release)

    p_lock_status = lock_sub.add_parser("status", help="Show advisory lock status.")
    p_lock_status.add_argument("--raw-dir", required=True)
    p_lock_status.add_argument("--json", action="store_true")
    p_lock_status.set_defaults(func=_cmd_lock_status)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
