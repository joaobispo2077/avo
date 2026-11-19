"""Seal returned bytes and compare them with the immutable base and current cut."""

import hashlib
import json

from .command_registry import authorize
from .contracts import (
    content_hash,
    file_fingerprint,
    fingerprint_stage,
    validate_document,
)
from .editor_feedback import compare_editor_feedback
from .editor_feedback_trims import ManualEditorFeedback, selected_editor_trims
from .editor_handoff import (
    SCHEMA,
    _admitted_path,
    _artifact,
    _bounded_window,
    _output_root,
    _publish_xml,
    _verify_originals,
    load_handoff,
)
from .motion_authoring import MotionAuthoringService
from .motion_review import MotionReviewService
from .store import timeline_writer, write_immutable_json

MAX_XML_BYTES = 16 * 1024 * 1024
MAX_REPORT_BYTES = 8 * 1024 * 1024


def _read_bound(path, expected, limit):
    with path.open("rb") as stream:
        payload = stream.read(limit + 1)
    if len(payload) > limit or hashlib.sha256(payload).hexdigest() != expected:
        raise ValueError(
            "Editor evidence bytes changed or exceeded the declared budget"
        )
    return payload


def _artifact_bytes(workspace, reference):
    return _read_bound(
        _artifact(workspace, reference["locator"]), reference["sha256"], MAX_XML_BYTES
    )


def _seal(workspace, body, category, definition):
    validate_document(body, SCHEMA + definition)
    locator = f"{_output_root(workspace)}/{category}/{content_hash(body)}.json"
    path = write_immutable_json(_artifact(workspace, locator), body)
    return {"locator": locator, "sha256": file_fingerprint(path)["sha256"]}


def _sources(model, approved):
    if len(model["sources"]) > 128:
        raise ValueError("Returned source count exceeds its inspection budget")
    original = {row["sha256"] for row in approved}
    rows = []
    with fingerprint_stage(verify_on_exit=True):
        for key, source in model["sources"].items():
            path = source["locator"]
            digest = file_fingerprint(path)["sha256"] if path.is_file() else None
            status = (
                "unavailable"
                if digest is None
                else "matches-original"
                if digest in original
                else "unadmitted-source"
            )
            rows.append(
                {
                    "fileId": key,
                    "locator": str(path),
                    "sha256": digest,
                    "status": status,
                }
            )
    return rows


def _read_return(service, payload, request):
    roots = [_admitted_path(value) for value in request["admittedRoots"]]
    return service.read_xml(
        payload,
        roots=roots,
        relink=request.get("relink"),
        sequence_id=request.get("sequenceId"),
    )


def _inspection_result(service, returned, request, approved):
    try:
        model = _read_return(service, returned, request)
        return {
            "status": "inspected",
            "sourceFacts": _sources(model, approved),
            "unknownElements": model["unknown"],
        }
    except (OSError, ValueError) as error:
        return {
            "status": "unsupported",
            "reason": str(error)[:4096],
            "sourceFacts": [],
            "unknownElements": {},
        }


def inspect_feedback(service, request):
    validate_document(request, SCHEMA + "inspectRequest")
    workspace = service.workspace
    base = load_handoff(workspace, request["handoffRef"])
    reference = request["returnedXml"]
    payload = _read_bound(
        _admitted_path(reference["locator"]), reference["sha256"], MAX_XML_BYTES
    )
    result = _inspection_result(service, payload, request, base["sources"])
    with timeline_writer(workspace.timeline_dir):
        body = {
            "provider": workspace.project["provider"],
            "videoId": workspace.video_id,
            "input": request,
            "receipt": _publish_xml(workspace, payload),
            **result,
        }
        inspection = _seal(workspace, body, "inspections", "inspection")
    return {**result, "inspectionRef": inspection, "returnedXmlRef": body["receipt"]}


