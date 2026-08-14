"""Video animation strategy and explicit sanitized provider pattern promotion."""
from __future__ import annotations
from copy import deepcopy
from datetime import datetime,timezone
from typing import Any
class AnimationError(ValueError):pass
_FORBIDDEN={"text","timestamps","timing","claims","screenshots","footage","media","projectPath","assetPath"}
def _keys(value:Any)->set[str]:
 if isinstance(value,dict):
  result=set(value)
  for child in value.values():result|=_keys(child)
  return result
 if isinstance(value,list):
  result=set()
  for child in value:result|=_keys(child)
  return result
 return set()
def promote_pattern(pattern:dict[str,Any],*,actor:str,approval_reference:str)->dict[str,Any]:
 if not actor or not approval_reference:raise AnimationError("explicit creator promotion approval required")
 forbidden=_keys(pattern)&_FORBIDDEN
 if forbidden:raise AnimationError("provider pattern contains project-specific content: "+", ".join(sorted(forbidden)))
 required={"patternId","name","behavior","contexts","exclusions","requiredAssets","accessibility","exemplars"}
 missing=required-set(pattern)
 if missing:raise AnimationError("pattern missing generalized fields: "+", ".join(sorted(missing)))
 result=deepcopy(pattern);result["promotion"]={"actor":actor,"promotedAt":datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00","Z"),"approvalReference":approval_reference};return result
def recommend_patterns(patterns:list[dict[str,Any]],diagnosis:dict[str,Any]|None)->list[dict[str,Any]]:
 if not diagnosis or not diagnosis.get("format"):raise AnimationError("format diagnosis required before animation recommendation")
 format_=diagnosis["format"];constraints=set(diagnosis.get("constraints") or [])
 return [deepcopy(p) for p in patterns if format_ in p.get("contexts",[]) and not constraints.intersection(p.get("exclusions",[]))]


_TIMING_FIELDS = {"start", "end", "startTicks", "endTicks", "timestamp", "timestamps", "timing"}


def _assert_no_timing(value: Any) -> None:
    forbidden = _keys(value) & _TIMING_FIELDS
    if forbidden:
        raise AnimationError(
            "video animation strategy cannot own cue timing: " + ", ".join(sorted(forbidden))
        )


class AnimationService:
    def __init__(self, workspace: Any):
        self.workspace = workspace
        self.store = workspace.store("animation")

    def _dependencies(self) -> dict[str, str]:
        bmap_index = self.workspace.require_active("bmap")
        tracks_index = self.workspace.require_active("tracks")
        bmap = self.workspace.store("bmap").revision(bmap_index["headRevisionId"])
        tracks = self.workspace.store("tracks").revision(tracks_index["headRevisionId"])
        cmap_hash = str((tracks["snapshot"].get("cmapBasis") or {}).get("sha256") or "")
        if len(cmap_hash) != 64:
            raise AnimationError("Animation requires exact inherited CMap basis")
        return {
            "cmap": cmap_hash,
            "bmap": bmap["contentHash"],
            "tracks": tracks["contentHash"],
        }

    def author(self, strategy: dict[str, Any], *, actor: str, reason: str) -> dict[str, Any]:
        from .lineage import persist_invalidation

        value = deepcopy(strategy)
        _assert_no_timing(value)
        diagnosis = value.get("formatDiagnosis") or {}
        if not diagnosis.get("format") or not diagnosis.get("viewerIntent"):
            raise AnimationError("animation strategy requires format diagnosis and viewer intent")
        if not value.get("components"):
            raise AnimationError("animation strategy requires declared components")
        for component in value["components"]:
            lifecycle = component.get("lifecycle") or {}
            if not all(key in lifecycle for key in ("preEntry", "entrance", "hold", "exit")):
                raise AnimationError("every component requires pre-entry/entrance/hold/exit")
        dependencies = self._dependencies()
        value["dependencies"] = dependencies
        index = self.store.load_index()
        expected = None
        if index["headRevisionId"]:
            expected = self.store.revision(index["headRevisionId"])["contentHash"]
        basis = []
        for artifact_type in ("cmap", "bmap", "tracks"):
            store = self.workspace.store(artifact_type)
            active = store.load_index()
            revision_id = active["headRevisionId"]
            basis.append(
                {
                    "artifactType": artifact_type,
                    "artifactId": active["artifactId"],
                    "revisionId": revision_id,
                    "contentSha256": dependencies[artifact_type],
                }
            )
        revision = self.store.append_revision(
            snapshot=value,
            actor=actor,
            reason=reason,
            dependencies=basis,
            expected_head_hash=expected,
        )
        if expected and expected != revision["contentHash"]:
            self.workspace.invalidate_descendants(
                "animation",
                before_hash=expected,
                after_hash=revision["contentHash"],
                reason="Animation strategy changed",
                actor=actor,
            )
        return revision

    @staticmethod
    def recommend(
        catalog: dict[str, Any],
        diagnosis: dict[str, Any],
        *,
        evidence_sha256: str,
    ) -> list[dict[str, Any]]:
        rejected = {
            (event["patternId"], event.get("evidenceSha256"))
            for event in catalog.get("events") or []
            if event.get("type") == "recommendation-rejected"
        }
        return [
            pattern
            for pattern in recommend_patterns(catalog.get("patterns") or [], diagnosis)
            if (pattern["patternId"], evidence_sha256) not in rejected
        ]
