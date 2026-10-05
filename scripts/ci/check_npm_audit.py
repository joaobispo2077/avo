#!/usr/bin/env python3
"""Failing npm audit gate for critical findings, with documented allowlist.

Runs ``npm audit --json``. Critical findings fail the process (exit 1).
High, moderate, and low findings are printed and recorded for the sticky
metric, and do not fail. String ``via`` names are followed to the root
advisory that carries a GHSA id. A critical finding that never reaches a
GHSA id still fails. Soft/warn-only mode is intentionally absent.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ALLOWLIST_PATH = Path(__file__).resolve().parent / "deps-audit-allowlist.json"
SUMMARY_PATH = ROOT / "reports" / "quality" / "npm-audit-summary.json"
GHSA_RE = re.compile(r"GHSA-[a-z0-9]{4}-[a-z0-9]{4}-[a-z0-9]{4}", re.I)
FAIL_SEVERITIES = frozenset({"critical"})
REPORT_SEVERITIES = frozenset({"high", "moderate", "low"})
_COUNT_KEYS = ("critical", "high", "moderate", "low")


def _load_allowlist() -> dict[str, dict]:
    raw = json.loads(ALLOWLIST_PATH.read_text(encoding="utf-8"))
    index: dict[str, dict] = {}
    today = date.today()
    for entry in raw.get("npm", {}).get("advisory_ids", []):
        adv_id = str(entry["id"]).upper()
        if adv_id in index:
            raise SystemExit(f"duplicate npm allowlist id: {adv_id}")
        if not entry.get("reason"):
            raise SystemExit(f"npm allowlist entry missing reason: {adv_id}")
        if not entry.get("package"):
            raise SystemExit(f"npm allowlist entry missing package: {adv_id}")
        expires = entry.get("expires")
        if expires:
            exp = date.fromisoformat(str(expires))
            if exp < today:
                raise SystemExit(
                    f"npm allowlist entry expired ({expires}): {adv_id} "
                    f"({entry['package']}) — fix upstream or renew with reason"
                )
        index[adv_id] = entry
    return index


def _ghsa_display(item: object) -> str | None:
    if isinstance(item, str):
        match = GHSA_RE.search(item)
        return match.group(0) if match else None
    if isinstance(item, dict):
        for key in ("url", "title", "name"):
            value = item.get(key)
            if isinstance(value, str):
                match = GHSA_RE.search(value)
                if match:
                    return match.group(0)
    return None


def _lock_packages() -> dict:
    path = ROOT / "package-lock.json"
    if not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    packages = payload.get("packages")
    return packages if isinstance(packages, dict) else {}


def _version(name: str, entry: dict, packages: dict) -> str:
    nodes = entry.get("nodes") if isinstance(entry, dict) else None
    if isinstance(nodes, list):
        for node in nodes:
            meta = packages.get(node)
            if isinstance(meta, dict) and isinstance(meta.get("version"), str):
                return meta["version"]
    meta = packages.get(f"node_modules/{name}")
    if isinstance(meta, dict) and isinstance(meta.get("version"), str):
        return meta["version"]
    return ""


def _root_label(package: str, version: str, ghsa: str) -> str:
    ident = f"{package}@{version}" if version else package
    return f"{ident} {ghsa}"


def _counts(vulns: dict) -> dict[str, int]:
    counts = {key: 0 for key in _COUNT_KEYS}
    for entry in vulns.values():
        if not isinstance(entry, dict):
            continue
        severity = str(entry.get("severity", "")).lower()
        if severity in counts:
            counts[severity] += 1
    return counts


def _summary_line(counts: dict[str, int], *, ok: bool) -> str:
    label = "PASS" if ok else "FAIL"
    return f"{label}, {counts['critical']} critical, {counts['high']} high reported"


def _write_summary(counts: dict[str, int], *, ok: bool) -> None:
    SUMMARY_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {"ok": ok, **counts}
    SUMMARY_PATH.write_text(
        json.dumps(payload, indent=2) + "\n",
        encoding="utf-8",
    )


def _root_record(name: str, entry: dict, ghsa: str, packages: dict) -> dict:
    return {
        "package": name,
        "ghsa": ghsa,
        "version": _version(name, entry, packages),
    }


def _walk(
    vulns: dict,
    name: str,
    packages: dict,
    trail: set[str],
    cache: dict[str, tuple[list[dict], bool]],
) -> tuple[list[dict], bool, bool]:
    """Follow string via names to GHSA-bearing advisories.

    Returns ``(roots, missing_id, incomplete)``. A via cycle is incomplete and
    is not cached, so a later pass can name the root once the cycle resolves.
    """
    cached = cache.get(name)
    if cached is not None:
        return cached[0], cached[1], False
    if name in trail:
        return [], False, True
    entry = vulns.get(name)
    if not isinstance(entry, dict):
        return [], True, False
    vias = entry.get("via") or []
    if not isinstance(vias, list) or not vias:
        return [], True, False

    found: list[dict] = []
    missing = False
    incomplete = False
    trail.add(name)
    for via in vias:
        if isinstance(via, str):
            ghsa = _ghsa_display(via)
            if ghsa:
                found.append(_root_record(name, entry, ghsa, packages))
                continue
            child_found, _child_missing, child_incomplete = _walk(
                vulns, via, packages, trail, cache
            )
            if child_found:
                found.extend(child_found)
            elif child_incomplete:
                incomplete = True
            else:
                missing = True
            continue
        if isinstance(via, dict):
            ghsa = _ghsa_display(via)
            if ghsa:
                found.append(_root_record(name, entry, ghsa, packages))
            else:
                missing = True
            continue
        missing = True
    trail.remove(name)

    deduped: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for item in found:
        key = (item["package"], item["ghsa"].upper())
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    if incomplete and not deduped:
        return [], True, True
    resolved = (deduped, missing and not deduped)
    cache[name] = resolved
    return resolved[0], resolved[1], False


def _npm_executable() -> str:
    npm = shutil.which("npm") or shutil.which("npm.cmd")
    if not npm:
        raise SystemExit("npm not found on PATH (required for quality:deps)")
    return npm


def _run_npm_audit() -> dict:
    proc = subprocess.run(
        [_npm_executable(), "audit", "--json"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    # npm audit exits non-zero when vulnerabilities exist; still parse stdout.
    raw = proc.stdout.strip() or proc.stderr.strip()
    if not raw:
        raise SystemExit(
            f"npm audit produced no JSON (exit {proc.returncode}): {proc.stderr}"
        )
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"npm audit JSON parse failed: {exc}\n{raw[:500]}") from exc


def _print_reported(lines: list[str]) -> None:
    if not lines:
        return
    print("npm audit reported (high, moderate, and low do not fail the gate):")
    for line in lines:
        print(f"  - {line}")


def main() -> int:
    allowlist = _load_allowlist()
    audit = _run_npm_audit()
    vulns = audit.get("vulnerabilities") or {}
    if not isinstance(vulns, dict):
        raise SystemExit("npm audit JSON missing vulnerabilities object")

    packages = _lock_packages()
    cache: dict[str, tuple[list[dict], bool]] = {}
    counts = _counts(vulns)
    reported: list[str] = []
    critical: dict[str, dict] = {}

    for name, entry in vulns.items():
        if not isinstance(entry, dict):
            continue
        severity = str(entry.get("severity", "")).lower()
        if severity not in FAIL_SEVERITIES and severity not in REPORT_SEVERITIES:
            continue
        roots, missing_id, incomplete = _walk(vulns, name, packages, set(), cache)
        if incomplete and not roots:
            missing_id = True
        if severity in FAIL_SEVERITIES and (missing_id or not roots):
            _write_summary(counts, ok=False)
            raise SystemExit(
                f"critical npm finding without GHSA id: package={name} via={entry.get('via')!r}"
            )
        if severity in FAIL_SEVERITIES:
            for root in roots:
                critical[root["ghsa"].upper()] = root
            continue
        if not roots:
            reported.append(f"{severity} {name} (no GHSA id)")
            continue
        for root in roots:
            label = _root_label(root["package"], root["version"], root["ghsa"])
            reported.append(f"{severity} {name} via {label}")

    unexpected: list[tuple[str, dict]] = []
    allowed_hits: list[tuple[str, dict]] = []
    for ghsa, root in sorted(critical.items()):
        if ghsa in allowlist:
            allowed_hits.append((ghsa, root))
        else:
            unexpected.append((ghsa, root))

    unused = sorted(set(allowlist) - set(critical))
    if unused:
        print(
            "ERROR: unused npm audit allowlist entries (remove or fix):",
            file=sys.stderr,
        )
        for ghsa in unused:
            entry = allowlist[ghsa]
            print(
                f"  - {ghsa} ({entry.get('package')}): {entry.get('reason')}",
                file=sys.stderr,
            )
        _print_reported(reported)
        print(_summary_line(counts, ok=False))
        _write_summary(counts, ok=False)
        return 1

    if allowed_hits:
        print("npm audit critical allowlisted (documented exceptions):")
        for ghsa, root in allowed_hits:
            reason = allowlist[ghsa]["reason"]
            label = _root_label(root["package"], root["version"], root["ghsa"])
            print(f"  - {label}: {reason}")

    if unexpected:
        print(
            "Dependency security gate failed — unexpected npm critical advisories:",
            file=sys.stderr,
        )
        for _ghsa, root in unexpected:
            label = _root_label(root["package"], root["version"], root["ghsa"])
            print(f"  - {label}", file=sys.stderr)
        print(
            "Fix the dependency, add a root override, or document a narrow "
            "allowlist entry in scripts/ci/deps-audit-allowlist.json.",
            file=sys.stderr,
        )
        _print_reported(reported)
        print(_summary_line(counts, ok=False))
        _write_summary(counts, ok=False)
        return 1

    _print_reported(reported)
    print(_summary_line(counts, ok=True))
    _write_summary(counts, ok=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
