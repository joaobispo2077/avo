"""Native library use cases. Discovery never confers editorial approval."""

from __future__ import annotations

import re
from pathlib import Path

from avo.library.rules import is_link, read_request, reject
from avo.library.store import LibraryStore
from avo.paths import providers_dir, repo_root


class LibraryService:
    def __init__(self, root, provider, *, probe=None):
        self.root = Path(root).expanduser().absolute()
        if not self.root.is_dir() or is_link(self.root):
            reject("LIB_ROOT_UNSAFE", "Choose an existing unlinked footage folder")
        if self.root.resolve().is_relative_to(repo_root().resolve()):
            reject(
                "LIB_ROOT_UNSAFE",
                "Footage and library outputs belong outside the AVO checkout",
            )
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", provider or ""):
            reject("LIB_PROVIDER_REQUIRED", "Declare a configured provider")
        manifest = providers_dir() / provider / "avo.provider.json"
        if not manifest.is_file():
            reject(
                "LIB_PROVIDER_REQUIRED",
                "Configure the selected provider before library work",
            )
        self.provider = provider
        self.store = LibraryStore(self.root, provider)
        self.probe = probe
        self.progress = None

    def writable(self):
        if self.store.head_path.exists() and "rootIdentity" not in self.store.head():
            reject(
                "LIB_ROOT_UNSAFE",
                "Legacy library root needs explicit identity adoption before mutation",
            )
        for name in ("preservation-result.json", "cleanup-result.json"):
            if self.store.path(f"edit/cleanup/{name}").exists():
                reject(
                    "LIB_PROJECT_CLOSED",
                    "Closed projects require explicit native reopening",
                    "conflict",
                )
        project = self.root / "avo.project.json"
        if project.exists() and read_request(project).get("provider") != self.provider:
            reject("LIB_INVALID_REQUEST", "Project and library providers differ")

    def status(self, operation=None):
        head = self.store.head()
        from avo.library.retention import retention_plan

        state = None
        if operation or head["activeOperation"]:
            from avo.library.moves import load

            state = load(self, operation or head["activeOperation"])
        return {
            "status": "ok",
            "summary": self.store.get(head["inventoryRef"])["summary"]
            if head["inventoryRef"]
            else {},
            "capabilities": self.capabilities(),
            "headHash": head["headHash"],
            "libraryId": head["libraryId"],
            "refs": {
                "inventory": head["inventoryRef"],
                "proposal": head["proposalRef"],
            },
            "activeOperation": head["activeOperation"],
            "operationState": state,
            "retention": retention_plan(self.root),
        }

    def capabilities(self):
        from avo.adapters.media.library_moves import capability

        return {"physicalMoves": capability(self.root), "paidTranscription": False}

    def scan(self, recursive=False, activity=None):
        from avo.library.inventory import scan_inventory
        from avo.library.proposals import checked_destinations, initial_proposal

        self.writable()
        with self.store.exclusive():
            head = self.store.initialize()
            if self.progress:
                self.progress.library_id = head["libraryId"]
            if head["activeOperation"]:
                reject(
                    "LIB_RESOURCE_BUSY",
                    "Reconcile the active operation before refreshing",
                    "conflict",
                )
            previous = (
                self.store.get(head["inventoryRef"]) if head["inventoryRef"] else None
            )
            inventory = scan_inventory(
                self.root,
                previous,
                recursive=recursive,
                probe=self.probe,
                activity=activity or self.activity,
            )
            inv_ref = self.store.put("inventory", inventory)
            proposal = checked_destinations(
                self.root, initial_proposal(inventory, inv_ref)
            )
            prop_ref = self.store.put("proposal", proposal)
            head = self.store.publish(
                {**head, "inventoryRef": inv_ref, "proposalRef": prop_ref},
                head["headHash"],
            )
        result = self._review_result(head, proposal)
        result.update(
            inventoryRef=inv_ref, proposalRef=prop_ref, summary=inventory["summary"]
        )
        return result

    def propose(self, request=None):
        from avo.library.proposals import apply_edits, initial_proposal

        self.writable()
        with self.store.exclusive():
            head = self.store.head()
            if head["activeOperation"]:
                reject(
                    "LIB_RESOURCE_BUSY",
                    "Reconcile the active operation first",
                    "conflict",
                )
            ref = head["proposalRef"]
            original = self.store.get(ref)
            if request:
                self.check_request(request, head)
                proposal = apply_edits(self.root, original, ref, request)
            else:
                proposal = initial_proposal(
                    self.store.get(head["inventoryRef"]), head["inventoryRef"]
                )
            new_ref = self.store.put("proposal", proposal)
            head = self.store.publish(
                {**head, "proposalRef": new_ref}, head["headHash"]
            )
        result = self._review_result(head, proposal)
        result.update(proposalRef=new_ref, inventoryRef=head["inventoryRef"])
        return result

    def check_request(self, request, head=None):
        head = head or self.store.head()
        if (
            request.get("libraryId") != head["libraryId"]
            or request.get("expectedHeadHash") != head["headHash"]
        ):
            reject("LIB_STALE_PROPOSAL", "Request library/head is stale", "stale")

    def _review_result(self, head, proposal):
        from avo.library.review import render_review

        review = render_review(self.root, proposal, head)
        self.store.created_bytes += sum(path.stat().st_size for path in review.values())
        return {
            "status": "ok",
            "libraryId": head["libraryId"],
            "headHash": head["headHash"],
            "refs": {
                "inventory": head["inventoryRef"],
                "proposal": head["proposalRef"],
                "review": {k: str(v) for k, v in review.items()},
            },
            "summary": proposal["summary"],
        }

    def prepare(self, proposal_identifier, selection):
        from avo.library.moves import prepare

        return prepare(self, proposal_identifier, selection)

    def approve(self, request):
        from avo.library.moves import approve

        return approve(self, request)

    def apply(self, approval_id, *, fault=None, mover=None):
        from avo.library.moves import apply

        return apply(self, approval_id, fault=fault, mover=mover)

    def resume(self, operation_id, *, fault=None, mover=None):
        from avo.library.moves import load, resume

        if load(self, operation_id)["kind"] == "batch":
            from avo.library.batch import resume_batch

            return resume_batch(self, operation_id)

        return resume(self, operation_id, fault=fault, mover=mover)

    def reverse(self, operation_id):
        from avo.library.moves import reverse

        return reverse(self, operation_id)

    def search(self, query, **options):
        from avo.library.search import search_library

        return search_library(self, query, **options)

    def admit_transcript(self, recording_id, relative):
        from avo.library.evidence import admit_transcript

        return admit_transcript(self, recording_id, relative)

    def select(self, request):
        from avo.library.evidence import select

        return select(self, request)

    def activity(self, completed=None, total=None, current=None, **values):
        if self.progress:
            cancelled = self.progress.cancelled
            if cancelled:
                reject(
                    "LIB_CANCELLED",
                    "Cancellation acknowledged; completed results remain",
                    "cancelled",
                )
            self.progress.update(
                completed=completed,
                total=total,
                current=current,
                cancelled=cancelled,
                **values,
            )

    def prepare_batch(self, request):
        from avo.library.batch import prepare_batch

        return prepare_batch(self, request)

    def run_batch(self, approval_id):
        from avo.library.batch import run_batch

        return run_batch(self, approval_id)
