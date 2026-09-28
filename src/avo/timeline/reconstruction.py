"""Verified compact reconstruction bundle for cleanup and archival."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .contracts import (
    content_hash,
    document_hash_excluding,
    file_fingerprint,
    validate_document,
)
from .store import ArtifactStore, atomic_write_json, now_iso


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
        path
        for path in raw_dir.iterdir()
        if path.is_file()
        and path.name not in excluded
        and not path.name.startswith(".")
    )


def _final_artifacts(raw_dir: Path, master_basename: str) -> tuple[Path, Path]:
    candidates = sorted((raw_dir / "edit" / "masters").glob(f"{master_basename}.*"))
    masters = [path for path in candidates if path.is_file()]
    if not masters:
        raise ReconstructionError("final master is missing")
    master = masters[0]
    transcript = raw_dir / "edit" / "transcripts" / f"{master_basename}.json"
    if not transcript.is_file():
        raise ReconstructionError("final master JSON transcript is missing")
    payload = json.loads(transcript.read_text(encoding="utf-8"))
    if (payload.get("source") or {}).get("sha256") != file_fingerprint(master)[
        "sha256"
    ]:
        raise ReconstructionError("final transcript is not bound to exact master bytes")
    return master, transcript


def _artifact_graph(
    workspace: Any, raw_dir: Path
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    canonical = []
    graph = []
    for artifact_type in ("cmap", "bmap", "tracks", "animation", "sync-map"):
        store = workspace.store(artifact_type)
        index = store.load_index()
        index_entry = _entry(raw_dir, store.path, f"{artifact_type}-index")
        canonical.append(index_entry)
        graph.append(index_entry)
        graph.extend(
            _entry(
                raw_dir,
                workspace.timeline_dir / ref["path"],
                f"{artifact_type}-revision",
            )
            for ref in index["revisionRefs"]
        )
        graph.extend(
            _entry(
                raw_dir,
                workspace.timeline_dir / ref["path"],
                f"{artifact_type}-event",
            )
            for ref in index["eventRefs"]
        )
    return canonical, graph


def _optional_state_entries(workspace: Any, raw_dir: Path) -> list[dict[str, Any]]:
    paths = (
        workspace.timeline_dir / "pipeline-run.json",
        workspace.timeline_dir / "projection.json",
        workspace.timeline_dir / "migration.json",
        workspace.raw_dir / "edit" / "delivery-manifest.json",
    )
    return [_entry(raw_dir, path, "timeline-state") for path in paths if path.is_file()]


def _review_entries(workspace: Any, raw_dir: Path) -> list[dict[str, Any]]:
    if not workspace.review_dir.is_dir():
        return []
    roles = {
        "review.json": "review-evidence",
        "approval-gate.md": "review-projection",
        "approval-manifest.json": "review-projection",
    }
    entries = [
        _entry(raw_dir, path, role)
        for filename, role in roles.items()
        for path in sorted(workspace.review_dir.rglob(filename))
    ]
    referenced: dict[Path, str] = {}
    for review_path in sorted(workspace.review_dir.rglob("review.json")):
        review = json.loads(review_path.read_text(encoding="utf-8"))
        for evidence in review.get("evidence") or []:
            for artifact in evidence.get("artifacts") or []:
                path = Path(str(artifact.get("path") or ""))
                path = path if path.is_absolute() else raw_dir / path
                path = path.resolve()
                try:
                    path.relative_to(workspace.review_dir.resolve())
                except ValueError:
                    continue
                if not path.is_file():
                    raise ReconstructionError(
                        f"referenced review artifact is missing: {path}"
                    )
                actual = file_fingerprint(path)["sha256"]
                expected = str(artifact.get("sha256") or "")
                if expected and expected != actual:
                    raise ReconstructionError(
                        f"referenced review artifact changed: {path}"
                    )
                referenced[path] = actual
    existing = {Path(raw_dir / item["path"]).resolve() for item in entries}
    entries.extend(
        _entry(raw_dir, path, "review-raw-artifact")
        for path in sorted(referenced)
        if path not in existing
    )
    return entries


def _shorts_entries(raw_dir: Path) -> list[dict[str, Any]]:
    from avo.shorts_delivery import preserved_shorts_paths

    return [
        _entry(raw_dir, path, "shorts-preservation")
        for path in preserved_shorts_paths(raw_dir)
    ]


def _json_entries(raw_dir: Path, root: Path, role: str) -> list[dict[str, Any]]:
    if not root.is_dir():
        return []
    return [
        _entry(raw_dir, path, role)
        for path in sorted(root.rglob("*.json"))
        if path.is_file()
    ]


def _lightweight_ancestry_entries(
    workspace: Any, raw_dir: Path
) -> list[dict[str, Any]]:
    return _json_entries(
        raw_dir,
        workspace.timeline_dir / "materializations",
        "ancestry-evidence",
    )


def _iteration_state_groups(
    workspace: Any,
    raw_dir: Path,
    *,
    iteration_ledgers: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    directories = {
        "proofPlans": ("proof-plans", "proof-plan"),
        "candidateSnapshots": ("candidate-snapshots", "candidate-snapshot"),
        "regressionResults": ("regression-results", "regression-result"),
        "generatedAssets": ("generated-assets", "generated-asset"),
        "componentInstances": ("component-instances", "component-instance"),
        "stillExtractionRecords": ("stills", "still-extraction-record"),
        "timelineLearning": ("timeline-learning", "timeline-learning"),
    }
    groups = {
        name: _json_entries(raw_dir, workspace.timeline_dir / dirname, role)
        for name, (dirname, role) in directories.items()
    }
    groups["iterationLedgers"] = iteration_ledgers
    groups["promotionDecisions"] = _json_entries(
        raw_dir,
        workspace.timeline_dir / "promotion-decisions",
        "provider-animation-promotion-decision",
    )
    project_code: list[dict[str, Any]] = []
    for directory in (
        raw_dir / "edit" / "derived" / "components",
        raw_dir / "edit" / "derived" / "provider-components",
    ):
        if not directory.is_dir():
            continue
        project_code.extend(
            _entry(raw_dir, path, "project-component-code")
            for path in sorted(directory.rglob("*"))
            if path.is_file()
        )
    groups["projectComponentCode"] = project_code
    return groups


def _validate_active_candidate_snapshot(
    workspace: Any, candidate_entries: list[dict[str, Any]]
) -> None:
    pipeline_path = workspace.timeline_dir / "pipeline-run.json"
    if not pipeline_path.is_file():
        return
    run = json.loads(pipeline_path.read_text(encoding="utf-8"))
    active_refs = run.get("activeRefs") or {}
    reference = active_refs.get("activeCandidateSnapshot")
    if reference is None:
        return
    stale_keys = {
        "candidatePath",
        "candidateSha256",
        "candidateIdentityHash",
        "cutCandidateSha256",
        "cutCandidateIdentityHash",
        "transcript",
        "materialization",
        "review",
        "reviewIdentityHash",
        "regressionResult",
        "approval",
        "masterSha256",
    }
    if stale_keys & set(active_refs):
        raise ReconstructionError(
            "candidate lifecycle has more than one active reference"
        )
    suffix = f"/{reference['snapshotId']}.json"
    matches = [entry for entry in candidate_entries if entry["path"].endswith(suffix)]
    if len(matches) != 1:
        raise ReconstructionError("active candidate snapshot is missing or ambiguous")
    snapshot_path = workspace.raw_dir / matches[0]["path"]
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    validate_document(snapshot, "avo.candidate-snapshot.schema.json")
    if snapshot.get("snapshotHash") != reference.get(
        "sha256"
    ) or document_hash_excluding(snapshot, "snapshotHash") != reference.get("sha256"):
        raise ReconstructionError("active candidate snapshot reference is stale")


def _iteration_ledger_graph(
    workspace: Any, raw_dir: Path
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    path = workspace.timeline_dir / "iteration-ledger.json"
    if not path.is_file():
        return None, []
    index = ArtifactStore(path).load_index()
    index_entry = _entry(raw_dir, path, "iteration-ledger-index")
    entries = [index_entry]
    entries.extend(
        _entry(
            raw_dir,
            workspace.timeline_dir / ref["path"],
            "iteration-ledger-revision",
        )
        for ref in index["revisionRefs"]
    )
    entries.extend(
        _entry(
            raw_dir,
            workspace.timeline_dir / ref["path"],
            "iteration-ledger-event",
        )
        for ref in index["eventRefs"]
    )
    return index_entry, entries


def build_reconstruction_bundle(
    workspace: Any,
    *,
    master_basename: str,
    actor: str,
) -> dict[str, Any]:
    raw_dir = workspace.raw_dir.resolve()
    master, transcript = _final_artifacts(raw_dir, master_basename)
    canonical, graph_files = _artifact_graph(workspace, raw_dir)
    graph_files.extend(_optional_state_entries(workspace, raw_dir))
    review_entries = _review_entries(workspace, raw_dir)
    graph_files.extend(review_entries)
    graph_files.extend(_shorts_entries(raw_dir))
    ancestry_entries = _lightweight_ancestry_entries(workspace, raw_dir)
    graph_files.extend(ancestry_entries)
    ledger_index, ledger_entries = _iteration_ledger_graph(workspace, raw_dir)
    if ledger_index is not None:
        canonical.append(ledger_index)
    state_groups = _iteration_state_groups(
        workspace,
        raw_dir,
        iteration_ledgers=ledger_entries,
    )
    _validate_active_candidate_snapshot(workspace, state_groups["candidateSnapshots"])
    for entries in state_groups.values():
        graph_files.extend(entries)

    raw_entries = [
        _entry(raw_dir, path, "raw-source") for path in _raw_sources(raw_dir)
    ]
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
        **state_groups,
        "files": [files_by_path[key] for key in sorted(files_by_path)],
    }
    body["bundleSha256"] = content_hash(body)
    validate_document(body, "avo.reconstruction-bundle.schema.json")
    path = workspace.timeline_dir / "reconstruction-bundle.json"
    atomic_write_json(path, body)
    return body


def verify_reconstruction_bundle(
    raw_dir: Path, bundle_path: Path | None = None
) -> dict[str, Any]:
    raw_dir = Path(raw_dir).resolve()
    bundle_path = Path(
        bundle_path or raw_dir / "edit" / "timeline" / "reconstruction-bundle.json"
    )
    try:
        bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ReconstructionError(
            f"cannot load reconstruction bundle: {error}"
        ) from error
    validate_document(bundle, "avo.reconstruction-bundle.schema.json")
    expected = bundle["bundleSha256"]
    actual = content_hash(
        {key: value for key, value in bundle.items() if key != "bundleSha256"}
    )
    if expected != actual:
        raise ReconstructionError("reconstruction bundle hash mismatch")
    for entry in bundle["files"]:
        path = raw_dir / entry["path"]
        if not path.is_file():
            raise ReconstructionError(f"reconstruction file missing: {entry['path']}")
        current = file_fingerprint(path)
        if (
            current["sha256"] != entry["sha256"]
            or current["sizeBytes"] != entry["sizeBytes"]
        ):
            raise ReconstructionError(f"reconstruction file changed: {entry['path']}")
    master = raw_dir / bundle["master"]["path"]
    transcript = json.loads(
        (raw_dir / bundle["finalTranscript"]["path"]).read_text(encoding="utf-8")
    )
    if (transcript.get("source") or {}).get("sha256") != file_fingerprint(master)[
        "sha256"
    ]:
        raise ReconstructionError(
            "reconstruction final transcript/master binding is stale"
        )
    return bundle
