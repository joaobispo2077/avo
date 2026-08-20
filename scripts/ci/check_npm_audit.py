#!/usr/bin/env python3
"""Failing npm audit gate at high+ with documented allowlist (task-011 / FR-6).

Runs ``npm audit --json``, keeps only high/critical advisories, subtracts
``deps-audit-allowlist.json``, and exits non-zero on anything unexpected.
Soft/warn-only mode is intentionally absent.
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
GHSA_RE = re.compile(r"GHSA-[a-z0-9]{4}-[a-z0-9]{4}-[a-z0-9]{4}", re.I)
FAIL_SEVERITIES = frozenset({"high", "critical"})


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


def _ghsa_from_via(item: object) -> str | None:
    if isinstance(item, str):
        match = GHSA_RE.search(item)
        return match.group(0).upper() if match else None
    if isinstance(item, dict):
        for key in ("url", "title", "name"):
            value = item.get(key)
            if isinstance(value, str):
                match = GHSA_RE.search(value)
                if match:
                    return match.group(0).upper()
        source = item.get("source")
        if source is not None:
            # Numeric npm advisory ids are unstable across registries; require GHSA.
            return None
    return None


def _high_advisory_ids(audit: dict) -> dict[str, dict]:
    """Map GHSA id -> {package, severity, nodes} for high/critical findings."""
    found: dict[str, dict] = {}
    vulns = audit.get("vulnerabilities") or {}
    if not isinstance(vulns, dict):
        raise SystemExit("npm audit JSON missing vulnerabilities object")

    for name, entry in vulns.items():
        if not isinstance(entry, dict):
            continue
        pkg_severity = str(entry.get("severity", "")).lower()
        if pkg_severity not in FAIL_SEVERITIES:
            continue
        vias = entry.get("via") or []
        if not isinstance(vias, list):
            continue
        matched_any = False
        for via in vias:
            via_severity = pkg_severity
            if isinstance(via, dict) and via.get("severity"):
                via_severity = str(via["severity"]).lower()
            if via_severity not in FAIL_SEVERITIES:
                continue
            ghsa = _ghsa_from_via(via)
            if not ghsa:
                raise SystemExit(
                    f"high/critical npm finding without GHSA id: package={name} via={via!r}"
                )
            matched_any = True
            found[ghsa] = {
                "package": name,
                "severity": via_severity,
                "nodes": entry.get("nodes") or [],
            }
        if not matched_any:
            # Package marked high/critical but only moderate vias — treat as fail.
            raise SystemExit(
                f"package {name!r} severity={pkg_severity} but no high/critical via GHSA"
            )
    return found


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


def main() -> int:
    allowlist = _load_allowlist()
    audit = _run_npm_audit()
    found = _high_advisory_ids(audit)

    unexpected: list[tuple[str, dict]] = []
    allowed_hits: list[tuple[str, dict]] = []
    for ghsa, meta in sorted(found.items()):
        if ghsa in allowlist:
            allowed_hits.append((ghsa, meta))
        else:
            unexpected.append((ghsa, meta))

    unused = sorted(set(allowlist) - set(found))
    if unused:
        print("ERROR: unused npm audit allowlist entries (remove or fix):", file=sys.stderr)
        for ghsa in unused:
            entry = allowlist[ghsa]
            print(
                f"  - {ghsa} ({entry.get('package')}): {entry.get('reason')}",
                file=sys.stderr,
            )
        return 1

    if allowed_hits:
        print("npm audit high+ allowlisted (documented exceptions):")
        for ghsa, meta in allowed_hits:
            reason = allowlist[ghsa]["reason"]
            print(f"  - {ghsa} {meta['package']} [{meta['severity']}]: {reason}")

    if unexpected:
        print(
            "Dependency security gate failed — unexpected npm high/critical advisories:",
            file=sys.stderr,
        )
        for ghsa, meta in unexpected:
            nodes = ", ".join(meta.get("nodes") or []) or "(no nodes)"
            print(
                f"  - {ghsa} {meta['package']} [{meta['severity']}] @ {nodes}",
                file=sys.stderr,
            )
        print(
            "Fix the dependency, add a root override, or document a narrow "
            "allowlist entry in scripts/ci/deps-audit-allowlist.json.",
            file=sys.stderr,
        )
        return 1

    print("npm audit high+ passed (after documented allowlist).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
