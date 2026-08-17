"""Resolve canonical timeline authority and active artifact lineage for a project."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .contracts import file_fingerprint
from .store import ArtifactStore, atomic_write_json

ARTIFACTS = {
    "cmap": "raw-source",
    "bmap": "cmap-output",
    "tracks": "cmap-output",
    "animation": "cmap-output",
    "sync-map": "raw-source",
}


class WorkspaceError(RuntimeError):
    pass


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
        raw_dir = Path(raw_value).expanduser()
        if not raw_dir.is_absolute():
            raw_dir = (project_path.parent / raw_dir).resolve()
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
        return self.status()

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

    def invalidate_descendants(
        self,
        changed_artifact_type: str,
        *,
        before_hash: str | None,
        after_hash: str | None,
        reason: str,
        actor: str,
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
        )

    def require_active(self, artifact_type: str) -> dict[str, Any]:
        index = self.store(artifact_type).load_index()
        if index["headRevisionId"] is None:
            raise WorkspaceError(f"{artifact_type} has no active revision")
        if index["activeState"] != "valid":
            raise WorkspaceError(
                f"{artifact_type} is {index['activeState']}; rebase/revalidate before render or approval"
            )
        return index
