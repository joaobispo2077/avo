"""Project-scoped briefing proposals; never another editing or approval engine."""

from __future__ import annotations

import json
from copy import deepcopy
from importlib import resources
from pathlib import Path

from avo.direction.rules import (
    DirectionError,
    _options_view,
    document_ref,
    parse_selector,
    seal,
    validate,
    validate_options,
    visible_word_count,
)
from avo.direction.sources import read_reference
from avo.direction.store import DirectionStore
from avo.paths import providers_dir
from avo.timeline.contracts import content_hash
from avo.timeline.workspace import resolve_project_raw_dir

_SCHEMA = "avo.briefstart.schema.json#/$defs/"
_MAX_INPUT = 2 * 1024 * 1024


def _context_questions(context):
    prompts = {
        "idea": "What is the video's idea?",
        "promise": "What promise should it deliver?",
        "audience": "Who is the intended viewer?",
        "viewerIntent": "What should the viewer gain?",
        "primaryFormat": "Which primary format fits this video?",
    }
    groups = [("idea", "promise"), ("audience", "viewerIntent"), ("primaryFormat",)]
    return [
        question
        for keys in groups
        if (question := " ".join(prompts[key] for key in keys if not context.get(key)))
    ]


def _source_diagnostics(sources):
    dispositions = [
        f"{source['id']}: {source.get('disposition', 'unknown')}. {source.get('description', '')}"
        for source in sources
    ]
    warnings = [
        disposition
        for disposition in dispositions
        if any(
            f"support-{state}" in disposition
            for state in ("changed", "partial", "unavailable", "not-rechecked")
        )
    ]
    return dispositions, warnings


