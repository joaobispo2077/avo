"""Verify and retain the selected editor evidence closure."""

import hashlib
import json

from .contracts import content_hash, validate_document
from .editor_handoff import SCHEMA, _artifact, _output_root

MAX_RECORDS = 1000
MAX_TOTAL_BYTES = 128 * 1024 * 1024
RECORD_DEFINITIONS = {
    "manifests": "manifest",
    "inspections": "inspection",
    "feedback": "feedbackProposal",
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
        return (body["xmlRef"],)
    if category == "inspections":
        return (body["input"]["handoffRef"], body["receipt"])
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


def _report(workspace, root, path, data):
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
    return [
        (_reference_path(workspace, root, ref), ref["sha256"])
        for ref in _references(body, category)
    ]


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
    selected = {}
    while queue:
        path, expected = queue.pop()
        if path not in selected:
            data = _read_evidence(path, remaining)
            remaining -= len(data)
            selected[path] = hashlib.sha256(data).hexdigest()
            if path.suffix == ".json":
                queue.extend(_report(workspace, root, path, data))
            elif path.stem != selected[path]:
                raise ValueError("Editor evidence XML identity changed")
        if expected is not None and selected[path] != expected:
            raise ValueError("Editor evidence reference changed")
    return selected
