"""Bounded, metadata-only motion review; canonical artifacts retain authority."""

from __future__ import annotations

import json
import re
from copy import deepcopy
from fractions import Fraction
from html import escape
from importlib.resources import files
from string import Template

from .contracts import content_hash, document_hash_excluding, validate_document
from .store import atomic_write_json
from .workspace import ARTIFACTS

GENERATOR = {"id": "avo.motion-review", "version": "1.0.0"}
MAX_ITEMS = 500
LIFECYCLE = ("preEntry", "entrance", "hold", "payoff", "exit")
MAX_DOCUMENT_BYTES = 4 * 1024 * 1024
MAX_METADATA_BYTES = 8 * 1024 * 1024
CONTEXT_LIMITS = {
    "nodes": 40000,
    "depth": 24,
    "items": 4096,
    "text": 8192,
    "characters": 1024 * 1024,
}
METADATA_LIMITS = {
    "nodes": 200000,
    "depth": 32,
    "items": 20000,
    "text": 65536,
    "characters": MAX_DOCUMENT_BYTES,
}


class MotionReviewError(ValueError):
    pass


def _budget_text(value, limits, statistics):
    if not isinstance(value, str) or len(value) > limits["text"]:
        raise MotionReviewError("Metadata text budget exceeded")
    statistics["characters"] += len(value)
    if statistics["characters"] > limits["characters"]:
        raise MotionReviewError("Metadata character budget exceeded")


def _budget_children(value, limits, statistics):
    if isinstance(value, str):
        _budget_text(value, limits, statistics)
        return ()
    if isinstance(value, dict):
        if len(value) > limits["items"]:
            raise MotionReviewError("Metadata object budget exceeded")
        for key in value:
            _budget_text(key, limits, statistics)
        return value.values()
    if isinstance(value, list):
        if len(value) > limits["items"]:
            raise MotionReviewError("Metadata array budget exceeded")
        return value
    if value is not None and not isinstance(value, (int, float, bool)):
        raise MotionReviewError("Metadata must contain JSON values")
    return ()


def _check_budget(value, limits):
    stack, nodes, statistics = [(value, 0)], 0, {"characters": 0}
    while stack:
        current, depth = stack.pop()
        nodes += 1
        if nodes > limits["nodes"] or depth > limits["depth"]:
            raise MotionReviewError("Metadata node/depth budget exceeded")
        stack.extend(
            (child, depth + 1)
            for child in _budget_children(current, limits, statistics)
        )


def _bounded_json(path, budget):
    limit = min(MAX_DOCUMENT_BYTES, budget["remaining"])
    with path.open("rb") as stream:
        payload = stream.read(limit + 1)
    if len(payload) > limit:
        raise MotionReviewError("Metadata byte budget exceeded")
    budget["remaining"] -= len(payload)
    value = json.loads(payload)
    _check_budget(value, METADATA_LIMITS)
    return value


def _metadata_path(path, root):
    path = path.resolve()
    if not path.is_relative_to(root):
        raise MotionReviewError("Selected metadata path escapes timeline containment")
    return path


def _head_reference(index):
    head = index["headRevisionId"]
    reference = next(ref for ref in index["revisionRefs"] if ref["revisionId"] == head)
    return {
        "revisionId": head,
        "sha256": reference["contentSha256"],
        "activeState": index["activeState"],
        "approvedRevisionId": index["approvedRevisionId"],
    }, reference


def _unavailable_head(head):
    return {
        **(
            head
            or {
                "revisionId": None,
                "sha256": None,
                "activeState": "unavailable",
                "approvedRevisionId": None,
            }
        ),
        "availability": "unavailable",
    }


def _selected_revision(store, index, reference, root, budget):
    revision = _bounded_json(_metadata_path(root / reference["path"], root), budget)
    store._validate_revision(revision)
    if (
        revision["revisionId"] != index["headRevisionId"]
        or revision["contentSha256"] != reference["contentSha256"]
    ):
        raise MotionReviewError(
            "Selected revision identity differs from its index head"
        )
    snapshot = revision["snapshot"]
    if index["artifactType"] == "bmap":
        validate_document(
            snapshot.get("cues") or [],
            "avo.motion-review.schema.json#/$defs/canonicalCues",
        )
    if (
        index["artifactType"] == "animation"
        and snapshot.get("strategyContractVersion") is not None
    ):
        validate_document(snapshot, "avo.animation.schema.json")
    return snapshot


