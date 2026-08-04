"""Gate 1 — orchestrator prerequisite validation for AVO CI and local setup.

Reads avo.dependencies.json and checks each declared tool. In --ci mode,
required git clones may be shallow-fetched; ffmpeg warns instead of failing;
Whisper models are never downloaded here.
"""

from __future__ import annotations

from avo.paths import repo_root, config_path
import argparse
import json
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class CheckResult:
    tool: str
    status: str  # OK | WARN | FAIL | SKIP
    note: str




def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_manifest(root: Path) -> dict[str, Any]:
    path = config_path("avo.dependencies.json") if root.resolve() == repo_root().resolve() else _config_at(root, "avo.dependencies.json")
    if not path.is_file():
        raise FileNotFoundError(f"missing dependency manifest: {path}")
    data = load_json(path)
    if "tools" not in data or not isinstance(data["tools"], dict):
        raise ValueError("avo.dependencies.json must contain a tools object")
    return data


def _config_at(root: Path, name: str) -> Path:
    nested = root / "config" / name
    if nested.is_file():
        return nested
    legacy = root / name
    if legacy.is_file():
        return legacy
    return nested


def load_routing(root: Path) -> dict[str, Any]:
    path = config_path("avo.config.json") if root.resolve() == repo_root().resolve() else _config_at(root, "avo.config.json")
    if not path.is_file():
        raise FileNotFoundError(f"missing routing config: {path}")
    return load_json(path)


def build_alias_index(tools: dict[str, Any]) -> dict[str, str]:
    """Map deprecated tool id -> canonical id from aliases fields."""
    index: dict[str, str] = {}
    for tool_id, spec in tools.items():
        for alias in spec.get("aliases") or []:
            index[alias] = tool_id
    return index


def iter_canonical_tools(
    tools: dict[str, Any],
) -> tuple[list[tuple[str, dict[str, Any]]], list[CheckResult]]:
    alias_index = build_alias_index(tools)
    warnings: list[CheckResult] = []
    canonical: list[tuple[str, dict[str, Any]]] = []
    for tool_id, spec in tools.items():
        if tool_id in alias_index:
            warnings.append(
                CheckResult(
                    tool_id,
                    "WARN",
                    f"deprecated alias for {alias_index[tool_id]} — use {alias_index[tool_id]} in avo.dependencies.json",
                )
            )
            continue
        canonical.append((tool_id, spec))
    return canonical, warnings


def routing_covers_manifest(routing: dict[str, Any], manifest: dict[str, Any]) -> list[str]:
    """Return manifest tools whose job id is absent from avo.config.json jobs."""
    jobs = routing.get("jobs") or {}
    missing: list[str] = []
    tools = manifest.get("tools") or {}
    canonical, _ = iter_canonical_tools(tools)
    for tool_id, spec in canonical:
        job = spec.get("job")
        if not job:
            continue
        if job not in jobs:
            missing.append(f"{tool_id} -> job '{job}'")
    return missing


def check_in_repo_paths(root: Path, tool_id: str, spec: dict[str, Any]) -> CheckResult:
    paths = spec.get("paths") or []
    found = [p for p in paths if (root / p).exists()]
    if found:
        return CheckResult(tool_id, "OK", f"found: {', '.join(found)}")
    return CheckResult(
        tool_id,
        "WARN",
        f"none of {paths} exist (SDD commands may be incomplete)",
    )


def check_python_project(root: Path, tool_id: str, spec: dict[str, Any]) -> CheckResult:
    manifest = spec.get("manifest", "pyproject.toml")
    if not (root / manifest).is_file():
        return CheckResult(tool_id, "FAIL", f"missing {manifest}")
    for helper in spec.get("helpers") or []:
        if not (root / helper).is_file():
            return CheckResult(tool_id, "FAIL", f"missing helper {helper}")
    return CheckResult(tool_id, "OK", f"{manifest} + engine modules present")


def check_system_binary(
    tool_id: str, spec: dict[str, Any], *, ci: bool
) -> CheckResult:
    binaries = spec.get("binaries") or []
    missing = [b for b in binaries if shutil.which(b) is None]
    if not missing:
        return CheckResult(tool_id, "OK", "on PATH")
    policy = spec.get("ciPolicy", "fail")
    if ci and policy == "warn":
        return CheckResult(
            tool_id,
            "WARN",
            f"missing on PATH: {', '.join(missing)} (Node static fallback ok in CI)",
        )
    return CheckResult(tool_id, "FAIL", f"missing on PATH: {', '.join(missing)}")


