"""Raw-only CMap authoring service with immutable stable-ID diffs."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from .contracts import file_fingerprint
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
        before = (parent or {}).get("segments") or []
        after = child.get("segments") or []
        before_by = {item["segmentId"]: item for item in before}
        after_by = {item["segmentId"]: item for item in after}
        ops = []
        ordinal = 1

        def add(
            op,
            target,
            before_value=None,
            after_value=None,
            from_order=None,
            to_order=None,
        ):
            nonlocal ordinal
            item = {
                "opId": f"diff-{ordinal:04d}",
                "op": op,
                "target": {"collection": "segments", "stableId": target},
                "reason": reason,
                "actorIntent": "preserve approved editorial meaning",
            }
            if before_value is not None:
                item["before"] = before_value
            if after_value is not None:
                item["after"] = after_value
            if from_order is not None:
                item["fromOrder"] = from_order
            if to_order is not None:
                item["toOrder"] = to_order
            item["affectedTimeRanges"] = []
            ops.append(item)
            ordinal += 1

        for sid, item in before_by.items():
            if sid not in after_by:
                add("remove", sid, before_value=item)
        for sid, item in after_by.items():
            if sid not in before_by:
                add("add", sid, after_value=item)
            elif before_by[sid] != item:
                add("replace", sid, before_value=before_by[sid], after_value=item)
        before_order = [item["segmentId"] for item in before]
        after_order = [item["segmentId"] for item in after]
        for sid in set(before_order) & set(after_order):
            if before_order.index(sid) != after_order.index(sid):
                add(
                    "move",
                    sid,
                    from_order=before_order.index(sid),
                    to_order=after_order.index(sid),
                )
        return ops

    def author(
        self, snapshot: dict[str, Any], *, actor: str, reason: str
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