def _load_inspection(workspace, reference):
    locator = reference["locator"]
    if not locator.startswith(f"{_output_root(workspace)}/inspections/"):
        raise ValueError("Select an immutable editor feedback inspection")
    path = _artifact(workspace, locator)
    body = json.loads(_read_bound(path, reference["sha256"], MAX_REPORT_BYTES))
    validate_document(body, SCHEMA + "inspection")
    if content_hash(body) != path.stem or (body["provider"], body["videoId"]) != (
        workspace.project["provider"],
        workspace.video_id,
    ):
        raise ValueError("Editor feedback inspection scope changed")
    if body["status"] != "inspected":
        raise ValueError("Unsupported returned editor bytes cannot become a proposal")
    return body


def _current_xml(service, base, expected):
    workspace = service.workspace
    if expected == base["request"]["expectedBasis"]:
        _verify_originals(base["sources"])
        return _artifact_bytes(workspace, base["xmlRef"]), base["sources"]
    request = {**base["request"], "expectedBasis": expected}
    window, fps = _bounded_window(request)
    roots = [_admitted_path(value) for value in request["admittedRoots"]]
    workspace.require_active("cmap")
    _, snapshots, _ = MotionReviewService(workspace)._metadata()
    bundle, payload = service._measure(
        request, base["profile"], snapshots, window, fps, roots
    )
    return payload, bundle["sources"]


def _add_digests(model, facts):
    for row in facts:
        model["sources"][row["fileId"]]["sha256"] = row["sha256"]
    return model


def _original_model(service, payload, base, originals):
    roots = [_admitted_path(value) for value in base["request"]["admittedRoots"]]
    model = service.read_xml(payload, roots=roots)
    by_location = {row["locator"]: row["sha256"] for row in originals}
    selected = [
        {"fileId": identity, "sha256": by_location.get(str(value["locator"]))}
        for identity, value in model["sources"].items()
    ]
    if not all(row["sha256"] for row in selected):
        raise ValueError("Editor model differs from its retained original sources")
    return _add_digests(model, selected)


def _comparison(service, base, receipt, expected):
    workspace = service.workspace
    payload = _artifact_bytes(workspace, receipt["receipt"])
    returned = _read_return(service, payload, receipt["input"])
    facts = _sources(returned, base["sources"])
    if facts != receipt["sourceFacts"]:
        raise ValueError("Returned editor source identities changed after inspection")
    baseline = _original_model(
        service, _artifact_bytes(workspace, base["xmlRef"]), base, base["sources"]
    )
    current_xml, current_sources = _current_xml(service, base, expected)
    current = _original_model(service, current_xml, base, current_sources)
    return compare_editor_feedback(
        baseline, current, _add_digests(returned, facts)
    ), current_xml


def propose_feedback(service, request):
    validate_document(request, SCHEMA + "feedbackRequest")
    workspace = service.workspace
    expected = request["expectedBasis"]
    owner = MotionAuthoringService(workspace)
    owner._check_heads(expected)
    inspection = _load_inspection(workspace, request["inspectionRef"])
    basis = inspection["input"]["handoffRef"]
    base = load_handoff(workspace, basis)
    changes, current = _comparison(service, base, inspection, expected)
    with timeline_writer(workspace.timeline_dir):
        owner._check_heads(expected)
        proposal = {
            "input": request,
            "basisRef": basis,
            "baseXmlRef": base["xmlRef"],
            "currentXmlRef": _publish_xml(workspace, current),
            "returnedXmlRef": inspection["receipt"],
            "profileHash": base["profileHash"],
            "changes": changes,
        }
        reference = _seal(workspace, proposal, "feedback", "feedbackProposal")
    return {"status": "review-required", "proposalRef": reference, **proposal}


def _load_feedback_proposal(workspace, reference):
    relative = reference["locator"]
    if not relative.startswith(f"{_output_root(workspace)}/feedback/"):
        raise ValueError("Select an immutable editor feedback proposal")
    path = _artifact(workspace, relative)
    proposal = json.loads(_read_bound(path, reference["sha256"], MAX_REPORT_BYTES))
    validate_document(proposal, SCHEMA + "feedbackProposal")
    if content_hash(proposal) != path.stem:
        raise ValueError("Editor feedback proposal identity changed")
    return proposal


