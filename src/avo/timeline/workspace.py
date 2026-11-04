"""Resolve canonical timeline authority and active artifact lineage for a project."""

from __future__ import annotations

import json
import re
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from avo.paths import repo_root

from .contracts import file_fingerprint, validate_document
from .store import (
    ArtifactStore,
    atomic_write_json,
    require_reconciled,
    serialized_timeline,
)

ARTIFACTS = {
    "cmap": "raw-source",
    "bmap": "cmap-output",
    "tracks": "cmap-output",
    "animation": "cmap-output",
    "sync-map": "raw-source",
}


class WorkspaceError(RuntimeError):
    pass


def _learning_active_reference(index, index_path):
    if not isinstance(index, dict):
        raise WorkspaceError(f"provider learning index must be an object: {index_path}")
    snapshots = index.get("snapshots") or []
    if not isinstance(snapshots, list) or any(
        not isinstance(item, dict) for item in snapshots
    ):
        raise WorkspaceError(
            f"provider learning snapshot references are malformed: {index_path}"
        )
    active_id = index.get("activeSnapshotId")
    reference = next(
        (item for item in snapshots if item.get("snapshotId") == active_id), None
    )
    if reference is None or not isinstance(reference.get("path"), str):
        raise WorkspaceError(
            f"provider learning index has no active snapshot: {index_path}"
        )
    return reference


_WSL_MNT_RE = re.compile(r"^/mnt/([a-zA-Z])/(.*)$")


def _wsl_mnt_text(declared: str | Path) -> str:
    text = str(declared).replace("\\", "/")
    if not text.startswith("/") and text.lower().startswith("mnt/"):
        text = "/" + text
    return text


def map_wsl_mnt_path(declared: str | Path, *, platform: str | None = None) -> Path:
    """Map WSL ``/mnt/<letter>/...`` paths to a Windows drive path when on win32."""
    platform = platform or sys.platform
    match = _WSL_MNT_RE.match(_wsl_mnt_text(declared))
    if platform == "win32" and match:
        rest = match.group(2).replace("/", "\\")
        return Path(f"{match.group(1).upper()}:\\{rest}")
    return Path(declared)


def _try_resolve_existing(path: Path, exists_fn: Callable[[Path], bool]) -> Path | None:
    if not exists_fn(path):
        return None
    try:
        if path.exists():
            return path.resolve()
    except OSError:
        pass
    return path


def _missing_raw_dir_error(
    candidate: Path, attempted: list[Path], parent_fallback: Path | None
) -> WorkspaceError:
    tried = "; ".join(str(path) for path in attempted)
    parent_note = (
        f"; project parent {parent_fallback}" if parent_fallback is not None else ""
    )
    return WorkspaceError(
        f"rawDir does not exist: declared/mapped {candidate}{parent_note} (tried: {tried})"
    )


def _declared_candidate(
    project_path: Path | None,
    declared: str | Path,
    *,
    platform: str,
) -> Path:
    candidate = map_wsl_mnt_path(declared, platform=platform)
    mapping_applied = (
        platform == "win32" and _WSL_MNT_RE.match(_wsl_mnt_text(declared)) is not None
    )
    if project_path is not None and not candidate.is_absolute() and not mapping_applied:
        return project_path.parent / candidate
    return candidate


def resolve_project_raw_dir(
    project_path: Path | None,
    declared: str | Path,
    *,
    platform: str | None = None,
    exists: Callable[[Path], bool] | None = None,
) -> Path:
    """Resolve a project ``rawDir`` to a usable footage root.

    On Windows, ``/mnt/<letter>/...`` maps to ``<letter>:\\...``. If the
    mapped/declared path is missing and ``project_path.parent / "edit"`` exists,
    the project parent is used. Fail closed naming both attempted paths.
    """
    platform = platform or sys.platform
    exists_fn = exists or (lambda path: Path(path).exists())
    project_path = Path(project_path).expanduser() if project_path else None
    candidate = _declared_candidate(project_path, declared, platform=platform)
    attempted: list[Path] = [candidate]
    found = _try_resolve_existing(candidate, exists_fn)
    if found is not None:
        return found

    parent_fallback: Path | None = None
    if project_path is not None:
        parent_fallback = project_path.parent
        attempted.append(parent_fallback)
        if exists_fn(parent_fallback / "edit"):
            found_parent = _try_resolve_existing(parent_fallback, exists_fn)
            return found_parent if found_parent is not None else parent_fallback

    raise _missing_raw_dir_error(candidate, attempted, parent_fallback)