def _artifact_metadata(workspace, name, budget):
    head = None
    try:
        path = workspace.artifact_path(name)
        try:
            path.stat()
        except FileNotFoundError:
            return None, None, name + ":missing"
        root, store = workspace.timeline_dir.resolve(), workspace.store(name)
        index = _bounded_json(_metadata_path(path, root), budget)
        store._validate_index(index)
        expected = {
            "artifactType": name,
            "videoId": workspace.video_id,
            "provider": workspace.project.get("provider"),
        }
        if any(index[key] != value for key, value in expected.items()):
            raise MotionReviewError(
                "Selected artifact identity differs from its workspace"
            )
        if index["headRevisionId"] is None:
            return None, None, name + ":no-active-revision"
        head, reference = _head_reference(index)
        return head, _selected_revision(store, index, reference, root, budget), None
    except (OSError, ValueError, RuntimeError, RecursionError) as error:
        return (
            _unavailable_head(head),
            None,
            {"kind": "artifact-unavailable", "artifact": name, "detail": str(error)},
        )


def _matches_bytes(path, expected):
    if path.stat().st_size != len(expected):
        return False
    with path.open("rb") as stream:
        return stream.read(len(expected) + 1) == expected


def _proposal_count(context):
    if not isinstance(context, dict) or not isinstance(context.get("proposal"), dict):
        return 0
    items = context["proposal"].get("items")
    return len(items) if isinstance(items, list) else None


def _budget_context(context, gaps):
    try:
        _check_budget(context, CONTEXT_LIMITS)
        return context, False
    except MotionReviewError as error:
        gaps.append({"kind": "context-unavailable", "detail": str(error)})
        return {}, True


def _object(context, key, gaps):
    value = context.get(key)
    if value is not None and not isinstance(value, dict):
        gaps.append(f"context:{key}:invalid")
        return None
    return deepcopy(value)


def _text(value, default="Unresolved"):
    if value is None:
        return default
    return value if isinstance(value, str) else json.dumps(value, sort_keys=True)


def _assets(data):
    assets = deepcopy(data.get("assets") or [])
    if data.get("assetRef"):
        assets.append({"status": "declared", "source": deepcopy(data["assetRef"])})
    if any(
        asset.get("status") in {"missing", "unavailable", "restricted"}
        for asset in assets
    ):
        return assets, "missing"
    if assets:
        return assets, "declared"
    return assets, "not-required" if data.get("treatment") == "static" else "unresolved"


def _evidence(data, heads):
    evidence = data.get("evidence") or {}
    kind = evidence.get("type", "concept")
    if kind == "rendered-frame":
        # Caller assertions remain claims until a native evidence owner validates them.
        declared = evidence.get("basisHeads")
        basis = (
            "unavailable"
            if not isinstance(declared, dict)
            else "matches"
            if declared == heads
            else "stale"
        )
        return {
            "type": kind,
            "status": "unverified",
            "inspectionRef": deepcopy(evidence.get("inspectionRef")),
            "basisStatus": basis,
        }
    return {"type": "sketch" if kind == "sketch" else "concept", "status": "unverified"}


def _card(item, data, heads):
    lifecycle = _lifecycle(data)
    return {
        "itemId": item["itemId"],
        "label": item["label"],
        "concept": item["concept"],
        "layers": deepcopy(
            data.get("layers")
            or {"background": None, "middle": None, "foreground": None}
        ),
        "layout": deepcopy(data.get("layout")),
        "lifecycle": lifecycle,
        "camera": _camera_states(data),
        "sound": deepcopy(data.get("sound", data.get("audio"))),
        "assets": item["assets"],
        "evidence": _evidence(data, heads),
        "unresolvedFields": [key for key, value in lifecycle.items() if value is None]
        + ([] if data.get("layout") else ["layout"]),
    }


