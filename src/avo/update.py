"""AVO self-update: git pull + full post-update sync with provider preservation."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from avo import avo_state
from avo.paths import providers_dir, repo_root

TEMPLATE_SLUG = "_template"
MANIFEST_NAME = "avo.provider.json"


@dataclass(frozen=True)
class ProviderWorkspace:
    slug: str
    path: Path
    manifest: Path

    def to_dict(self) -> dict[str, str]:
        return {
            "slug": self.slug,
            "path": str(self.path.resolve()),
            "manifest": str(self.manifest.resolve()),
        }


@dataclass(frozen=True)
class GitStatus:
    branch: str
    behind: int
    ahead: int
    upstream: str
    fetch_ok: bool


@dataclass
class UpdateReport:
    local_version: str
    remote_version: str | None
    providers_before: list[ProviderWorkspace]
    providers_after: list[ProviderWorkspace]
    git: GitStatus | None
    pulled: bool
    synced_skills: bool
    synced_toolchain: bool
    dry_run: bool
    check_only: bool
    messages: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "localVersion": self.local_version,
            "remoteVersion": self.remote_version,
            "providersBefore": [p.to_dict() for p in self.providers_before],
            "providersAfter": [p.to_dict() for p in self.providers_after],
            "git": None
            if self.git is None
            else {
                "branch": self.git.branch,
                "behind": self.git.behind,
                "ahead": self.git.ahead,
                "upstream": self.git.upstream,
                "fetchOk": self.git.fetch_ok,
            },
            "pulled": self.pulled,
            "syncedSkills": self.synced_skills,
            "syncedToolchain": self.synced_toolchain,
            "dryRun": self.dry_run,
            "checkOnly": self.check_only,
            "messages": self.messages,
        }


def list_provider_workspaces(root: Path | None = None) -> list[ProviderWorkspace]:
    """List user provider workspaces under ``providers/<slug>/`` (excludes ``_template``)."""
    base = providers_dir() if root is None else root / "providers"
    if not base.is_dir():
        return []
    workspaces: list[ProviderWorkspace] = []
    for entry in sorted(base.iterdir()):
        if not entry.is_dir() or entry.name.startswith("."):
            continue
        if entry.name == TEMPLATE_SLUG:
            continue
        manifest = entry / MANIFEST_NAME
        if not manifest.is_file():
            continue
        workspaces.append(
            ProviderWorkspace(slug=entry.name, path=entry, manifest=manifest)
        )
    return workspaces


def verify_providers_preserved(
    before: list[ProviderWorkspace],
    after: list[ProviderWorkspace],
) -> list[str]:
    """Return error strings when any pre-update provider is missing or lost its manifest."""
    after_by_slug = {p.slug: p for p in after}
    errors: list[str] = []
    for prev in before:
        current = after_by_slug.get(prev.slug)
        if current is None:
            errors.append(f"provider missing after update: {prev.slug}")
            continue
        if not current.manifest.is_file():
            errors.append(f"provider manifest missing after update: {prev.slug}")
    return errors


def _run_git(args: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )


def is_git_repo(root: Path | None = None) -> bool:
    root = root or repo_root()
    result = _run_git(["rev-parse", "--is-inside-work-tree"], cwd=root)
    return result.returncode == 0 and result.stdout.strip() == "true"


def tracked_tree_dirty(root: Path | None = None) -> bool:
    """True when git reports any working-tree change (gitignored providers excluded)."""
    root = root or repo_root()
    result = _run_git(["status", "--porcelain"], cwd=root)
    if result.returncode != 0:
        return True
    return bool(result.stdout.strip())


def git_fetch(root: Path | None = None) -> bool:
    root = root or repo_root()
    result = _run_git(["fetch", "--quiet"], cwd=root)
    return result.returncode == 0


def git_upstream_status(root: Path | None = None) -> GitStatus | None:
    root = root or repo_root()
    branch = _run_git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=root)
    if branch.returncode != 0:
        return None
    upstream = _run_git(["rev-parse", "--abbrev-ref", "@{u}"], cwd=root)
    if upstream.returncode != 0:
        return GitStatus(
            branch=branch.stdout.strip(),
            behind=0,
            ahead=0,
            upstream="",
            fetch_ok=True,
        )
    behind = _run_git(["rev-list", "--count", "HEAD..@{u}"], cwd=root)
    ahead = _run_git(["rev-list", "--count", "@{u}..HEAD"], cwd=root)
    return GitStatus(
        branch=branch.stdout.strip(),
        behind=int(behind.stdout.strip() or "0"),
        ahead=int(ahead.stdout.strip() or "0"),
        upstream=upstream.stdout.strip(),
        fetch_ok=True,
    )


def git_pull_ff_only(root: Path | None = None) -> tuple[bool, str]:
    root = root or repo_root()
    result = _run_git(["pull", "--ff-only", "--quiet"], cwd=root)
    if result.returncode == 0:
        return True, "pulled latest (fast-forward)"
    detail = (result.stderr or result.stdout or "fast-forward pull failed").strip()
    return False, detail


def stored_transcription_language(state: dict[str, Any] | None = None) -> str:
    state = state or avo_state.load_state()
    transcription = state.get("transcription") or {}
    lang = str(transcription.get("language") or "").strip()
    return lang or "en"


def run_install_skills(
    root: Path | None = None,
    *,
    dry_run: bool = False,
    runner: Callable[[list[str], Path], int] | None = None,
) -> tuple[bool, str]:
    root = root or repo_root()
    install_cjs = root / "bin" / "install.cjs"
    if not install_cjs.is_file():
        return False, f"missing {install_cjs}"
    cmd = ["node", str(install_cjs), "--yes"]
    if dry_run:
        return True, f"would run: {' '.join(cmd)}"
    run = runner or _default_runner
    code = run(cmd, root)
    if code != 0:
        return False, f"install.cjs exited {code}"
    return True, "agent skills refreshed"


def run_toolchain_setup(
    root: Path | None = None,
    *,
    lang: str = "en",
    dry_run: bool = False,
    runner: Callable[[list[str], Path], int] | None = None,
) -> tuple[bool, str]:
    root = root or repo_root()
    if sys.platform == "win32":
        script = root / "scripts" / "setup.ps1"
        if not script.is_file():
            return False, f"missing {script}"
        shell = "pwsh" if _has_command("pwsh") else "powershell"
        cmd = [
            shell,
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script),
            "--lang",
            lang,
            "--yes",
        ]
    else:
        script = root / "scripts" / "setup.sh"
        if not script.is_file():
            return False, f"missing {script}"
        cmd = ["bash", str(script), "--lang", lang, "--yes"]
    if dry_run:
        return True, f"would run: {' '.join(cmd)}"
    run = runner or _default_runner
    code = run(cmd, root)
    if code != 0:
        return False, f"setup exited {code}"
    return True, "toolchain refreshed"


def _has_command(name: str) -> bool:
    probe = subprocess.run(
        ["where", name] if sys.platform == "win32" else ["sh", "-c", f"command -v {name}"],
        capture_output=True,
        check=False,
        shell=sys.platform == "win32",
    )
    return probe.returncode == 0


def _default_runner(cmd: list[str], cwd: Path) -> int:
    result = subprocess.run(cmd, cwd=cwd, check=False)
    return int(result.returncode)


def record_update_result(report: UpdateReport) -> None:
    state = avo_state.load_state()
    state["version"] = avo_state.package_version()
    state["lastUpdateCheck"] = avo_state.now_iso()
    state["lastUpdate"] = {
        "at": avo_state.now_iso(),
        "localVersion": report.local_version,
        "remoteVersion": report.remote_version,
        "pulled": report.pulled,
        "syncedSkills": report.synced_skills,
        "syncedToolchain": report.synced_toolchain,
        "providers": [p.slug for p in report.providers_after],
    }
    avo_state.save_state(state)


def run_update(
    *,
    yes: bool = False,
    check_only: bool = False,
    dry_run: bool = False,
    skip_sync: bool = False,
    force_fetch: bool = True,
    root: Path | None = None,
    runner: Callable[[list[str], Path], int] | None = None,
) -> UpdateReport:
    root = root or repo_root()
    messages: list[str] = []
    local_version = avo_state.package_version()
    providers_before = list_provider_workspaces(root)

    if not is_git_repo(root):
        messages.append(
            "AVO is not a git clone — /avo.update needs a clone install; "
            "Tier 1 installs should re-run the README installer"
        )
        return UpdateReport(
            local_version=local_version,
            remote_version=None,
            providers_before=providers_before,
            providers_after=providers_before,
            git=None,
            pulled=False,
            synced_skills=False,
            synced_toolchain=False,
            dry_run=dry_run,
            check_only=check_only,
            messages=messages,
        )

    if tracked_tree_dirty(root):
        messages.append(
            "working tree has local changes — commit or stash tracked files, then rerun"
        )
        return UpdateReport(
            local_version=local_version,
            remote_version=None,
            providers_before=providers_before,
            providers_after=providers_before,
            git=None,
            pulled=False,
            synced_skills=False,
            synced_toolchain=False,
            dry_run=dry_run,
            check_only=check_only,
            messages=messages,
        )

    git_info: GitStatus | None = None
    if force_fetch or not check_only:
        if dry_run:
            messages.append("would run: git fetch --quiet")
            git_info = git_upstream_status(root)
        else:
            if not git_fetch(root):
                messages.append("git fetch failed (offline?) — try again later")
                return UpdateReport(
                    local_version=local_version,
                    remote_version=None,
                    providers_before=providers_before,
                    providers_after=providers_before,
                    git=None,
                    pulled=False,
                    synced_skills=False,
                    synced_toolchain=False,
                    dry_run=dry_run,
                    check_only=check_only,
                    messages=messages,
                )
            git_info = git_upstream_status(root)
            if git_info is not None:
                git_info = GitStatus(
                    branch=git_info.branch,
                    behind=git_info.behind,
                    ahead=git_info.ahead,
                    upstream=git_info.upstream,
                    fetch_ok=True,
                )
    else:
        git_info = git_upstream_status(root)

    pulled = False
    synced_skills = False
    synced_toolchain = False
    remote_version: str | None = None

    if git_info is None:
        messages.append("could not read git branch status")
    elif not git_info.upstream:
        messages.append(f"no upstream tracking branch for '{git_info.branch}'")
    elif git_info.behind == 0:
        messages.append(f"up to date on '{git_info.branch}'")
    else:
        messages.append(
            f"{git_info.behind} commit(s) available on '{git_info.branch}' "
            f"(local ahead: {git_info.ahead})"
        )
        if not check_only and (yes or dry_run):
            if dry_run:
                messages.append("would run: git pull --ff-only")
                pulled = True
            elif yes:
                ok, detail = git_pull_ff_only(root)
                messages.append(detail)
                pulled = ok
                if ok:
                    local_version = avo_state.package_version()
            else:
                messages.append("re-run with --yes to pull and sync")

    if check_only:
        report = UpdateReport(
            local_version=local_version,
            remote_version=remote_version,
            providers_before=providers_before,
            providers_after=providers_before,
            git=git_info,
            pulled=False,
            synced_skills=False,
            synced_toolchain=False,
            dry_run=dry_run,
            check_only=True,
            messages=messages,
        )
        if not dry_run:
            avo_state.update_state(lastUpdateCheck=avo_state.now_iso())
        return report

    if pulled and not skip_sync:
        lang = stored_transcription_language()
        ok, detail = run_install_skills(root, dry_run=dry_run, runner=runner)
        messages.append(detail)
        synced_skills = ok
        if ok:
            ok2, detail2 = run_toolchain_setup(
                root, lang=lang, dry_run=dry_run, runner=runner
            )
            messages.append(detail2)
            synced_toolchain = ok2
        elif not dry_run:
            messages.append("skipped toolchain refresh because skills refresh failed")
    elif pulled and skip_sync:
        messages.append("skipped post-update sync (--skip-sync)")
    elif git_info and git_info.behind == 0 and not skip_sync and yes:
        lang = stored_transcription_language()
        ok, detail = run_install_skills(root, dry_run=dry_run, runner=runner)
        messages.append(detail)
        synced_skills = ok
        if ok:
            ok2, detail2 = run_toolchain_setup(
                root, lang=lang, dry_run=dry_run, runner=runner
            )
            messages.append(detail2)
            synced_toolchain = ok2

    providers_after = list_provider_workspaces(root)
    preserve_errors = verify_providers_preserved(providers_before, providers_after)
    for err in preserve_errors:
        messages.append(f"provider preservation failed: {err}")

    report = UpdateReport(
        local_version=local_version,
        remote_version=remote_version,
        providers_before=providers_before,
        providers_after=providers_after,
        git=git_info,
        pulled=pulled,
        synced_skills=synced_skills,
        synced_toolchain=synced_toolchain,
        dry_run=dry_run,
        check_only=False,
        messages=messages,
    )

    if preserve_errors and not dry_run:
        return report

    if not dry_run and (pulled or synced_skills or synced_toolchain):
        record_update_result(report)
    elif not dry_run and git_info is not None:
        avo_state.update_state(lastUpdateCheck=avo_state.now_iso())

    return report


def _print_report(report: UpdateReport, *, json_out: bool) -> None:
    if json_out:
        print(json.dumps(report.to_dict(), indent=2, ensure_ascii=False))
        return
    if report.providers_before:
        slugs = ", ".join(p.slug for p in report.providers_before)
        print(f"providers: {slugs}")
    else:
        print("providers: (none)")
    print(f"version: {report.local_version}")
    if report.git:
        print(
            f"git: branch={report.git.branch} behind={report.git.behind} "
            f"ahead={report.git.ahead}"
        )
    for line in report.messages:
        print(line)


def _cmd_check(args: argparse.Namespace) -> int:
    report = run_update(
        check_only=True,
        dry_run=args.dry_run,
        force_fetch=not args.no_fetch,
        root=args.root,
    )
    _print_report(report, json_out=args.json)
    if any("failed" in m or "missing" in m for m in report.messages):
        return 1
    return 0


def _cmd_apply(args: argparse.Namespace) -> int:
    report = run_update(
        yes=args.yes,
        dry_run=args.dry_run,
        skip_sync=args.skip_sync,
        force_fetch=not args.no_fetch,
        root=args.root,
    )
    _print_report(report, json_out=args.json)
    if any("preservation failed" in m for m in report.messages):
        return 2
    if any(
        kw in m
        for m in report.messages
        for kw in ("failed", "missing", "not a git", "local changes")
    ):
        return 1
    if report.git and report.git.behind > 0 and not report.pulled and not args.dry_run:
        return 1
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=None, help="AVO repo root override")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable report")
    sub = parser.add_subparsers(dest="command", required=True)

    parent = argparse.ArgumentParser(add_help=False)
    parent.add_argument("--dry-run", action="store_true")
    parent.add_argument("--no-fetch", action="store_true")

    p_check = sub.add_parser("check", parents=[parent], help="Fetch/compare only; no pull/sync")
    p_check.set_defaults(func=_cmd_check)

    p_apply = sub.add_parser("apply", parents=[parent], help="Pull (ff-only) and full sync")
    p_apply.add_argument("--yes", "-y", action="store_true", help="Pull and sync without prompt")
    p_apply.add_argument(
        "--skip-sync",
        action="store_true",
        help="Pull only; skip skills and toolchain refresh",
    )
    p_apply.set_defaults(func=_cmd_apply)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
