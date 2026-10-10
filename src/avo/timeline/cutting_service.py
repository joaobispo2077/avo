"""Opt-in cutting orchestration; immutable evidence, sole CMap authority."""

from __future__ import annotations

import json
import re
from copy import deepcopy
from dataclasses import replace
from fractions import Fraction
from math import ceil, floor
from pathlib import Path

from .cmap_service import CMapService
from .contracts import ContractError, content_hash, file_fingerprint
from .cutting_audit import audit_joins
from .cutting_boundaries import propose_pause
from .cutting_content_proposals import editorial_proposal
from .cutting_contracts import (
    make_document,
    occurrence_id,
    selection_graph_hash,
    source_interval,
    validate_source_range,
)
from .cutting_policy import resolve_cutting_policy, resolve_section_policy
from .cutting_requests import validate_cutting_request
from .cutting_store import CuttingStore, CuttingStoreError
from .cutting_take_proposals import propose_retakes
from .lifecycle import PipelineRunStore
from .ports import BoundaryVerificationPort
from .store import now_iso


class CuttingServiceError(ValueError):
    """A proposal cannot be used with missing or changed evidence."""


def _proposal_status(occurrences, unobserved, joins):
    if (
        unobserved
        or joins
        or any(item["disposition"] == "needs-review" for item in occurrences)
    ):
        return "needs-review"
    return "proposed"


def _content_reports(request, content):
    if request.get("targetDurationMs") is not None or request.get("editorialUnits"):
        return [content]
    return []


def _validated_request(request, operation="analyze"):
    try:
        return validate_cutting_request(request, operation)
    except ContractError as exc:
        raise CuttingServiceError(str(exc)) from exc


def _validate_decision(decision, occurrence, preview, proposal):
    disposition = decision["disposition"]
    if disposition in {"keep", "needs-review"}:
        return
    planned = {edit["occurrenceId"] for edit in proposal["edits"]}
    if occurrence["occurrenceId"] not in planned:
        raise CuttingServiceError("a new verified proposal is required for this repair")
    if decision.get("alternativeId") is not None and decision[
        "alternativeId"
    ] != occurrence.get("selectedAlternativeId"):
        raise CuttingServiceError(
            "a changed alternative requires a new verified proposal"
        )
    if occurrence.get("editorialApprovalRequired"):
        if decision.get("editorialApproval") is not True:
            raise CuttingServiceError(
                "substantive removal requires explicit editorialApproval"
            )
        return
    if disposition != occurrence["disposition"]:
        raise CuttingServiceError("decision changes the proposed repair selection")
    if preview["status"] != "pass":
        raise CuttingServiceError(
            "preview verification must pass before accepting a repair"
        )


def _decision_leaves(records):
    superseded, children = set(), {}
    for digest, record in records.items():
        parent = record.get("supersedesRef")
        if parent is None:
            continue
        prior = records.get(parent["sha256"])
        if (
            prior is None
            or prior["decisionRef"] != parent
            or prior["occurrenceId"] != record["occurrenceId"]
        ):
            raise CuttingServiceError("invalid decision supersession")
        if parent["sha256"] in children:
            raise CuttingServiceError(
                "concurrent decision choices require a new proposal"
            )
        children[parent["sha256"]] = digest
        superseded.add(parent["sha256"])
    decisions = {}
    for digest, record in records.items():
        if digest in superseded:
            continue
        identity = record["occurrenceId"]
        if identity in decisions:
            raise CuttingServiceError(
                "conflicting immutable decisions need a new proposal"
            )
        decisions[identity] = record
    return decisions


def segment_range(segment):
    if segment["in"]["timebase"] != segment["out"]["timebase"]:
        raise CuttingServiceError("mixed source clocks need explicit normalization")
    return {
        "sourceId": segment["sourceId"],
        "startTicks": segment["in"]["ticks"],
        "endTicksExclusive": segment["out"]["ticks"],
        "timebase": segment["in"]["timebase"],
    }


def _contained(inner, outer):
    validate_source_range(inner)
    validate_source_range(outer)

    def seconds(interval, key):
        basis = interval["timebase"]
        return interval[key] * Fraction(basis["num"], basis["den"])

    return (
        inner["sourceId"] == outer["sourceId"]
        and seconds(inner, "startTicks") >= seconds(outer, "startTicks")
        and seconds(inner, "endTicksExclusive") <= seconds(outer, "endTicksExclusive")
    )


