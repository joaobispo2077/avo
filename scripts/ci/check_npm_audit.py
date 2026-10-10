#!/usr/bin/env python3
"""Failing npm audit gate for critical findings, with documented allowlist.

Runs ``npm audit --json``. Critical findings fail the process (exit 1).
High, moderate, and low findings are printed and recorded for the sticky
metric, and do not fail. String ``via`` names are followed to the root
advisory that carries a GHSA id. A critical finding that never reaches a
GHSA id still fails. Soft/warn-only mode is intentionally absent.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ALLOWLIST_PATH = Path(__file__).resolve().parent / "deps-audit-allowlist.json"
FINDINGS_PATH = ROOT / "reports" / "quality" / "deps-findings.json"
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


def write_deps_findings(findings: list[dict], path: Path | None = None) -> None:
    """Persist the findings that failed the gate. Not an allowlist."""
    dest = FINDINGS_PATH if path is None else path
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(
        json.dumps({"findings": findings}, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _via_path(via: object) -> str:
    if isinstance(via, str):
        return via
    if isinstance(via, dict):
        name = via.get("name")
        if isinstance(name, str):
            return name
    return ""


def _ghsa_from_via(item: object) -> str | None:
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


def _collect_high_hits(audit: dict) -> list[dict]:
    """Every high/critical hit, including dev paths and hits with no GHSA id.

    Does not exit. Callers waive by GHSA id, then fail if anything remains.
    """
    vulns = audit.get("vulnerabilities") or {}
    if not isinstance(vulns, dict):
        raise SystemExit("npm audit JSON missing vulnerabilities object")

    hits: list[dict] = []
    for name, entry in vulns.items():
        if not isinstance(entry, dict):
            continue
        pkg_severity = str(entry.get("severity", "")).lower()
        if pkg_severity not in FAIL_SEVERITIES:
            continue
        vias = entry.get("via") or []
        if not isinstance(vias, list):
            continue
        saw_high = False
        nodes = entry.get("nodes") or []
        for via in vias:
            via_severity = pkg_severity
            if isinstance(via, dict) and via.get("severity"):
                via_severity = str(via["severity"]).lower()
            if via_severity not in FAIL_SEVERITIES:
                continue
            saw_high = True
            hits.append(
                {
                    "package": name,
                    "id": _ghsa_from_via(via),
                    "via": _via_path(via),
                    "severity": via_severity,
                    "nodes": nodes,
                    "bare": False,
                }
            )
        if not saw_high:
            # High/critical package with no high/critical via still fails.
            hits.append(
                {
                    "package": name,
                    "id": None,
                    "via": "",
                    "severity": pkg_severity,
                    "nodes": nodes,
                    "bare": True,
                }
            )
    return hits


def _high_advisory_ids(audit: dict) -> dict[str, dict]:
    """Map GHSA id -> {package, severity, nodes} for high/critical findings."""
    found: dict[str, dict] = {}
    for hit in _collect_high_hits(audit):
        ghsa = hit.get("id")
        if not isinstance(ghsa, str) or not ghsa:
            continue
        found[ghsa] = {
            "package": hit["package"],
            "severity": hit["severity"],
            "nodes": hit["nodes"],
            "via": hit["via"],
        }
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


def pip_findings(payload: dict) -> list[dict]:
    """pip-audit ``--format json`` rows that carry an advisory id (PYSEC/GHSA)."""
    deps = payload.get("dependencies")
    if not isinstance(deps, list):
        return []
    findings: list[dict] = []
    for dep in deps:
        if not isinstance(dep, dict):
            continue
        package = dep.get("name")
        vulns = dep.get("vulns")
        if not isinstance(package, str) or not package or not isinstance(vulns, list):
            continue
        for vuln in vulns:
            if not isinstance(vuln, dict):
                continue
            advisory = vuln.get("id")
            if not isinstance(advisory, str) or not advisory.strip():
                continue
            findings.append({"package": package, "id": advisory.strip(), "via": ""})
    return findings


def record_pip_payload(payload: dict) -> int:
    findings = pip_findings(payload) if isinstance(payload, dict) else []
    if findings:
        write_deps_findings(findings)
    return 0


def record_pip_stdin() -> int:
    raw = sys.stdin.read().strip()
    if not raw:
        return 0
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return 0
    return record_pip_payload(payload)


def _print_unwaived(hits: list[dict]) -> None:
    bare = [hit for hit in hits if hit.get("bare")]
    no_id = [hit for hit in hits if not hit.get("id") and not hit.get("bare")]
    identified = [hit for hit in hits if hit.get("id")]
    for hit in no_id:
        print(
            "high/critical npm finding without GHSA id: "
            f"package={hit['package']} via={hit['via']!r}",
            file=sys.stderr,
        )
    for hit in bare:
        print(
            f"package {hit['package']!r} severity={hit['severity']} "
            "but no high/critical via GHSA",
            file=sys.stderr,
        )
    if not identified:
        return
    print(
        "Dependency security gate failed — unexpected npm high/critical advisories:",
        file=sys.stderr,
    )
    for hit in identified:
        nodes = ", ".join(hit.get("nodes") or []) or "(no nodes)"
        print(
            f"  - {hit['id']} {hit['package']} [{hit['severity']}] @ {nodes}",
            file=sys.stderr,
        )
    print(
        "Fix the dependency, add a root override, or document a narrow "
        "allowlist entry in scripts/ci/deps-audit-allowlist.json.",
        file=sys.stderr,
    )


def _finding_record(hit: dict) -> dict:
    advisory = hit.get("id")
    if not isinstance(advisory, str) or not advisory:
        advisory = None
    via = hit.get("via")
    return {
        "package": hit["package"],
        "id": advisory,
        "via": via if isinstance(via, str) else "",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--record-pip",
        action="store_true",
        help="Read pip-audit JSON on stdin and record findings. Does not waive.",
    )
    args = parser.parse_args([] if argv is None else argv)
    if args.record_pip:
        return record_pip_stdin()

    allowlist = _load_allowlist()
    audit = _run_npm_audit()
    hits = _collect_high_hits(audit)

    allowed_hits: list[dict] = []
    unwaived: list[dict] = []
    seen: set[str] = set()
    for hit in hits:
        advisory = hit.get("id")
        if isinstance(advisory, str) and advisory:
            seen.add(advisory)
            if advisory in allowlist:
                allowed_hits.append(hit)
                continue
        # No GHSA id cannot be waived. Dev paths are not exempt.
        unwaived.append(hit)

    unused = sorted(set(allowlist) - seen)
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

    if allowed_hits:
        print("npm audit high+ allowlisted (documented exceptions):")
        for hit in allowed_hits:
            reason = allowlist[hit["id"]]["reason"]
            print(f"  - {hit['id']} {hit['package']} [{hit['severity']}]: {reason}")

    if unwaived:
        write_deps_findings([_finding_record(hit) for hit in unwaived])
        _print_unwaived(unwaived)
        return 1

    if unused:
        return 1

    write_deps_findings([])
    print("npm audit high+ passed (after documented allowlist).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
