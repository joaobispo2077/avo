"""Gate 2 — project usability validation for AVO CI and local setup.

Runs only after Gate 1 passes. Validates routing config, provider scaffolds,
setup dry-run contract, and core helper imports — not external clone presence
(Gate 1 owns orchestrator prerequisites).
"""

from __future__ import annotations

from avo.paths import repo_root, config_path
import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any




def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _config_at(root: Path, name: str) -> Path:
    nested = root / "config" / name
    if nested.is_file():
        return nested
    legacy = root / name
    if legacy.is_file():
        return legacy
    return nested


def check_avo_config(root: Path) -> tuple[str, str]:
    path = config_path("avo.config.json") if root.resolve() == repo_root().resolve() else _config_at(root, "avo.config.json")
    if not path.is_file():
        return "FAIL", "avo.config.json missing"
    data = load_json(path)
    if data.get("version") != 1:
        return "FAIL", "avo.config.json version must be 1"
    jobs = data.get("jobs")
    if not isinstance(jobs, dict) or not jobs:
        return "FAIL", "avo.config.json jobs missing or empty"
    required_jobs = {"plan", "transcribe", "understand", "motion", "render", "cleanup"}
    missing = required_jobs - set(jobs)
    if missing:
        return "FAIL", f"missing jobs: {', '.join(sorted(missing))}"
    return "OK", f"{len(jobs)} jobs declared"


def check_provider_scaffold(root: Path) -> tuple[str, str]:
    template = root / "providers/_template/avo.provider.json"
    schema = root / "providers/avo.provider.schema.json"
    if not template.is_file():
        return "FAIL", "providers/_template/avo.provider.json missing"
    if not schema.is_file():
        return "WARN", "providers/avo.provider.schema.json missing"
    try:
        import jsonschema  # noqa: WPS433

        schema_data = load_json(schema)
        jsonschema.validate(load_json(template), schema_data)
    except ImportError:
        return "WARN", "jsonschema not installed; skipped provider schema validation"
    except Exception as exc:  # noqa: BLE001
        return "FAIL", f"provider schema validation failed: {exc}"
    return "OK", "_template provider scaffold present"


def _run_native_script(root: Path, name: str, *args: str) -> subprocess.CompletedProcess[str]:
    is_windows = platform.system() == "Windows"
    if is_windows:
        ps1 = root / "scripts" / f"{name}.ps1"
        shell = "pwsh" if shutil.which("pwsh") else "powershell"
        cmd = [shell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ps1), *args]
    else:
        sh = root / "scripts" / f"{name}.sh"
        cmd = ["bash", str(sh), *args]
    return subprocess.run(cmd, cwd=root, capture_output=True, text=True)


def check_setup_dry_run(root: Path) -> tuple[str, str]:
    if not (root / "scripts/setup.sh").is_file() and not (root / "scripts/setup.ps1").is_file():
        return "FAIL", "setup script missing"
    proc = _run_native_script(
        root,
        "setup",
        "--dry-run",
        "--yes",
        "--lang",
        "en",
        "--skip",
        "engine",
    )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "setup dry-run failed").strip()
        return "FAIL", detail[:500]
    return "OK", "setup --dry-run exited 0"


def check_scaffold_scripts(root: Path) -> tuple[str, str]:
    for name in ("new-provider", "init-project"):
        sh = root / "scripts" / f"{name}.sh"
        ps1 = root / "scripts" / f"{name}.ps1"
        if not sh.is_file() and not ps1.is_file():
            return "FAIL", f"scripts/{name} missing"
        proc = _run_native_script(root, name, "--help")
        if proc.returncode not in (0, 1):
            return "FAIL", f"{name} --help exited {proc.returncode}"
    return "OK", "new-provider + init-project --help ok"


def check_core_helpers_import(root: Path) -> tuple[str, str]:
    modules = [
        "src/avo/avo_state.py",
        "src/avo/transcribe.py",
        "src/avo/prepare_transcription.py",
    ]
    for rel in modules:
        if not (root / rel).is_file():
            return "FAIL", f"missing {rel}"
    src = root / "src"
    proc = subprocess.run(
        [sys.executable, "-c", "import avo.avo_state; print('ok')"],
        cwd=root,
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": str(src)},
    )
    if proc.returncode != 0:
        return "WARN", "avo package import needs PYTHONPATH=src or pip install -e ."
    return "OK", "core engine modules present"


def run_checks(root: Path, *, ci: bool) -> list[tuple[str, str, str]]:
    checks = [
        ("avo.config", check_avo_config(root)),
        ("provider-scaffold", check_provider_scaffold(root)),
        ("setup-dry-run", check_setup_dry_run(root)),
        ("scaffold-scripts", check_scaffold_scripts(root)),
        ("core-helpers", check_core_helpers_import(root)),
    ]
    if ci:
        deps_manifest = _config_at(root, "avo.dependencies.json")
        if not deps_manifest.is_file():
            checks.append(("avo.dependencies", ("FAIL", "avo.dependencies.json missing")))
        else:
            checks.append(("avo.dependencies", ("OK", "manifest present")))
    return [(name, status, note) for name, (status, note) in checks]


def print_report(results: list[tuple[str, str, str]]) -> int:
    exit_code = 0
    print("Gate 2 — Project usability\n")
    for name, status, note in results:
        print(f"  [{status:4}] {name}: {note}")
        if status == "FAIL":
            exit_code = 1
    print()
    if exit_code:
        print("Gate 2 FAILED — AVO project usability checks did not pass.")
    else:
        print("Gate 2 passed (WARN items are advisory).")
    return exit_code


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="AVO Gate 2 — project usability")
    parser.add_argument("--ci", action="store_true", help="CI mode")
    parser.add_argument("--root", type=Path, default=None)
    args = parser.parse_args(argv)
    root = args.root or repo_root()
    results = run_checks(root, ci=args.ci)
    return print_report(results)


if __name__ == "__main__":
    sys.exit(main())