_IMPORT_EVIDENCE_NAMES = (
    "session",
    "export",
    "activation",
    "validation",
    "proposal",
    "activationResult",
)
_IMPORT_REVIEW_ACTION = (
    "Build the canonical cut proof, then obtain current transcript, Watch, "
    "listening and creator review"
)


def _valid_pending_import(value):
    return set(value) == {"importId", "operationId"} and all(
        isinstance(item, str) and re.fullmatch(r"[a-f0-9]{64}", item)
        for item in value.values()
    )


def _pending_import_status(marker):
    if not marker.exists() and not marker.is_symlink():
        return None
    result = {"path": str(marker), "status": "invalid"}
    try:
        if marker.is_symlink() or marker.stat().st_size > 4096:
            return result
        from .otio_import import parse_export_bytes

        with marker.open("rb") as stream:
            data = stream.read(4097)
        if len(data) > 4096:
            return result
        _, value, _ = parse_export_bytes(data)
        if not _valid_pending_import(value):
            return result
    except (OSError, ValueError, TypeError):
        return result
    return {**result, **value, "status": "pending"}


def _import_evidence_status(workspace, revision):
    from .contracts import fingerprint_stage
    from .import_evidence import verify_import_origin

    paths = verify_import_origin(workspace, revision)
    packet = paths[0].parent
    # Hash the displayed refs around another verification, so the reported
    # byte identities belong to the exact chain that was actually checked.
    with fingerprint_stage(verify_on_exit=True):
        refs = {}
        for name, path in zip(_IMPORT_EVIDENCE_NAMES, paths, strict=True):
            actual = file_fingerprint(path)
            refs[name] = {
                "path": path.relative_to(packet).as_posix(),
                "sha256": actual["sha256"],
                "sizeBytes": actual["sizeBytes"],
            }
        if verify_import_origin(workspace, revision) != paths:
            raise ValueError("Activated evidence paths changed during status")
    origin = revision["snapshot"]["originRef"]
    return {
        "source": {
            "sha256": origin["exportSha256"],
            "sizeBytes": refs["export"]["sizeBytes"],
            "timelinePointer": origin["timelinePointer"],
        },
        "packet": {
            "importId": origin["importId"],
            "path": str(packet),
            "refs": refs,
        },
        "compatibilityState": "verified-activation",
    }


def _import_status_blocker(code, message):
    return {
        "code": code,
        "message": message,
        "blocking": True,
        "remediation": "Restore the exact retained import evidence or reconcile its activation before continuing.",
    }


def _import_status_result(workspace, revision, pending):
    snapshot = revision["snapshot"] if revision else {}
    imported = bool(
        {"originRef", "sourceAssemblyPolicy", "importOutput"}.intersection(snapshot)
    )
    if not imported and pending is None:
        return None
    result = {
        "status": "active-draft" if imported else "recovery-required",
        "originRef": snapshot.get("originRef"),
        "provider": workspace.project.get("provider"),
        "videoId": workspace.video_id,
        "capabilityLevel": (
            "placed-experimental"
            if snapshot.get("layoutMode") == "placed"
            else "contiguous-experimental"
        )
        if imported
        else None,
        "compatibilityState": "not-checked",
        "recoveryRequired": pending is not None,
        "pendingActivation": pending,
        "pendingFinishing": [],
        "blockers": [],
        "reviewState": "normal-current-candidate-gates-required",
        "nextAction": _IMPORT_REVIEW_ACTION,
    }
    if imported:
        result["currentCanonical"] = {
            "revisionId": revision["revisionId"],
            "contentHash": revision["contentHash"],
        }
        _check_import_status(workspace, revision, result)
    if pending is not None:
        result["status"] = "recovery-required"
        result["blockers"].append(
            _import_status_blocker(
                "OTIO_RECOVERY_REQUIRED", "An import activation requires reconciliation"
            )
        )
        result["nextAction"] = (
            "Reconcile the exact pending import activation before editing or rendering"
        )
    return result


def _check_import_status(workspace, revision, result):
    try:
        result.update(_import_evidence_status(workspace, revision))
    except (KeyError, TypeError, ValueError, OSError, RuntimeError):
        result["status"] = "blocked"
        result["compatibilityState"] = "blocked"
        result["blockers"].append(
            _import_status_blocker(
                "OTIO_SOURCE_CHANGED",
                "Immutable activated import evidence could not be verified",
            )
        )
        result["nextAction"] = (
            "Restore and verify the exact activated import packet before continuing"
        )


