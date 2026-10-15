#!/usr/bin/env python3
"""Critical-only npm gate and shared pip/npm dependency audit reporting."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import UTC, date, datetime
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parents[2]
ALLOWLIST_PATH = Path(__file__).resolve().parent / "deps-audit-allowlist.json"
SUMMARY_PATH = ROOT / "reports" / "quality" / "npm-audit-summary.json"
FINDINGS_PATH = ROOT / "reports" / "quality" / "deps-findings.json"
GHSA_RE = re.compile(r"GHSA-[a-z0-9]{4}-[a-z0-9]{4}-[a-z0-9]{4}", re.IGNORECASE)
FAIL_SEVERITIES = frozenset({"critical"})
REPORT_SEVERITIES = frozenset({"high", "moderate", "low"})
_COUNT_KEYS = ("critical", "high", "moderate", "low")
_RAW_DETAILS: dict[str, dict] = {}
_SECRET_KEY = re.compile(
    r"token|password|secret|authorization|credential|api[_-]?key|^env(?:ironment)?$",
    re.IGNORECASE,
)


def _sanitize_url(value: str) -> str:
    try:
        parts = urlsplit(value)
    except ValueError:
        return "[REDACTED INVALID URL]"
    host = parts.netloc.rsplit("@", 1)[-1]
    query = urlencode(
        [
            (key, "[REDACTED]" if _SECRET_KEY.search(key) else item)
            for key, item in parse_qsl(parts.query, keep_blank_values=True)
        ]
    )
    return urlunsplit((parts.scheme, host, parts.path, query, parts.fragment))


def _sanitize(value: object) -> object:
    """Keep advisory detail without persisting credentials or environment data."""
    if isinstance(value, dict):
        return {
            str(key): "[REDACTED]" if _SECRET_KEY.search(str(key)) else _sanitize(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_sanitize(item) for item in value]
    if isinstance(value, str):
        return re.sub(
            r"https?://[^\s\"']+", lambda match: _sanitize_url(match.group()), value
        )
    return value


def _policy(tool: str, allowlist: dict | None = None) -> dict:
    raw = json.loads(ALLOWLIST_PATH.read_text(encoding="utf-8"))
    if tool == "npm":
        return {
            "blocking_severities": sorted(FAIL_SEVERITIES),
            "reported_severities": sorted(REPORT_SEVERITIES),
            "include_dev_dependencies": True,
            "fail_on_unknown_critical_advisory": True,
            "fail_on_unused_allowlist": True,
            "advisory_exceptions": list(allowlist.values())
            if allowlist is not None
            else raw.get("npm", {}).get("advisory_ids", []),
        }
    return {
        "scope": "installed interpreter environment",
        "skip_editable": True,
        "blocking_severities": "all unignored advisories",
        "ignore_vulns": raw.get("pip", {}).get("ignore_vulns", []),
    }


def _write_raw(
    tool: str,
    payload: object = None,
    *,
    status: str = "COMPLETE",
    error: str | None = None,
    policy: dict | None = None,
) -> None:
    details = _RAW_DETAILS.get(tool, {})
    _write_json(
        SUMMARY_PATH.with_name(f"{tool}-audit-raw.json"),
        {
            "schema_version": 1,
            "tool": tool,
            "sha": os.environ.get("AVO_QUALITY_SHA") or os.environ.get("GITHUB_SHA"),
            "run_id": os.environ.get("AVO_QUALITY_RUN_ID")
            or os.environ.get("GITHUB_RUN_ID"),
            "recorded_at": datetime.now(UTC).isoformat(),
            "status": status,
            "exit_code": details.get("exit_code"),
            "command": details.get("command"),
            "policy": _sanitize(policy) if policy is not None else None,
            "payload": _sanitize(payload),
            "error": _sanitize(error),
        },
    )


def _load_allowlist() -> dict[str, dict]:
    raw = json.loads(ALLOWLIST_PATH.read_text(encoding="utf-8"))
    index: dict[str, dict] = {}
    for entry in raw.get("npm", {}).get("advisory_ids", []):
        adv_id = str(entry["id"]).upper()
        if not GHSA_RE.fullmatch(adv_id):
            raise ValueError(f"invalid npm allowlist id: {adv_id}")
        if adv_id in index:
            raise ValueError(f"duplicate npm allowlist id: {adv_id}")
        for field in ("reason", "package"):
            if not isinstance(entry.get(field), str) or not entry[field].strip():
                raise ValueError(f"npm allowlist entry missing {field}: {adv_id}")
        expires = entry.get("expires")
        if expires and date.fromisoformat(str(expires)) < datetime.now(UTC).date():
            raise ValueError(f"npm allowlist entry expired ({expires}): {adv_id}")
        index[adv_id] = entry
    return index


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def write_deps_findings(
    findings: list[dict], path: Path | None = None, *, error: str | None = None
) -> None:
    _write_json(
        FINDINGS_PATH if path is None else path,
        {"findings": findings, "error": error},
    )


def _write_summary(
    counts: dict | None,
    *,
    ok: bool,
    reported: list[dict] | None = None,
    error: str | None = None,
) -> None:
    _write_json(
        SUMMARY_PATH,
        {
            "ok": ok,
            **(counts or dict.fromkeys(_COUNT_KEYS)),
            "reported": reported or [],
            "error": error,
        },
    )


def _ghsa_from_via(item: object) -> str | None:
    values = [item] if isinstance(item, str) else []
    if isinstance(item, dict):
        values = [item.get(key) for key in ("url", "title", "name")]
    for value in values:
        if isinstance(value, str) and (match := GHSA_RE.search(value)):
            return match.group(0)
    return None


def _lock_packages() -> dict:
    payload = json.loads((ROOT / "package-lock.json").read_text(encoding="utf-8"))
    packages = payload.get("packages")
    if not isinstance(packages, dict):
        raise ValueError("package-lock.json missing packages object")
    return packages


def _version(name: str, entry: dict, packages: dict) -> str:
    for node in [*entry.get("nodes", []), f"node_modules/{name}"]:
        meta = packages.get(node, {})
        if isinstance(meta, dict) and isinstance(meta.get("version"), str):
            return meta["version"]
    return ""


def _walk(vulns: dict, name: str, trail: set[str]) -> tuple[list[dict], list[str]]:
    """Resolve every advisory branch; cycles may have a valid advisory exit."""
    if name in trail:
        return [], []
    entry = vulns.get(name)
    if entry is None:
        return [], [name]
    roots: list[dict] = []
    missing: list[str] = []
    for via in entry.get("via", []):
        advisory = _ghsa_from_via(via)
        if advisory:
            roots.append({"package": name, "id": advisory})
        elif isinstance(via, str):
            child_roots, child_missing = _walk(vulns, via, trail | {name})
            roots.extend(child_roots)
            missing.extend(child_missing)
        else:
            missing.append(str(via.get("name", "")))
    if not entry.get("via"):
        missing.append("")
    return roots, missing


def _validate_audit(audit: object) -> dict:
    if (
        not isinstance(audit, dict)
        or audit.get("error")
        or not isinstance(audit.get("vulnerabilities"), dict)
    ):
        raise ValueError(
            "npm audit JSON missing vulnerabilities object or execution error"
        )
    vulns = audit["vulnerabilities"]
    for name, entry in vulns.items():
        if not isinstance(entry, dict) or entry.get("severity") not in (
            *_COUNT_KEYS,
            "info",
        ):
            raise ValueError(f"npm audit invalid vulnerability entry: {name}")
        if not isinstance(entry.get("via", []), list) or not isinstance(
            entry.get("nodes", []), list
        ):
            raise ValueError(f"npm audit invalid dependency paths: {name}")
        if any(not isinstance(via, (str, dict)) for via in entry.get("via", [])):
            raise ValueError(f"npm audit invalid via entry: {name}")
        if any(not isinstance(node, str) for node in entry.get("nodes", [])):
            raise ValueError(f"npm audit invalid installed path: {name}")
    return vulns


def _collect_findings(vulns: dict, packages: dict) -> list[dict]:
    findings: list[dict] = []
    for name, entry in vulns.items():
        severity = entry["severity"]
        if severity not in _COUNT_KEYS:
            continue
        roots, missing = _walk(vulns, name, set())
        if not roots and not missing:
            missing = [str(entry.get("via", []))]
        seen: set[tuple[str, str]] = set()
        for root in roots:
            key = (root["package"], root["id"].upper())
            if key in seen:
                continue
            seen.add(key)
            root_entry = vulns[root["package"]]
            findings.append(
                {
                    **root,
                    "severity": severity,
                    "affectedPackage": name,
                    "via": name if name != root["package"] else "",
                    "version": _version(root["package"], root_entry, packages),
                    "nodes": root_entry.get("nodes", []),
                }
            )
        for via in dict.fromkeys(missing):
            findings.append(
                {
                    "package": name,
                    "id": None,
                    "via": via,
                    "severity": severity,
                    "affectedPackage": name,
                    "version": _version(name, entry, packages),
                    "nodes": entry.get("nodes", []),
                }
            )
    return findings


def _npm_executable() -> str:
    npm = shutil.which("npm") or shutil.which("npm.cmd")
    if not npm:
        raise ValueError("npm not found on PATH (required for quality:deps)")
    return npm


def _run_npm_audit() -> dict:
    command = [_npm_executable(), "audit", "--json"]
    proc = subprocess.run(
        command,
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    _RAW_DETAILS["npm"] = {"command": command, "exit_code": proc.returncode}
    raw = proc.stdout.strip() or proc.stderr.strip()
    if not raw:
        _write_raw(
            "npm",
            status="ERROR",
            error="npm audit produced no JSON",
            policy=_policy("npm"),
        )
        raise ValueError(
            f"npm audit produced no JSON (exit {proc.returncode}): {proc.stderr}"
        )
    try:
        audit = json.loads(raw)
    except json.JSONDecodeError as exc:
        _write_raw(
            "npm",
            status="ERROR",
            error=f"npm audit JSON parse failed: {exc}",
            policy=_policy("npm"),
        )
        raise ValueError(f"npm audit JSON parse failed: {exc}") from exc
    _write_raw("npm", audit, policy=_policy("npm"))
    try:
        _validate_audit(audit)
    except ValueError as exc:
        _write_raw("npm", audit, status="ERROR", error=str(exc), policy=_policy("npm"))
        raise
    if proc.returncode not in (0, 1):
        _write_raw(
            "npm",
            audit,
            status="ERROR",
            error=f"npm audit execution failed (exit {proc.returncode})",
            policy=_policy("npm"),
        )
        raise ValueError(
            f"npm audit execution failed (exit {proc.returncode}): {proc.stderr}"
        )
    return audit


def pip_findings(payload: dict) -> list[dict]:
    if not isinstance(payload, dict) or not isinstance(
        payload.get("dependencies"), list
    ):
        raise ValueError("pip-audit JSON missing dependencies list")
    findings: list[dict] = []
    for dep in payload["dependencies"]:
        if not isinstance(dep, dict):
            raise ValueError("pip-audit invalid dependency entry")
        if dep.get("skip_reason"):
            continue
        if not isinstance(dep.get("name"), str) or not isinstance(
            dep.get("vulns"), list
        ):
            raise ValueError("pip-audit invalid vulnerability evidence")
        for vuln in dep["vulns"]:
            if (
                not isinstance(vuln, dict)
                or not isinstance(vuln.get("id"), str)
                or not vuln["id"].strip()
            ):
                raise ValueError("pip-audit vulnerability missing advisory id")
            findings.append(
                {
                    "package": dep["name"],
                    "id": vuln["id"].strip(),
                    "via": "",
                    "version": dep.get("version", ""),
                }
            )
    return findings


def record_pip_payload(payload: dict) -> int:
    try:
        findings = pip_findings(payload)
    except ValueError as exc:
        _write_raw(
            "pip", payload, status="ERROR", error=str(exc), policy=_policy("pip")
        )
        raise
    _write_raw("pip", payload, policy=_policy("pip"))
    write_deps_findings(findings)
    return 0


def record_pip_stdin() -> int:
    return record_pip_payload(json.loads(sys.stdin.read()))


def _run_pip_audit() -> int:
    raw = json.loads(ALLOWLIST_PATH.read_text(encoding="utf-8"))
    argv = [sys.executable, "-m", "pip_audit", "--skip-editable", "--format", "json"]
    for item in raw.get("pip", {}).get("ignore_vulns", []):
        advisory = item.get("id") if isinstance(item, dict) else item
        if not isinstance(advisory, str) or not advisory.strip():
            raise ValueError("pip audit ignore entry missing id")
        argv += ["--ignore-vuln", advisory]
    proc = subprocess.run(argv, cwd=ROOT, capture_output=True, text=True, check=False)
    _RAW_DETAILS["pip"] = {"command": argv, "exit_code": proc.returncode}
    try:
        payload = json.loads(proc.stdout)
        _write_raw("pip", payload, policy=_policy("pip"))
        findings = pip_findings(payload)
    except (ValueError, TypeError) as exc:
        _write_raw(
            "pip",
            status="ERROR",
            error=f"pip-audit execution failed: {exc}",
            policy=_policy("pip"),
        )
        raise ValueError(
            f"pip-audit execution failed: {proc.stderr.strip() or exc}"
        ) from exc
    if proc.returncode and not findings:
        _write_raw(
            "pip",
            payload,
            status="ERROR",
            error=f"pip-audit execution failed (exit {proc.returncode})",
            policy=_policy("pip"),
        )
        raise ValueError(
            f"pip-audit execution failed (exit {proc.returncode}): {proc.stderr.strip()}"
        )
    write_deps_findings(findings)
    if findings:
        print(f"pip-audit found {len(findings)} vulnerabilities", file=sys.stderr)
        return proc.returncode or 1
    print("pip-audit passed")
    return 0


def _label(hit: dict) -> str:
    version = f"@{hit['version']}" if hit.get("version") else ""
    return f"{hit['package']}{version} {hit['id']}"


def _npm_gate() -> int:
    allowlist = _load_allowlist()
    audit = _run_npm_audit()
    _write_raw("npm", audit, policy=_policy("npm", allowlist))
    try:
        vulns = _validate_audit(audit)
    except ValueError as exc:
        _write_raw(
            "npm",
            audit,
            status="ERROR",
            error=str(exc),
            policy=_policy("npm", allowlist),
        )
        raise
    counts = {
        key: sum(entry["severity"] == key for entry in vulns.values())
        for key in _COUNT_KEYS
    }
    findings = _collect_findings(vulns, _lock_packages())
    unwaived: list[dict] = []
    reported = [hit for hit in findings if hit["severity"] in REPORT_SEVERITIES]
    seen: set[str] = set()
    for hit in findings:
        if hit["severity"] not in FAIL_SEVERITIES:
            continue
        advisory = (hit["id"] or "").upper()
        if advisory:
            seen.add(advisory)
        exception = allowlist.get(advisory)
        if exception and exception["package"] != hit["package"]:
            raise ValueError(f"npm allowlist package mismatch: {advisory}")
        if exception:
            print(f"npm critical allowlisted: {_label(hit)}: {exception['reason']}")
        else:
            unwaived.append(hit)
    unused = sorted(set(allowlist) - seen)
    error = (
        f"unused npm audit allowlist entries: {', '.join(unused)}" if unused else None
    )
    if error:
        print(error, file=sys.stderr)
    for hit in reported:
        label = _label(hit) if hit["id"] else f"{hit['package']} (no GHSA id)"
        print(f"{hit['severity']} {hit['affectedPackage']} via {label}")
    unique: dict[tuple, dict] = {}
    for hit in unwaived:
        key = (hit["package"], hit["id"], hit["via"] if not hit["id"] else "")
        unique[key] = hit
    unwaived = list(unique.values())
    for hit in unwaived:
        if hit["id"]:
            print(f"unexpected npm critical advisory: {_label(hit)}", file=sys.stderr)
        else:
            print(
                f"critical npm finding without GHSA id: package={hit['package']} via={hit['via']!r}",
                file=sys.stderr,
            )
    ok = not unwaived and not error
    write_deps_findings(unwaived, error=error)
    _write_summary(counts, ok=ok, reported=reported, error=error)
    print(
        f"{'PASS' if ok else 'FAIL'}, {counts['critical']} critical, {counts['high']} high reported"
    )
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--all", action="store_true", help="Audit pip dependencies before npm."
    )
    group.add_argument(
        "--record-pip", action="store_true", help="Record pip-audit JSON from stdin."
    )
    args = parser.parse_args([] if argv is None else argv)
    _RAW_DETAILS.clear()
    _write_raw("npm", status="NOT_RUN", error="npm audit has not run")
    _write_raw("pip", status="NOT_RUN", error="pip audit has not run")
    write_deps_findings([])
    _write_summary(None, ok=False)
    try:
        if args.record_pip:
            return record_pip_stdin()
        if args.all and (status := _run_pip_audit()):
            return status
        return _npm_gate()
    except (OSError, ValueError, TypeError, KeyError, SystemExit) as exc:
        error = f"Dependency audit failed: {exc}"
        write_deps_findings([], error=error)
        _write_summary(None, ok=False, error=error)
        print(error, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
