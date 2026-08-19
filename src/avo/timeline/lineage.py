"""Timeline basis validation, approvals, dependency staleness, and rebasing."""

from __future__ import annotations

from typing import Any

from .store import ArtifactStore


class LineageError(ValueError):
    pass


def validate_cmap_snapshot(snapshot: dict[str, Any]) -> None:
    sources = snapshot.get("sources") or []
    if not sources:
        raise LineageError("CMap requires fingerprinted raw sources")
    source_ids: set[str] = set()
    for source in sources:
        source_id = str(source.get("sourceId") or "")
        if not source_id or source_id in source_ids:
            raise LineageError("CMap source IDs must be stable and unique")
        source_ids.add(source_id)
        if source.get("kind") != "raw":
            raise LineageError("CMap editorial truth must use brute/raw material")
        fingerprint = source.get("fingerprint") or {}
        if len(str(fingerprint.get("sha256") or "")) != 64:
            raise LineageError("CMap raw source requires SHA-256 fingerprint")
    segment_ids: set[str] = set()
    segments = snapshot.get("segments") or []
    if not segments:
        raise LineageError("CMap requires at least one kept segment")
    for segment in segments:
        segment_id = str(segment.get("segmentId") or "")
        source_id = str(segment.get("sourceId") or "")
        if not segment_id or segment_id in segment_ids:
            raise LineageError("CMap segment IDs must be stable and unique")
        segment_ids.add(segment_id)
        if source_id not in source_ids:
            raise LineageError(
                f"CMap segment references unknown raw source: {source_id}"
            )
        if not str(segment.get("reason") or "").strip():
            raise LineageError("CMap segment requires editorial reason")
        start, end = segment.get("in") or {}, segment.get("out") or {}
        for value in (start, end):
            if (
                value.get("domain") != "raw-source"
                or value.get("sourceId") != source_id
            ):
                raise LineageError("CMap segment times must use their raw source clock")
            base = value.get("timebase") or {}
            if int(base.get("num") or 0) <= 0 or int(base.get("den") or 0) <= 0:
                raise LineageError("CMap segment timebase must be positive")
        if int(end.get("ticks", 0)) <= int(start.get("ticks", 0)):
            raise LineageError("CMap segment out must be after in")


