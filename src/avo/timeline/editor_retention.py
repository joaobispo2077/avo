"""Verify and retain the selected editor evidence closure."""

import hashlib
import json
from pathlib import Path

from .contracts import content_hash, file_fingerprint, validate_document
from .editor_handoff import SCHEMA, _artifact, _output_root
from .preparation_retention import retained_preparation_files

MAX_RECORDS = 1000
MAX_TOTAL_BYTES = 128 * 1024 * 1024
RECORD_DEFINITIONS = {
    "manifests": "manifest",
    "inspections": "inspection",
    "feedback": "feedbackProposal",
    "qualifications": "qualification",
    "routes": "feedbackRoute",
}


def _selected_records(root):
    records = []
    for category in RECORD_DEFINITIONS:
        directory = root / category
        if directory.is_symlink():
            raise ValueError("Editor evidence directories must be project-owned")
        for path in directory.glob("*.json"):
            records.append(path)
            if len(records) > MAX_RECORDS:
                raise ValueError("Editor evidence exceeds its document budget")
    return records


def _references(body, category):
    if category == "manifests":
        selected = body["request"].get("qualificationRef")
        return (body["xmlRef"], selected) if selected else (body["xmlRef"],)
    if category == "inspections":
        return (body["input"]["handoffRef"], body["receipt"])
    if category == "qualifications":
        return body["basisRef"], body["input"]["inspectionRef"], body["returnedXmlRef"]
    if category == "routes":
        return (body["input"]["proposalRef"],)
    return (
        body["basisRef"],
        body["input"]["inspectionRef"],
        body["baseXmlRef"],
        body["currentXmlRef"],
        body["returnedXmlRef"],
    )


def _reference_path(workspace, root, reference):
    path = _artifact(workspace, reference["locator"])
    allowed = path.parent.parent == root and (
        path.parent.name in RECORD_DEFINITIONS
        and path.suffix == ".json"
        or path.parent.name == "xml"
        and path.suffix == ".xml"
    )
    if not allowed or path.parent.is_symlink() or path.is_symlink():
        raise ValueError("Editor evidence reference escapes its published scope")
    return path


def _report(workspace, root, path, data, cutting_refs, generated_files):
    body = json.loads(data)
    category = path.parent.name
    validate_document(body, SCHEMA + RECORD_DEFINITIONS[category])
    if content_hash(body) != path.stem:
        raise ValueError("Editor evidence document identity changed")
    if category != "feedback" and (body["provider"], body["videoId"]) != (
        workspace.project["provider"],
        workspace.video_id,
    ):
        raise ValueError("Editor evidence belongs to a different project")
    if category == "routes" and body["cuttingProposalRef"] is not None:
        cutting_refs.append(body["cuttingProposalRef"])
    if category == "manifests" and body["request"].get("generatedAlphaPlan"):
        generated_files.update(_generated_files(workspace, body))
    return [
        (_reference_path(workspace, root, ref), ref["sha256"])
        for ref in _references(body, category)
    ]


def _generated_files(workspace, manifest):
    """Keep selected alpha originals and exact receipts usable after cleanup."""
    from .editor_generated import load_alpha_plan
    from .generated_assets import GeneratedAssetService

    plan_ref = manifest["request"]["generatedAlphaPlan"]
    _, proof_path, plan = load_alpha_plan(workspace, plan_ref)
    retained = {proof_path: file_fingerprint(proof_path)["sha256"]}
    registry = GeneratedAssetService(workspace)
    for source in manifest["sources"]:
        if source["kind"] == "generated-alpha":
            retained.update(
                _generated_source_files(source, plan, registry, workspace.raw_dir)
            )
    return retained


def _generated_source_files(source, plan, registry, raw_dir):
    reference = source["generatedAsset"]
    record = registry.load(reference["id"])
    if (
        record["recordHash"] != reference["sha256"]
        or plan["canonicalInputLock"].get("generated:" + reference["id"])
        != reference["sha256"]
    ):
        raise ValueError("Retained generated alpha receipt identity changed")
    original, keys = reference["original"], ("locator", "sha256", "sizeBytes")
    if any(original[key] != record["output"][key] for key in keys):
        raise ValueError("Retained generated alpha original differs from its receipt")
    retained = {}
    for item in (original, source):
        path = Path(item["locator"])
        if path.is_symlink() or not path.resolve().is_relative_to(
            (raw_dir / "edit/derived").resolve()
        ):
            raise ValueError(
                "Retained generated alpha escaped its project output folder"
            )
        measured = file_fingerprint(path)
        if any(measured[key] != item[key] for key in keys):
            raise ValueError("Retained generated alpha source changed")
        retained[path] = measured["sha256"]
    receipt = registry.path(reference["id"])
    return {**retained, receipt: file_fingerprint(receipt)["sha256"]}


def _read_evidence(path, remaining):
    per_file_limit = 8 if path.suffix == ".json" else 16
    limit = min(per_file_limit * 1024 * 1024, remaining)
    if path.is_symlink():
        raise ValueError("Editor evidence files must be project-owned")
    with path.open("rb") as stream:
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise ValueError("Editor evidence exceeds its byte budget")
    return data


def retained_editor_files(workspace):
    """Retain selected histories and referenced XML. Orphan bytes are disposable."""
    root = workspace.raw_dir / _output_root(workspace)
    if root.is_symlink():
        raise ValueError("Editor evidence directory must be project-owned")
    queue = [(path, None) for path in _selected_records(root)]
    remaining = MAX_TOTAL_BYTES
    selected, cutting_refs, generated_files = {}, [], {}
    while queue:
        path, expected = queue.pop()
        if path not in selected:
            data = _read_evidence(path, remaining)
            remaining -= len(data)
            selected[path] = hashlib.sha256(data).hexdigest()
            if path.suffix == ".json":
                queue.extend(
                    _report(workspace, root, path, data, cutting_refs, generated_files)
                )
            elif path.stem != selected[path]:
                raise ValueError("Editor evidence XML identity changed")
        if expected is not None and selected[path] != expected:
            raise ValueError("Editor evidence reference changed")
    if cutting_refs:
        selected.update(retained_preparation_files(workspace, references=cutting_refs))
    selected.update(generated_files)
    return selected