def consolidate_removals(snapshot, edits):
    """Subtract within existing units; never bridge a rejected gap or reorder."""
    result = deepcopy(snapshot)
    if edits:
        result.pop("cuttingRef", None)
    by_segment = {}
    for edit in edits:
        by_segment.setdefault(edit["segmentId"], []).append(edit["removeRange"])
    known = {segment["segmentId"] for segment in result["segments"]}
    if set(by_segment) - known:
        raise CuttingServiceError("edit refers to an unknown canonical segment")
    selected = []
    for segment in result["segments"]:
        selected.extend(
            _subtract_unit(segment, by_segment.get(segment["segmentId"], []))
        )
    result["segments"] = selected
    return result


def _subtract_unit(segment, cuts):
    if not cuts:
        return [segment]
    unit = segment_range(segment)
    if any(
        not _contained(cut, unit) or cut["timebase"] != unit["timebase"] for cut in cuts
    ):
        raise CuttingServiceError("removal crosses a retained unit or source clock")
    cursor = unit["startTicks"]
    intervals = []
    for cut in sorted(cuts, key=lambda value: value["startTicks"]):
        if cut["startTicks"] < cursor:
            raise CuttingServiceError(
                "overlapping removals cannot duplicate or restore speech"
            )
        if cursor < cut["startTicks"]:
            intervals.append((cursor, cut["startTicks"]))
        cursor = cut["endTicksExclusive"]
    if cursor < unit["endTicksExclusive"]:
        intervals.append((cursor, unit["endTicksExclusive"]))
    selected = []
    for ordinal, (start, end) in enumerate(intervals, 1):
        part = deepcopy(segment)
        part["segmentId"] = f"{segment['segmentId']}-cut-{ordinal}"
        part["in"]["ticks"], part["out"]["ticks"] = start, end
        selected.append(part)
    return selected