def _item(data, *, timed, stale, heads):
    identifier = str(data.get("itemId") or data.get("cueId") or "")
    if not identifier:
        raise MotionReviewError(
            "Motion review item requires a persistent itemId or cueId"
        )
    disposition, recorded, rebase = _disposition(data, stale)
    content = data.get("contentRef") or {}
    assets, readiness = _assets(data)
    item = {
        "itemId": identifier,
        "label": str(data.get("label") or identifier),
        "sectionId": _section_id(data),
        "concept": _text(data.get("concept", content.get("concept"))),
        "purpose": _text(data.get("purpose", data.get("intent"))),
        "treatment": _text(data.get("treatment", data.get("kind")), "undecided"),
        "timing": {"start": deepcopy(data["start"]), "end": deepcopy(data["end"])}
        if timed
        else None,
        "timingState": "timed" if timed else "provisional",
        "anchor": _anchor(data, timed),
        "camera": deepcopy(data.get("camera")),
        "sound": deepcopy(data.get("sound", data.get("audio"))),
        "assets": assets,
        "assetReadiness": readiness,
        "disposition": disposition,
        "recordedDisposition": recorded,
        "rebaseState": rebase,
        "cueId": data.get("cueId"),
        "componentRef": data.get("componentRef"),
        "targetLayerId": data.get("targetLayerId"),
    }
    item["parts"] = deepcopy(data.get("_parts", []))
    item["identityConflicts"] = deepcopy(data.get("_identityConflicts", []))
    if len(item["parts"]) > 1:
        item["timingState"] = "split"
    return item, _card(item, data, heads)


def _lanes(snapshot):
    return {
        kind: sorted(
            [deepcopy(layer) for layer in (snapshot.get(key) or {}).get("layers", [])],
            key=lambda layer: (layer.get("order", 0), layer.get("layerId", "")),
        )
        for kind, key in (("audio", "audioTracks"), ("video", "videoTracks"))
    }


def _stale(snapshots, heads):
    for name, dependency in (("bmap", "cmap"), ("tracks", "bmap")):
        basis = (snapshots.get(name) or {}).get("basis") or {}
        if basis.get("sha256") and basis["sha256"] != (heads.get(dependency) or {}).get(
            "sha256"
        ):
            return True
    return any(
        head
        and (
            head["activeState"] != "valid" or head.get("availability") == "unavailable"
        )
        for head in heads.values()
    )


def _section_id(data):
    return str(
        data.get("sectionId")
        or (data.get("contentRef") or {}).get("sectionId")
        or "unassigned"
    )


def _lifecycle(data):
    value = (
        data.get("lifecycle") or (data.get("animation") or {}).get("lifecycle") or {}
    )
    return {key: deepcopy(value.get(key)) for key in LIFECYCLE}


def _camera_states(data):
    camera = data.get("camera") or {}
    if not isinstance(camera, dict):
        camera = {"during": camera}
    return {key: deepcopy(camera.get(key)) for key in ("before", "during", "after")}


def _disposition(data, stale):
    recorded = str(data.get("disposition") or data.get("reviewState") or "proposed")
    rebase = data.get("rebaseState", "preserved")
    disposition = "stale" if stale else recorded
    if rebase in {"ambiguous", "unsupported"} or recorded == "needs-human-judgment":
        disposition = "needs-judgment"
    return disposition, recorded, rebase


def _anchor_type(spoken, timed, anchors):
    if spoken is not None:
        return "spoken"
    if timed:
        return "cut"
    return "source" if anchors else "unresolved"


def _anchor(data, timed):
    anchors = deepcopy(
        data.get("rawAnchors")
        or (data.get("rebaseHints") or {}).get("rawAnchors")
        or []
    )
    spoken = data.get("spokenTrigger")
    anchor = deepcopy(data.get("anchor") or {})
    anchor.setdefault("type", _anchor_type(spoken, timed, anchors))
    anchor.setdefault("spokenTrigger", spoken)
    anchor.setdefault("rawAnchors", anchors)
    return anchor


def _pending(context, gaps):
    value = context.get("pendingRevisions") or []
    if not isinstance(value, list):
        gaps.append("context:pendingRevisions:invalid")
        return []
    return value


