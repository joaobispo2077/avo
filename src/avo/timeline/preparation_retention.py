"""Bounded verified closure for the existing source-preparation journal."""

import hashlib
import json

from avo.library.rules import safe_path

from .contracts import content_hash
from .cutting_contracts import validate_cutting_document
from .cutting_store import CuttingStore


def _references(value):
    if isinstance(value, dict):
        if set(value) == {"locator", "sha256"} and value["locator"].startswith(
            ("documents/", "preparation-results/")
        ):
            yield value
        else:
            for key, child in value.items():
                if key not in {
                    "sourceRef",
                    "sourceRefs",
                    "syncRef",
                    "budgetSource",
                    "originalBinding",
                    "modelBindings",
                    "tools",
                }:
                    yield from _references(child)
    elif isinstance(value, list):
        for child in value:
            yield from _references(child)


class _Evidence:
    def __init__(self, workspace):
        self.root = workspace.timeline_dir / "cutting"
        self.store = CuttingStore(
            self.root,
            video_id=workspace.video_id,
            provider=workspace.project["provider"],
        )
        self.files = {}
        self.total = 0

    def read(self, relative):
        path = safe_path(self.root, relative)
        if path not in self.files:
            if len(self.files) >= 2000:
                raise ValueError("preparation evidence exceeds its file budget")
            with path.open("rb") as stream:
                data = stream.read(
                    min(16 * 1024 * 1024, 64 * 1024 * 1024 - self.total) + 1
                )
            self.total += len(data)
            if len(data) > 16 * 1024 * 1024 or self.total > 64 * 1024 * 1024:
                raise ValueError("preparation evidence exceeds its byte budget")
            self.files[path] = (json.loads(data), hashlib.sha256(data).hexdigest())
        return self.files[path][0]

    def document(self, reference):
        document = validate_cutting_document(self.read(reference["locator"]))
        if content_hash(document) != reference["sha256"]:
            raise ValueError("preparation evidence reference changed")
        return document

    def closure(self):
        ledger = self.journal()
        queue = list(_references(ledger))
        visited = set()
        while queue:
            reference = queue.pop()
            identity = (reference["locator"], reference["sha256"])
            if identity in visited:
                continue
            visited.add(identity)
            document = self.document(reference)
            queue.extend(_references(document))
            if document["documentType"] == "speech-recovery-attempt":
                self.pending_result(reference, queue)
        return {path: digest for path, (_, digest) in self.files.items()}

    def journal(self):
        ledger = self.read("repair-ledger.json")
        self.store.ledger._validate_index(ledger)
        if (
            ledger["videoId"] != self.store.video_id
            or ledger["provider"] != self.store.provider
        ):
            raise ValueError("preparation journal belongs to a different project")
        revisions = [
            self.revision(reference, ledger) for reference in ledger["revisionRefs"]
        ]
        for reference in ledger["eventRefs"]:
            event = self.read(reference["path"])
            self.store.ledger._validate_event(event)
            if content_hash(event) != reference["sha256"]:
                raise ValueError("preparation journal event changed")
        return revisions

    def revision(self, reference, index):
        revision = self.read(reference["path"])
        self.store.ledger._validate_revision(revision)
        if (
            revision["revisionId"] != reference["revisionId"]
            or revision["contentSha256"] != reference["contentSha256"]
        ):
            raise ValueError("preparation journal revision changed")
        if any(
            revision[key] != index[key]
            for key in ("artifactType", "artifactId", "timelineDomain")
        ):
            raise ValueError("preparation journal revision changed its owner")
        return revision

    def pending_result(self, attempt_ref, queue):
        relative = "preparation-results/" + attempt_ref["sha256"] + ".json"
        if not safe_path(self.root, relative).exists():
            return
        document = validate_cutting_document(
            self.read(relative), "speech-recovery-result"
        )
        if document["payload"]["attemptRef"] != attempt_ref:
            raise ValueError("interrupted recovery result changed its attempt")
        queue.append({"locator": relative, "sha256": content_hash(document)})


def retained_preparation_files(workspace):
    evidence = _Evidence(workspace)
    if not evidence.store.ledger.path.exists():
        return {}
    try:
        return evidence.closure()
    except (OSError, ValueError, KeyError, TypeError, RuntimeError) as error:
        raise ValueError(
            f"Cannot retain preparation recovery evidence: {error}"
        ) from error
