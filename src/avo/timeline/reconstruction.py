"""Verified compact reconstruction bundle for cleanup and archival."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .contracts import content_hash, file_fingerprint, validate_document
from .store import atomic_write_json, now_iso


class ReconstructionError(RuntimeError):
    pass


def _entry(raw_dir: Path, path: Path, role: str) -> dict[str, Any]:
    path = Path(path).resolve()
    if not path.is_file():
        raise ReconstructionError(f"required reconstruction file missing: {path}")
    fingerprint = file_fingerprint(path)
    return {
        "path": path.relative_to(raw_dir.resolve()).as_posix(),
        "sha256": fingerprint["sha256"],
        "sizeBytes": fingerprint["sizeBytes"],
        "role": role,
    }


def _raw_sources(raw_dir: Path) -> list[Path]:
    raw_root = raw_dir / "raw"
    if raw_root.is_dir():
        return sorted(path for path in raw_root.rglob("*") if path.is_file())
    excluded = {"avo.project.json", "EDITLOG.md", "SOURCE-LOG.md"}
    return sorted(
        path for path in raw_dir.iterdir()
        if path.is_file() and path.name not in excluded and not path.name.startswith(".")
    )


def build_reconstruction_bundle(
    workspace: Any,
    *,
    master_basename: str,
    actor: str,
) -> dict[str, Any]:
    raw_dir = workspace.raw_dir.resolve()
    master_candidates = sorted((raw_dir / "edit" / "masters").glob(f"{master_basename}.*"))
    master_candidates = [path for path in master_candidates if path.is_file()]
    if not master_candidates:
        raise ReconstructionError("final master is missing")
    master = master_candidates[0]
    transcript = raw_dir / "edit" / "transcripts" / f"{master_basename}.json"
    if not transcript.is_file():
        raise ReconstructionError("final master JSON transcript is missing")
    transcript_payload = json.loads(transcript.read_text(encoding="utf-8"))
    master_hash = file_fingerprint(master)["sha256"]
    if (transcript_payload.get("source") or {}).get("sha256") != master_hash:
        raise ReconstructionError("final transcript is not bound to exact master bytes")

    canonical = []
    graph_files: list[dict[str, Any]] = []
    for artifact_type in ("cmap", "bmap", "tracks", "animation", "sync-map"):
        store = workspace.store(artifact_type)
        index = store.load_index()
        index_entry = _entry(raw_dir, store.path, f"{artifact_type}-index")
        canonical.append(index_entry)
        graph_files.append(index_entry)
        for ref in index["revisionRefs"]:
            graph_files.append(_entry(raw_dir, workspace.timeline_dir / ref["path"], f"{artifact_type}-revision"))
        for ref in index["eventRefs"]:
            graph_files.append(_entry(raw_dir, workspace.timeline_dir / ref["path"], f"{artifact_type}-event"))

    for optional in (
        workspace.timeline_dir / "pipeline-run.json",
        workspace.timeline_dir / "projection.json",
        workspace.timeline_dir / "migration.json",
        workspace.raw_dir / "edit" / "delivery-manifest.json",
    ):
        if optional.is_file():
            graph_files.append(_entry(raw_dir, optional, "timeline-state"))

    review_entries = []
    if workspace.review_dir.is_dir():
        for path in sorted(workspace.review_dir.rglob("review.json")):
            review_entries.append(_entry(raw_dir, path, "review-evidence"))
        for path in sorted(workspace.review_dir.rglob("approval-gate.md")):
            review_entries.append(_entry(raw_dir, path, "review-projection"))
    graph_files.extend(review_entries)

    raw_entries = [_entry(raw_dir, path, "raw-source") for path in _raw_sources(raw_dir)]
    if not raw_entries:
        raise ReconstructionError("raw source inventory is empty")
    master_entry = _entry(raw_dir, master, "final-master")
    transcript_entry = _entry(raw_dir, transcript, "final-transcript")
    files_by_path = {
        item["path"]: item
        for item in [*raw_entries, master_entry, transcript_entry, *graph_files]
    }
    body = {
        "schemaVersion": "1.0.0",
        "videoId": workspace.video_id,
        "createdAt": now_iso(),
        "master": master_entry,
        "finalTranscript": transcript_entry,
        "rawSources": raw_entries,
        "canonicalArtifacts": canonical,
        "reviewEvidence": review_entries,
        "files": [files_by_path[key] for key in sorted(files_by_path)],
    }
    body["bundleSha256"] = content_hash(body)
    validate_document(body, "avo.reconstruction-bundle.schema.json")
    path = workspace.timeline_dir / "reconstruction-bundle.json"
    atomic_write_json(path, body)
    return body


def verify_reconstruction_bundle(raw_dir: Path, bundle_path: Path | None = None) -> dict[str, Any]:
    raw_dir = Path(raw_dir).resolve()
    bundle_path = Path(bundle_path or raw_dir / "edit" / "timeline" / "reconstruction-bundle.json")
    try:
        bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ReconstructionError(f"cannot load reconstruction bundle: {error}") from error
    validate_document(bundle, "avo.reconstruction-bundle.schema.json")
    expected = bundle["bundleSha256"]
    actual = content_hash({key: value for key, value in bundle.items() if key != "bundleSha256"})
    if expected != actual:
        raise ReconstructionError("reconstruction bundle hash mismatch")
    for entry in bundle["files"]:
        path = raw_dir / entry["path"]
        if not path.is_file():
            raise ReconstructionError(f"reconstruction file missing: {entry['path']}")
        current = file_fingerprint(path)
        if current["sha256"] != entry["sha256"] or current["sizeBytes"] != entry["sizeBytes"]:
            raise ReconstructionError(f"reconstruction file changed: {entry['path']}")
    master = raw_dir / bundle["master"]["path"]
    transcript = json.loads((raw_dir / bundle["finalTranscript"]["path"]).read_text(encoding="utf-8"))
    if (transcript.get("source") or {}).get("sha256") != file_fingerprint(master)["sha256"]:
        raise ReconstructionError("reconstruction final transcript/master binding is stale")
    return bundle