def _applicability(context, gaps):
    value = context.get("applicability", "applicable")
    if value not in {"applicable", "explicitly-skipped", "unavailable-context"}:
        gaps.append("context:applicability:invalid")
        return "unavailable-context"
    return value


def _context(context, gaps):
    proposal_count = _proposal_count(context)
    context, unavailable = _budget_context(context, gaps)
    if context is not None and not isinstance(context, dict):
        gaps.append("context:invalid")
    context = context if isinstance(context, dict) else {}
    supplied = context.get("gaps") or []
    if isinstance(supplied, list):
        gaps.extend(deepcopy(supplied))
    else:
        gaps.append("context:gaps:invalid")
    result = {
        key: _object(context, key, gaps) for key in ("direction", "options", "proposal")
    }
    result["proposal"] = result["proposal"] or {}
    result["pendingRevisions"] = _pending(context, gaps)
    result["applicability"] = _applicability(context, gaps)
    result["coverageUnavailable"] = unavailable
    result["proposalDefinitionCount"] = proposal_count
    return result


def _proposals(proposal, gaps):
    proposed = proposal.get("items") or []
    if not isinstance(proposed, list) or any(
        not isinstance(item, dict) for item in proposed
    ):
        gaps.append("context:proposal-items:invalid")
        return []
    return proposed


def _combined(proposal, snapshots, gaps):
    groups = {}
    for item in _proposals(proposal, gaps):
        identifier = item.get("itemId")
        if not isinstance(identifier, str) or not 1 <= len(identifier) <= 128:
            gaps.append("context:proposal-identity:invalid")
            continue
        groups.setdefault(identifier, {"proposals": [], "cues": []})[
            "proposals"
        ].append(item)
    for cue in (snapshots.get("bmap") or {}).get("cues", []):
        identifier = str((cue.get("contentRef") or {}).get("itemId") or cue["cueId"])
        groups.setdefault(identifier, {"proposals": [], "cues": []})["cues"].append(cue)
    return groups


def _enrich_components(combined, animation):
    components = {
        component["componentId"]: component
        for component in animation.get("components", [])
    }
    for data in combined.values():
        component = components.get(data.get("componentRef")) or {}
        if component.get("lifecycle"):
            data.setdefault("lifecycle", deepcopy(component["lifecycle"]))
        if component.get("audioRelationship"):
            data.setdefault("sound", deepcopy(component["audioRelationship"]))


def _project_items(proposal, snapshots, heads, gaps):
    groups = _combined(proposal, snapshots, gaps)
    stale = _stale(snapshots, heads)
    if proposal.get("basisHeads") is not None and proposal["basisHeads"] != heads:
        stale = True
    sections = {
        name: index
        for index, name in enumerate(
            dict.fromkeys(_section_id(_group_seed(group)) for group in groups.values())
        )
    }
    ordered = sorted(groups.items(), key=lambda pair: _group_sort(pair, sections))
    selected = {
        identifier: _group_data(identifier, group)
        for identifier, group in ordered[:MAX_ITEMS]
    }
    _enrich_components(selected, snapshots.get("animation") or {})
    pairs = [
        _item(data, timed=len(data["_parts"]) == 1, stale=stale, heads=heads)
        for data in selected.values()
    ]
    counts = {
        "total": len(groups),
        "canonicalPartCount": sum(len(group["cues"]) for group in groups.values()),
    }
    return pairs, counts, stale


def _group_seed(group):
    if len(group["proposals"]) == 1:
        return group["proposals"][0]
    if len(group["cues"]) == 1:
        return group["cues"][0]
    sections = {_section_id(cue) for cue in group["cues"]}
    return {"sectionId": next(iter(sections)) if len(sections) == 1 else "unassigned"}


def _canonical_part(cue):
    return {
        "cueId": cue["cueId"],
        "timing": {"start": deepcopy(cue["start"]), "end": deepcopy(cue["end"])},
        "targetLayerId": cue["targetLayerId"],
        "componentRef": cue.get("componentRef"),
        "cue": deepcopy(cue),
    }