class CuttingService:
    def __init__(
        self,
        workspace,
        *,
        policy=None,
        analysis_port=None,
        preview_port=None,
        verification_port: BoundaryVerificationPort | None = None,
        retake_port=None,
        context_port=None,
        run_store=None,
    ):
        self.workspace = workspace
        self.policy = policy or resolve_cutting_policy(
            project_settings=workspace.project.get("cutting")
        )
        self.analysis_port = analysis_port
        self.preview_port = preview_port
        self.verification_port = verification_port
        self.retake_port = retake_port
        self.context_port = context_port
        self.run_store = run_store or PipelineRunStore(workspace.pipeline_run_path)
        self.store = CuttingStore(
            workspace.timeline_dir / "cutting",
            video_id=workspace.video_id,
            provider=workspace.project["provider"],
        )

    def _current(self):
        cmap = self.workspace.store("cmap")
        index = cmap.load_index()
        if not index["headRevisionId"]:
            raise CuttingServiceError(
                "canonical CMap is required before cutting analysis"
            )
        revision = cmap.revision(index["headRevisionId"])
        CMapService(self.workspace)._verify_raw(revision["snapshot"])
        return revision

    def _sync_ref(self):
        basis = CMapService(self.workspace)._sync_basis()
        return {"locator": basis["revisionId"], "sha256": basis["contentSha256"]}

    def resolve_ref(self, reference):
        if isinstance(reference, dict):
            self.store.load_document(reference)
            return reference
        path = Path(reference).resolve()
        if not path.is_relative_to(self.store.directory.resolve()):
            raise CuttingServiceError(
                "proposal must be inside the cutting evidence directory"
            )
        document = json.loads(path.read_text(encoding="utf-8"))
        ref = {
            "locator": path.relative_to(self.store.directory.resolve()).as_posix(),
            "sha256": content_hash(document),
        }
        self.store.load_document(ref)
        return ref

    def _proposal(self, reference):
        ref = self.resolve_ref(reference)
        document = self.store.load_document(ref)
        if document["documentType"] != "proposal":
            raise CuttingServiceError("expected a cutting proposal")
        proposal = document["payload"]
        if proposal["baseCMapHash"] != self._current()["contentHash"]:
            raise CuttingServiceError("stale cutting proposal: CMap changed")
        if proposal["syncRef"] != self._sync_ref():
            raise CuttingServiceError("stale cutting proposal: Sync changed")
        policy = self.store.load_document(proposal["policyRef"])["payload"]
        if policy["policyHash"] != self.policy.policy_hash:
            raise CuttingServiceError("stale cutting proposal: policy changed")
        binding = proposal.get("implementationBindings") or {}
        current_binding = self._implementation_binding()
        if binding.get("files") != current_binding["files"]:
            raise CuttingServiceError("stale cutting proposal: implementation changed")
        if binding.get("dependencies") != current_binding["dependencies"]:
            raise CuttingServiceError(
                "stale cutting proposal: runtime or model changed"
            )
        return ref, proposal

    def _implementation_binding(self):
        directory = Path(__file__).parent
        root = directory.parent
        names = [
            *directory.glob("cutting_*.py"),
            directory / "initial_cut.py",
            directory / "proof_plan.py",
            directory / "materialize.py",
        ]
        names.extend(root.glob("adapters/**/cutting*.py"))
        names.extend(
            [
                root / "adapters/understand/watch_skill.py",
                root / "adapters/media/timeline_render.py",
                root / "transcribe.py",
                root.parent.parent / "schemas/avo.cutting.schema.json",
            ]
        )
        return {
            "files": {
                str(path.relative_to(root.parent.parent)): file_fingerprint(path)[
                    "sha256"
                ]
                for path in sorted(names)
            },
            "dependencies": {
                "projectHash": content_hash(self.workspace.project),
                "analysis": self.analysis_port.dependency_bindings()
                if hasattr(self.analysis_port, "dependency_bindings")
                else None,
            },
        }

    def _bind(self, **references):
        if self.workspace.pipeline_run_path.exists():
            self.run_store.bind_cutting_context(references)

    def _analysis(self, source, segment, sync_ref):
        source_ref = {
            "locator": source["locator"],
            "sha256": source["fingerprint"]["sha256"],
        }
        source_range = segment_range(segment)
        routing = source.get("streamMetadata", {}).get("audioSelection")
        if self.analysis_port is None or not routing:
            return {
                "sourceRef": source_ref,
                "status": "blocked",
                "uncertainty": ["routed analysis unavailable"],
                "coverage": {"observed": False},
                "pauseCandidates": [],
            }
        result = self.analysis_port.analyze(
            Path(source["locator"]),
            selection=routing,
            source_range=source_range,
            fingerprint=source["fingerprint"],
            sync_ref=sync_ref,
            output_dir=self.store.directory / "analysis-media",
            language=self.policy.effective.get("language"),
        )
        if result.get("sourceRef") != source_ref or result.get("syncRef") != sync_ref:
            raise CuttingServiceError(
                "analysis does not bind the exact original and Sync"
            )
        if (
            result.get("routing") != routing
            or result.get("preprocessing", {}).get("sourceRange") != source_range
        ):
            raise CuttingServiceError(
                "analysis selection or source-clock coverage differs"
            )
        return self._contextual_analysis(source, result, sync_ref)

    def _contextual_analysis(self, source, analysis, sync_ref):
        if self.context_port is None:
            return analysis
        result = deepcopy(analysis)
        for candidate in result.get("pauseCandidates", []):
            observation = self.context_port.analyze_pause(
                source, candidate, analysis, sync_ref=sync_ref
            )
            expected = {
                "sourceRef": analysis["sourceRef"],
                "syncRef": sync_ref,
                "routing": analysis["routing"],
                "pauseHash": content_hash(candidate),
            }
            bound = all(
                observation.get(key) == value for key, value in expected.items()
            )
            if (
                bound
                and observation.get("modelIdentity")
                and observation.get("promptHash")
            ):
                candidate["evidence"]["context"] = observation.get("context") or {}
                candidate["evidence"]["contextObservation"] = observation
        return result

    def analyze(self, request=None):
        request = request or {}
        if not self.policy.enabled:
            return {
                "status": "disabled",
                "mutated": False,
                "policy": self.policy.payload(),
            }
        request = _validated_request(request)
        revision = self._current()
        snapshot = revision["snapshot"]
        sync_ref = self._sync_ref()
        policy_ref = self.store.save_document(
            make_document("policy", self.policy.payload())
        )
        scope = request.get("scope") or {}
        occurrences, edits, unobserved, analysis_refs, analyses = self._analyze_units(
            snapshot, scope, sync_ref, request
        )
        protected_policy = replace(
            self.policy,
            protections=self.policy.protections + self._canonical_protections(snapshot),
        )
        retakes, retake_edits = propose_retakes(
            snapshot,
            analyses,
            analysis_refs=analysis_refs,
            evidence_port=self.retake_port,
            policy=protected_policy,
        )
        occurrences.extend(retakes)
        edits.extend(retake_edits)
        content, content_occurrences, content_edits = editorial_proposal(
            snapshot, request, protected_policy.protections
        )
        occurrences.extend(content_occurrences)
        edits.extend(content_edits)
        consolidate_removals(
            snapshot,
            [edit for edit in edits if not edit.get("editorialApprovalRequired")],
        )
        joins = audit_joins(
            snapshot, frame_rate=request.get("frameRate") or {"num": 30, "den": 1}
        )
        source_refs = [
            {"locator": source["locator"], "sha256": source["fingerprint"]["sha256"]}
            for source in snapshot["sources"]
        ]
        payload = {
            "baseCMapHash": revision["contentHash"],
            "frameRate": request.get("frameRate") or {"num": 30, "den": 1},
            "baseCMapRevisionId": revision["revisionId"],
            "syncRef": sync_ref,
            "policyRef": policy_ref,
            "sourceRefs": source_refs,
            "occurrences": occurrences,
            "contentReduction": _content_reports(request, content),
            "edits": edits,
            "requiredWindows": joins,
            "scope": scope,
            "implementationBindings": {
                **self._implementation_binding(),
                "sourceAnalysisRefs": list(analysis_refs.values()),
            },
            "status": _proposal_status(occurrences, unobserved, joins),
        }
        proposal_ref = self.store.save_document(make_document("proposal", payload))
        self._bind(proposal=proposal_ref)
        return {
            "status": payload["status"],
            "proposalRef": proposal_ref,
            "mutated": False,
            "coverage": {
                "unobservedSources": sorted(set(unobserved)),
                "joinCount": len(joins),
                "scope": scope,
            },
            "policy": self.policy.payload(),
        }

    def _analyze_units(self, snapshot, scope, sync_ref, request):
        sources = {source["sourceId"]: source for source in snapshot["sources"]}
        occurrences, edits, unobserved = [], [], []
        analysis_refs = {}
        analyses = {}
        segment_ids = self._scope_ids(snapshot, scope)
        protected_policy = replace(
            self.policy,
            protections=self.policy.protections + self._canonical_protections(snapshot),
        )
        for segment in snapshot["segments"]:
            if segment_ids is not None and segment["segmentId"] not in segment_ids:
                continue
            source = sources[segment["sourceId"]]
            analysis = self._analysis(source, segment, sync_ref)
            analysis_ref = self.store.save_document(
                make_document("source-analysis", analysis)
            )
            analysis_refs[segment["segmentId"]] = analysis_ref
            analyses[segment["segmentId"]] = analysis
            if analysis["status"] != "pass":
                unobserved.append(source["sourceId"])
            found, changes = self._pause_occurrences(
                analysis, analysis_ref, source, segment, request, protected_policy
            )
            occurrences.extend(found)
            edits.extend(changes)
        return occurrences, edits, unobserved, analysis_refs, analyses

    @staticmethod
    def _scope_ids(snapshot, scope):
        if set(scope) - {"segmentIds"}:
            raise CuttingServiceError("scope requires explicit canonical segmentIds")
        identities = scope.get("segmentIds")
        if identities is not None:
            known = {segment["segmentId"] for segment in snapshot["segments"]}
            if not isinstance(identities, list) or set(identities) - known:
                raise CuttingServiceError("scope contains unknown canonical segmentIds")
        return identities

    def _pause_occurrences(
        self, analysis, analysis_ref, source, segment, request, protected_policy
    ):
        occurrences, edits = [], []
        for candidate in analysis.get("pauseCandidates", []):
            gap = candidate["sourceRange"]
            if not _contained(gap, segment_range(segment)):
                raise CuttingServiceError(
                    "analysis candidate is outside the selected source unit"
                )
            proposed = propose_pause(
                gap,
                resolve_section_policy(
                    protected_policy,
                    request.get("segmentSectionIds", {}).get(segment["segmentId"]),
                ),
                candidate["evidence"],
                frame_rate=request.get("frameRate"),
            )
            identity = occurrence_id(
                source["fingerprint"]["sha256"],
                source["sourceId"],
                {
                    "unit": re.sub(r"(?:-cut-\d+)+$", "", segment["segmentId"]),
                    "words": candidate["evidence"].get("adjacentWords", {}),
                    "originalRange": gap,
                },
            )
            removed = proposed.pop("removeRange", None)
            if (
                analysis["status"] != "pass"
                or analysis.get("coverage", {}).get("observed") is not True
            ):
                proposed["disposition"] = "needs-review"
                proposed["reasons"].append(
                    "complete observed acoustic coverage is unavailable"
                )
                removed = None
            proposed.pop("retainedMs", None)
            occurrences.append(
                {
                    **proposed,
                    "occurrenceId": identity,
                    "evidenceRefs": [analysis_ref],
                    "anchor": {
                        "unit": re.sub(r"(?:-cut-\d+)+$", "", segment["segmentId"]),
                        "words": candidate["evidence"].get("adjacentWords", {}),
                    },
                }
            )
            if removed:
                edits.append(
                    {
                        "occurrenceId": identity,
                        "segmentId": segment["segmentId"],
                        "removeRange": removed,
                    }
                )
        return occurrences, edits

    def _canonical_protections(self, snapshot):
        protected = deepcopy(snapshot.get("protectedEvents", []))
        if snapshot.get("protectionRef"):
            policy = self.store.load_document(snapshot["protectionRef"])
            if policy["documentType"] != "policy":
                raise CuttingServiceError("protectionRef must bind a cutting policy")
            protected.extend(policy["payload"]["protectedEvents"])
        sources = {
            Path(source["locator"]).name: source["sourceId"]
            for source in snapshot["sources"]
        }
        for ordinal, hold in enumerate(snapshot.get("protectedQuizWindows", [])):
            source_id = sources.get(Path(hold["sourceBasename"]).name)
            if source_id is None:
                raise CuttingServiceError("protected quiz source is missing")
            protected.append(
                {
                    "eventId": f"canonical-quiz-{ordinal}",
                    "sourceRange": {
                        "sourceId": source_id,
                        "startTicks": floor(Fraction(str(hold["start"])) * 1000000),
                        "endTicksExclusive": ceil(Fraction(str(hold["end"])) * 1000000),
                        "timebase": {"num": 1, "den": 1000000},
                    },
                }
            )
        return tuple(protected)

    def preview(self, proposal_ref):
        ref, proposal = self._proposal(proposal_ref)
        selected_edits = self._selected_edits(
            proposal, self._decisions(ref), include_undecided=True
        )
        candidate = consolidate_removals(self._current()["snapshot"], selected_edits)
        required = self._required_coverage(candidate, selected_edits)
        cached = self._cached_preview(ref, selection_graph_hash(candidate), required)
        if cached is not None:
            return {"status": "pass", "verificationRef": cached, "cached": True}
        if self.preview_port is None:
            return {
                "status": "blocked",
                "reason": "native preview and actual verification unavailable",
                "proposalRef": ref,
            }
        preview_proposal = {**proposal, "edits": selected_edits}
        reservations = self._reserve_preview_repairs(ref, preview_proposal, candidate)
        if reservations is None:
            return {
                "status": "needs-human",
                "reason": "two automatic selection attempts consumed",
                "proposalRef": ref,
            }
        result = self.preview_port.render(
            candidate, proposal_ref=ref, proposal=preview_proposal
        )
        if self.verification_port is None:
            return {
                **result,
                "status": "blocked",
                "reason": "render success does not verify retained speech",
            }
        verified = self.verification_port.verify(
            result["candidate"],
            proposal_ref=ref,
            **result.get("verificationRequest", {}),
        )
        if verified.get("status") == "pass":
            self._require_coverage(verified, required)
        if verified.get("proposalRef") != ref or verified.get(
            "graphHash"
        ) != selection_graph_hash(candidate):
            raise CuttingServiceError(
                "verification does not bind the exact proposed candidate"
            )
        verification_ref = self.store.save_document(
            make_document("verification", verified)
        )
        for reservation in reservations:
            self.store.record_result(
                reservation,
                status="completed" if verified["status"] == "pass" else "failed",
                result_ref=verification_ref,
                actor="cutting",
                expected_head_hash=self.store.head_hash(),
            )
        self._bind(verification=verification_ref)
        return {
            **result,
            "status": verified["status"],
            "verificationRef": verification_ref,
        }

    def _reserve_preview_repairs(self, proposal_ref, proposal, candidate):
        reservations = []
        identities = sorted({edit["occurrenceId"] for edit in proposal["edits"]})
        bindings = self._repair_bindings(proposal, identities)
        if any(
            len(self.store.reservations(identity, original_binding=bindings[identity]))
            >= 2
            for identity in identities
        ):
            return None
        for identity in identities:
            try:
                reservation = self.store.reserve_repair(
                    occurrence_id=identity,
                    proposal_ref=proposal_ref,
                    selection_hash=content_hash(candidate),
                    actor="cutting",
                    expected_head_hash=self.store.head_hash(),
                    original_binding=bindings[identity],
                )
            except CuttingStoreError as exc:
                if "two automatic" in str(exc):
                    return None
                raise
            reservations.append(reservation)
        return reservations

    def _repair_bindings(self, proposal, identities):
        snapshot = self._current()["snapshot"]
        sources = {
            source["sourceId"]: source["fingerprint"]["sha256"]
            for source in snapshot["sources"]
        }
        occurrences = {
            occurrence["occurrenceId"]: occurrence
            for occurrence in proposal["occurrences"]
        }
        return {
            identity: {
                "sourceSha256": sources[
                    occurrences[identity]["sourceRange"]["sourceId"]
                ],
                "sourceRange": occurrences[identity]["sourceRange"],
                "unitAnchor": occurrences[identity].get("anchor")
                or {"originalUnit": identity},
            }
            for identity in identities
        }

    def _cached_preview(self, proposal_ref, selection_hash, required):
        directory = self.store.directory / "documents/verification"
        for path in sorted(directory.glob("*.json")):
            ref = self.resolve_ref(path)
            payload = self.store.load_document(ref)["payload"]
            if (
                payload["proposalRef"] == proposal_ref
                and payload["status"] == "pass"
                and payload.get("graphHash") == selection_hash
            ):
                try:
                    self._verify_candidate_bytes(payload)
                    self._require_coverage(payload, required)
                except CuttingServiceError:
                    continue
                return ref
        return None

    @staticmethod
    def _required_coverage(candidate, edits):
        return {edit["occurrenceId"] for edit in edits} | {
            join["joinId"] for join in audit_joins(candidate, {"num": 30, "den": 1})
        }

    @staticmethod
    def _require_coverage(verified, required):
        if not required <= set(verified.get("occurrenceCoverage", [])):
            raise CuttingServiceError(
                "verification coverage does not include all current occurrences and joins"
            )
        checks = verified.get("checks", [])
        if required and (
            not checks or any(check.get("status") != "pass" for check in checks)
        ):
            raise CuttingServiceError(
                "required verification checks are missing or failed"
            )

    def decide(self, proposal_ref, request):
        request = _validated_request(request, "decide")
        ref, proposal = self._proposal(proposal_ref)
        preview_ref = request.get("previewRef")
        if not preview_ref:
            raise CuttingServiceError(
                "an exact preview reference is required for a human decision"
            )
        preview_document = self.store.load_document(preview_ref)
        if preview_document["documentType"] != "verification":
            raise CuttingServiceError("expected an actual preview verification")
        preview = preview_document["payload"]
        if preview.get("proposalRef") != ref:
            raise CuttingServiceError("preview belongs to another proposal")
        known = {item["occurrenceId"]: item for item in proposal["occurrences"]}
        previous = self._decisions(ref)
        saved = []
        for decision in request.get("decisions", []):
            identity = decision["occurrenceId"]
            if identity not in known:
                raise CuttingServiceError("decision refers to an unknown occurrence")
            _validate_decision(decision, known[identity], preview, proposal)
            payload = {
                **decision,
                "actor": request.get("actor", "human"),
                "decidedAt": now_iso(),
                "proposalRef": ref,
                "previewRef": preview_ref,
            }
            if identity in previous:
                payload["supersedesRef"] = previous[identity]["decisionRef"]
            saved.append(self.store.save_document(make_document("decision", payload)))
        return {"status": "decided", "decisionRefs": saved, "mutated": False}

    def _decisions(self, proposal_ref):
        records = {}
        directory = self.store.directory / "documents/decision"
        for path in sorted(directory.glob("*.json")):
            ref = self.resolve_ref(path)
            payload = self.store.load_document(ref)["payload"]
            if payload["proposalRef"] != proposal_ref:
                continue
            records[ref["sha256"]] = {**payload, "decisionRef": ref}
        return _decision_leaves(records)

    @staticmethod
    def _selected_edits(proposal, decisions, *, include_undecided=False):
        selected = []
        for edit in proposal["edits"]:
            choice = decisions.get(edit["occurrenceId"])
            if edit.get("editorialApprovalRequired") and (
                choice is None or choice.get("editorialApproval") is not True
            ):
                continue
            if (
                choice is None
                and include_undecided
                or choice is not None
                and choice["disposition"]
                not in {
                    "keep",
                    "needs-review",
                }
            ):
                selected.append(edit)
        return selected

    def apply(self, proposal_ref):
        ref, proposal = self._proposal(proposal_ref)
        decisions = self._decisions(ref)
        unresolved = [
            o["occurrenceId"]
            for o in proposal["occurrences"]
            if o["disposition"] != "keep"
            and (
                o["occurrenceId"] not in decisions
                or decisions[o["occurrenceId"]]["disposition"] == "needs-review"
            )
        ]
        if unresolved:
            return {
                "status": "needs-review",
                "unresolved": unresolved,
                "mutated": False,
            }
        edits = self._selected_edits(proposal, decisions)
        if not edits:
            return {"status": "no-op", "mutated": False}
        snapshot = self._current()["snapshot"]
        self._revalidate_protections(snapshot, edits)
        candidate = consolidate_removals(snapshot, edits)
        self._verify_selected_candidate(edits, decisions, ref, candidate)
        candidate["cuttingRef"] = decisions[edits[0]["occurrenceId"]]["previewRef"]
        revision = CMapService(self.workspace).author(
            candidate,
            actor="cutting",
            reason="apply reviewed cutting proposal",
            expected_head_hash=proposal["baseCMapHash"],
        )
        return {"status": "applied", "revision": revision, "mutated": True}

    def _revalidate_protections(self, snapshot, edits):
        protections = self.policy.protections + self._canonical_protections(snapshot)
        for edit in edits:
            source, first, last = source_interval(edit["removeRange"])
            for event in protections:
                other, start, end = source_interval(event["sourceRange"])
                if source == other and max(first, start) < min(last, end):
                    raise CuttingServiceError(
                        f"removal intersects protected source event: {event['eventId']}"
                    )

    def _verify_selected_candidate(self, edits, decisions, ref, candidate):
        for edit in edits:
            preview = self.store.load_document(
                decisions[edit["occurrenceId"]]["previewRef"]
            )["payload"]
            if (
                preview["status"] != "pass"
                or preview["proposalRef"] != ref
                or preview.get("graphHash") != selection_graph_hash(candidate)
            ):
                raise CuttingServiceError(
                    "current exact preview verification is required"
                )
            self._verify_candidate_bytes(preview)
            self._require_coverage(preview, self._required_coverage(candidate, edits))

    @staticmethod
    def _verify_candidate_bytes(preview):
        references = [
            preview["candidateRef"],
            *preview.get("claims", {}).get("previewFiles", []),
        ]
        for recorded in references:
            path = Path(recorded["locator"])
            if (
                not path.is_file()
                or file_fingerprint(path)["sha256"] != recorded["sha256"]
            ):
                raise CuttingServiceError(
                    "verified candidate bytes changed or disappeared"
                )

    def status(self, proposal_ref=None):
        result = {
            "status": "enabled" if self.policy.enabled else "disabled",
            "policy": self.policy.payload(),
            "calibrationStatus": "unvalidated",
            "mutated": False,
        }
        if proposal_ref is not None:
            ref, proposal = self._proposal(proposal_ref)
            result.update(
                proposalRef=ref, proposal=proposal, decisions=self._decisions(ref)
            )
        return result