def repo_reachable(repo: str) -> bool:
    try:
        req = urllib.request.Request(repo, method="HEAD")
        with urllib.request.urlopen(req, timeout=15) as resp:
            return 200 <= resp.status < 400
    except urllib.error.HTTPError as exc:
        return exc.code in (301, 302, 403, 405)
    except OSError:
        return False


def shallow_clone(repo: str, dest: Path) -> bool:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        shutil.rmtree(dest)
    proc = subprocess.run(
        ["git", "clone", "--depth", "1", repo, str(dest)],
        capture_output=True,
        text=True,
    )
    return proc.returncode == 0


def check_git_clone(
    root: Path, tool_id: str, spec: dict[str, Any], *, ci: bool
) -> CheckResult:
    rel = spec.get("path", "")
    dest = root / rel
    repo = spec.get("repo", "")
    if dest.is_dir() and any(dest.iterdir()):
        return CheckResult(tool_id, "OK", f"present at {rel}")
    if not repo:
        return CheckResult(tool_id, "FAIL", "no repo URL in manifest")
    if not repo_reachable(repo):
        if ci and spec.get("ciPolicy") == "shallow-clone-if-missing":
            return CheckResult(tool_id, "WARN", f"repo unreachable offline: {repo}")
        return CheckResult(tool_id, "FAIL", f"repo unreachable: {repo}")
    if ci and spec.get("ciPolicy") == "shallow-clone-if-missing":
        if shallow_clone(repo, dest):
            return CheckResult(tool_id, "OK", f"shallow-cloned to {rel}")
        return CheckResult(tool_id, "WARN", f"clone failed (offline?): {rel}")
    return CheckResult(
        tool_id,
        "WARN" if not spec.get("required") else "FAIL",
        f"missing clone at {rel} — run setup or git clone {repo}",
    )


def check_npm_package(root: Path, tool_id: str, spec: dict[str, Any]) -> CheckResult:
    pkg_json = root / spec.get("packageJson", "package.json")
    if not pkg_json.is_file():
        return CheckResult(tool_id, "FAIL", "package.json missing")
    data = load_json(pkg_json)
    name = spec.get("package", "")
    deps = {**(data.get("dependencies") or {}), **(data.get("devDependencies") or {})}
    if name not in deps:
        return CheckResult(tool_id, "FAIL", f"{name} not listed in package.json")
    return CheckResult(tool_id, "OK", f"{name} declared in package.json")


def check_documentation_only(root: Path, tool_id: str, spec: dict[str, Any]) -> CheckResult:
    doc = spec.get("doc")
    if doc and (root / doc).is_file():
        return CheckResult(tool_id, "OK", doc)
    return CheckResult(tool_id, "SKIP", "per-project install documented elsewhere")




def _probe_ai_memory_server() -> bool:
    try:
        req = urllib.request.Request("http://127.0.0.1:49374/health", method="GET")
        with urllib.request.urlopen(req, timeout=2) as resp:
            return 200 <= resp.status < 400
    except (OSError, urllib.error.URLError, ValueError):
        return False


def _wsl_bash(command: str) -> tuple[int, str]:
    import platform
    import subprocess

    if platform.system() != "Windows":
        return 1, ""
    try:
        proc = subprocess.run(
            ["wsl", "-e", "bash", "-lc", command],
            capture_output=True,
            text=True,
            timeout=20,
        )
        out = (proc.stdout or proc.stderr or "").strip()
        return proc.returncode, out
    except (OSError, subprocess.TimeoutExpired):
        return 1, ""


def check_ai_memory_optional(
    root: Path, tool_id: str, spec: dict[str, Any], *, ci: bool
) -> CheckResult:
    base = check_git_clone(root, tool_id, spec, ci=ci)
    on_path = bool(shutil.which("ai-memory"))
    server_up = _probe_ai_memory_server()
    doc = "see docs/ai-memory-and-ai-jail.md"
    if on_path and server_up:
        return CheckResult(tool_id, "OK", "ai-memory on PATH; server reachable")
    if on_path:
        return CheckResult(tool_id, "WARN", f"ai-memory on PATH; server not detected ({doc})")
    if base.status == "OK" and server_up:
        return CheckResult(tool_id, "OK", f"{base.note}; server reachable")
    if base.status == "OK":
        return CheckResult(tool_id, "WARN", f"{base.note}; server not running ({doc})")
    return base