def _group_data(identifier, group):
    data = deepcopy(_group_seed(group))
    if len(group["cues"]) == 1:
        data.update(deepcopy(group["cues"][0]))
    if len(group["cues"]) > 1:
        data.update(
            {
                "concept": data.get(
                    "concept", "Split motion item; inspect every canonical part"
                ),
                "treatment": "split",
                "rebaseState": "split",
                "disposition": "needs-judgment",
                "anchor": {
                    "type": "split",
                    "spokenTrigger": None,
                    "rawAnchors": [],
                    "cueIds": [cue["cueId"] for cue in group["cues"]],
                },
            }
        )
    if len(group["proposals"]) > 1:
        data.update(
            {
                "concept": "Conflicting proposal definitions require review",
                "disposition": "needs-judgment",
                "label": identifier,
            }
        )
    data["itemId"] = identifier
    data["_parts"] = [_canonical_part(cue) for cue in group["cues"]]
    data["_identityConflicts"] = (
        deepcopy(group["proposals"]) if len(group["proposals"]) > 1 else []
    )
    return data


def _cue_seconds(cue):
    start = cue["start"]
    return Fraction(start["ticks"] * start["timebase"]["num"], start["timebase"]["den"])


def _group_sort(pair, sections):
    identifier, group = pair
    section = sections[_section_id(_group_seed(group))]
    if group["cues"]:
        return 0, min(_cue_seconds(cue) for cue in group["cues"]), section, identifier
    return 1, Fraction(0), section, identifier


def _unavailable_artifacts(gaps):
    return {
        gap["artifact"]
        for gap in gaps
        if isinstance(gap, dict) and gap.get("kind") == "artifact-unavailable"
    }


def _coverage(pairs, counts, context, gaps):
    unavailable = _unavailable_artifacts(gaps)
    unknown = (
        context["coverageUnavailable"]
        or "bmap" in unavailable
        or context["proposalDefinitionCount"] is None
    )
    total = None if unknown else counts["total"]
    return {
        "shown": len(pairs),
        "total": total,
        "canonicalPartCount": None
        if "bmap" in unavailable
        else counts["canonicalPartCount"],
        "proposalDefinitionCount": context["proposalDefinitionCount"],
        "complete": total is not None and len(pairs) == total and not gaps,
    }


def _projection_readiness(items, snapshots, stale, context, gaps):
    if context["coverageUnavailable"] or _unavailable_artifacts(gaps):
        return "unavailable"
    return _readiness(items, snapshots, stale)


def _resolved(items, snapshots):
    return (
        "tracks" in snapshots
        and "animation" in snapshots
        and all(
            item["assetReadiness"] in {"declared", "not-required"} for item in items
        )
    )


def _readiness(items, snapshots, stale):
    readiness = (
        "timed-unresolved" if any(item["timing"] for item in items) else "conceptual"
    )
    if readiness == "timed-unresolved" and _resolved(items, snapshots):
        readiness = "resolved"
    if stale:
        readiness = "stale"
    if any(item["disposition"] == "needs-judgment" for item in items):
        readiness = "needs-judgment"
    return readiness


