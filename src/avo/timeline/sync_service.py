"""Application service for generic raw Sync authoring, evidence, and decisions."""

from __future__ import annotations

from typing import Any

from .contracts import content_hash
from .store import atomic_write_json
from .sync import (
    SyncError,
    build_constant_offset_snapshot,
    build_linear_snapshot,
    build_not_applicable_snapshot,
    build_piecewise_snapshot,
    validate_sync_snapshot,
)
from .workspace import TimelineWorkspace


class SyncService:
    def __init__(self, workspace: TimelineWorkspace):
        self.workspace = workspace
        if not workspace.artifact_path("sync-map").is_file():
            workspace.initialize()
        self.store = workspace.store("sync-map")

    def _append(
        self, snapshot: dict[str, Any], *, actor: str, reason: str
    ) -> dict[str, Any]:
        before_index = self.store.load_index()
        before = None
        if before_index["headRevisionId"]:
            before = next(
                item["contentSha256"]
                for item in before_index["revisionRefs"]
                if item["revisionId"] == before_index["headRevisionId"]
            )
        revision = self.store.append_revision(
            snapshot=snapshot, actor=actor, reason=reason, expected_head_hash=before
        )
        if before and before != revision["contentHash"]:
            from .lineage import persist_invalidation

            stores = {
                kind: self.workspace.store(kind)
                for kind in ("cmap", "bmap", "tracks", "animation")
                if self.workspace.artifact_path(kind).is_file()
            }
            persist_invalidation(
                stores,
                "sync-map",
                before_hash=before,
                after_hash=revision["contentHash"],
                reason="Sync revision changed",
                actor=actor,
            )
        revision["editlogRefresh"] = self.workspace.notify_editlog()
        return revision

    def author_constant(
        self,
        *,
        picture: dict[str, Any],
        audio: dict[str, Any],
        offset_ticks: int,
        timebase: dict[str, int],
        samples: list[tuple[int, int]],
        tolerance_ticks: int,
        actor: str,
        reason: str,
    ) -> dict[str, Any]:
        if len(samples) < 3:
            raise SyncError(
                "constant-offset approval requires start/middle/end samples"
            )
        return self._append(
            build_constant_offset_snapshot(
                picture=picture,
                audio=audio,
                offset_ticks=offset_ticks,
                timebase=timebase,
                samples=samples,
                tolerance_ticks=tolerance_ticks,
            ),
            actor=actor,
            reason=reason,
        )

    def author_linear(
        self,
        *,
        picture: dict[str, Any],
        audio: dict[str, Any],
        rate_ratio: dict[str, int],
        offset_ticks: int,
        timebase: dict[str, int],
        samples: list[tuple[int, int, int]],
        tolerance_ticks: int,
        actor: str,
        reason: str,
    ) -> dict[str, Any]:
        if len(samples) < 3:
            raise SyncError("linear drift approval requires start/middle/end samples")
        return self._append(
            build_linear_snapshot(
                picture=picture,
                audio=audio,
                rate_ratio=rate_ratio,
                offset_ticks=offset_ticks,
                timebase=timebase,
                samples=samples,
                tolerance_ticks=tolerance_ticks,
            ),
            actor=actor,
            reason=reason,
        )

    def author_piecewise(
        self,
        *,
        picture: dict[str, Any],
        audio: dict[str, Any],
        control_points: list[dict[str, int]],
        timebase: dict[str, int],
        samples: list[tuple[int, int, int]],
        tolerance_ticks: int,
        actor: str,
        reason: str,
    ) -> dict[str, Any]:
        if len(samples) < len(control_points):
            raise SyncError(
                "piecewise approval requires every interval and full-program samples"
            )
        return self._append(
            build_piecewise_snapshot(
                picture=picture,
                audio=audio,
                control_points=control_points,
                timebase=timebase,
                samples=samples,
                tolerance_ticks=tolerance_ticks,
            ),
            actor=actor,
            reason=reason,
        )

    def author_not_applicable(
        self, *, raw_fingerprints: dict[str, str], actor: str, reason: str
    ) -> dict[str, Any]:
        return self._append(
            build_not_applicable_snapshot(
                raw_fingerprints=raw_fingerprints, actor=actor, reason=reason
            ),
            actor=actor,
            reason=reason,
        )

    def validate_current(self) -> dict[str, Any]:
        document = self.store.load()
        revision_id = document.get("currentRevisionId")
        if not revision_id:
            raise SyncError("no Sync revision to validate")
        revision = self.store.revision(revision_id)
        snapshot = revision["snapshot"]
        validate_sync_snapshot(snapshot)
        if snapshot.get("status") == "not-applicable":
            body = {
                "schemaVersion": "1.0.0",
                "kind": "sync",
                "status": "not-applicable",
                "revisionId": revision_id,
                "revisionHash": revision["contentHash"],
                "candidateHash": revision["contentHash"],
                "dependencyHashes": snapshot["rawFingerprints"],
                "scope": "raw-inventory",
                "coverage": {"mode": "not-applicable", "windows": []},
                "rationale": snapshot["rationale"],
                "producer": {"name": "avo.sync", "version": "1.0.0"},
            }
        else:
            samples = snapshot.get("calibrationSamples") or []
            body = {
                "schemaVersion": "1.0.0",
                "kind": "sync",
                "status": "pass",
                "revisionId": revision_id,
                "revisionHash": revision["contentHash"],
                "candidateHash": revision["contentHash"],
                "dependencyHashes": {
                    snapshot["picture"]["sourceId"]: snapshot["picture"]["fingerprint"][
                        "sha256"
                    ],
                    snapshot["audio"]["sourceId"]: snapshot["audio"]["fingerprint"][
                        "sha256"
                    ],
                },
                "scope": "full-program",
                "coverage": {
                    "mode": "windows",
                    "windows": [item["pictureTicks"] for item in samples],
                },
                "maxResidualTicks": snapshot["fullProgramValidation"][
                    "maxResidualTicks"
                ],
                "toleranceTicks": snapshot["toleranceTicks"],
                "producer": {"name": "avo.sync", "version": "1.0.0"},
            }
        body["sha256"] = content_hash(body)
        target = self.workspace.review_dir / "sync-ready" / revision_id / "review.json"
        atomic_write_json(target, body)
        return body

    def decide(
        self,
        *,
        decision: str,
        candidate_hash: str,
        evidence_bundle_hash: str,
        actor: str,
        reason: str,
    ) -> dict[str, Any]:
        evidence = self.validate_current()
        revision = self.store.revision(evidence["revisionId"])
        if evidence_bundle_hash != evidence["sha256"]:
            raise SyncError("Sync decision evidence bundle is stale")
        event = self.store.record_decision(
            decision=decision,
            revision_id=revision["revisionId"],
            revision_hash=revision["contentHash"],
            candidate_hash=candidate_hash,
            dependency_hashes=evidence["dependencyHashes"],
            actor=actor,
            checkpoint="sync-ready",
            scope=evidence["scope"],
            reason=reason,
            evidence_bundle_hash=evidence_bundle_hash,
        )
        event["editlogRefresh"] = self.workspace.notify_editlog()
        return event
