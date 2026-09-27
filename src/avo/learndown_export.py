"""Export provider-scoped learndown entries under providers/<slug>/learndowns/."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path
from typing import Any

from avo import avo_state
from avo.paths import repo_root
from avo.project_inventory import load_project
from avo.timeline.contracts import (
    content_hash,
    document_hash_excluding,
    validate_document,
)
from avo.timeline.review_study import build_rework_report
from avo.timeline.store import atomic_write_json, write_immutable_json

SCHEMA_VERSION = 1
INDEX_NAME = "index.json"
LEARNDOWN_JSON = "learndown.json"
LEARNDOWN_MD = "learndown.md"
WRAP_DRAFT_JSON = "wrap.draft.json"
WRAP_DRAFT_MD = "wrap.draft.md"
WRAP_FINAL_JSON = "wrap.json"
WRAP_FINAL_MD = "wrap.md"
EDITLOG_LOCK = "EDITLOG.md"
TIMELINE_LEARNING_DIR = "timeline-learning"
TIMELINE_LEARNING_INDEX = "index.json"


def _sanitize_learning_text(value: Any) -> str:
    text = str(value or "").strip()
    text = re.sub(r"(?i)\b[A-Z]:[\\/][^\s]+", "[project-path]", text)
    text = re.sub(
        r"(?<!:)\/(?:home|mnt|Users|private|tmp)\/[^\s]+", "[project-path]", text
    )
    text = re.sub(
        r"(?i)\b(api[_-]?key|token|secret|password)\s*[:=]\s*\S+",
        r"\1=[redacted]",
        text,
    )
    return text or "Unspecified"


def _sanitize_learning_value(value: Any) -> Any:
    if isinstance(value, str):
        return _sanitize_learning_text(value)
    if isinstance(value, list):
        return [_sanitize_learning_value(item) for item in value]
    if isinstance(value, dict):
        return {
            str(key): "[redacted]"
            if str(key).lower() in {"api_key", "apikey", "token", "secret", "password"}
            else _sanitize_learning_value(item)
            for key, item in value.items()
        }
    return value


def _sanitized_record(
    *,
    record_id: str,
    summary: Any,
    status: str | None = None,
    evidence_classes: list[str] | None = None,
    impact: dict[str, Any] | None = None,
    recurrence: int = 0,
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "id": record_id,
        "summary": _sanitize_learning_text(summary),
        "evidenceClasses": sorted(set(evidence_classes or [])),
        "impact": _sanitize_learning_value(dict(impact or {})),
        "recurrence": recurrence,
    }
    if status is not None:
        record["status"] = status
    return record


def build_timeline_learning_snapshot(
    *,
    ledger: dict[str, Any],
    candidate_snapshot_hash: str,
    status: str,
    master_fingerprint: dict[str, Any] | None = None,
    reconstruction_bundle_hash: str | None = None,
    prevention_rules: list[dict[str, Any]] | None = None,
    technique_candidates: list[dict[str, Any]] | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    """Build one sanitized immutable learning snapshot from complete history."""
    if status not in {"draft", "final"}:
        raise ValueError("timeline learning status must be draft or final")
    if status == "final" and master_fingerprint is None:
        raise ValueError("final timeline learning requires the approved master")
    report = build_rework_report(ledger)
    decisions = [
        _sanitized_record(
            record_id=str(item["decisionId"]),
            summary=item.get("statement"),
            status=str(item.get("status") or "unknown"),
            evidence_classes=[
                str(ref.get("kind") or "unspecified")
                for ref in item.get("evidenceRefs") or []
            ],
            impact={"scope": item.get("scope") or {}},
        )
        for item in ledger.get("decisions") or []
    ]
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in report["items"]:
        group_id = str(item.get("reworkGroupId") or item.get("reworkId"))
        grouped.setdefault(group_id, []).append(item)
    rework_groups = []
    capability_gaps = []
    uncertainties = []
    for group_id, items in sorted(grouped.items()):
        origins = sorted({str(item.get("origin") or "unknown") for item in items})
        rework_groups.append(
            _sanitized_record(
                record_id=group_id,
                summary="; ".join(
                    _sanitize_learning_text(item.get("summary")) for item in items
                ),
                status="active",
                evidence_classes=sorted(
                    {
                        str(ref.get("kind") or "unspecified")
                        for item in items
                        for ref in item.get("evidenceRefs") or []
                    }
                ),
                impact={"origins": origins},
                recurrence=len(items),
            )
        )
        for item in items:
            gap = item.get("capabilityGap")
            if gap:
                capability_gaps.append(
                    _sanitized_record(
                        record_id=str(item["reworkId"]),
                        summary=gap.get("desiredBehavior"),
                        status="candidate",
                        impact={"operation": gap.get("operation")},
                        recurrence=1,
                    )
                )
            if item.get("origin") == "unknown":
                uncertainties.append(
                    _sanitized_record(
                        record_id=str(item["reworkId"]),
                        summary=item.get("summary"),
                        status="unknown",
                        recurrence=1,
                    )
                )
    for decision in ledger.get("decisions") or []:
        if decision.get("status") == "awaiting-human":
            uncertainties.append(
                _sanitized_record(
                    record_id=str(decision["decisionId"]),
                    summary=decision.get("statement"),
                    status="awaiting-human",
                )
            )
    rules = [
        _sanitized_record(
            record_id=str(item.get("id") or f"rule-{index:04d}"),
            summary=item.get("summary"),
            status=str(item.get("status") or "candidate"),
            evidence_classes=list(item.get("evidenceClasses") or []),
            impact=dict(item.get("impact") or {}),
            recurrence=int(item.get("recurrence") or 0),
        )
        for index, item in enumerate(prevention_rules or [], start=1)
    ]
    techniques = [
        _sanitized_record(
            record_id=str(item.get("id") or f"technique-{index:04d}"),
            summary=item.get("summary"),
            status=str(item.get("status") or "candidate"),
            impact=dict(item.get("impact") or {}),
        )
        for index, item in enumerate(technique_candidates or [], start=1)
    ]
    master = None
    if master_fingerprint is not None:
        master = {
            "sha256": str(master_fingerprint["sha256"]),
            "sizeBytes": int(master_fingerprint["sizeBytes"]),
        }
    identity = content_hash(
        {
            "videoId": ledger["videoId"],
            "ledgerHash": ledger["ledgerHash"],
            "candidateSnapshotHash": candidate_snapshot_hash,
            "status": status,
            "master": master,
        }
    )
    snapshot = {
        "schemaVersion": "1.0.0",
        "snapshotId": f"timeline-learning-{identity[:16]}",
        "videoId": str(ledger["videoId"]),
        "provider": str(ledger["provider"]),
        "status": status,
        "masterFingerprint": master,
        "candidateSnapshotHash": candidate_snapshot_hash,
        "iterationLedgerHash": str(ledger["ledgerHash"]),
        "reconstructionBundleHash": reconstruction_bundle_hash,
        "decisionOutcomes": decisions,
        "reworkGroups": rework_groups,
        "preventionRules": rules,
        "capabilityGaps": capability_gaps,
        "costSignals": {
            "iterations": len(ledger.get("iterations") or []),
            "reworkGroups": report["reworkGroupCount"],
            **report["costSignals"],
        },
        "techniqueCandidates": techniques,
        "uncertainties": uncertainties,
        "createdAt": created_at
        or str(
            (ledger.get("iterations") or [{}])[-1].get("createdAt")
            or "1970-01-01T00:00:00Z"
        ),
        "snapshotHash": "",
    }
    snapshot["snapshotHash"] = document_hash_excluding(snapshot, "snapshotHash")
    validate_document(snapshot, "avo.timeline-learning.schema.json")
    return snapshot


def export_timeline_learning_snapshot(
    entry_dir: Path, snapshot: dict[str, Any]
) -> Path:
    """Publish immutable history and atomically advance one lightweight index."""
    validate_document(snapshot, "avo.timeline-learning.schema.json")
    directory = Path(entry_dir) / TIMELINE_LEARNING_DIR
    snapshot_path = directory / f"{snapshot['snapshotId']}.json"
    write_immutable_json(snapshot_path, snapshot)
    index_path = directory / TIMELINE_LEARNING_INDEX
    if index_path.is_file():
        index = json.loads(index_path.read_text(encoding="utf-8"))
    else:
        index = {"schemaVersion": "1.0.0", "snapshots": []}
    reference = {
        "snapshotId": snapshot["snapshotId"],
        "snapshotHash": snapshot["snapshotHash"],
        "status": snapshot["status"],
        "path": snapshot_path.name,
    }
    existing = {item["snapshotId"]: item for item in index.get("snapshots") or []}
    if (
        snapshot["snapshotId"] in existing
        and existing[snapshot["snapshotId"]] != reference
    ):
        raise ValueError("timeline learning snapshot identity collision")
    existing[snapshot["snapshotId"]] = reference
    index["snapshots"] = sorted(existing.values(), key=lambda item: item["snapshotId"])
    index["activeSnapshotId"] = snapshot["snapshotId"]
    index["activeSnapshotHash"] = snapshot["snapshotHash"]
    atomic_write_json(index_path, index)
    return snapshot_path


def load_active_timeline_learning(entry_dir: Path) -> dict[str, Any] | None:
    index_path = Path(entry_dir) / TIMELINE_LEARNING_DIR / TIMELINE_LEARNING_INDEX
    if not index_path.is_file():
        return None
    index = json.loads(index_path.read_text(encoding="utf-8"))
    active_id = index.get("activeSnapshotId")
    reference = next(
        (
            item
            for item in index.get("snapshots") or []
            if item["snapshotId"] == active_id
        ),
        None,
    )
    if reference is None:
        raise ValueError("timeline learning index has no active snapshot")
    snapshot = json.loads(
        (index_path.parent / reference["path"]).read_text(encoding="utf-8")
    )
    validate_document(snapshot, "avo.timeline-learning.schema.json")
    if snapshot["snapshotHash"] != reference["snapshotHash"]:
        raise ValueError("timeline learning active snapshot hash mismatch")
    return snapshot


def _slugify(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    value = re.sub(r"-{2,}", "-", value)
    return value.strip("-")


def build_entry_id(
    master_basename: str,
    *,
    title: str = "",
    generated_at: str = "",
) -> str:
    """Build ``YYYYMMDD-topic-slug`` from master basename or title."""
    date_match = re.match(r"^(\d{8})", master_basename)
    date = date_match.group(1) if date_match else ""
    if not date and generated_at:
        date = generated_at[:10].replace("-", "")

    body = master_basename
    if date and body.startswith(date):
        body = body[len(date) :].lstrip("-")
    body = re.sub(r"-master-.*$", "", body)
    if not body:
        body = _slugify(title or master_basename)
    body = _slugify(body) or "untitled"
    return f"{date}-{body}" if date else body


def provider_learndowns_dir(provider: str, *, root: Path | None = None) -> Path:
    return (root or repo_root()) / "providers" / provider / "learndowns"


def build_learndown_payload(wrap_payload: dict[str, Any]) -> dict[str, Any]:
    provider = str(wrap_payload.get("provider") or "").strip()
    master = str(wrap_payload.get("masterBasename") or "")
    generated_at = str(wrap_payload.get("generatedAt") or avo_state.now_iso())
    entry_id = build_entry_id(
        master,
        title=str(wrap_payload.get("title") or ""),
        generated_at=generated_at,
    )
    learning = dict(wrap_payload.get("learning") or {})
    ai_memory = str(learning.get("aiMemory") or "skipped")
    if ai_memory == "skipped":
        ai_memory = "exported"

    raw_dir = Path(str(wrap_payload.get("rawDir") or "."))
    space = wrap_payload.get("space") or {}
    status = str(wrap_payload.get("status") or "draft")

    wrap_paths = {
        "draftJson": str((raw_dir / "avo.wrap.draft.json").resolve()),
        "draftMd": str((raw_dir / "avo.wrap.draft.md").resolve()),
        "finalJson": str((raw_dir / "avo.wrap.json").resolve()),
        "finalMd": str((raw_dir / "avo.wrap.md").resolve()),
    }

    return {
        "schemaVersion": SCHEMA_VERSION,
        "entryId": entry_id,
        "provider": provider,
        "masterBasename": master,
        "rawDir": str(raw_dir.resolve()),
        "title": str(wrap_payload.get("title") or ""),
        "status": status,
        "generatedAt": generated_at,
        "sessionId": str(wrap_payload.get("sessionId") or ""),
        "summary": str(wrap_payload.get("summary") or ""),
        "space": {
            "preCleanupProjectBytes": int(space.get("preCleanupProjectBytes", 0)),
            "deleteCandidateBytes": int(space.get("deleteCandidateBytes", 0)),
            "preservedBytes": int(space.get("preservedBytes", 0)),
            "freedBytes": space.get("freedBytes"),
        },
        "learning": {
            "aiMemory": ai_memory,
            "note": str(learning.get("note") or ""),
        },
        "wrapPaths": wrap_paths,
        "editlogLock": None,
    }


def render_learndown_markdown(payload: dict[str, Any]) -> str:
    lines = [
        f"# Provider learndown — {payload.get('entryId', '')}",
        "",
        f"- **Provider:** {payload.get('provider', '')}",
        f"- **Master:** `{payload.get('masterBasename', '')}`",
        f"- **Status:** {payload.get('status', '')}",
        f"- **Generated:** {payload.get('generatedAt', '')}",
        f"- **Raw dir:** `{payload.get('rawDir', '')}`",
        "",
    ]
    summary = str(payload.get("summary") or "").strip()
    if summary:
        lines.extend(["## Summary", "", summary, ""])
    learning = payload.get("learning") or {}
    note = str(learning.get("note") or "").strip()
    if note:
        lines.extend(["## Learning note", "", note, ""])
    lock = payload.get("editlogLock")
    if lock:
        lines.extend(
            [
                "## EDITLOG lock",
                "",
                (
                    f"Snapshot `{lock}` in this entry (copied at learndown; "
                    "footage-root EDITLOG.md may still refresh)."
                ),
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def _load_index(index_path: Path, provider: str) -> dict[str, Any]:
    if index_path.is_file():
        try:
            data = json.loads(index_path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except (OSError, ValueError):
            pass
    return {
        "schemaVersion": SCHEMA_VERSION,
        "provider": provider,
        "updatedAt": avo_state.now_iso(),
        "entries": [],
    }


def _upsert_index_entry(index: dict[str, Any], payload: dict[str, Any]) -> None:
    entries = list(index.get("entries") or [])
    entry = {
        "entryId": payload["entryId"],
        "masterBasename": payload["masterBasename"],
        "rawDir": payload["rawDir"],
        "title": payload.get("title") or "",
        "status": payload["status"],
        "generatedAt": payload["generatedAt"],
    }
    entries = [e for e in entries if e.get("entryId") != entry["entryId"]]
    entries.append(entry)
    entries.sort(key=lambda e: (e.get("generatedAt", ""), e.get("entryId", "")))
    index["entries"] = entries
    index["updatedAt"] = avo_state.now_iso()
    index["provider"] = payload["provider"]


def _copy_if_exists(source: Path, dest: Path) -> None:
    if source.is_file():
        shutil.copy2(source, dest)


def _copy_editlog_lock_once(raw_dir: Path, entry_dir: Path) -> bool:
    """Copy footage-root EDITLOG into the entry. First copy is the lock."""
    dest = entry_dir / EDITLOG_LOCK
    if dest.is_file():
        return True
    source = raw_dir / "EDITLOG.md"
    if not source.is_file():
        return False
    shutil.copy2(source, dest)
    return True


def export_provider_learndown(
    wrap_payload: dict[str, Any],
    *,
    root: Path | None = None,
) -> Path | None:
    """Write provider learndown entry. Returns entry dir or None when skipped."""
    payload = build_learndown_payload(wrap_payload)
    provider = payload["provider"]
    if not provider or provider == "unknown":
        print(
            f"learndown export skipped: unknown provider for {payload['masterBasename']}",
            file=sys.stderr,
        )
        return None

    base = provider_learndowns_dir(provider, root=root)
    entry_dir = base / payload["entryId"]
    entry_dir.mkdir(parents=True, exist_ok=True)

    raw_dir = Path(payload["rawDir"])
    status = payload["status"]
    payload["editlogLock"] = (
        EDITLOG_LOCK if _copy_editlog_lock_once(raw_dir, entry_dir) else None
    )

    (entry_dir / LEARNDOWN_JSON).write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (entry_dir / LEARNDOWN_MD).write_text(
        render_learndown_markdown(payload),
        encoding="utf-8",
    )

    _copy_if_exists(raw_dir / "avo.wrap.draft.json", entry_dir / WRAP_DRAFT_JSON)
    _copy_if_exists(raw_dir / "avo.wrap.draft.md", entry_dir / WRAP_DRAFT_MD)
    if status == "final":
        _copy_if_exists(raw_dir / "avo.wrap.json", entry_dir / WRAP_FINAL_JSON)
        _copy_if_exists(raw_dir / "avo.wrap.md", entry_dir / WRAP_FINAL_MD)

    index_path = base / INDEX_NAME
    index = _load_index(index_path, provider)
    _upsert_index_entry(index, payload)
    index_path.write_text(
        json.dumps(index, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    print(f"provider learndown: {entry_dir}")
    return entry_dir


def _resolve_backfill_provider(
    payload: dict[str, Any],
    *,
    override: str = "",
) -> str:
    if override.strip():
        return override.strip()
    provider = str(payload.get("provider") or "").strip()
    if provider and provider != "unknown":
        return provider
    raw_dir = Path(str(payload.get("rawDir") or ""))
    project = load_project(raw_dir)
    resolved = str(project.get("provider") or "").strip()
    if resolved:
        return resolved
    return provider or "unknown"


def _cmd_backfill(args: argparse.Namespace) -> int:
    wrap_path = Path(args.wrap_json)
    payload = json.loads(wrap_path.read_text(encoding="utf-8"))
    provider = _resolve_backfill_provider(payload, override=args.provider or "")
    if provider and provider != str(payload.get("provider") or ""):
        payload = dict(payload)
        payload["provider"] = provider
    entry = export_provider_learndown(payload, root=args.root)
    return 0 if entry is not None else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_backfill = sub.add_parser("backfill", help="Export from an existing wrap JSON.")
    p_backfill.add_argument("--wrap-json", type=Path, required=True)
    p_backfill.add_argument("--root", type=Path, default=None)
    p_backfill.add_argument(
        "--provider",
        default="",
        help="Override provider slug (defaults to wrap JSON or avo.project.json).",
    )
    p_backfill.set_defaults(func=_cmd_backfill)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