class MotionReviewService:
    def __init__(self, workspace):
        self.workspace = workspace

    def _metadata(self, *, snapshots=True):
        heads, bodies, gaps = {}, {}, []
        budget = {"remaining": MAX_METADATA_BYTES}
        for name in ARTIFACTS:
            head, body, gap = _artifact_metadata(self.workspace, name, budget)
            heads[name] = head
            if snapshots and body is not None:
                bodies[name] = body
            if gap is not None:
                gaps.append(gap)
        return heads, bodies, gaps

    def project(self, context=None):
        heads, snapshots, gaps = self._metadata()
        context = _context(context, gaps)
        pairs, counts, stale = _project_items(
            context["proposal"], snapshots, heads, gaps
        )
        items, cards = [pair[0] for pair in pairs], [pair[1] for pair in pairs]
        snapshot = {
            "schemaVersion": "1.0.0",
            "snapshotHash": "",
            "generator": deepcopy(GENERATOR),
            "videoId": self.workspace.video_id,
            "provider": str(self.workspace.project.get("provider") or ""),
            "basisHeads": heads,
            "applicability": context["applicability"],
            "readiness": _projection_readiness(items, snapshots, stale, context, gaps),
            "direction": context["direction"],
            "options": context["options"],
            "items": items,
            "storyboardCards": cards,
            "lanes": _lanes(snapshots.get("tracks") or {}),
            "gaps": [
                value
                for _, value in sorted(
                    {json.dumps(value, sort_keys=True): value for value in gaps}.items()
                )
            ],
            "pendingRevisions": deepcopy(context["pendingRevisions"]),
            "coverage": _coverage(pairs, counts, context, gaps),
        }
        snapshot["snapshotHash"] = document_hash_excluding(snapshot, "snapshotHash")
        validate_document(snapshot, "avo.motion-review.schema.json")
        return snapshot

    def _directory(self, snapshot):
        digest = snapshot.get("snapshotHash")
        if not isinstance(digest, str) or not re.fullmatch(r"[a-f0-9]{64}", digest):
            raise MotionReviewError("Invalid motion snapshot hash")
        if digest != document_hash_excluding(snapshot, "snapshotHash"):
            raise MotionReviewError("Motion snapshot hash differs from its payload")
        validate_document(snapshot, "avo.motion-review.schema.json")
        raw, review = (
            self.workspace.raw_dir.resolve(),
            self.workspace.review_dir.resolve(),
        )
        target = (review / "motion-plan" / digest).resolve()
        if not review.is_relative_to(raw) or not target.is_relative_to(review):
            raise MotionReviewError("Motion report containment failed")
        for name in ("snapshot.json", "review.md", "review.html", "review.css"):
            if (target / name).resolve().parent != target:
                raise MotionReviewError("Motion report child containment failed")
        return target

    @staticmethod
    def _snapshot_matches(path, snapshot):
        expected = (
            json.dumps(snapshot, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
        ).encode("utf-8")
        return _matches_bytes(path, expected)

    def report_status(self, snapshot):
        target = self._directory(snapshot)
        refs = {
            key: str(target / name)
            for key, name in (
                ("snapshot", "snapshot.json"),
                ("text", "review.md"),
                ("visual", "review.html"),
            )
        }
        if not all(
            (target / name).is_file()
            for name in ("snapshot.json", "review.md", "review.html", "review.css")
        ):
            return {"freshness": "missing", "refs": {}, "warnings": []}
        try:
            contents = _report_contents(snapshot)
            if not self._snapshot_matches(target / "snapshot.json", snapshot):
                raise MotionReviewError("Mismatching immutable motion report")
            for name, content in contents.items():
                path = target / name
                if not _matches_bytes(path, content.encode("utf-8")):
                    raise MotionReviewError(
                        f"Mismatching immutable motion report: {name}"
                    )
        except (OSError, ValueError) as error:
            return {"freshness": "invalid", "refs": {}, "warnings": [str(error)]}
        current = self._metadata(snapshots=False)[0]
        freshness = "current" if current == snapshot["basisHeads"] else "historical"
        return {"freshness": freshness, "refs": refs, "warnings": []}

    @staticmethod
    def _write_immutable(path, content):
        if path.exists():
            if not _matches_bytes(path, content.encode("utf-8")):
                raise MotionReviewError(f"Mismatching immutable motion report: {path}")
            return
        with path.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(content)

    def publish(self, snapshot=None, expected_basis=None):
        snapshot = deepcopy(snapshot) if snapshot is not None else self.project()
        target = self._directory(snapshot)
        if expected_basis is not None and expected_basis != snapshot["basisHeads"]:
            raise MotionReviewError(
                "Expected basis differs from the selected motion snapshot"
            )
        target.mkdir(parents=True, exist_ok=True)
        path = target / "snapshot.json"
        if path.exists():
            try:
                matching = self._snapshot_matches(path, snapshot)
            except (OSError, ValueError):
                matching = False
            if not matching:
                raise MotionReviewError(f"Mismatching immutable motion report: {path}")
        else:
            atomic_write_json(path, snapshot)
        for name, content in _report_contents(snapshot).items():
            self._write_immutable(target / name, content)
        report = self.report_status(snapshot)
        warnings = report["warnings"]
        if report["freshness"] == "historical":
            warnings = [
                *warnings,
                "Canonical heads changed; report retained as historical, not current review approval",
            ]
        return {
            "status": "published" if report["freshness"] == "current" else "stale",
            "snapshot": snapshot,
            **report,
            "warnings": warnings,
        }


def render_text(snapshot):
    lines = [
        f"Motion plan: {snapshot['videoId']}",
        f"Readiness: {snapshot['readiness']}",
        f"Applicability: {snapshot['applicability']}",
        "",
    ]
    for item, card in zip(snapshot["items"], snapshot["storyboardCards"], strict=True):
        lines.extend(
            [
                f"{item['label']} ({item['itemId']}) | {item['sectionId']} | {item['disposition']}",
                f"Purpose: {item['purpose']}",
                f"Treatment: {item['treatment']}; timing: {_text(item['timing'], 'provisional')}",
                f"Anchor: {_text(item['anchor'])}",
                f"Concept: {card['concept']}",
                f"Layers: {_text(card['layers'])}",
                f"Layout: {_text(card['layout'])}",
                f"Lifecycle: {_text(card['lifecycle'])}",
                f"Camera: {_text(card['camera'])}",
                f"Sound: {_text(card['sound'])}",
                f"Assets ({item['assetReadiness']}): {_text(card['assets'])}",
                f"Canonical parts (exact BMap ranges): {_text(item['parts'])}",
                f"Non-authoritative proposal identity conflicts: {_text(item['identityConflicts'])}",
                f"Evidence: {_text(card['evidence'])}",
                f"Unresolved: {', '.join(card['unresolvedFields'])}",
                "",
            ]
        )
    lines.extend(
        [
            "Tracks",
            json.dumps(snapshot["lanes"], indent=2, sort_keys=True),
            "Pending revisions",
            json.dumps(snapshot["pendingRevisions"], indent=2, sort_keys=True),
            "Gaps",
            *(_text(gap) for gap in snapshot["gaps"]),
            f"Shown: {snapshot['coverage']['shown']} / {snapshot['coverage']['total']}",
        ]
    )
    return "\n".join(lines) + "\n"


def render_html(snapshot):
    template = (
        files("avo")
        .joinpath("templates/motion_review/review.html")
        .read_text(encoding="utf-8")
    )
    map_rows, cards = [], []
    for item, card in zip(snapshot["items"], snapshot["storyboardCards"], strict=True):
        anchor = "item-" + content_hash(item["itemId"])
        map_rows.append(
            f'<li><a href="#{anchor}">{escape(item["label"])}</a> '
            f"{escape(item['sectionId'])} | {escape(item['treatment'])} | "
            f"{escape(item['disposition'])} | {escape(_text(item['timing'], 'provisional'))}</li>"
        )
        fields = {
            "Canonical parts (exact BMap ranges)": item["parts"],
            "Non-authoritative proposal identity conflicts": item["identityConflicts"],
            "Purpose": item["purpose"],
            "Anchor": item["anchor"],
            "Layers": card["layers"],
            "Layout": card["layout"],
            "Lifecycle": card["lifecycle"],
            "Camera": card["camera"],
            "Sound": card["sound"],
            "Assets": card["assets"],
            "Evidence": card["evidence"],
            "Unresolved": card["unresolvedFields"],
        }
        descriptions = "".join(
            f"<dt>{escape(key)}</dt><dd>{escape(_text(value))}</dd>"
            for key, value in fields.items()
        )
        cards.append(
            f'<article id="{anchor}"><h3>{escape(card["label"])}</h3>'
            f"<p>{escape(card['concept'])}</p><dl>{descriptions}</dl></article>"
        )
    return Template(template).substitute(
        title=escape(f"Motion plan: {snapshot['videoId']}"),
        map_rows="".join(map_rows),
        cards="".join(cards),
        content=escape(render_text(snapshot)),
    )


def _report_contents(snapshot):
    return {
        "review.md": render_text(snapshot),
        "review.html": render_html(snapshot),
        "review.css": files("avo")
        .joinpath("templates/motion_review/review.css")
        .read_text(encoding="utf-8"),
    }
