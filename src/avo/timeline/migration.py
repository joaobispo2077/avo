"""Additive, dry-run-safe migration from legacy EDL into canonical artifacts."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .contracts import content_hash, file_fingerprint, validate_document
from .store import atomic_write_json, now_iso


def _file_time(path: Path) -> str:
    value = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
    return value.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _tv(seconds: float, source_id: str) -> dict[str, Any]:
    ticks = round(float(seconds) * 1000)
    return {
        "ticks": ticks,
        "timebase": {"num": 1, "den": 1000},
        "domain": "raw-source",
        "sourceId": source_id,
    }


def legacy_edl_to_cmap(
    edl: dict[str, Any],
    *,
    edl_path: Path,
    video_id: str,
    provider: str,
) -> tuple[dict[str, Any], list[str]]:
    unresolved: list[str] = []
    sources = []
    for source_id, locator in (edl.get("sources") or {}).items():
        path = (edl_path.parent / str(locator)).resolve()
        if path.is_file():
            fingerprint = file_fingerprint(path)
        else:
            unresolved.append(str(source_id))
            fingerprint = {"sha256": "0" * 64, "sizeBytes": 0, "locator": str(locator)}
        sources.append(
            {
                "sourceId": str(source_id),
                "kind": "raw",
                "fingerprint": fingerprint,
                "locator": str(locator),
            }
        )
    segments = []
    for index, item in enumerate(edl.get("ranges") or [], start=1):
        source_id = str(item["source"])
        segment = {
            "segmentId": f"legacy-segment-{index:04d}",
            "sourceId": source_id,
            "in": _tv(float(item["start"]), source_id),
            "out": _tv(float(item["end"]), source_id),
            "reason": "Imported legacy kept range; editorial reason unknown",
        }
        if item.get("story_section_id"):
            segment["storySectionId"] = str(item["story_section_id"])
        segments.append(segment)
    snapshot = {"sources": sources, "segments": segments}
    revision = {
        "revisionId": "r0001",
        "parentRevisionId": None,
        "createdAt": _file_time(edl_path),
        "actor": "avo-migrate-timeline",
        "reason": "Import legacy EDL ranges without inferring approval",
        "snapshot": snapshot,
        "diff": [],
        "dependencies": [],
        "evidence": [],
        "state": "blocked" if unresolved else "unknown",
    }
    revision["contentHash"] = content_hash(revision)
    artifact = {
        "schemaVersion": "1.0.0",
        "artifactType": "cmap",
        "artifactId": "cmap-main",
        "videoId": video_id,
        "provider": provider,
        "timelineDomain": "raw-source",
        "currentRevisionId": revision["revisionId"],
        "approvedRevisionId": None,
        "revisions": [revision],
        "decisions": [],
    }
    return artifact, unresolved


def migrate_legacy_edl(
    edl_path: Path,
    target: Path,
    *,
    video_id: str,
    provider: str,
    dry_run: bool = True,
) -> dict[str, Any]:
    edl_path = Path(edl_path)
    target = Path(target)
    edl = json.loads(edl_path.read_text(encoding="utf-8"))
    artifact, unresolved = legacy_edl_to_cmap(
        edl,
        edl_path=edl_path,
        video_id=video_id,
        provider=provider,
    )
    idempotent = False
    if target.is_file():
        existing = json.loads(target.read_text(encoding="utf-8"))
        if existing == artifact:
            idempotent = True
            artifact = existing
        elif not dry_run:
            raise ValueError(f"canonical target already differs: {target}")
    elif not dry_run:
        atomic_write_json(target, artifact)
    return {
        "dryRun": dry_run,
        "idempotent": idempotent,
        "sourceEdl": str(edl_path),
        "target": str(target),
        "approvalStatus": "unknown",
        "unresolvedFingerprints": unresolved,
        "artifact": artifact,
    }


def import_legacy_sync_map(
    payload: dict[str, Any], *, video_id: str, provider: str
) -> dict[str, Any]:
    """Import verifiable calibration facts without helper/script dependency or approval."""
    snapshot = {
        key: payload[key]
        for key in (
            "picture",
            "audio",
            "referenceClock",
            "signConvention",
            "transform",
            "calibrationSamples",
            "toleranceTicks",
            "fullProgramValidation",
        )
        if key in payload
    }
    revision = {
        "revisionId": "r0001",
        "parentRevisionId": None,
        "createdAt": payload.get("createdAt") or "1970-01-01T00:00:00Z",
        "actor": "avo-migrate-timeline",
        "reason": "Import verified legacy sync facts without inferring approval",
        "snapshot": snapshot,
        "diff": [],
        "dependencies": [],
        "evidence": [],
        "state": "unknown",
    }
    revision["contentHash"] = content_hash(revision)
    return {
        "schemaVersion": "1.0.0",
        "artifactType": "sync-map",
        "artifactId": "sync-main",
        "videoId": video_id,
        "provider": provider,
        "timelineDomain": "raw-source",
        "currentRevisionId": "r0001",
        "approvedRevisionId": None,
        "revisions": [revision],
        "decisions": [],
    }


def _output_tv(seconds: float) -> dict[str, Any]:
    return {
        "ticks": round(float(seconds) * 1000),
        "timebase": {"num": 1, "den": 1000},
        "domain": "cmap-output",
    }


def legacy_edl_snapshots(
    edl: dict[str, Any], *, edl_path: Path
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    """Extract every representable legacy domain without inventing approval."""
    from avo.edl_timeline import parse_ranges, source_to_output

    cmap, unresolved = legacy_edl_to_cmap(
        edl,
        edl_path=edl_path,
        video_id="migration",
        provider="migration",
    )
    findings = [
        {
            "classification": "unresolved-source",
            "message": f"source fingerprint unresolved: {source_id}",
        }
        for source_id in unresolved
    ]
    ranges = parse_ranges(edl)
    cues = []
    audio_layers = []
    video_layers = []
    ordinal = 0
    for collection, kind in (("overlays", "insert-image"), ("sound_effects", "sfx")):
        for item in edl.get(collection) or []:
            ordinal += 1
            start = item.get("start_in_output")
            if start is None and item.get("anchor_in_source") is not None:
                start = source_to_output(
                    ranges,
                    float(item["anchor_in_source"]),
                    source=str(item.get("anchor_source"))
                    if item.get("anchor_source")
                    else None,
                )
            if start is None:
                findings.append(
                    {
                        "classification": "unsupported-timing",
                        "message": f"{collection} item {ordinal} has no resolvable B-time",
                    }
                )
                continue
            duration = max(
                0.05, float(item.get("duration") or item.get("duration_seconds") or 1.0)
            )
            cue_id = f"legacy-cue-{ordinal:04d}"
            locator = str(item.get("file") or item.get("path") or "")
            cue = {
                "cueId": cue_id,
                "kind": kind,
                "start": _output_tv(float(start)),
                "end": _output_tv(float(start) + duration),
                "targetLayerId": "audio-sfx" if kind == "sfx" else "video-inserts",
                "intent": "Imported legacy cue; intent unknown",
                "reason": "Legacy EDL migration",
                "reviewState": "pending",
            }
            if locator:
                asset = (edl_path.parent / locator).resolve()
                if asset.is_file():
                    cue["assetRef"] = {
                        "locator": locator,
                        "sha256": file_fingerprint(asset)["sha256"],
                        "sizeBytes": asset.stat().st_size,
                    }
                else:
                    findings.append(
                        {
                            "classification": "unresolved-asset",
                            "message": f"asset missing: {locator}",
                        }
                    )
            cues.append(cue)
            layer = {
                "layerId": cue["targetLayerId"],
                "role": "sfx" if kind == "sfx" else "insert",
                "cueIds": [cue_id],
                "range": {"start": cue["start"], "end": cue["end"]},
                "legacy": dict(item),
            }
            (audio_layers if kind == "sfx" else video_layers).append(layer)
    if edl.get("subtitles"):
        ordinal += 1
        cues.append(
            {
                "cueId": f"legacy-cue-{ordinal:04d}",
                "kind": "caption",
                "start": _output_tv(0),
                "end": _output_tv(sum(item.duration for item in ranges)),
                "targetLayerId": "captions",
                "intent": "Imported subtitle track",
                "reason": "Legacy EDL migration",
                "reviewState": "pending",
                "assetRef": {"locator": str(edl["subtitles"])},
            }
        )
        video_layers.append(
            {
                "layerId": "captions",
                "role": "caption",
                "cueIds": [f"legacy-cue-{ordinal:04d}"],
                "legacy": {"subtitles": edl["subtitles"]},
            }
        )
    snapshots = {
        "cmap": cmap["revisions"][0]["snapshot"],
        "bmap": {
            "migrationBasis": {"approvalStatus": "unknown"},
            "cues": cues,
        },
        "tracks": {
            "migrationBasis": {"approvalStatus": "unknown"},
            "audioTracks": {"layers": audio_layers},
            "videoTracks": {"layers": video_layers},
            "legacyAudio": edl.get("audio") or {},
        },
        "animation": {
            "migrationBasis": {"approvalStatus": "unknown"},
            "formatDiagnosis": {"status": "unknown"},
            "strategy": edl.get("motion_policy") or {},
            "components": [],
        },
        "sync-map": {
            "migrationStatus": "unknown",
            "facts": {
                key: value
                for key, value in (edl.get("sync_map") or {}).items()
                if key not in {"script", "helper", "command"}
            },
        },
    }
    known = {
        "version",
        "feature_id",
        "story_map_approval",
        "sources",
        "ranges",
        "grade",
        "overlays",
        "sound_effects",
        "subtitles",
        "audio",
        "caption_burn_in",
        "caption_policy",
        "motion_policy",
        "render_gate",
        "review_package",
        "blocked_source_ranges",
        "ad_segment",
        "sync_map",
    }
    for field in sorted(set(edl) - known):
        findings.append(
            {
                "classification": "unsupported-field",
                "message": f"legacy field retained only in source EDL: {field}",
            }
        )
    return snapshots, findings


class MigrationService:
    VERSION = "1.0.0"

    def __init__(self, workspace: Any, edl_path: Path):
        self.workspace = workspace
        self.edl_path = Path(edl_path).resolve()
        self.path = workspace.timeline_dir / "migration.json"

    def _source(self) -> dict[str, Any]:
        value = file_fingerprint(self.edl_path)
        return {
            "path": str(self.edl_path),
            "sha256": value["sha256"],
            "sizeBytes": value["sizeBytes"],
        }

    def _config_hash(self) -> str:
        return content_hash(
            {
                "videoId": self.workspace.video_id,
                "provider": self.workspace.project.get("provider"),
                "toolVersion": self.VERSION,
            }
        )

    def plan(self) -> dict[str, Any]:
        edl = json.loads(self.edl_path.read_text(encoding="utf-8"))
        snapshots, findings = legacy_edl_snapshots(edl, edl_path=self.edl_path)
        return {
            "dryRun": True,
            "status": "dry-run-passed",
            "source": self._source(),
            "tool": {
                "name": "avo-migrate-timeline",
                "version": self.VERSION,
                "configSha256": self._config_hash(),
            },
            "approvalStatus": "unknown",
            "snapshots": snapshots,
            "findings": findings,
            "writes": [],
        }

    inspect = plan

    def _load_manifest(self) -> dict[str, Any] | None:
        if not self.path.is_file():
            return None
        value = json.loads(self.path.read_text(encoding="utf-8"))
        validate_document(value, "avo.timeline-migration.schema.json")
        return value

    def apply(self, *, actor: str, reason: str) -> dict[str, Any]:
        plan = self.plan()
        existing = self._load_manifest()
        if existing is not None:
            same = (
                existing["source"]["sha256"] == plan["source"]["sha256"]
                and existing["tool"]["configSha256"] == plan["tool"]["configSha256"]
            )
            if same and existing["status"] in {
                "applied-unverified",
                "validated",
                "canonical-active",
            }:
                return {**existing, "idempotent": True}
            raise ValueError(
                "migration source/config changed or target collision exists"
            )
        original_hash = plan["source"]["sha256"]
        self.workspace.initialize()
        for artifact_type in ("cmap", "bmap", "tracks", "animation", "sync-map"):
            index = self.workspace.store(artifact_type).load_index()
            if index["headRevisionId"] is not None:
                raise ValueError(f"canonical target collision: {artifact_type}")
        outputs = []
        for artifact_type, snapshot in plan["snapshots"].items():
            revision = self.workspace.store(artifact_type).append_revision(
                snapshot=snapshot,
                actor={"type": "migration", "id": actor, "toolVersion": self.VERSION},
                reason=reason,
                created_at=now_iso(),
            )
            outputs.append(
                {
                    "artifactType": artifact_type,
                    "path": str(self.workspace.artifact_path(artifact_type)),
                    "sha256": revision["contentHash"],
                }
            )
        if file_fingerprint(self.edl_path)["sha256"] != original_hash:
            raise ValueError("legacy EDL changed during migration apply")
        timestamp = now_iso()
        manifest = {
            "schemaVersion": "1.0.0",
            "migrationId": f"{self.workspace.video_id}-timeline-migration",
            "status": "applied-unverified",
            "source": plan["source"],
            "tool": plan["tool"],
            "outputs": outputs,
            "findings": plan["findings"],
            "history": [
                {
                    "from": "not-started",
                    "to": "assessed",
                    "occurredAt": timestamp,
                    "actor": actor,
                    "reason": reason,
                },
                {
                    "from": "assessed",
                    "to": "dry-run-passed",
                    "occurredAt": timestamp,
                    "actor": actor,
                    "reason": reason,
                },
                {
                    "from": "dry-run-passed",
                    "to": "applied-unverified",
                    "occurredAt": timestamp,
                    "actor": actor,
                    "reason": reason,
                },
            ],
            "authority": "legacy",
            "legacyPreservedSha256": original_hash,
            "parity": None,
            "confirmation": None,
        }
        validate_document(manifest, "avo.timeline-migration.schema.json")
        atomic_write_json(self.path, manifest)
        return manifest

    def validate(self, *, actor: str, reason: str) -> dict[str, Any]:
        manifest = self._load_manifest()
        if manifest is None or manifest["status"] not in {
            "applied-unverified",
            "validated",
        }:
            raise ValueError("migration must be applied before validation")
        if (
            file_fingerprint(self.edl_path)["sha256"]
            != manifest["legacyPreservedSha256"]
        ):
            raise ValueError("legacy EDL bytes changed after migration")
        edl = json.loads(self.edl_path.read_text(encoding="utf-8"))
        cmap = self.workspace.store("cmap").revision(
            self.workspace.store("cmap").load_index()["headRevisionId"]
        )["snapshot"]
        expected = [
            (
                str(item["source"]),
                round(float(item["start"]), 3),
                round(float(item["end"]), 3),
            )
            for item in edl.get("ranges") or []
        ]
        actual = [
            (
                str(item["sourceId"]),
                round(
                    item["in"]["ticks"]
                    * item["in"]["timebase"]["num"]
                    / item["in"]["timebase"]["den"],
                    3,
                ),
                round(
                    item["out"]["ticks"]
                    * item["out"]["timebase"]["num"]
                    / item["out"]["timebase"]["den"],
                    3,
                ),
            )
            for item in cmap.get("segments") or []
        ]
        unresolved = [
            source["sourceId"]
            for source in cmap.get("sources") or []
            if source.get("fingerprint", {}).get("sha256") == "0" * 64
        ]
        parity = {
            "rangesEqual": actual == expected,
            "expectedRanges": len(expected),
            "actualRanges": len(actual),
            "durationDeltaSeconds": abs(
                sum(end - start for _, start, end in expected)
                - sum(end - start for _, start, end in actual)
            ),
            "unresolvedSources": unresolved,
        }
        if (
            not parity["rangesEqual"]
            or parity["durationDeltaSeconds"] > 0.001
            or unresolved
        ):
            raise ValueError(f"migration parity validation blocked: {parity}")
        updated = dict(manifest)
        updated["status"] = "validated"
        updated["parity"] = parity
        updated["history"] = [
            *manifest["history"],
            {
                "from": manifest["status"],
                "to": "validated",
                "occurredAt": now_iso(),
                "actor": actor,
                "reason": reason,
            },
        ]
        validate_document(updated, "avo.timeline-migration.schema.json")
        atomic_write_json(self.path, updated)
        return updated

    def activate(
        self, *, actor: str, reason: str, confirm_unknown_approvals: bool
    ) -> dict[str, Any]:
        manifest = self._load_manifest()
        if manifest is None or manifest["status"] != "validated":
            raise ValueError(
                "only a validated migration can activate canonical authority"
            )
        if not confirm_unknown_approvals:
            raise ValueError(
                "explicit confirmation is required because legacy approvals are unknown"
            )
        project = json.loads(self.workspace.project_path.read_text(encoding="utf-8"))
        timeline = dict(project.get("timeline") or {})
        migration = dict(timeline.get("migration") or {})
        timeline["canonicalFirst"] = True
        migration["allowLegacyEdlFallback"] = False
        timeline["migration"] = migration
        project["timeline"] = timeline
        atomic_write_json(self.workspace.project_path, project)
        updated = dict(manifest)
        updated["status"] = "canonical-active"
        updated["authority"] = "canonical"
        updated["confirmation"] = {
            "actor": actor,
            "reason": reason,
            "occurredAt": now_iso(),
            "unknownApprovalsAcceptedAsPending": True,
        }
        updated["history"] = [
            *manifest["history"],
            {
                "from": "validated",
                "to": "canonical-active",
                "occurredAt": now_iso(),
                "actor": actor,
                "reason": reason,
            },
        ]
        validate_document(updated, "avo.timeline-migration.schema.json")
        atomic_write_json(self.path, updated)
        return updated

    def rollback(self, *, actor: str, reason: str) -> dict[str, Any]:
        manifest = self._load_manifest()
        if manifest is None:
            raise ValueError("migration manifest is missing")
        project = json.loads(self.workspace.project_path.read_text(encoding="utf-8"))
        timeline = dict(project.get("timeline") or {})
        migration = dict(timeline.get("migration") or {})
        timeline["canonicalFirst"] = False
        migration["allowLegacyEdlFallback"] = True
        timeline["migration"] = migration
        project["timeline"] = timeline
        atomic_write_json(self.workspace.project_path, project)
        updated = dict(manifest)
        updated["status"] = "rolled-back"
        updated["authority"] = "legacy"
        updated["history"] = [
            *manifest["history"],
            {
                "from": manifest["status"],
                "to": "rolled-back",
                "occurredAt": now_iso(),
                "actor": actor,
                "reason": reason,
            },
        ]
        validate_document(updated, "avo.timeline-migration.schema.json")
        atomic_write_json(self.path, updated)
        return updated
