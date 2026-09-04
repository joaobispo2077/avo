"""Deterministic picture ancestry built from actual timeline contributors."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from .contracts import content_hash, file_fingerprint
from .tracks import compile_video_layers

REVISION_TYPES = ("sync-map", "cmap", "bmap", "tracks")
SUPPORTED_BASE_TRANSFORMS = frozenset(
    {"crop", "reframe", "rotate", "scale", "scale-down", "grade/color"}
)


class PictureLineageError(ValueError):
    """Raised when canonical picture ancestry cannot be proven."""


def _hash(value: Any) -> str:
    return content_hash(value)


def _media_class(value: dict[str, Any], *, default: str) -> str:
    provenance = value.get("provenance") or {}
    return str(provenance.get("mediaClass") or default)


def _node_sha(source: dict[str, Any], locator: str, fallback: Any) -> str:
    expected = str(source.get("sha256") or "")
    if not locator:
        return expected or _hash(fallback)
    path = Path(locator)
    if not path.is_file():
        raise PictureLineageError(f"picture contributor is missing: {path}")
    actual = file_fingerprint(path)["sha256"]
    if expected and actual != expected:
        raise PictureLineageError(f"picture contributor fingerprint changed: {path}")
    return actual


def _current_revision(workspace: Any, artifact_type: str) -> dict[str, Any]:
    index = workspace.require_active(artifact_type)
    revision_id = index.get("headRevisionId")
    if not revision_id:
        raise PictureLineageError(f"{artifact_type} has no current revision")
    return workspace.store(artifact_type).revision(revision_id)


def _reference_digest(reference: dict[str, Any]) -> Any:
    return reference.get("sha256") or reference.get("contentSha256")


def _validate_basis(
    reference: dict[str, Any], revision: dict[str, Any], label: str
) -> None:
    valid_id = reference.get("revisionId") == revision.get("revisionId")
    valid_hash = _reference_digest(reference) == revision.get("contentHash")
    if not valid_id or not valid_hash:
        raise PictureLineageError(f"{label} basis is not current")


def _validate_revision_chain(revisions: dict[str, dict[str, Any]]) -> None:
    sync = revisions["sync-map"]
    cmap = revisions["cmap"]
    bmap = revisions["bmap"]
    tracks = revisions["tracks"]
    expected_refs = (
        ((cmap.get("snapshot") or {}).get("syncRef") or {}, sync, "CMap Sync"),
        ((bmap.get("snapshot") or {}).get("basis") or {}, cmap, "BMap CMap"),
        ((tracks.get("snapshot") or {}).get("basis") or {}, bmap, "Tracks BMap"),
        (
            (tracks.get("snapshot") or {}).get("cmapBasis") or {},
            cmap,
            "Tracks CMap",
        ),
    )
    for reference, revision, label in expected_refs:
        _validate_basis(reference, revision, label)


def _raw_fingerprints(cmap_revision: dict[str, Any]) -> dict[str, str]:
    sources = (cmap_revision.get("snapshot") or {}).get("sources") or []
    result = {
        str(source["sourceId"]): str(
            (source.get("fingerprint") or {}).get("sha256") or ""
        )
        for source in sources
    }
    if not result or any(len(value) != 64 for value in result.values()):
        raise PictureLineageError("CMap raw source fingerprints are incomplete")
    return result


def current_assembly_lock(
    workspace: Any,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    """Return and cross-check the exact current Sync/CMap/BMap/Tracks heads."""
    revisions = {name: _current_revision(workspace, name) for name in REVISION_TYPES}
    _validate_revision_chain(revisions)
    sync = revisions["sync-map"]
    cmap = revisions["cmap"]
    bmap = revisions["bmap"]
    tracks = revisions["tracks"]
    lock = {
        "cmapRevisionId": cmap["revisionId"],
        "cmapRevisionHash": cmap["contentHash"],
        "syncRevisionId": sync["revisionId"],
        "syncRevisionHash": sync["contentHash"],
        "bmapRevisionId": bmap["revisionId"],
        "bmapRevisionHash": bmap["contentHash"],
        "tracksRevisionId": tracks["revisionId"],
        "tracksRevisionHash": tracks["contentHash"],
        "rawFingerprints": _raw_fingerprints(cmap),
    }
    return lock, revisions


def _add_edge(
    edges: list[dict[str, Any]],
    source_id: str,
    target_id: str,
    operation: str,
    parameters: dict[str, Any],
    *,
    approval_reference: str | None = None,
) -> None:
    edge: dict[str, Any] = {
        "edgeId": f"edge-{len(edges) + 1:04d}",
        "from": source_id,
        "to": target_id,
        "operation": operation,
        "order": len(edges),
        "parameters": deepcopy(parameters),
    }
    if approval_reference:
        edge["approvalReference"] = approval_reference
    edges.append(edge)


def _cmap_source_node(
    source: dict[str, Any], segment: dict[str, Any], ordinal: int
) -> dict[str, Any]:
    fingerprint = source.get("fingerprint") or {}
    locator = str(source.get("locator") or fingerprint.get("locator") or "")
    node_id = f"cmap-segment-{ordinal + 1:04d}"
    media_class = (
        "camera-original"
        if source.get("kind") == "raw"
        else str(source.get("kind") or "source")
    )
    return {
        "nodeId": node_id,
        "kind": "source",
        "role": "base",
        "mediaClass": media_class,
        "locator": locator,
        "sha256": _node_sha(fingerprint, locator, source),
        "pictureCarrying": True,
        "media": deepcopy(fingerprint.get("mediaSignature") or {}),
        "sourceId": str(source["sourceId"]),
        "segmentId": str(segment.get("segmentId") or node_id),
    }


def _append_cmap_base(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    cmap_revision: dict[str, Any],
) -> tuple[str, int]:
    snapshot = cmap_revision.get("snapshot") or {}
    sources = {
        str(source["sourceId"]): source for source in snapshot.get("sources") or []
    }
    segments = snapshot.get("segments") or []
    if not segments:
        raise PictureLineageError("picture lineage requires at least one CMap segment")
    base_id = "canonical-cmap-picture"
    for ordinal, segment in enumerate(segments):
        _append_cmap_segment(nodes, edges, sources, segment, ordinal, base_id)
    nodes.append(
        {
            "nodeId": base_id,
            "kind": "intermediate",
            "role": "base",
            "mediaClass": "canonical-cut",
            "locator": f"canonical:cmap:{cmap_revision.get('revisionId')}",
            "sha256": str(cmap_revision.get("contentHash") or _hash(snapshot)),
            "pictureCarrying": True,
            "media": {},
        }
    )
    return base_id, len(segments)


def _append_cmap_segment(nodes, edges, sources, segment, ordinal, base_id) -> None:
    source_id = str(segment.get("sourceId") or "")
    source = sources.get(source_id)
    if source is None:
        raise PictureLineageError(
            f"CMap segment references unknown source: {source_id}"
        )
    node = _cmap_source_node(source, segment, ordinal)
    nodes.append(node)
    _add_edge(
        edges,
        node["nodeId"],
        base_id,
        "trim",
        {
            "segmentOrder": ordinal,
            "in": deepcopy(segment.get("in") or {}),
            "out": deepcopy(segment.get("out") or {}),
        },
    )


def _append_base_transforms(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    base_id: str,
    render_contract: dict[str, Any],
) -> str:
    current = base_id
    for ordinal, transform in enumerate(render_contract.get("transformations") or []):
        operation = str(transform.get("operation") or "")
        if operation not in SUPPORTED_BASE_TRANSFORMS:
            raise PictureLineageError(
                f"unsupported declared picture transformation: {operation}"
            )
        target = f"base-transform-{ordinal + 1:04d}"
        nodes.append(
            {
                "nodeId": target,
                "kind": "intermediate",
                "role": "base",
                "mediaClass": "canonical-transform",
                "locator": f"canonical:transform:{ordinal + 1}",
                "sha256": _hash({"from": current, "transform": transform}),
                "pictureCarrying": True,
                "media": deepcopy(transform.get("media") or {}),
            }
        )
        _add_edge(
            edges,
            current,
            target,
            operation,
            transform.get("parameters") or {},
            approval_reference=transform.get("approvalReference"),
        )
        current = target
    return current


def _append_assembly_node(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    current_base: str,
    projection_hash: str,
    segment_count: int,
) -> str:
    assembly_id = "assembly-picture"
    nodes.append(
        {
            "nodeId": assembly_id,
            "kind": "intermediate",
            "role": "base",
            "mediaClass": "assembly",
            "locator": "canonical:assembly",
            "sha256": _hash({"base": current_base, "projectionHash": projection_hash}),
            "pictureCarrying": True,
            "media": {},
        }
    )
    _add_edge(
        edges, current_base, assembly_id, "concat", {"segmentCount": segment_count}
    )
    return assembly_id


def _generator_payload(generator: Any) -> dict[str, Any]:
    return (
        deepcopy(generator) if isinstance(generator, dict) else {"id": str(generator)}
    )


def _track_identity(layer: dict[str, Any]) -> tuple[str, dict, Any, str, bool]:
    layer_id = str(layer.get("layerId") or "")
    source = layer.get("source") or {}
    generator = layer.get("generator") or source.get("generator")
    locator = str(source.get("locator") or "")
    generated = bool(generator) and not locator
    return layer_id, source, generator, locator, generated


def _track_source_node(layer: dict[str, Any], role: str) -> dict[str, Any]:
    layer_id, source, generator, locator, generated = _track_identity(layer)
    media_class = _media_class(
        layer, default="generated" if generated else "overlay-asset"
    )
    node = {
        "nodeId": f"track-{layer_id}",
        "kind": "generated" if generated else "source",
        "role": role,
        "mediaClass": media_class,
        "locator": locator or f"generator:{layer_id}",
        "sha256": _node_sha(source, locator, {"generator": generator, "layer": layer}),
        "pictureCarrying": True,
        "media": deepcopy(source.get("mediaSignature") or {}),
        "layerId": layer_id,
    }
    if generated:
        node["generator"] = _generator_payload(generator)
    return node


def _append_track_crop(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    node: dict[str, Any],
    layer: dict[str, Any],
) -> str:
    current = str(node["nodeId"])
    if not layer.get("crop"):
        return current
    transformed = f"{current}-crop"
    nodes.append(
        {
            "nodeId": transformed,
            "kind": "intermediate",
            "role": node["role"],
            "mediaClass": node["mediaClass"],
            "locator": f"canonical:track-transform:{node['layerId']}:crop",
            "sha256": _hash({"from": current, "crop": layer["crop"]}),
            "pictureCarrying": True,
            "media": {},
            "layerId": node["layerId"],
        }
    )
    _add_edge(
        edges,
        current,
        transformed,
        "crop",
        layer["crop"],
        approval_reference=(layer.get("provenance") or {}).get("approvalReference"),
    )
    return transformed


def _composite_parameters(
    layer: dict[str, Any], trace: dict[str, Any]
) -> dict[str, Any]:
    return {
        "layerId": layer.get("layerId"),
        "zOrder": trace.get("zOrder", 0),
        "regions": deepcopy(layer.get("regions") or []),
        "fit": layer.get("fit"),
        "placement": deepcopy(layer.get("placement") or {}),
        "composite": deepcopy(layer.get("composite") or {}),
    }


def _append_compiled_layers(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    tracks_revision: dict[str, Any],
    assembly_id: str,
) -> None:
    layers = ((tracks_revision.get("snapshot") or {}).get("videoTracks") or {}).get(
        "layers"
    ) or []
    layer_by_id = {str(layer.get("layerId")): layer for layer in layers}
    for trace in compile_video_layers(layers).get("trace") or []:
        role = str(trace.get("role") or "")
        if role == "base":
            continue
        _append_compiled_layer(nodes, edges, layer_by_id, trace, role, assembly_id)


def _append_compiled_layer(nodes, edges, layer_by_id, trace, role, assembly_id) -> None:
    layer = layer_by_id[str(trace.get("layerId") or "")]
    node = _track_source_node(layer, role)
    nodes.append(node)
    current = _append_track_crop(nodes, edges, node, layer)
    operation = "captions" if role == "caption" else "place/composite"
    _add_edge(
        edges,
        current,
        assembly_id,
        operation,
        _composite_parameters(layer, trace),
    )


def _append_output(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    assembly_id: str,
    output: dict[str, Any],
    render_contract: dict[str, Any],
) -> str:
    output_id = "rendered-output"
    locator = str(output.get("locator") or "")
    sha256 = str(output.get("sha256") or "")
    if not locator or len(sha256) != 64:
        raise PictureLineageError("rendered output fingerprint is incomplete")
    nodes.append(
        {
            "nodeId": output_id,
            "kind": "output",
            "role": "output",
            "mediaClass": "rendered-output",
            "locator": locator,
            "sha256": sha256,
            "pictureCarrying": True,
            "media": deepcopy(output.get("media") or {}),
        }
    )
    _add_edge(
        edges,
        assembly_id,
        output_id,
        "encode",
        {"renderContract": deepcopy(render_contract)},
    )
    return output_id


def build_picture_lineage(
    *,
    cmap_revision: dict[str, Any],
    tracks_revision: dict[str, Any],
    canonical_input_lock: dict[str, Any],
    projection_hash: str,
    output: dict[str, Any],
    render_contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build an ordered graph from CMap ranges and compiled visual layers only."""
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    contract = render_contract or {}
    base_id, segment_count = _append_cmap_base(nodes, edges, cmap_revision)
    transformed_base = _append_base_transforms(nodes, edges, base_id, contract)
    assembly_id = _append_assembly_node(
        nodes, edges, transformed_base, projection_hash, segment_count
    )
    _append_compiled_layers(nodes, edges, tracks_revision, assembly_id)
    output_id = _append_output(nodes, edges, assembly_id, output, contract)
    body = {
        "schemaVersion": "1.0.0",
        "canonicalInputLock": deepcopy(canonical_input_lock),
        "projectionHash": projection_hash,
        "nodes": nodes,
        "edges": edges,
        "rootIds": [output_id],
    }
    return {**body, "pictureLineageHash": _hash(body)}