def _input(value):
    if isinstance(value, dict):
        if (
            len(json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8"))
            > _MAX_INPUT
        ):
            raise DirectionError("DIR_INVALID_REFERENCE", "Inline input exceeds 2 MiB.")
        return deepcopy(value)
    try:
        with Path(value).open("rb") as stream:
            encoded = stream.read(_MAX_INPUT + 1)
        if len(encoded) > _MAX_INPUT:
            raise ValueError("Input exceeds 2 MiB.")
        document = json.loads(encoded)
        if not isinstance(document, dict):
            raise ValueError("Input must be an object.")
        return document
    except (OSError, ValueError, TypeError) as exc:
        raise DirectionError(
            "DIR_INVALID_REFERENCE", f"Cannot read bounded input: {exc}"
        ) from exc


class BriefService:
    """One external project's optional artistic-direction context."""

    def __init__(self, project_path: Path, *, provider_root=None, clock=None):
        self.project_path = Path(project_path).expanduser().resolve()
        self.project = _input(self.project_path)
        self.provider = str(self.project.get("provider") or "").strip()
        if not self.provider or any(character in self.provider for character in "/\\:"):
            raise DirectionError(
                "DIR_INVALID_REFERENCE", "Project provider identity is required."
            )
        self.raw_dir = resolve_project_raw_dir(
            self.project_path, self.project.get("rawDir") or self.project_path.parent
        )
        self.video_id = str(self.project.get("videoId") or self.raw_dir.name)
        self.root = self.raw_dir / "edit" / "briefstart"
        if not self.root.resolve().is_relative_to(self.raw_dir.resolve()):
            raise DirectionError(
                "DIR_INVALID_REFERENCE",
                "Briefing storage must remain inside the declared raw directory.",
            )
        self.store = DirectionStore(self.root)
        self.provider_root = (
            Path(provider_root)
            if provider_root is not None
            else providers_dir() / self.provider
        )
        self.clock = clock

    def _result(self, operation, status, *, refs=None, warnings=None, **fields):
        return {
            "operation": operation,
            "status": status,
            "provider": self.provider,
            "videoId": self.video_id,
            "refs": refs or {},
            "coverage": {},
            "warnings": warnings or [],
            "nextAction": None,
            **fields,
        }

    def _identity(self, document):
        if (
            document.get("provider") != self.provider
            or document.get("videoId") != self.video_id
        ):
            raise DirectionError(
                "DIR_INVALID_REFERENCE",
                "Brief document belongs to another provider or project.",
            )

    def _load_ref(self, reference, kind=None):
        validate("DocumentRef", reference)
        document = self.store.load_document(
            reference["path"], _SCHEMA + kind if kind else None
        )
        if document_ref(document, reference["path"]) != reference:
            raise DirectionError(
                "DIR_SOURCE_CHANGED",
                "Referenced document identity has changed.",
                status="stale",
            )
        self._identity(document)
        return document

    def _materialize(self, kind, fields, directory):
        if (
            kind == "BriefInputPacket"
            and len(json.dumps(fields, ensure_ascii=False).split()) > 24000
        ):
            raise DirectionError(
                "DIR_PACKET_LIMIT",
                "Authoring packet exceeds 24,000 words; select fewer or narrower references.",
            )
        identifier = fields.get("id") or f"{kind.lower()}-{content_hash(fields)[:16]}"
        path = f"{directory}/{identifier}.json"
        document = seal(kind, {"id": identifier, **fields}, clock=self.clock)
        document = self._reuse_envelope(document, path, kind)
        self.store.write_document(path, document, _SCHEMA + kind)
        return document, document_ref(document, path)

    def _reuse_envelope(self, document, relative, kind):
        if not (self.root / relative).is_file():
            return document
        existing = self.store.load_document(relative, _SCHEMA + kind)
        ignored = {"createdAt", "documentHash"}
        old_fields = {
            key: value for key, value in existing.items() if key not in ignored
        }
        new_fields = {
            key: value for key, value in document.items() if key not in ignored
        }
        if old_fields != new_fields:
            raise DirectionError(
                "DIR_INDEX_CONFLICT",
                "An existing immutable body has different content or identity.",
                status="conflict",
            )
        return existing

    @staticmethod
    def _reference_sources(references):
        result = []
        for value in references:
            document = (
                _input(value) if isinstance(value, dict) else read_reference(value)
            )
            validate("ReferenceDescriptor", document)
            result.append(
                {
                    "id": document["referenceId"],
                    "kind": "reference",
                    "document": document,
                    "disposition": document["observationKind"],
                }
            )
        if len({source["id"] for source in result}) != len(result):
            raise DirectionError(
                "DIR_INVALID_REFERENCE", "Reference identities must be unique."
            )
        return result

    @staticmethod
    def _builtin_source(selected, selector):
        try:
            catalog = json.loads(
                resources.files("avo.resources.directions")
                .joinpath("catalog.json")
                .read_text(encoding="utf-8")
            )
        except (OSError, ValueError, ModuleNotFoundError) as exc:
            raise DirectionError(
                "DIR_INVALID_REFERENCE",
                "Packaged directions are unavailable.",
                status="unavailable",
            ) from exc
        document = next(
            (
                item
                for item in catalog["directions"]
                if item["builtinId"] == selected["id"]
                and item["version"] == selected["version"]
            ),
            None,
        )
        if document is None:
            raise DirectionError(
                "DIR_INVALID_REFERENCE",
                "Requested packaged direction version is unavailable.",
                status="unavailable",
            )
        validate("BuiltinDirection", document)
        return {
            "id": document["builtinId"],
            "kind": "builtin",
            "selector": selector,
            "document": document,
            "disposition": "packaged-exact-version",
        }

    def _provider_source(self, selected, selector):
        from avo.direction.service import DirectionService

        try:
            shown = DirectionService(
                self.provider_root, self.provider, clock=self.clock
            ).show(f"{selected['id']}@{selected['version']}", check_sources=True)
        except (OSError, ValueError) as exc:
            raise DirectionError(
                "BRIEF_UNACCEPTED_PROVIDER_PROFILE",
                "An exact accepted provider profile is required; choose a built-in, references or none instead.",
                status="unavailable",
            ) from exc
        if shown.get("reviewState") != "accepted":
            raise DirectionError(
                "BRIEF_UNACCEPTED_PROVIDER_PROFILE",
                "The requested exact provider revision is not accepted.",
                status="unavailable",
            )
        document = shown["profile"]
        if document["provider"] != self.provider:
            raise DirectionError(
                "DIR_INVALID_REFERENCE", "Provider profile belongs to another provider."
            )
        freshness = shown.get("freshness", {"status": "not-rechecked"})
        state = freshness["status"]
        affected = ", ".join(freshness.get("affectedEntryIds", []))
        return {
            "id": document["id"],
            "kind": "provider",
            "selector": selector,
            "document": document,
            "ref": shown["refs"]["profile"],
            "disposition": f"accepted-exact-version;support-{state}",
            "description": f"Historical profile support: {state}. Affected entries: {affected or 'none reported'}. Reconsider linked conclusions when support is changed or unavailable.",
        }

    def _sources(self, selector, references):
        selected = parse_selector(selector)
        result = self._reference_sources(references)
        if selected["mode"] == "builtin":
            result.insert(0, self._builtin_source(selected, selector))
        if selected["mode"] == "provider":
            result.insert(0, self._provider_source(selected, selector))
        if not result:
            raise DirectionError(
                "DIR_INVALID_REFERENCE",
                "References mode needs at least one explicit reference.",
            )
        if len({source["id"] for source in result}) != len(result):
            raise DirectionError(
                "DIR_INVALID_REFERENCE", "Selected source identities must be unique."
            )
        return result

    def _opt_out(self, current):
        fields = {
            "provider": self.provider,
            "videoId": self.video_id,
            "selector": "none",
            "previousSelectionRef": current["selectedSelectionRef"],
            "expectedIndexHash": current["indexHash"],
        }
        _, reference = self._materialize("BriefOptOutProposal", fields, "briefs")
        return self._result(
            "briefstart.prepare",
            "needs-review",
            refs={"proposal": reference},
            expectedIndexHash=current["indexHash"],
            nextAction="Record the explicit opt-out against this exact proposal.",
        )

    def _start(self, selector, references):
        current = self.store.load_index()
        if selector is None and current and current.get("selectedBriefRef"):
            return None, self.show()
        initial = (self.project.get("direction") or {}).get("selector", "none")
        selector = selector if selector is not None else initial
        if selector != "none":
            return selector, None
        if references:
            raise DirectionError(
                "DIR_INVALID_REFERENCE",
                "No-reference cannot include artistic references; choose references mode.",
            )
        if current and current.get("selectedBriefRef"):
            return None, self._opt_out(current)
        return None, self._result("briefstart.prepare", "bypassed", mode="none")

    def _configured_input(self, locator):
        path = (self.project_path.parent / locator).resolve()
        if not path.is_relative_to(self.root.resolve()):
            raise DirectionError(
                "DIR_INVALID_REFERENCE",
                "Declared briefing inputs must remain inside edit/briefstart.",
            )
        return path

    def _intake_inputs(self, context, references):
        declared = self.project.get("direction") or {}
        if context is None and declared.get("contextFile"):
            context = self._configured_input(declared["contextFile"])
        if references is None:
            references = [
                self._configured_input(path)
                for path in declared.get("referenceFiles", [])
            ]
        return context, references or []

    def prepare(self, selector=None, context=None, references=None):
        selector, early = self._start(selector, references)
        if early is not None:
            return early
        parse_selector(selector)
        context, references = self._intake_inputs(context, references)
        normalized = (
            _input(context) if context is not None else {"schemaVersion": "1.0.0"}
        )
        if not normalized.get("idea") and self.project.get("title"):
            normalized["idea"] = self.project["title"]
        validate("Context", normalized)
        questions = _context_questions(normalized)
        fields = {
            "provider": self.provider,
            "videoId": self.video_id,
            "selector": selector,
            "context": normalized,
            "contextHash": content_hash(normalized),
            "sources": self._sources(selector, references or []),
            "assumptions": normalized.get("assumptions", []),
            "questions": questions[:3],
            "expectedIndexHash": self.store.index_hash(),
            "submissionTemplateVersion": "1.0.0",
        }
        fields["sourceDispositions"], warnings = _source_diagnostics(fields["sources"])
        packet, reference = self._materialize("BriefInputPacket", fields, "inputs")
        return self._result(
            "briefstart.prepare",
            "needs-context" if questions else "needs-authoring",
            refs={"packet": reference},
            expectedIndexHash=packet["expectedIndexHash"],
            questions=packet["questions"],
            warnings=warnings,
            nextAction="Provide missing context."
            if questions
            else "Author options from this exact packet.",
        )

    def _proposal_packet(self, request):
        validate("BriefProposeRequest", request)
        packet = self._load_ref(request["packetRef"], "BriefInputPacket")
        if packet["questions"]:
            raise DirectionError(
                "BRIEF_MISSING_CONTEXT",
                "Answer material context questions before proposing options.",
            )
        if request["expectedIndexHash"] != packet["expectedIndexHash"]:
            raise DirectionError(
                "DIR_INDEX_CONFLICT",
                "Proposal expected index differs from its prepared packet.",
                status="conflict",
            )
        if request["synthesisProvenance"].get("packetHash") != packet["documentHash"]:
            raise DirectionError(
                "DIR_INVALID_REFERENCE",
                "Proposal provenance must identify its exact packet hash.",
            )
        return packet

    @staticmethod
    def _option_statements(option, sources):
        selected = {source["sourceId"] for source in option["sourceContribution"]}
        return {
            statement["statementId"]
            for source in sources
            if source["kind"] == "provider" and source["id"] in selected
            for statement in source["document"].get("statements", [])
        }

    @staticmethod
    def _validate_contributions(request, packet):
        validate_options(
            request["options"], request["shortView"], request.get("singletonReason", "")
        )
        known = {source["id"] for source in packet["sources"]}
        for option in request["options"]:
            if not option["sourceContribution"] or any(
                source["sourceId"] not in known
                for source in option["sourceContribution"]
            ):
                raise DirectionError(
                    "DIR_INVALID_REFERENCE",
                    "Option contributions must cite exact packet sources.",
                )
            if not set(option["statementIds"]).issubset(
                BriefService._option_statements(option, packet["sources"])
            ):
                raise DirectionError(
                    "DIR_INVALID_REFERENCE",
                    "Option statement identities must exist in its selected provider source.",
                )

    def _proposal_retry(self, request, current, identifier):
        if current and request["requestId"] in current.get("requests", {}):
            current = self.store.request_result(request["requestId"])
            previous = next(
                (
                    ref
                    for ref in current.get("proposedRefs", [])
                    if ref["id"] == identifier
                ),
                None,
            )
            if previous:
                return self._result(
                    "briefstart.propose",
                    "needs-review",
                    refs={"proposal": previous},
                    expectedIndexHash=current["indexHash"],
                )
            raise DirectionError(
                "DIR_INDEX_CONFLICT",
                "Request identity was already used with different content.",
                status="conflict",
            )
        return None

    def _proposal_document(self, request, packet, identifier):
        if self.store.index_hash() != request["expectedIndexHash"]:
            raise DirectionError(
                "DIR_INDEX_CONFLICT",
                "Project selection changed after packet preparation.",
                status="conflict",
            )
        fields = {
            key: deepcopy(packet[key])
            for key in (
                "provider",
                "videoId",
                "selector",
                "context",
                "contextHash",
                "sources",
                "assumptions",
                "questions",
            )
        }
        fields.update(
            id=identifier,
            packetRef=request["packetRef"],
            options=request["options"],
            shortView=_options_view(
                request["options"],
                request["shortView"],
                request.get("singletonReason", ""),
            ),
            synthesisProvenance=request["synthesisProvenance"],
            sourceDispositions=packet.get("sourceDispositions", []),
            summaryText=request["shortView"],
        )
        if request.get("singletonReason"):
            fields["singletonReason"] = request["singletonReason"]
        return seal("ProjectBriefVersion", fields, clock=self.clock)

    def _index(self, current):
        if current:
            return deepcopy(current)
        return {
            "schemaVersion": "1.0.0",
            "documentType": "ProjectBriefIndex",
            "provider": self.provider,
            "videoId": self.video_id,
            "proposedRefs": [],
            "selectedBriefRef": None,
            "selectedSelectionRef": None,
        }

    def _write_view(self, document):
        warnings = []
        try:
            view = self.store._path(f"views/{document['id']}.md")
            view.parent.mkdir(parents=True, exist_ok=True)
            view.write_text(document["shortView"] + "\n", encoding="utf-8")
        except (OSError, DirectionError):
            warnings.append(
                "Derived Markdown is unavailable; JSON proposal remains authoritative."
            )
        return warnings

    def propose(self, request):
        packet = self._proposal_packet(request)
        self._validate_contributions(request, packet)
        current = self.store.load_index()
        identifier = f"brief-{content_hash(request)[:16]}"
        retry = self._proposal_retry(request, current, identifier)
        if retry:
            return retry
        document = self._proposal_document(request, packet, identifier)
        path = f"briefs/{identifier}.json"
        document = self._reuse_envelope(document, path, "ProjectBriefVersion")
        reference = document_ref(document, path)
        index = self._index(current)
        index["proposedRefs"].append(reference)
        published = self.store.publish(
            expected_index_hash=request["expectedIndexHash"],
            request_id=request["requestId"],
            documents=[(reference["path"], document, _SCHEMA + "ProjectBriefVersion")],
            index=index,
        )
        return self._result(
            "briefstart.propose",
            "needs-review",
            refs={"proposal": reference},
            expectedIndexHash=published["indexHash"],
            warnings=self._write_view(document),
            nextAction="Review these exact options and select or edit one for this project.",
        )

    def _decision_retry(self, request, current):
        if not current or request["requestId"] not in current.get("requests", {}):
            return None
        current = self.store.request_result(request["requestId"])
        identifier = f"decision-{content_hash(request)[:16]}"
        event_ref = next(
            (ref for ref in current.get("decisionRefs", []) if ref["id"] == identifier),
            None,
        )
        if event_ref is None:
            raise DirectionError(
                "DIR_INDEX_CONFLICT",
                "Request ID was reused with different decision content.",
                status="conflict",
            )
        return self._replay_decision(request, current, event_ref)

    def _replay_decision(self, request, current, event_ref):
        if request["action"] in {"edit", "qualify"}:
            proposal = next(
                ref
                for ref in current.get("proposedRefs", [])
                if ref["id"] == f"brief-edit-{content_hash(request)[:16]}"
            )
            return self._result(
                "briefstart.decide",
                "needs-review",
                refs={"proposal": proposal, "decision": event_ref},
                expectedIndexHash=current["indexHash"],
            )
        if request["action"] in {"reject", "defer"}:
            return self._result(
                "briefstart.decide",
                "ok",
                refs={"decision": event_ref},
                disposition=request["action"],
                expectedIndexHash=current["indexHash"],
            )
        references = {"decision": event_ref}
        if current.get("selectedBriefRef"):
            references.update(
                brief=current["selectedBriefRef"],
                selection=current["selectedSelectionRef"],
            )
        return self._result(
            "briefstart.decide",
            "selected",
            refs=references,
            expectedIndexHash=current["indexHash"],
        )

    def _decision_target(self, request, current):
        if not current or current["indexHash"] != request["expectedIndexHash"]:
            raise DirectionError(
                "DIR_INDEX_CONFLICT",
                "Selection changed before the creator decision.",
                status="conflict",
            )
        target = self._load_ref(request["targetRef"])
        if target["documentType"] == "BriefOptOutProposal":
            validate("BriefOptOutProposal", target)
            if (
                target["previousSelectionRef"] != current.get("selectedSelectionRef")
                or target["expectedIndexHash"] != current["indexHash"]
            ):
                raise DirectionError(
                    "DIR_INDEX_CONFLICT",
                    "Opt-out no longer targets the current exact selection.",
                    status="conflict",
                )
            return target
        if request["targetRef"] not in current.get("proposedRefs", []):
            raise DirectionError(
                "DIR_INVALID_REFERENCE",
                "Creator decision must target an exact current proposal.",
            )
        return self._load_ref(request["targetRef"], "ProjectBriefVersion")

    def _decision_event(self, request):
        event = seal(
            "CreatorDecision",
            {"id": f"decision-{content_hash(request)[:16]}", **request},
            clock=self.clock,
        )
        path = f"decisions/{event['id']}.json"
        event = self._reuse_envelope(event, path, "CreatorDecision")
        reference = document_ref(event, path)
        return event, reference

    def _publish_event(self, request, current, *, updates=None, documents=None):
        event, event_ref = self._decision_event(request)
        index = deepcopy(current)
        index.update(updates or {})
        index.setdefault("decisionRefs", []).append(event_ref)
        bodies = list(documents or []) + [
            (
                event_ref["path"],
                event,
                _SCHEMA + "CreatorDecision",
            )
        ]
        published = self.store.publish(
            expected_index_hash=request["expectedIndexHash"],
            request_id=request["requestId"],
            documents=bodies,
            index=index,
        )
        return published, event_ref

    def _decide_opt_out(self, request, current):
        if (
            request["action"] != "select"
            or request.get("edits")
            or request.get("optionId")
        ):
            raise DirectionError(
                "DIR_APPROVAL_SCOPE",
                "Opt-out requires exact selection of the no-reference proposal.",
            )
        published, reference = self._publish_event(
            request,
            current,
            updates={
                "mode": "none",
                "selector": "none",
                "selectedBriefRef": None,
                "selectedSelectionRef": None,
                "replanRequired": True,
            },
        )
        return self._result(
            "briefstart.decide",
            "selected",
            mode="none",
            refs={"decision": reference},
            expectedIndexHash=published["indexHash"],
        )

    def _decide_inactive(self, request, current):
        if current.get("selectedBriefRef") == request["targetRef"]:
            raise DirectionError(
                "DIR_APPROVAL_SCOPE",
                "Use the explicit no-reference choice to withdraw an already selected brief.",
            )
        published, reference = self._publish_event(request, current)
        return self._result(
            "briefstart.decide",
            "ok",
            refs={"decision": reference},
            disposition=request["action"],
            expectedIndexHash=published["indexHash"],
        )

    @staticmethod
    def _edit_summary(request, brief):
        edits = request["edits"]
        if "shortView" in edits:
            return edits["shortView"]
        if "summaryText" in brief:
            return brief["summaryText"]
        if "options" in edits or "singletonReason" in edits:
            raise DirectionError(
                "BRIEF_MISSING_CONTEXT",
                "This legacy brief needs a revised summary when its options change.",
            )
        return None

    @staticmethod
    def _edited_view(brief, fields, edits, summary, singleton):
        if summary is None:
            view, changes = brief["shortView"], edits.get("creatorChanges", [])
        else:
            view = _options_view(fields["options"], summary, singleton)
            changes = fields["creatorChanges"]
        if changes:
            view += "\n\nCreator changes:\n" + "\n".join(
                f"- {change}" for change in changes
            )
        if visible_word_count(view) > 600:
            raise DirectionError(
                "BRIEF_WORD_LIMIT", "The edited visible briefing exceeds 600 words."
            )
        return view

    def _edited_packet(self, request, brief):
        fields = {
            key: deepcopy(brief[key])
            for key in (
                "provider",
                "videoId",
                "selector",
                "context",
                "contextHash",
                "sources",
            )
        }
        fields.update(
            assumptions=brief.get("assumptions", []),
            questions=[],
            expectedIndexHash=request["expectedIndexHash"],
            sourceDispositions=brief.get("sourceDispositions", []),
            submissionTemplateVersion="1.0.0",
        )
        return self._materialize("BriefInputPacket", fields, "inputs")

    def _edited_document(self, request, brief):
        if not request.get("edits"):
            raise DirectionError(
                "DIR_INVALID_REQUEST",
                "An edit or qualification requires its concrete proposed content.",
            )
        edits = request["edits"]
        options = deepcopy(edits.get("options", brief["options"]))
        summary = self._edit_summary(request, brief)
        singleton = edits.get("singletonReason", brief.get("singletonReason", ""))
        _, packet_ref = self._edited_packet(request, brief)
        packet = self._load_ref(packet_ref, "BriefInputPacket")
        validation_request = {
            "options": options,
            "shortView": summary or "",
            "singletonReason": singleton,
        }
        self._validate_contributions(validation_request, packet)
        fields = {
            key: deepcopy(value)
            for key, value in brief.items()
            if key
            not in {
                "schemaVersion",
                "documentType",
                "id",
                "createdAt",
                "createdBy",
                "documentHash",
            }
        }
        fields.update(
            id=f"brief-edit-{content_hash(request)[:16]}",
            packetRef=packet_ref,
            options=options,
            creatorChanges=brief.get("creatorChanges", [])
            + edits.get("creatorChanges", []),
        )
        if summary is not None:
            fields["summaryText"] = summary
        fields["shortView"] = self._edited_view(
            brief, fields, edits, summary, singleton
        )
        fields["synthesisProvenance"] = {
            "executionKind": "human",
            "agentId": None,
            "modelId": None,
            "packetHash": packet_ref["documentHash"],
            "promptHash": None,
        }
        if singleton:
            fields["singletonReason"] = singleton
        return seal("ProjectBriefVersion", fields, clock=self.clock)

    def _decide_edit(self, request, current, brief):
        document = self._edited_document(request, brief)
        path = f"briefs/{document['id']}.json"
        document = self._reuse_envelope(document, path, "ProjectBriefVersion")
        reference = document_ref(document, path)
        proposed = current.get("proposedRefs", []) + [reference]
        published, event_ref = self._publish_event(
            request,
            current,
            updates={"proposedRefs": proposed},
            documents=[(reference["path"], document, _SCHEMA + "ProjectBriefVersion")],
        )
        return self._result(
            "briefstart.decide",
            "needs-review",
            refs={"proposal": reference, "decision": event_ref},
            expectedIndexHash=published["indexHash"],
            warnings=self._write_view(document),
            nextAction="Review and select the new exact edited proposal; the prior selection is unchanged.",
        )

    def _frozen_sources(self, brief, option):
        selected = {source["sourceId"] for source in option["sourceContribution"]}
        documents, references = [], []
        for source in brief["sources"]:
            if source["id"] not in selected:
                continue
            fields = {
                "provider": self.provider,
                "videoId": self.video_id,
                "source": source,
            }
            fields["id"] = f"frozen-{content_hash(fields)[:16]}"
            path = f"frozen/{content_hash(source)}.json"
            frozen = seal("FrozenBriefSource", fields, clock=self.clock)
            frozen = self._reuse_envelope(frozen, path, "FrozenBriefSource")
            documents.append((path, frozen, _SCHEMA + "FrozenBriefSource"))
            references.append(document_ref(frozen, path))
        return documents, references

    def _selection_documents(self, request, brief, option):
        documents, sources = self._frozen_sources(brief, option)
        decision, event_ref = self._decision_event(request)
        selection = seal(
            "BriefSelection",
            {
                "provider": self.provider,
                "videoId": self.video_id,
                "briefRef": request["targetRef"],
                "optionId": option["id"],
                "scope": "project",
                "decisionRef": event_ref,
                "sourceRefs": sources,
                "creatorChanges": brief.get("creatorChanges", []),
            },
            clock=self.clock,
        )
        path = f"decisions/{selection['id']}.json"
        selection = self._reuse_envelope(selection, path, "BriefSelection")
        selection_ref = document_ref(selection, path)
        documents.extend(
            [
                (
                    event_ref["path"],
                    decision,
                    _SCHEMA + "CreatorDecision",
                ),
                (selection_ref["path"], selection, _SCHEMA + "BriefSelection"),
            ]
        )
        return documents, event_ref, selection_ref

    def decide(self, request):
        validate("BriefDecideRequest", request)
        current = self.store.load_index()
        retry = self._decision_retry(request, current)
        if retry:
            return retry
        brief = self._decision_target(request, current)
        if brief["documentType"] == "BriefOptOutProposal":
            return self._decide_opt_out(request, current)
        if request["action"] in {"edit", "qualify"}:
            return self._decide_edit(request, current, brief)
        if request["action"] in {"reject", "defer"}:
            return self._decide_inactive(request, current)
        return self._decide_select(request, current, brief)

    def _decide_select(self, request, current, brief):
        if request["action"] not in {"select", "accept"} or request.get("edits"):
            raise DirectionError(
                "DIR_APPROVAL_SCOPE",
                "This operation requires exact option selection; edits need a new proposal.",
            )
        option = next(
            (
                option
                for option in brief["options"]
                if option["id"] == request.get("optionId")
            ),
            None,
        )
        if option is None:
            raise DirectionError(
                "DIR_INVALID_REFERENCE",
                "Select an option from the exact reviewed proposal.",
            )
        documents, event_ref, selection_ref = self._selection_documents(
            request, brief, option
        )
        index = deepcopy(current)
        index["replanRequired"] = bool(index.get("selectedBriefRef"))
        index.update(
            selectedBriefRef=request["targetRef"],
            selectedSelectionRef=selection_ref,
            selector=brief["selector"],
            mode=parse_selector(brief["selector"])["mode"],
        )
        index.setdefault("decisionRefs", []).append(event_ref)
        index.setdefault("selectionRefs", []).append(selection_ref)
        index.setdefault("inputRefs", []).append(brief["packetRef"])
        published = self.store.publish(
            expected_index_hash=request["expectedIndexHash"],
            request_id=request["requestId"],
            documents=documents,
            index=index,
        )
        return self._result(
            "briefstart.decide",
            "selected",
            refs={
                "brief": request["targetRef"],
                "selection": selection_ref,
                "decision": event_ref,
            },
            expectedIndexHash=published["indexHash"],
            nextAction="Continue normal project planning with the exact selected brief.",
        )

    @staticmethod
    def _shown_reference(index, ref):
        if ref is None:
            return index.get("selectedBriefRef")
        reference = next(
            (
                candidate
                for candidate in index.get("proposedRefs", [])
                if candidate["id"] == ref
            ),
            None,
        )
        if reference is None:
            raise DirectionError(
                "DIR_INVALID_REFERENCE", "Unknown historical brief identity."
            )
        return reference

    def show(self, ref=None):
        index = self.store.load_index()
        if not index:
            return self._result(
                "briefstart.show", "bypassed", mode="none", brief=None, selection=None
            )
        reference = self._shown_reference(index, ref)
        if reference is None:
            return self._result(
                "briefstart.show",
                "bypassed",
                mode=index.get("mode", "none"),
                brief=None,
                selection=None,
                expectedIndexHash=index["indexHash"],
            )
        brief = self._load_ref(reference, "ProjectBriefVersion")
        selection = None
        if index.get("selectedSelectionRef") and reference == index.get(
            "selectedBriefRef"
        ):
            selection = self._load_ref(index["selectedSelectionRef"], "BriefSelection")
        return self._result(
            "briefstart.show",
            "selected" if selection else "needs-review",
            refs={
                "brief": reference,
                "selection": index.get("selectedSelectionRef") if selection else None,
            },
            brief=brief,
            selection=selection,
            expectedIndexHash=index["indexHash"],
        )

    def _stage_statements(self, selection, option, stage):
        dimensions = {
            "structure": {
                "editorial-voice",
                "creator-presence",
                "emotional-arc",
                "pacing",
            },
            "cmap": {"pacing", "editorial-voice", "avoidance"},
            "bmap": {"visual-support", "evidence-inserts", "captions", "avoidance"},
            "motion": {"motion", "visual-support", "captions", "avoidance"},
            "sound": {"sound", "pacing", "avoidance"},
        }[stage]
        statements = []
        for reference in selection["sourceRefs"]:
            frozen = self._load_ref(reference, "FrozenBriefSource")
            source = frozen["source"]
            if source["kind"] != "provider":
                continue
            statements.extend(
                statement
                for statement in source["document"].get("statements", [])
                if statement["statementId"] in option["statementIds"]
                and statement["dimension"] in dimensions
            )
        return statements

    def _stage_value(self, shown, stage, canonical_heads):
        brief, selection = shown["brief"], shown["selection"]
        option = next(
            option
            for option in brief["options"]
            if option["id"] == selection["optionId"]
        )
        statements = self._stage_statements(selection, option, stage)
        exclusions = list(option["exclusions"])
        for statement in statements:
            exclusions.extend(statement["exclusions"])
            exclusions.extend(statement["applicability"].get("exclusions", []))
        return {
            "briefRef": shown["refs"]["brief"],
            "optionId": option["id"],
            "option": deepcopy(option),
            "treatment": deepcopy(option["treatment"]),
            "statementIds": [statement["statementId"] for statement in statements],
            "statements": deepcopy(statements),
            "exclusions": list(dict.fromkeys(exclusions)),
            "constraints": brief["context"].get("constraints", []),
            "sourceDispositions": brief.get("sourceDispositions", []),
            "overrides": brief["context"].get("currentInstructions", [])
            + selection.get("creatorChanges", []),
            "canonicalHeads": deepcopy(canonical_heads or {}),
        }

    def _stage_receipt(self, stage, context):
        fields = {
            "provider": self.provider,
            "videoId": self.video_id,
            "stage": stage,
            "status": "offered-to-authoring",
            **{
                key: value
                for key, value in context.items()
                if key
                not in {
                    "option",
                    "treatment",
                    "statements",
                    "constraints",
                    "sourceDispositions",
                }
            },
        }
        _, reference = self._materialize("StageGuidanceReceipt", fields, "context")
        return reference

    def stage_context(self, stage: str, canonical_heads=None, *, record=False):
        if stage not in {"structure", "cmap", "bmap", "motion", "sound"}:
            raise DirectionError("DIR_INVALID_REFERENCE", "Unknown authoring stage.")
        shown = self.show()
        if not shown["selection"]:
            return self._result(
                "briefstart.stage-context", "bypassed", stage=stage, context=None
            )
        context = self._stage_value(shown, stage, canonical_heads)
        result = self._result(
            "briefstart.stage-context",
            "ok",
            refs={"brief": shown["refs"]["brief"]},
            stage=stage,
            context=context,
        )
        if record:
            receipt_ref = self._stage_receipt(stage, context)
            result["receiptRef"] = receipt_ref
            result["refs"]["receipt"] = receipt_ref
        return result
