"""Raw-only CMap authoring service with immutable stable-ID diffs."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from .contracts import file_fingerprint
from .diff import stable_id_diff
from .lineage import LineageError, validate_cmap_snapshot
from .workspace import TimelineWorkspace


class CMapService:
    def __init__(self, workspace: TimelineWorkspace):
        self.workspace = workspace
        if workspace.authority != "canonical":
            workspace.initialize()
        self.store = workspace.store("cmap")

    def _sync_basis(self) -> dict[str, Any]:
        sync_store = self.workspace.store("sync-map")
        approval = sync_store.effective_approval()
        if approval is None:
            raise LineageError(
                "CMap materialization requires approved current Sync or explicit approved N/A"
            )
        revision = sync_store.revision(approval["subject"]["revisionId"])
        return {
            "artifactType": "sync-map",
            "artifactId": sync_store.load_index()["artifactId"],
            "revisionId": revision["revisionId"],
            "contentSha256": revision["contentHash"],
        }

    def _verify_raw(self, snapshot: dict[str, Any]) -> None:
        edit_root = (self.workspace.raw_dir / "edit").resolve()
        for source in snapshot.get("sources") or []:
            locator = str(
                source.get("locator")
                or source.get("fingerprint", {}).get("locator")
                or ""
            )
            if not locator:
                raise LineageError(
                    f"raw source {source.get('sourceId')} requires locator"
                )
            path = Path(locator).resolve()
            if path == edit_root or edit_root in path.parents:
                raise LineageError(
                    f"derived edit/proof cannot be a CMap raw source: {path}"
                )
            if not path.is_file():
                raise LineageError(f"raw source missing: {path}")
            actual = file_fingerprint(path)
            if actual["sha256"] != (source.get("fingerprint") or {}).get("sha256"):
                raise LineageError(
                    f"raw source fingerprint mismatch: {source.get('sourceId')}"
                )

    @staticmethod
    def _diff(
        parent: dict[str, Any] | None, child: dict[str, Any], reason: str
    ) -> list[dict[str, Any]]:
        return stable_id_diff(
            parent,
            child,
            reason,
            collection="segments",
            id_key="segmentId",
            actor_intent="preserve approved editorial meaning",
        )

    def author(
        self,
        snapshot: dict[str, Any],
        *,
        actor: str,
        reason: str,
        expected_head_hash: str | None = None,
    ) -> dict[str, Any]:
        snapshot = deepcopy(snapshot)
        validate_cmap_snapshot(snapshot)
        self._verify_raw(snapshot)
        basis = self._sync_basis()
        snapshot["syncRef"] = basis
        index = self.store.load_index()
        parent = None
        before = None
        if index["headRevisionId"]:
            current = self.store.revision(index["headRevisionId"])
            parent = current["snapshot"]
            before = current["contentHash"]
        if expected_head_hash is not None and expected_head_hash != before:
            raise LineageError("stale cutting proposal: CMap head changed")
        diff = self._diff(parent, snapshot, reason)
        revision = self.store.append_revision(
            snapshot=snapshot,
            actor=actor,
            reason=reason,
            diff=diff,
            dependencies=[basis],
            expected_head_hash=before,
        )
        if before and before != revision["contentHash"]:
            self.workspace.invalidate_descendants(
                "cmap",
                before_hash=before,
                after_hash=revision["contentHash"],
                reason="CMap revision changed",
                actor=actor,
            )
        revision["editlogRefresh"] = self.workspace.notify_editlog()
        return revision
