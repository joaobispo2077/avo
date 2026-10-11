"""BMap authoring on the exact effective approved CMap cut-output clock."""

from __future__ import annotations

import re
from copy import deepcopy
from fractions import Fraction
from pathlib import Path
from typing import Any

from .contracts import file_fingerprint
from .diff import stable_id_diff
from .lifecycle import PipelineRunStore, PipelineState, TransitionFacts
from .lineage import LineageError, validate_bmap_basis
from .mapping import cmap_output_duration
from .workspace import TimelineWorkspace

_STABLE_ID = re.compile(r"^[a-z][a-z0-9-]{2,63}$")


def _ticks_in_base(value: dict[str, Any], base: dict[str, int]) -> Fraction:
    seconds = Fraction(
        int(value["ticks"]) * int(value["timebase"]["num"]),
        int(value["timebase"]["den"]),
    )
    return seconds / Fraction(int(base["num"]), int(base["den"]))


class BMapService:
    def __init__(self, workspace: TimelineWorkspace):
        self.workspace = workspace
        if workspace.authority != "canonical":
            workspace.initialize()
        self.store = workspace.store("bmap")

    def current_basis(self) -> tuple[dict[str, Any], dict[str, Any], str]:
        cmap_store = self.workspace.store("cmap")
        approval = cmap_store.effective_approval()
        if approval is None:
            raise LineageError(
                "BMap requires the latest effective approved CMap and exact cut output"
            )
        index = cmap_store.load_index()
        revision = cmap_store.revision(index["headRevisionId"])
        basis = {
            "artifactType": "cmap",
            "artifactId": index["artifactId"],
            "revisionId": revision["revisionId"],
            "sha256": revision["contentHash"],
            "outputSha256": approval["candidateSha256"],
            "state": "valid",
        }
        validate_bmap_basis(basis, cmap_store.load())
        return basis, revision, approval["candidateSha256"]

    @staticmethod
    def _asset(cue: dict[str, Any]) -> None:
        asset = cue.get("assetRef")
        if not asset:
            return
        locator = str(asset.get("locator") or "")
        digest = str(asset.get("sha256") or "")
        if not locator or len(digest) != 64:
            raise LineageError(
                f"BMap cue {cue.get('cueId')} requires an exact asset reference"
            )
        path = Path(locator)
        if not path.is_file():
            raise LineageError(f"BMap asset is missing: {path}")
        if file_fingerprint(path)["sha256"] != digest:
            raise LineageError(f"BMap asset fingerprint changed: {path}")

    @classmethod
    def _validate_snapshot(
        cls,
        snapshot: dict[str, Any],
        basis: dict[str, Any],
        cmap_revision: dict[str, Any],
    ) -> None:
        if snapshot.get("basis") != basis:
            raise LineageError(
                "BMap snapshot basis must equal the current approved CMap/cut"
            )
        cues = snapshot.get("cues") or []
        ids: set[str] = set()
        output_base = cmap_revision["snapshot"]["segments"][0]["in"]["timebase"]
        duration = cmap_output_duration(cmap_revision["snapshot"])
        allowed = {
            "insert",
            "text",
            "clip",
            "music",
            "sfx",
            "animation",
            "caption",
            "grade",
            "end-screen",
            "card",
            "transition",
            "ambience",
        }
        for cue in cues:
            cue_id = str(cue.get("cueId") or "")
            if not _STABLE_ID.fullmatch(cue_id) or cue_id in ids:
                raise LineageError("BMap cue IDs must be unique stable IDs")
            ids.add(cue_id)
            if cue.get("kind") not in allowed:
                raise LineageError(f"unsupported BMap cue kind: {cue.get('kind')}")
            if not str(cue.get("targetLayerId") or ""):
                raise LineageError(f"BMap cue {cue_id} requires target layer")
            if not str(cue.get("intent") or "") or not str(cue.get("reason") or ""):
                raise LineageError(f"BMap cue {cue_id} requires intent and reason")
            start, end = cue.get("start") or {}, cue.get("end") or {}
            for value in (start, end):
                if value.get("domain") != "cmap-output" or "sourceId" in value:
                    raise LineageError("BMap timing authority must be cmap-output")
            start_ticks = _ticks_in_base(start, output_base)
            end_ticks = _ticks_in_base(end, output_base)
            if start_ticks < 0 or end_ticks <= start_ticks or end_ticks > duration:
                raise LineageError(
                    f"BMap cue {cue_id} is outside the approved cut duration"
                )
            cls._asset(cue)

    @staticmethod
    def _diff(
        parent: dict[str, Any] | None, child: dict[str, Any], reason: str
    ) -> list[dict[str, Any]]:
        return stable_id_diff(
            parent,
            child,
            reason,
            collection="cues",
            id_key="cueId",
            actor_intent="preserve beat intent on approved cut output",
        )

    def author(
        self, snapshot: dict[str, Any], *, actor: str, reason: str
    ) -> dict[str, Any]:
        snapshot = deepcopy(snapshot)
        basis, cmap_revision, cut_hash = self.current_basis()
        snapshot["basis"] = basis
        self._validate_snapshot(snapshot, basis, cmap_revision)
        index = self.store.load_index()
        parent = None
        expected = None
        if index["headRevisionId"]:
            current = self.store.revision(index["headRevisionId"])
            parent = current["snapshot"]
            expected = current["contentHash"]
        revision = self.store.append_revision(
            snapshot=snapshot,
            actor=actor,
            reason=reason,
            diff=self._diff(parent, snapshot, reason),
            dependencies=[
                {
                    "artifactType": "cmap",
                    "artifactId": basis["artifactId"],
                    "revisionId": basis["revisionId"],
                    "contentSha256": basis["sha256"],
                },
                {
                    "artifactType": "cut-output",
                    "artifactId": f"{self.workspace.video_id}:cut-output",
                    "revisionId": basis["revisionId"],
                    "contentSha256": cut_hash,
                },
            ],
            expected_head_hash=expected,
        )
        if expected and expected != revision["contentHash"]:
            self.workspace.invalidate_descendants(
                "bmap",
                before_hash=expected,
                after_hash=revision["contentHash"],
                reason="BMap revision changed",
                actor=actor,
            )
        run_store = PipelineRunStore(self.workspace.pipeline_run_path)
        run = run_store.load()
        if (
            run["mainState"] == PipelineState.CMAP_APPROVED.value
            and run["sideState"] is None
        ):
            run_store.advance(
                PipelineState.BMAP_DRAFT,
                TransitionFacts(cmap_approved=True, cut_output_hash=cut_hash),
                actor=actor,
                reason=reason,
                active_refs={
                    **run["activeRefs"],
                    "bmapRevisionId": revision["revisionId"],
                    "cutOutputSha256": cut_hash,
                },
            )
        revision["editlogRefresh"] = self.workspace.notify_editlog()
        return revision

    def status(self) -> dict[str, Any]:
        basis = None
        try:
            basis, _, _ = self.current_basis()
        except LineageError as error:
            return {
                "activeState": "blocked",
                "reason": str(error),
                "artifact": self.workspace.status()["artifacts"]["bmap"],
            }
        index = self.store.load_index()
        return {"activeState": index["activeState"], "basis": basis, "artifact": index}

    def rebase(
        self,
        mapped_ranges: dict[str, list[list[int]]],
        *,
        actor: str,
        reason: str,
    ) -> dict[str, Any]:
        from .lineage import propose_bmap_rebase
        from .store import atomic_write_json, now_iso

        index = self.store.load_index()
        if not index["headRevisionId"]:
            raise LineageError("BMap rebase requires an existing revision")
        current = self.store.revision(index["headRevisionId"])
        basis, _, _ = self.current_basis()
        report = propose_bmap_rebase(current["snapshot"]["cues"], mapped_ranges)
        report.update(
            {
                "schemaVersion": "1.0.0",
                "sourceBmapRevisionId": current["revisionId"],
                "targetCmapBasis": basis,
                "createdAt": now_iso(),
            }
        )
        report_path = (
            self.workspace.review_dir
            / "bmap-rebase"
            / f"{current['revisionId']}-to-{basis['revisionId']}.json"
        )
        atomic_write_json(report_path, report)
        if report["blockers"]:
            return {**report, "revision": None, "reportPath": str(report_path)}
        snapshot = {"basis": basis, "cues": report["proposedCues"]}
        revision = self.author(snapshot, actor=actor, reason=reason)
        return {**report, "revision": revision, "reportPath": str(report_path)}