class TimelineWorkspace:
    def __init__(
        self,
        *,
        project_path: Path,
        project: dict[str, Any],
        raw_dir: Path,
        video_id: str,
    ):
        self.project_path = Path(project_path)
        self.project = project
        self.raw_dir = Path(raw_dir)
        self.video_id = video_id
        policy = project.get("timeline") or {}
        self.timeline_dir = self.raw_dir / str(
            policy.get("directory") or "edit/timeline"
        )
        self.review_dir = self.raw_dir / str(
            policy.get("reviewDirectory") or "edit/review"
        )
        self.generated_edl = self.raw_dir / str(
            policy.get("generatedEdlPath") or "edit/edl.json"
        )
        self.pipeline_run_path = self.timeline_dir / "pipeline-run.json"

    def finalized_provider_learning(self) -> list[dict[str, Any]]:
        """Load finalized provider learning as non-binding project guidance."""
        provider = str(self.project.get("provider") or "").strip()
        if not provider:
            return []
        configured = self.project.get("providerLearningDirectory")
        base = (
            Path(str(configured)).expanduser()
            if configured
            else repo_root() / "providers" / provider / "learndowns"
        )
        if not base.is_dir():
            return []
        loaded: list[dict[str, Any]] = []
        for entry in sorted(path for path in base.iterdir() if path.is_dir()):
            index_path = entry / "timeline-learning" / "index.json"
            if not index_path.is_file():
                continue
            index = json.loads(index_path.read_text(encoding="utf-8"))
            reference = _learning_active_reference(index, index_path)
            snapshot = json.loads(
                (index_path.parent / reference["path"]).read_text(encoding="utf-8")
            )
            validate_document(snapshot, "avo.timeline-learning.schema.json")
            if snapshot.get("snapshotHash") != reference.get("snapshotHash"):
                raise WorkspaceError(
                    f"provider learning snapshot hash mismatch: {index_path}"
                )
            if snapshot is None or snapshot.get("status") != "final":
                continue
            loaded.append(snapshot)
        return loaded

    def provider_learning_diagnostic(self) -> dict[str, Any]:
        """Optional historical guidance cannot block current-source validation."""
        base = {"binding": False, "inheritedApprovals": False}
        try:
            snapshots = getattr(self, "finalized_provider_learning", list)()
        except (OSError, ValueError, RuntimeError, KeyError, TypeError):
            return {
                **base,
                "status": "unavailable",
                "loadedFinalSnapshots": None,
                "snapshots": [],
                "warnings": [
                    "Optional provider learning is unavailable; coverage is unknown."
                ],
            }
        return {
            **base,
            "status": "available",
            "loadedFinalSnapshots": len(snapshots),
            "snapshots": snapshots,
            "warnings": [],
        }

    @classmethod
    def from_project(
        cls, project_path: Path, *, video_id: str | None = None
    ) -> TimelineWorkspace:
        project_path = Path(project_path).expanduser().resolve()
        try:
            project = json.loads(project_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise WorkspaceError(f"cannot load project {project_path}: {exc}") from exc
        raw_value = str(project.get("rawDir") or project_path.parent)
        raw_dir = resolve_project_raw_dir(project_path, raw_value)
        return cls(
            project_path=project_path,
            project=project,
            raw_dir=raw_dir,
            video_id=video_id or str(project.get("videoId") or raw_dir.name),
        )

    @property
    def authority(self) -> str:
        if all((self.timeline_dir / f"{name}.json").is_file() for name in ARTIFACTS):
            return "canonical"
        return "legacy"

    def artifact_path(self, artifact_type: str) -> Path:
        if artifact_type not in ARTIFACTS:
            raise WorkspaceError(f"unknown artifact type: {artifact_type}")
        return self.timeline_dir / f"{artifact_type}.json"

    def store(self, artifact_type: str) -> ArtifactStore:
        return ArtifactStore(self.artifact_path(artifact_type))

    @serialized_timeline(lambda self: self.timeline_dir)
    def initialize(self, *, provider: str | None = None) -> dict[str, Any]:
        provider = provider or str(self.project.get("provider") or "").strip()
        if not provider:
            raise WorkspaceError("provider identity is required")
        self.timeline_dir.mkdir(parents=True, exist_ok=True)
        self.review_dir.mkdir(parents=True, exist_ok=True)
        for artifact_type, domain in ARTIFACTS.items():
            self.store(artifact_type).initialize(
                artifact_type=artifact_type,
                artifact_id=f"{self.video_id}:{artifact_type}",
                video_id=self.video_id,
                provider=provider,
                timeline_domain=domain,
            )
        projection = self.timeline_dir / "projection.json"
        if not projection.exists():
            atomic_write_json(
                projection,
                {
                    "schemaVersion": "1.0.0",
                    "canonicalDirectory": "edit/timeline",
                    "generatedEdlPath": "edit/edl.json",
                    "canonicalFirst": True,
                    "status": "not-generated",
                },
            )
        from .lifecycle import PipelineRunStore

        PipelineRunStore(self.pipeline_run_path).initialize(
            run_id=f"{self.video_id}-run-0001",
            video_id=self.video_id,
            provider=provider,
            project_path=self.project_path,
        )
        status = self.status()
        status["providerLearning"] = {
            key: value
            for key, value in self.provider_learning_diagnostic().items()
            if key != "snapshots"
        }
        return status

    def validate(self) -> dict[str, Any]:
        if self.authority != "canonical":
            migration = (self.project.get("timeline") or {}).get("migration") or {}
            if not migration.get("allowLegacyEdlFallback", True):
                raise WorkspaceError(
                    "canonical timeline is unavailable and legacy fallback is disabled"
                )
            return {"authority": "legacy", "valid": True, "artifacts": {}}
        status = self.status()
        projection_path = self.timeline_dir / "projection.json"
        if projection_path.is_file():
            projection = json.loads(projection_path.read_text(encoding="utf-8"))
            if projection.get("status") == "generated" and self.generated_edl.is_file():
                expected = str(projection.get("edlSha256") or "")
                actual = file_fingerprint(self.generated_edl)["sha256"]
                if expected and expected != actual:
                    raise WorkspaceError(
                        "derived EDL fingerprint mismatch; regenerate from canonical state or migrate the external edit"
                    )
        return {**status, "valid": True}

    def status(self) -> dict[str, Any]:
        artifacts: dict[str, Any] = {}
        for artifact_type in ARTIFACTS:
            path = self.artifact_path(artifact_type)
            if not path.is_file():
                artifacts[artifact_type] = {"status": "missing"}
                continue
            index = self.store(artifact_type).load_index()
            artifacts[artifact_type] = {
                "headRevisionId": index["headRevisionId"],
                "approvedRevisionId": index["approvedRevisionId"],
                "activeState": index["activeState"],
                "revisionCount": len(index["revisionRefs"]),
                "eventCount": len(index["eventRefs"]),
            }
        result = {
            "authority": self.authority,
            "projectPath": str(self.project_path),
            "rawDir": str(self.raw_dir),
            "videoId": self.video_id,
            "provider": str(self.project.get("provider") or ""),
            "artifacts": artifacts,
        }
        imported = self.timeline_import_status()
        if imported is not None:
            result["timelineImport"] = imported
        if self.pipeline_run_path.is_file():
            from .lifecycle import PipelineRunStore

            run = PipelineRunStore(self.pipeline_run_path).load()
            result["pipeline"] = {
                "runId": run["runId"],
                "mainState": run["mainState"],
                "sideState": run["sideState"],
                "blockers": run["blockers"],
                "updatedAt": run["updatedAt"],
            }
        return result

    def timeline_import_status(self):
        """Report only canonical selection and its exact retained activation."""
        pending = _pending_import_status(
            self.timeline_dir / "import-activation.pending.json"
        )
        revision = None
        if self.artifact_path("cmap").is_file():
            store = self.store("cmap")
            index = store.load_index()
            if index["headRevisionId"]:
                revision = store.revision(index["headRevisionId"])
        return _import_status_result(self, revision, pending)

    def active_dependency_snapshot(self) -> dict[str, str]:
        result: dict[str, str] = {}
        for artifact_type in ARTIFACTS:
            path = self.artifact_path(artifact_type)
            if not path.is_file():
                continue
            index = self.store(artifact_type).load_index()
            head = index["headRevisionId"]
            if head:
                ref = next(
                    item for item in index["revisionRefs"] if item["revisionId"] == head
                )
                result[artifact_type] = ref["contentSha256"]
        return dict(sorted(result.items()))

    def review_change_summary(
        self,
        dependencies: dict[str, str],
        *,
        windows: list[dict[str, Any]] | None = None,
        target_limit: int = 6,
    ) -> dict[str, Any]:
        """Summarize exact active revision diffs for a two-minute human gate."""
        items: list[dict[str, Any]] = []
        stale: list[str] = []
        for artifact_type in ARTIFACTS:
            path = self.artifact_path(artifact_type)
            if not path.is_file():
                continue
            index = self.store(artifact_type).load_index()
            if index["activeState"] != "valid":
                stale.append(artifact_type)
            dependency_hash = dependencies.get(artifact_type)
            if not dependency_hash:
                continue
            ref = next(
                (
                    item
                    for item in index["revisionRefs"]
                    if item["contentSha256"] == dependency_hash
                ),
                None,
            )
            if ref is None:
                continue
            revision = self.store(artifact_type).revision(ref["revisionId"])
            counts: dict[str, int] = {}
            targets: list[str] = []
            for operation in revision.get("diff") or []:
                name = str(operation.get("op") or "update")
                counts[name] = counts.get(name, 0) + 1
                target = operation.get("target") or {}
                label = ":".join(
                    value
                    for value in (
                        str(target.get("collection") or ""),
                        str(target.get("stableId") or ""),
                    )
                    if value
                )
                if label and label not in targets:
                    targets.append(label)
            if not counts:
                counts = {"update": 1}
            shown_targets = targets[:target_limit]
            items.append(
                {
                    "artifactType": artifact_type,
                    "revisionId": revision["revisionId"],
                    "reason": revision["reason"],
                    "operationCounts": dict(sorted(counts.items())),
                    "targets": shown_targets,
                    "truncatedTargets": max(0, len(targets) - len(shown_targets)),
                }
            )
        if not items:
            keys = sorted(dependencies)
            items = [
                {
                    "artifactType": "candidate",
                    "revisionId": "dependency-lock",
                    "reason": "materialized from the exact declared dependency snapshot",
                    "operationCounts": {"materialize": 1},
                    "targets": keys[:target_limit],
                    "truncatedTargets": max(0, len(keys) - target_limit),
                }
            ]
        phrases = []
        for item in items:
            operations = ", ".join(
                f"{name} {count}" for name, count in item["operationCounts"].items()
            )
            phrases.append(f"{item['artifactType']} {item['revisionId']}: {operations}")
        return {
            "headline": "; ".join(phrases),
            "items": items,
            "windows": list(windows or []),
            "staleDependencies": sorted(stale),
        }

    @serialized_timeline(lambda self: self.timeline_dir)
    def invalidate_descendants(
        self,
        changed_artifact_type: str,
        *,
        before_hash: str | None,
        after_hash: str | None,
        reason: str,
        actor: str,
        idempotent: bool = False,
    ) -> dict[str, Any]:
        from .lineage import persist_invalidation

        stores = {
            artifact_type: self.store(artifact_type)
            for artifact_type in ARTIFACTS
            if self.artifact_path(artifact_type).is_file()
        }
        return persist_invalidation(
            stores,
            changed_artifact_type,
            before_hash=before_hash,
            after_hash=after_hash,
            reason=reason,
            actor=actor,
            idempotent=idempotent,
        )

    def require_active(self, artifact_type: str) -> dict[str, Any]:
        require_reconciled(self.timeline_dir)
        index = self.store(artifact_type).load_index()
        if index["headRevisionId"] is None:
            raise WorkspaceError(f"{artifact_type} has no active revision")
        if index["activeState"] != "valid":
            raise WorkspaceError(
                f"{artifact_type} is {index['activeState']}; rebase/revalidate before render or approval"
            )
        return index

    def notify_editlog(self) -> dict[str, Any]:
        """Refresh footage-root EDITLOG after a successful canonical write."""
        from avo.editlog import after_canonical_write

        return after_canonical_write(self.raw_dir)


def resolve_timeline_workspace(raw_dir, *, project_path=None, canonical_cmap_path=None):
    """Resolve one declared project for retention without scanning or initializing."""
    raw = Path(raw_dir).resolve()
    known = (
        Path(canonical_cmap_path).resolve() if canonical_cmap_path is not None else None
    )
    selected = (
        Path(project_path)
        if project_path is not None
        else _retained_project_path(raw, known)
    )
    if selected is None:
        return None
    workspace = TimelineWorkspace.from_project(selected)
    timeline = workspace.timeline_dir.resolve()
    if workspace.raw_dir.resolve() != raw or not timeline.is_relative_to(raw / "edit"):
        raise WorkspaceError(
            "Retained canonical target differs from the declared project/edit directory"
        )
    if known is not None and workspace.artifact_path("cmap").resolve() != known:
        raise WorkspaceError(
            "Retained canonical CMap path differs from the declared project"
        )
    return workspace


def _retained_project_path(raw, known):
    if known is not None:
        run_path = known.parent / "pipeline-run.json"
        if run_path.is_file():
            from .otio_import import parse_export_bytes

            with run_path.open("rb") as stream:
                data = stream.read(64 * 1024 * 1024 + 1)
            _, run, _ = parse_export_bytes(data)
            validate_document(run, "avo.pipeline-run.schema.json")
            return Path(run["projectPath"])
    conventional = raw / "avo.project.json"
    return conventional if conventional.is_file() else None
