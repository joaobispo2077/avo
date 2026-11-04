"""Verify activated import provenance without treating mutable packet refs as authority."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from fractions import Fraction
from pathlib import Path

from .contracts import content_hash, validate_document
from .lineage import LineageError
from .otio_import import packet_identity, parse_export_bytes

_SCHEMA = "avo.timeline-import.schema.json"
_LIMIT = 64 * 1024 * 1024
_CAPABILITIES = {"contiguous": "contiguous-1.0.0", "placed": "placed-1.0.0"}


def _require(condition, detail):
    if not condition:
        raise LineageError(
            f"Cannot verify activated import evidence: {detail}; "
            "restore the immutable import packet or reconcile its activation"
        )


def _path(packet, relative):
    path = (packet / relative).resolve()
    _require(
        path != packet and path.is_relative_to(packet), "packet path escapes its root"
    )
    return path


def _bytes(path):
    _require(path.stat().st_size <= _LIMIT, f"evidence exceeds 64 MiB: {path}")
    with path.open("rb") as stream:
        data = stream.read(_LIMIT + 1)
    _require(len(data) <= _LIMIT, f"evidence exceeds 64 MiB: {path}")
    return data


def _document(path, schema=None, semantic_hash=None):
    data = _bytes(path)
    parse_export_bytes(data)
    value = json.loads(data)
    if schema is not None:
        validate_document(value, _SCHEMA + "#/$defs/" + schema)
    if semantic_hash is not None:
        _require(content_hash(value) == semantic_hash, f"evidence hash differs: {path}")
    return value, hashlib.sha256(data).hexdigest()


def _target(workspace, index, context, normalizer_version):
    from .workspace import TimelineWorkspace

    current = TimelineWorkspace.from_project(workspace.project_path)
    identity = (str(workspace.project.get("provider") or ""), workspace.video_id)
    _require(
        (index["provider"], index["videoId"]) == identity,
        "canonical target identity differs",
    )
    _require(
        (str(current.project.get("provider") or ""), current.video_id) == identity,
        "current project identity differs",
    )
    timeline, raw = workspace.timeline_dir.resolve(), workspace.raw_dir.resolve()
    _require(
        (current.timeline_dir.resolve(), current.raw_dir.resolve()) == (timeline, raw),
        "current project roots differ",
    )
    _require(
        timeline.is_relative_to(raw / "edit"), "canonical timeline escapes edit root"
    )
    roots = {"timelineRoot": timeline, "importsRoot": timeline / "imports"}
    _require(
        normalizer_version == "1.0.0" or roots.keys() <= context.keys(),
        "activation lacks canonical root locks",
    )
    _require(
        all(
            Path(context[key]).resolve() == path
            for key, path in roots.items()
            if key in context
        ),
        "activation belongs to different canonical roots",
    )
    # Manifest bytes may legitimately change after activation. Current proof
    # locks govern them; historical provenance binds stable identity and roots.
    # Normalizer 1 receipts predate root locks. Their exact packet identity and
    # committed canonical chain remain required at the current contained roots.


def _session(packet, origin, workspace):
    session, _ = _document(_path(packet, "index.json"), "session")
    source = session["source"]
    _require(
        (session["provider"], session["videoId"])
        == (str(workspace.project.get("provider") or ""), workspace.video_id),
        "packet target identity differs",
    )
    _require(
        source["sha256"] == origin["exportSha256"]
        and source["timelinePointer"] == origin["timelinePointer"],
        "export identity or selected timeline differs",
    )
    expected = packet_identity(
        source["sha256"],
        source["timelinePointer"],
        session["provider"],
        session["videoId"],
        session["options"],
        normalizer_version=session["normalizerVersion"],
    )
    _require(
        session["importId"] == origin["importId"] == expected, "packet identity differs"
    )
    return session


def _activation(packet, origin):
    path = _path(packet, f"activation/{origin['activationId']}.json")
    intent, _ = _document(path, "activation")
    operation = content_hash(
        {
            "importId": origin["importId"],
            "validationHash": intent["validationHash"],
            "expectedHeadHash": intent["expectedHeadHash"],
        }
    )
    _require(
        intent["importId"] == origin["importId"]
        and intent["operationId"] == origin["activationId"] == operation
        and intent["revisionId"] == "cmap-import-" + operation[:24]
        and intent["phase"] == "prepared",
        "activation intent identity differs",
    )
    return intent, path


def _ready_receipt(packet, intent, session):
    digest = intent["validationHash"]
    path = _path(packet, f"validations/{digest}.json")
    receipt, _ = _document(path, "validation", digest)
    _require(
        receipt["importId"] == session["importId"]
        and receipt["ready"] is True
        and receipt["state"] == "ready-to-activate"
        and not receipt["findings"],
        "activation lacks an exact ready receipt without unresolved findings",
    )
    locks = receipt["locks"]
    _require(locks["source"] == session["source"], "receipt export identity differs")
    _require(
        locks["expectedHeadHash"] == intent["expectedHeadHash"] and locks.get("sync"),
        "receipt target or Sync basis differs",
    )
    _require(
        all(
            locks["checks"].get(key) == "passed"
            for key in (
                "semanticValidation",
                "mediaReady",
                "syncReady",
                "reconstructionReady",
            )
        ),
        "receipt contains unresolved readiness",
    )
    accounting = locks.get("elementAccounting", {})
    _require(
        not any(
            accounting.get("byDisposition", {}).get(key, 0)
            for key in ("unsupported", "unresolved")
        )
        and not accounting.get("truncated", False),
        "receipt contains unresolved or truncated element accounting",
    )
    return receipt, path


def _proposal(packet, origin, receipt):
    digest = receipt["locks"]["proposalHash"]
    path = _path(packet, f"proposals/{digest}.json")
    proposal, file_hash = _document(path, "proposal", digest)
    _require(
        file_hash == origin["proposalSha256"], "proposal file-byte fingerprint differs"
    )
    _require(
        proposal["importId"] == origin["importId"]
        and not proposal["findings"]
        and not proposal["provisionalFinishing"],
        "proposal contains unresolved import content",
    )
    _require(
        not any(
            item["disposition"] in {"unsupported", "unresolved"}
            for item in proposal.get("elements", [])
        ),
        "proposal contains unresolved elements",
    )
    layout = proposal["snapshot"].get("layoutMode", "contiguous")
    _require(
        _CAPABILITIES.get(layout) == origin["capabilityVersion"],
        "unsupported import capability or layout",
    )
    return proposal, path


def _initial_revision(store, current, initial_id):
    actual = store.revision(current["revisionId"])
    _require(
        all(
            actual[key] == current[key]
            for key in ("revisionId", "parentRevisionId", "contentHash", "snapshot")
        ),
        "supplied CMap is not its immutable canonical revision",
    )
    seen = set()
    while actual["revisionId"] != initial_id:
        _require(actual["revisionId"] not in seen, "CMap parent chain contains a cycle")
        seen.add(actual["revisionId"])
        parent = actual["parentRevisionId"]
        _require(parent is not None, "activation revision is not a canonical ancestor")
        actual = store.revision(parent)
    return actual


def _committed(packet, intent, proposal, origin, initial):
    expected = deepcopy(proposal["snapshot"])
    expected.update(
        sourceAssemblyPolicy="preserve-import",
        importOutput=proposal["output"],
        originRef=origin,
    )
    actual = deepcopy(initial["snapshot"])
    actual.pop("syncRef", None)
    _require(
        actual == expected, "committed initial CMap differs from validated proposal"
    )
    _require(
        initial["createdAt"] == intent["createdAt"]
        and all(initial[key] == intent[key].strip() for key in ("actor", "reason")),
        "initial CMap does not match its activation intent",
    )
    completed = {
        **intent,
        "phase": "reconciled",
        "revisionHash": initial["contentHash"],
    }
    path = _path(packet, f"activation-results/{content_hash(completed)}.json")
    result, _ = _document(path, "activation")
    _require(result == completed, "activation reconciliation evidence differs")
    return path


def _previous_selection(store, intent, initial):
    previous_id = intent["previousRevisionId"]
    _require(
        initial["parentRevisionId"] == previous_id,
        "activation parent differs from prior-state evidence",
    )
    if intent["expectedHeadHash"] == "empty":
        _require(
            previous_id is None and intent["previousSnapshot"] is None,
            "empty activation has unexpected prior content",
        )
        return
    _require(
        previous_id is not None and intent["previousSnapshot"] is not None,
        "nonempty activation lacks prior-state evidence",
    )
    previous = store.revision(previous_id)
    _require(
        previous["contentHash"] == intent["expectedHeadHash"]
        and previous["snapshot"] == intent["previousSnapshot"],
        "activation prior-state evidence differs from canonical history",
    )


def _output(output, canonical):
    if output is None:
        return
    _require(
        Fraction(output["frameRate"]["num"], output["frameRate"]["den"])
        == Fraction(canonical["frameRate"]["num"], canonical["frameRate"]["den"]),
        "requested output clock differs from canonical import",
    )
    _require(
        output["audioSampleRate"] == canonical["audioSampleRate"]
        and output["channelLayout"] == canonical["channelLayout"]
        and output["width"] * canonical["height"]
        == output["height"] * canonical["width"],
        "requested output routing or canvas differs from canonical import",
    )


def verify_import_origin(workspace, cmap_revision, output=None):
    """Verify activated origin and return its exact retained evidence paths.

    Later canonical edits may change source intervals. Authority comes from the
    original committed ancestor, not whichever proposal a session now points to.
    """
    snapshot = cmap_revision["snapshot"]
    if not {"originRef", "sourceAssemblyPolicy", "importOutput"}.intersection(snapshot):
        return []
    try:
        origin = snapshot["originRef"]
        validate_document(
            origin, "avo.timeline-common.schema.json#/$defs/importOriginRef"
        )
        _require(
            snapshot["sourceAssemblyPolicy"] == "preserve-import",
            "import policy differs",
        )
        _require(
            origin["capabilityVersion"] in _CAPABILITIES.values(),
            "unsupported import capability",
        )
        root = workspace.timeline_dir.resolve() / "imports"
        packet = _path(root, origin["importId"])
        session = _session(packet, origin, workspace)
        intent, intent_path = _activation(packet, origin)
        receipt, receipt_path = _ready_receipt(packet, intent, session)
        store = workspace.store("cmap")
        _target(
            workspace,
            store.load_index(),
            receipt["locks"]["context"],
            session["normalizerVersion"],
        )
        proposal, proposal_path = _proposal(packet, origin, receipt)
        export_path = _path(packet, "source.otio")
        data = _bytes(export_path)
        _require(
            hashlib.sha256(data).hexdigest() == origin["exportSha256"]
            and len(data) == session["source"]["sizeBytes"],
            "original export bytes differ",
        )
        initial = _initial_revision(store, cmap_revision, intent["revisionId"])
        _previous_selection(store, intent, initial)
        result_path = _committed(packet, intent, proposal, origin, initial)
        _output(output, snapshot["importOutput"])
        return [
            _path(packet, "index.json"),
            export_path,
            intent_path,
            receipt_path,
            proposal_path,
            result_path,
        ]
    except LineageError:
        raise
    except (KeyError, TypeError, ValueError, OSError, RuntimeError) as exc:
        raise LineageError(
            f"Cannot verify activated import evidence: {exc}; "
            "restore the immutable import packet or reconcile its activation"
        ) from exc