def create_cmap_revision(
    store: ArtifactStore,
    snapshot: dict[str, Any],
    *,
    actor: str,
    reason: str,
    diff: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    validate_cmap_snapshot(snapshot)
    return store.append_revision(
        snapshot=snapshot,
        actor=actor,
        reason=reason,
        diff=diff or [],
    )


def approve_cmap_revision(
    store: ArtifactStore,
    revision_id: str,
    revision_hash: str,
    cut_output_hash: str,
) -> dict[str, Any]:
    return store.approve(
        revision_id,
        revision_hash=revision_hash,
        candidate_hash=cut_output_hash,
    )


_DEPENDENCY_DAG = {
    "raw": {
        "sync-map",
        "cmap",
        "bmap",
        "tracks",
        "animation",
        "candidate",
        "review",
        "approval",
    },
    "sync-map": {
        "cmap",
        "bmap",
        "tracks",
        "animation",
        "candidate",
        "review",
        "approval",
    },
    "cmap": {"bmap", "tracks", "animation", "candidate", "review", "approval"},
    "bmap": {"tracks", "animation", "candidate", "review", "approval"},
    "tracks": {"candidate", "review", "approval"},
    "animation": {"candidate", "review", "approval"},
    "candidate": {"review", "approval"},
}


def stale_descendants(
    artifact_type: str,
    *,
    before_hash: str | None = None,
    after_hash: str | None = None,
) -> set[str]:
    if before_hash is not None and before_hash == after_hash:
        return set()
    return set(_DEPENDENCY_DAG.get(artifact_type, set()))


def validate_bmap_basis(basis: dict[str, Any], cmap: dict[str, Any]) -> None:
    approved = cmap.get("approvedRevisionId")
    if not approved or approved != cmap.get("currentRevisionId"):
        raise LineageError("BMap requires latest approved final CMap")
    if basis.get("revisionId") != approved:
        raise LineageError("BMap basis is not latest approved CMap revision")
    revision = next(
        (r for r in cmap.get("revisions") or [] if r.get("revisionId") == approved),
        None,
    )
    if revision is None or basis.get("sha256") != revision.get("contentHash"):
        raise LineageError("BMap CMap revision fingerprint mismatch")
    decisions = [
        d
        for d in cmap.get("decisions") or []
        if d.get("revisionId") == approved and d.get("decision") == "approved"
    ]
    if not decisions:
        raise LineageError("BMap requires exact CMap approval decision")
    if basis.get("outputSha256") != decisions[-1].get("candidateHash"):
        raise LineageError("BMap cut-output fingerprint mismatch")


def rebase_bmap(
    cues: list[dict[str, Any]],
    mapped_ranges: dict[str, list[list[int]]],
) -> list[dict[str, Any]]:
    from copy import deepcopy

    from .mapping import classify_cue_rebase

    result = []
    for cue in cues:
        item = deepcopy(cue)
        state = classify_cue_rebase(
            cue.get("rawAnchorRanges") or [],
            mapped_ranges.get(str(cue.get("cueId")), []),
        )
        item["rebaseState"] = state
        if state in {"ambiguous", "unsupported"}:
            item["reviewState"] = "needs-human-judgment"
        elif state == "removed":
            item["reviewState"] = "stale"
        result.append(item)
    return result


def persist_invalidation(
    stores: dict[str, ArtifactStore],
    changed_artifact_type: str,
    *,
    before_hash: str | None,
    after_hash: str | None,
    reason: str,
    actor: str = "avo-lineage",
) -> dict[str, Any]:
    """Persist derived stale state for all currently stored descendants."""
    descendants = stale_descendants(
        changed_artifact_type,
        before_hash=before_hash,
        after_hash=after_hash,
    )
    affected: list[dict[str, str]] = []
    for artifact_type in sorted(descendants):
        store = stores.get(artifact_type)
        if store is None or not store.path.is_file():
            continue
        index = store.load_index()
        if index["headRevisionId"] is None:
            continue
        updated = store.set_active_state(
            "stale",
            reason=f"{reason}; changed {changed_artifact_type}",
            actor=actor,
        )
        affected.append(
            {
                "artifactType": artifact_type,
                "revisionId": str(updated["headRevisionId"]),
                "state": "stale",
            }
        )
    return {
        "changedArtifactType": changed_artifact_type,
        "beforeHash": before_hash,
        "afterHash": after_hash,
        "affected": affected,
    }


def propose_bmap_rebase(
    cues: list[dict[str, Any]],
    mapped_ranges: dict[str, list[list[int]]],
) -> dict[str, Any]:
    """Classify every cue and move only deterministic preserved/shifted cues."""
    from copy import deepcopy

    from .mapping import classify_cue_rebase

    outcomes: list[dict[str, Any]] = []
    proposed: list[dict[str, Any]] = []
    blockers: list[dict[str, Any]] = []
    for cue in cues:
        cue_id = str(cue.get("cueId"))
        old_ranges = cue.get("rawAnchorRanges")
        if old_ranges is None:
            old_ranges = (cue.get("rebaseHints") or {}).get("rawAnchorRanges") or []
        new_ranges = mapped_ranges.get(cue_id, [])
        outcome = classify_cue_rebase(old_ranges, new_ranges)
        record = {
            "cueId": cue_id,
            "outcome": outcome,
            "oldRanges": old_ranges,
            "newRanges": new_ranges,
            "reason": f"rebase classified {outcome}",
        }
        outcomes.append(record)
        item = deepcopy(cue)
        if outcome in {"preserved", "shifted"}:
            if new_ranges:
                item["start"]["ticks"] = int(new_ranges[0][0])
                item["end"]["ticks"] = int(new_ranges[-1][1])
            item["reviewState"] = "pending"
        else:
            item["reviewState"] = (
                "stale" if outcome == "removed" else "needs-human-judgment"
            )
            blockers.append(record)
        item["rebaseState"] = outcome
        proposed.append(item)
    return {
        "outcomes": outcomes,
        "proposedCues": proposed,
        "blockers": blockers,
        "safe": not blockers,
    }
