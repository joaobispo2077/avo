"""Diff bundled helpers/ against upstream video-use helpers for agent-ready reports."""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


MAX_PATCH_BYTES = 200 * 1024


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def list_py_files(root: Path) -> dict[str, Path]:
    if not root.is_dir():
        return {}
    out: dict[str, Path] = {}
    for path in sorted(root.rglob("*.py")):
        rel = path.relative_to(root).as_posix()
        out[rel] = path
    return out


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def unified_diff(a_path: Path, b_path: Path, rel: str) -> str:
    a_lines = a_path.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
    b_lines = b_path.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
    return "".join(
        difflib.unified_diff(
            a_lines,
            b_lines,
            fromfile=f"upstream/helpers/{rel}",
            tofile=f"avo-engine/helpers/{rel}",
        )
    )


def load_pin(upstream_root: Path) -> dict:
    pin_path = upstream_root.parent / ".avo-upstream-pin.json"
    if pin_path.is_file():
        return json.loads(pin_path.read_text(encoding="utf-8"))
    return {"ref": "unknown", "sha": "unknown"}


def write_summary(
    path: Path,
    *,
    ref: str,
    sha: str,
    changed: list[str],
    only_avo: list[str],
    only_upstream: list[str],
) -> None:
    lines = [
        "# Upstream engine diff summary\n",
        f"\n**Generated:** {datetime.now(timezone.utc).isoformat()}\n",
        f"**Upstream ref:** `{ref}` (`{sha[:12]}`)\n",
        "\n## Overview\n",
        f"- Changed files: **{len(changed)}**\n",
        f"- AVO-only files: **{len(only_avo)}**\n",
        f"- Upstream-only files: **{len(only_upstream)}**\n",
        "\n## Suggested actions for agents\n",
        "1. Read `only-in-avo.txt` — do **not** overwrite these with upstream patches.\n",
        "2. Review `helpers/*.patch` for safe cherry-picks (transcribe, captions).\n",
        "3. Re-run Gate 1 and transcribe adapter tests after merging engine changes.\n",
        "\n## Changed files\n",
    ]
    for rel in changed[:50]:
        lines.append(f"- `{rel}`\n")
    if len(changed) > 50:
        lines.append(f"- … and {len(changed) - 50} more\n")
    if only_avo:
        lines.append("\n## AVO-only (preserve)\n")
        for rel in only_avo[:30]:
            lines.append(f"- `{rel}`\n")
    path.write_text("".join(lines), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Diff avo-engine helpers vs upstream")
    parser.add_argument("--root", type=Path, default=None)
    parser.add_argument("--bundled", type=Path, default=None, help="Bundled helpers dir")
    parser.add_argument("--upstream", type=Path, default=None, help="Upstream helpers dir")
    parser.add_argument("--out", type=Path, default=None, help="Output base dir")
    args = parser.parse_args(argv)

    root = args.root or repo_root()
    bundled = (args.bundled or root / "helpers").resolve()
    upstream_helpers = (args.upstream or root / "tools" / "video-use-upstream" / "helpers").resolve()
    out_base = (args.out or root / "specs" / "upstream-diffs" / "video-use").resolve()

    if not bundled.is_dir():
        print(f"bundled helpers missing: {bundled}", file=sys.stderr)
        return 1
    if not upstream_helpers.is_dir():
        print(
            f"upstream helpers missing: {upstream_helpers} — run scripts/upstream/sync-video-use-upstream.sh",
            file=sys.stderr,
        )
        return 1

    pin = load_pin(upstream_helpers.parent)
    ref = pin.get("ref", "unknown")
    sha = pin.get("sha", "unknown")
    short = sha[:7] if sha != "unknown" else "unknown"
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    run_dir = out_base / f"{stamp}-{short}"
    patches_dir = run_dir / "helpers"
    patches_dir.mkdir(parents=True, exist_ok=True)

    bundled_files = list_py_files(bundled)
    upstream_files = list_py_files(upstream_helpers)
    bundled_keys = set(bundled_files)
    upstream_keys = set(upstream_files)

    only_avo = sorted(bundled_keys - upstream_keys)
    only_upstream = sorted(upstream_keys - bundled_keys)
    changed: list[str] = []
    for rel in sorted(bundled_keys & upstream_keys):
        if file_sha256(bundled_files[rel]) != file_sha256(upstream_files[rel]):
            changed.append(rel)
            patch = unified_diff(upstream_files[rel], bundled_files[rel], rel)
            patch_path = patches_dir / f"{rel.replace('/', '__')}.patch"
            patch_path.parent.mkdir(parents=True, exist_ok=True)
            encoded = patch.encode("utf-8")
            if len(encoded) > MAX_PATCH_BYTES:
                patch = patch[:MAX_PATCH_BYTES].rsplit("\n", 1)[0] + "\n\n… [truncated]\n"
            patch_path.write_text(patch, encoding="utf-8")

    (run_dir / "only-in-avo.txt").write_text("\n".join(only_avo) + ("\n" if only_avo else ""), encoding="utf-8")
    (run_dir / "only-in-upstream.txt").write_text(
        "\n".join(only_upstream) + ("\n" if only_upstream else ""), encoding="utf-8"
    )

    manifest = {
        "ref": ref,
        "sha": sha,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "bundledRoot": str(bundled),
        "upstreamRoot": str(upstream_helpers),
        "changed": changed,
        "onlyInAvo": only_avo,
        "onlyInUpstream": only_upstream,
        "changedCount": len(changed),
        "onlyInAvoCount": len(only_avo),
        "onlyInUpstreamCount": len(only_upstream),
    }
    (run_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    write_summary(
        run_dir / "summary.md",
        ref=ref,
        sha=sha,
        changed=changed,
        only_avo=only_avo,
        only_upstream=only_upstream,
    )

    latest = {
        "ref": ref,
        "sha": sha,
        "generatedAt": manifest["generatedAt"],
        "summaryPath": str((run_dir / "summary.md").relative_to(root)).replace("\\", "/"),
        "diffDir": str(run_dir.relative_to(root)).replace("\\", "/"),
        "changedCount": len(changed),
        "onlyInAvoCount": len(only_avo),
    }
    out_base.mkdir(parents=True, exist_ok=True)
    (out_base / "LATEST.json").write_text(json.dumps(latest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(latest))
    return 0


if __name__ == "__main__":
    sys.exit(main())