def check_ai_jail_optional(
    root: Path, tool_id: str, spec: dict[str, Any], *, ci: bool
) -> CheckResult:
    import platform

    binary = spec.get("binary", "ai-jail")
    if shutil.which(binary):
        notes = [f"{binary} on PATH"]
        if platform.system() == "Linux" and not shutil.which("bwrap"):
            notes.append("bwrap missing on PATH")
            return CheckResult(tool_id, "WARN", "; ".join(notes))
        return CheckResult(tool_id, "OK", "; ".join(notes))
    if platform.system() == "Windows":
        code, out = _wsl_bash("command -v ai-jail >/dev/null && ai-jail --version")
        if code == 0:
            bwrap_code, _ = _wsl_bash("command -v bwrap >/dev/null")
            if bwrap_code != 0:
                return CheckResult(
                    tool_id,
                    "WARN",
                    "ai-jail in WSL; bwrap missing — sudo apt install bubblewrap",
                )
            line = out.splitlines()[-1] if out else "verified in WSL"
            return CheckResult(tool_id, "OK", f"ai-jail in WSL ({line})")
    return check_git_clone(root, tool_id, spec, ci=ci)

def check_external_binary_or_clone(
    root: Path, tool_id: str, spec: dict[str, Any], *, ci: bool
) -> CheckResult:
    binary = spec.get("binary")
    if binary and shutil.which(binary):
        return CheckResult(tool_id, "OK", f"{binary} on PATH")
    return check_git_clone(root, tool_id, spec, ci=ci)


def run_checks(root: Path, *, ci: bool, optional: bool) -> list[CheckResult]:
    manifest = load_manifest(root)
    routing = load_routing(root)
    alignment = routing_covers_manifest(routing, manifest)
    results: list[CheckResult] = []
    if alignment:
        results.append(
            CheckResult(
                "avo.config-alignment",
                "WARN",
                "jobs missing for: " + "; ".join(alignment),
            )
        )
    else:
        results.append(CheckResult("avo.config-alignment", "OK", "jobs cover manifest"))

    canonical_tools, alias_warnings = iter_canonical_tools(manifest["tools"])
    results.extend(alias_warnings)

    for tool_id, spec in canonical_tools:
        spec = {**spec, "_id": tool_id}
        required = bool(spec.get("required"))
        if not required and not optional:
            results.append(CheckResult(tool_id, "SKIP", "optional (not requested)"))
            continue

        kind = spec.get("kind", "")
        if kind == "in-repo-paths":
            r = check_in_repo_paths(root, tool_id, spec)
        elif kind == "python-project":
            r = check_python_project(root, tool_id, spec)
        elif kind == "system-binary":
            r = check_system_binary(tool_id, spec, ci=ci)
        elif kind == "git-clone":
            if tool_id == "ai-memory":
                r = check_ai_memory_optional(root, tool_id, spec, ci=ci)
            else:
                r = check_git_clone(root, tool_id, spec, ci=ci)
        elif kind == "npm-package":
            r = check_npm_package(root, tool_id, spec)
        elif kind == "documentation-only":
            r = check_documentation_only(root, tool_id, spec)
        elif kind == "external-binary-or-clone":
            if tool_id == "ai-jail":
                r = check_ai_jail_optional(root, tool_id, spec, ci=ci)
            else:
                r = check_external_binary_or_clone(root, tool_id, spec, ci=ci)
        else:
            r = CheckResult(tool_id, "FAIL", f"unknown kind: {kind}")
        r.tool = tool_id
        if not required and r.status == "FAIL":
            r = CheckResult(tool_id, "WARN", r.note)
        results.append(r)
    return results


def print_report(results: list[CheckResult]) -> int:
    exit_code = 0
    print("Gate 1 — Orchestrator prerequisites\n")
    for r in results:
        print(f"  [{r.status:4}] {r.tool}: {r.note}")
        if r.status == "FAIL":
            exit_code = 1
    print()
    if exit_code:
        print("Gate 1 FAILED — fix required prerequisites before usability checks.")
    else:
        print("Gate 1 passed (WARN items are advisory).")
    return exit_code


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="AVO Gate 1 — orchestrator prerequisites")
    parser.add_argument("--ci", action="store_true", help="CI mode: lighter checks, shallow clone")
    parser.add_argument(
        "--include-optional",
        action="store_true",
        help="Also validate optional orchestrator tools",
    )
    parser.add_argument("--root", type=Path, default=None, help="Repo root override")
    args = parser.parse_args(argv)
    root = args.root or repo_root()
    results = run_checks(root, ci=args.ci, optional=args.include_optional)
    return print_report(results)


if __name__ == "__main__":
    sys.exit(main())