def _chosen_editor_fields(changes, choices):
    by_key = {
        (row["id"], row["field"]): row
        for kind in ("proposals", "conflicts")
        for row in changes[kind]
    }
    seen, chosen = set(), {}
    for choice in choices:
        key = choice["id"], choice["field"]
        if key in seen or key not in by_key:
            raise ValueError(
                "Choose each proposed or conflicting editor field at most once"
            )
        seen.add(key)
        row = by_key[key]
        if choice["selection"] == "returned":
            chosen.setdefault(row["id"], {})[row["field"]] = row
    return chosen


def _verified_feedback(service, request):
    workspace = service.workspace
    proposal = _load_feedback_proposal(workspace, request["proposalRef"])
    if proposal["input"]["expectedBasis"] != request["expectedBasis"]:
        raise ValueError(
            "Editor decisions must use the proposal's exact current timeline basis"
        )
    inspection = _load_inspection(workspace, proposal["input"]["inspectionRef"])
    base = load_handoff(workspace, proposal["basisRef"])
    if (
        inspection["input"]["handoffRef"] != proposal["basisRef"]
        or base["profileHash"] != proposal["profileHash"]
        or base["xmlRef"] != proposal["baseXmlRef"]
        or inspection["receipt"] != proposal["returnedXmlRef"]
    ):
        raise ValueError("Editor proposal inputs changed")
    changes, current = _comparison(service, base, inspection, request["expectedBasis"])
    if changes != proposal["changes"] or current != _artifact_bytes(
        workspace, proposal["currentXmlRef"]
    ):
        raise ValueError("Editor proposal no longer matches the exact comparison")
    return changes, current, base


def _route_chosen_fields(service, request, chosen, current_xml, base, cutting_factory):
    if not chosen:
        return {"status": "current-retained", "cuttingProposalRef": None}
    workspace = service.workspace
    _, snapshots, _ = MotionReviewService(workspace)._metadata()
    roots = [_admitted_path(value) for value in base["request"]["admittedRoots"]]
    current = service.read_xml(current_xml, roots=roots)
    try:
        if any(
            row["identity"] != "exact"
            for fields in chosen.values()
            for row in fields.values()
        ):
            raise ManualEditorFeedback(
                "A suggested occurrence match requires manual editor review"
            )
        values = {
            identity: {field: row["returned"] for field, row in fields.items()}
            for identity, fields in chosen.items()
        }
        trims = selected_editor_trims(snapshots["cmap"], current, values)
    except ManualEditorFeedback as error:
        return {
            "status": "manual-review",
            "reason": str(error),
            "cuttingProposalRef": None,
        }
    authorize("trim", mutation="cmap")
    reference = cutting_factory().propose_editor_trims(
        trims,
        expected_cmap=request["expectedBasis"]["cmap"]["sha256"],
        frame_rate=base["request"]["programRate"],
        editor_ref=request["proposalRef"],
    )
    return {"status": "cutting-review-required", "cuttingProposalRef": reference}


def apply_feedback(service, request, *, cutting_factory):
    """Route explicit choices to their supported owner without bypassing review."""
    validate_document(request, SCHEMA + "applyFeedbackRequest")
    workspace = service.workspace
    owner = MotionAuthoringService(workspace)
    owner._check_heads(request["expectedBasis"])
    changes, current, base = _verified_feedback(service, request)
    chosen = _chosen_editor_fields(changes, request["choices"])
    with timeline_writer(workspace.timeline_dir):
        owner._check_heads(request["expectedBasis"])
        outcome = _route_chosen_fields(
            service, request, chosen, current, base, cutting_factory
        )
        body = {
            "provider": workspace.project["provider"],
            "videoId": workspace.video_id,
            "input": request,
            **outcome,
        }
        reference = _seal(workspace, body, "routes", "feedbackRoute")
    return {**outcome, "routeRef": reference, "mutated": False}
