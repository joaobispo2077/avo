#!/usr/bin/env python3
"""Run one quality command and bind its outcome to its saved evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import signal
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = 1


class GateInterrupted(Exception):
    def __init__(self, signum: int) -> None:
        self.signum = signum


def _interrupted(signum: int, _frame: object) -> None:
    raise GateInterrupted(signum)


def _path(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def _digest(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def source_fingerprint() -> dict:
    """Fingerprint file contents and paths, including additions and deletions."""
    source = ROOT / "src" / "avo"
    if not source.is_dir():
        return {"sha256": None, "files": None, "error": "src/avo is unavailable"}
    try:
        files = []
        for path in sorted(source.rglob("*.py")):
            if not path.resolve().is_relative_to(source.resolve()):
                raise ValueError(f"source path escapes src/avo: {path}")
            files.append(
                {"path": path.relative_to(ROOT).as_posix(), "sha256": _digest(path)}
            )
        digest = hashlib.sha256(
            json.dumps(files, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        return {"sha256": digest, "files": files, "error": None}
    except (OSError, ValueError) as exc:
        return {"sha256": None, "files": None, "error": str(exc)}


def _artifact(path: Path, started_ns: int) -> dict:
    record = {"path": _path(path), "sha256": None, "bytes": None, "reason": None}
    try:
        if not path.is_file():
            record["reason"] = "artifact was not produced"
            return record
        stat = path.stat()
        record.update(sha256=_digest(path), bytes=stat.st_size)
        if stat.st_mtime_ns < started_ns:
            record["reason"] = "artifact predates command"
    except OSError as exc:
        record["reason"] = str(exc)
    return record


def _tee(chunk: bytes) -> None:
    stream = getattr(sys.stdout, "buffer", None)
    if stream is not None:
        stream.write(chunk)
        stream.flush()
    else:
        sys.stdout.write(chunk.decode("utf-8", errors="replace"))
        sys.stdout.flush()


def _evidence_path(raw: str, artifact_root: Path | None) -> Path:
    path = Path(raw)
    if artifact_root is None:
        return path if path.is_absolute() else ROOT / path
    normalized = raw.replace("\\", "/")
    if normalized.startswith("/") or (
        path.is_absolute()
        or re.match(r"^[A-Za-z]:", raw)
        or ".." in normalized.split("/")
    ):
        raise ValueError("gate evidence path escapes artifact root")
    prefix = "reports/quality/"
    if not normalized.startswith(prefix):
        raise ValueError("gate evidence path must be under reports/quality")
    target = (artifact_root / normalized[len(prefix) :]).resolve()
    if not target.is_relative_to(artifact_root.resolve()):
        raise ValueError("gate evidence path escapes artifact root")
    return target


def _validate_receipt(
    receipt: dict,
    *,
    sha: str,
    run_id: str,
    gate: str | None,
    artifact_root: Path | None,
) -> None:
    if receipt.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unsupported gate receipt schema")
    if receipt.get("sha") != sha or receipt.get("run_id") != run_id:
        raise ValueError("gate receipt provenance mismatch")
    if gate is not None and receipt.get("gate") != gate:
        raise ValueError("gate receipt key mismatch")
    code = receipt.get("exit_code")
    status = receipt.get("status")
    if status not in {"PASS", "FAIL", "ERROR", "CANCELLED"}:
        raise ValueError("invalid gate receipt status")
    if status == "PASS" and (type(code) is not int or code != 0):
        raise ValueError("passing gate receipt requires exit code 0")
    if status == "FAIL" and (type(code) is not int or code == 0):
        raise ValueError("failing gate receipt requires a nonzero exit code")
    if status in {"ERROR", "CANCELLED"} and code == 0:
        raise ValueError("incomplete gate receipt cannot have exit code 0")
    if not isinstance(receipt.get("log"), dict) or receipt["log"].get("reason"):
        raise ValueError("gate log is unavailable")
    records = [receipt.get("log"), *receipt.get("artifacts", [])]
    for record in records:
        if not isinstance(record, dict) or not isinstance(record.get("path"), str):
            raise ValueError("invalid gate evidence path")
        target = _evidence_path(record["path"], artifact_root)
        if record.get("sha256") is None and record.get("reason"):
            continue
        if not target.is_file() or _digest(target) != record.get("sha256"):
            raise ValueError(f"gate evidence hash mismatch: {record['path']}")
        if target.stat().st_size != record.get("bytes"):
            raise ValueError(f"gate evidence size mismatch: {record['path']}")


def validate_receipt(
    path: Path,
    *,
    sha: str,
    run_id: str,
    gate: str | None = None,
    artifact_root: Path | None = None,
) -> dict:
    """Validate identity and hashes, optionally within downloaded evidence."""
    receipt = None
    try:
        receipt = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(receipt, dict):
            raise ValueError("gate receipt must be an object")
        _validate_receipt(
            receipt, sha=sha, run_id=run_id, gate=gate, artifact_root=artifact_root
        )
    except (OSError, ValueError, TypeError, KeyError) as exc:
        return {"valid": False, "reason": str(exc), "receipt": receipt}
    return {"valid": True, "reason": "", "receipt": receipt}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gate", required=True)
    parser.add_argument("--out-dir", type=Path, default=ROOT / "reports/quality/gates")
    parser.add_argument("--sha", default=os.environ.get("GITHUB_SHA", ""))
    parser.add_argument("--run-id", default=os.environ.get("GITHUB_RUN_ID", ""))
    parser.add_argument("--artifact", action="append", type=Path, default=[])
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    if not re.fullmatch(r"[a-z][a-z0-9-]*", args.gate):
        parser.error(
            "gate must be a lowercase key containing letters, digits or hyphens"
        )
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        parser.error("a command is required after --")
    if not args.sha or not args.run_id:
        parser.error("sha and run-id are required")
    if not args.out_dir.is_absolute():
        args.out_dir = ROOT / args.out_dir
    directory = args.out_dir / args.gate
    directory.mkdir(parents=True, exist_ok=True)
    log_path = directory / "gate.log"
    started_at = datetime.now(UTC).isoformat()
    started_ns = time.time_ns()
    started = time.monotonic()
    source_start = source_fingerprint()
    code = None
    error = None
    status = "ERROR"
    proc = None
    interrupted_signal = None
    previous_sigterm = signal.signal(signal.SIGTERM, _interrupted)
    env = {**os.environ, "AVO_QUALITY_SHA": args.sha, "AVO_QUALITY_RUN_ID": args.run_id}
    with log_path.open("wb") as log:
        try:
            proc = subprocess.Popen(
                command,
                cwd=ROOT,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
            assert proc.stdout is not None
            for chunk in iter(proc.stdout.readline, b""):
                log.write(chunk)
                log.flush()
                _tee(chunk)
            code = proc.wait()
            status = "PASS" if code == 0 else "FAIL"
        except (KeyboardInterrupt, GateInterrupted) as exc:
            status = "CANCELLED"
            error = "gate wrapper interrupted"
            interrupted_signal = (
                exc.signum if isinstance(exc, GateInterrupted) else signal.SIGINT
            )
            if proc is not None:
                proc.terminate()
                try:
                    code = proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    code = proc.wait()
        except OSError as exc:
            error = str(exc)
            line = f"quality gate could not run: {error}\n".encode()
            log.write(line)
            _tee(line)
        finally:
            signal.signal(signal.SIGTERM, previous_sigterm)
            if proc is not None and proc.stdout is not None:
                proc.stdout.close()
    source_end = source_fingerprint()
    receipt = {
        "schema_version": SCHEMA_VERSION,
        "gate": args.gate,
        "sha": args.sha,
        "run_id": args.run_id,
        "started_at": started_at,
        "finished_at": datetime.now(UTC).isoformat(),
        "duration_seconds": time.monotonic() - started,
        "command": command,
        "status": status,
        "exit_code": code,
        "signal": interrupted_signal
        or (-code if isinstance(code, int) and code < 0 else None),
        "error": error,
        "log": {
            "path": _path(log_path),
            "sha256": _digest(log_path),
            "bytes": log_path.stat().st_size,
        },
        "artifacts": [
            _artifact(path if path.is_absolute() else ROOT / path, started_ns)
            for path in args.artifact
        ],
        "source": {
            "start": source_start,
            "end": source_end,
            "unchanged": bool(
                source_start["sha256"]
                and source_start["sha256"] == source_end["sha256"]
            ),
        },
    }
    (directory / "gate.json").write_text(
        json.dumps(receipt, indent=2) + "\n", encoding="utf-8"
    )
    if status == "CANCELLED":
        return 128 + interrupted_signal
    if code is None:
        return 1
    return code if code >= 0 else 128 - code


if __name__ == "__main__":
    raise SystemExit(main())
