"""Native, original-source previews for a proposed selection, never full proofs."""

from __future__ import annotations

import json
from copy import deepcopy
from fractions import Fraction
from pathlib import Path

from avo.timeline.contracts import content_hash, file_fingerprint
from avo.timeline.cutting_audit import audit_joins
from avo.timeline.cutting_contracts import selection_graph_hash, source_interval
from avo.timeline.cutting_previews import group_preview_windows
from avo.timeline.cutting_store import CuttingStore
from avo.timeline.event_clock import frame_to_sample, sample_rate_boundary
from avo.timeline.initial_cut import initial_cut_proof_request
from avo.timeline.lineage import validate_cmap_snapshot
from avo.timeline.materialize import _proof_render, canonical_proof_media_inputs
from avo.timeline.proof_plan import ProofPlanCompiler
from avo.timeline.store import write_immutable_json


class CuttingWordBoundaryError(ValueError):
    """An observed original word crosses a selected source boundary."""


def _retained_word(word, first, last):
    if not word.get("eligibleEdge"):
        return False
    if word["start"] >= last or word["end"] <= first:
        return False
    if not first <= word["start"] < word["end"] <= last:
        raise CuttingWordBoundaryError(
            "observed original word crosses selected source boundary: "
            + str(word.get("text") or word.get("word"))
        )
    return True


class _ProposedStore:
    def __init__(self, store, snapshot):
        self.store, self.snapshot = store, snapshot

    def load_index(self):
        return self.store.load_index()

    def revision(self, revision_id):
        revision = self.store.revision(revision_id)
        return {**revision, "snapshot": deepcopy(self.snapshot)}


class _ProposedWorkspace:
    """Read-only proposed graph view; the real canonical head remains locked."""

    def __init__(self, workspace, snapshot):
        self.cutting_preview = True
        self.workspace, self.snapshot = workspace, deepcopy(snapshot)
        self.snapshot.pop("cuttingRef", None)
        self.snapshot.pop("protectionRef", None)

    def __getattr__(self, name):
        return getattr(self.workspace, name)

    def store(self, name):
        store = self.workspace.store(name)
        return _ProposedStore(store, self.snapshot) if name == "cmap" else store


def _preview_contract(identity):
    contract = {
        "contractId": f"cutting-preview-{identity}",
        "ledgerHash": content_hash([]),
        "iterationId": f"cutting-preview-{identity}",
        "obligations": [],
        "historicalRiskWindows": [],
        "conflicts": [],
    }
    return {**contract, "contractHash": content_hash(contract)}


def _join_covers_removal(join, interval):
    source, start, end = source_interval(interval)
    left_source, _, before = source_interval(join["leftSourceRange"])
    right_source, after, _ = source_interval(join["rightSourceRange"])
    if left_source == right_source == source:
        return before < end and after > start
    return (left_source == source and start <= before <= end) or (
        right_source == source and start <= after <= end
    )


def _assign_edit_windows(windows, joins, edits):
    for edit in edits:
        for window, join in zip(windows, joins, strict=True):
            if _join_covers_removal(join, edit["removeRange"]):
                window["occurrenceIds"].append(edit["occurrenceId"])


def _operation_source_interval(operation):
    parameters = operation["parameters"]
    source = parameters["sourceRange"]
    return source_interval(
        {
            "sourceId": parameters["sourceId"],
            "startTicks": source["startTicks"],
            "endTicksExclusive": source["endTicks"],
            "timebase": source["timebase"],
        }
    )


def _alternative_program_edges(request, alternative):
    source, first, last = source_interval(alternative["sourceRange"])
    edges = {}
    fps = Fraction(
        request["output"]["frameRate"]["num"], request["output"]["frameRate"]["den"]
    )
    for operation in request["videoGraph"]["operations"]:
        if operation["kind"] != "trim":
            continue
        other, start, end = _operation_source_interval(operation)
        if other != source:
            continue
        _map_alternative_edge(
            edges, "startFrame", first, start, end, operation["outputRange"], fps
        )
        _map_alternative_edge(
            edges, "endFrameExclusive", last, start, end, operation["outputRange"], fps
        )
    if set(edges) != {"startFrame", "endFrameExclusive"}:
        raise ValueError(
            "complete selected retake cannot be mapped to the retained original selection"
        )
    return edges


def _map_alternative_edge(edges, key, point, start, end, output, fps):
    contains = start <= point < end if key == "startFrame" else start < point <= end
    if not contains:
        return
    if point == end:
        edges[key] = output["endFrameExclusive"]
        return
    offset = (point - start) * fps
    edges[key] = output["startFrame"] + (2 * offset.numerator + offset.denominator) // (
        2 * offset.denominator
    )


def _complete_take_windows(request, occurrences, edits):
    selected = {edit["occurrenceId"] for edit in edits}
    windows = []
    for occurrence in occurrences:
        if occurrence["occurrenceId"] not in selected or not occurrence.get(
            "selectedAlternativeId"
        ):
            continue
        alternatives = {
            take.get("takeId") or take.get("unitId"): take
            for take in occurrence.get("alternatives", [])
        }
        alternative = alternatives.get(occurrence["selectedAlternativeId"])
        if alternative is None:
            raise ValueError("selected retake alternative is missing")
        windows.append(
            {
                **_alternative_program_edges(request, alternative),
                "occurrenceIds": [occurrence["occurrenceId"]],
            }
        )
    return windows


def _alternative_review_refs(snapshot, proposal):
    sources = {source["sourceId"]: source for source in snapshot["sources"]}
    records = []
    for occurrence in proposal["occurrences"]:
        for alternative in occurrence.get("alternatives", []):
            source = sources[alternative["sourceRange"]["sourceId"]]
            records.append(
                {
                    "occurrenceId": occurrence["occurrenceId"],
                    "alternativeId": alternative.get("takeId")
                    or alternative.get("unitId"),
                    "sourceRef": {
                        "locator": source["locator"],
                        "sha256": source["fingerprint"]["sha256"],
                    },
                    "sourceRange": deepcopy(alternative["sourceRange"]),
                    "evidenceRefs": deepcopy(occurrence.get("evidenceRefs", [])),
                    "claimScope": "original-source-reference; not encoded candidate coverage",
                }
            )
    return records


def _group_windows(request, joins, occurrences, edits=()):
    fps = Fraction(
        request["output"]["frameRate"]["num"], request["output"]["frameRate"]["den"]
    )
    total = max(
        operation["outputRange"]["endFrameExclusive"]
        for operation in request["videoGraph"]["operations"]
    )
    radius = max(1, int(8 * fps))
    windows = [
        {
            "startFrame": max(0, join["programFrame"] - radius),
            "endFrameExclusive": min(total, join["programFrame"] + radius),
            "occurrenceIds": [join["joinId"]],
        }
        for join in joins
    ]
    _assign_edit_windows(windows, joins, edits)
    for occurrence in occurrences:
        interval = occurrence.get("sourceRange")
        if interval is None:
            continue
        for index, join in enumerate(joins):
            left, right = join["leftSourceRange"], join["rightSourceRange"]
            if left["sourceId"] == right["sourceId"] == interval["sourceId"]:
                base = interval["timebase"]
                middle = Fraction(
                    (interval["startTicks"] + interval["endTicksExclusive"])
                    * base["num"],
                    2 * base["den"],
                )
                before = Fraction(
                    left["endTicksExclusive"] * left["timebase"]["num"],
                    left["timebase"]["den"],
                )
                after = Fraction(
                    right["startTicks"] * right["timebase"]["num"],
                    right["timebase"]["den"],
                )
                if before <= middle <= after:
                    windows[index]["occurrenceIds"].append(occurrence["occurrenceId"])
    windows.extend(_complete_take_windows(request, occurrences, edits))
    windows.extend(
        {**window, "occurrenceIds": []}
        for window in request["validationPlan"]["microproof"]
    )
    if not windows:
        windows = [
            {
                "startFrame": 0,
                "endFrameExclusive": min(total, int(16 * fps)),
                "occurrenceIds": [],
            }
        ]
    return group_preview_windows(windows, request["output"]["frameRate"])


class CuttingPreviewAdapter:
    def __init__(self, workspace, *, render_port=None, verifier=None):
        from avo.adapters.media.timeline_render import TimelineRenderAdapter
        from avo.adapters.qc.cutting_boundary import CuttingBoundaryVerifier

        self.workspace = workspace
        self.render_port = render_port or TimelineRenderAdapter()
        self.directory = Path(workspace.timeline_dir) / "cutting" / "previews"
        self.verifier = verifier or CuttingBoundaryVerifier(
            self.directory / "verification"
        )

    def _require_basis(self, snapshot, proposal):
        validate_cmap_snapshot(snapshot)
        index = self.workspace.require_active("cmap")
        revision = self.workspace.store("cmap").revision(index["headRevisionId"])
        if revision["contentHash"] != proposal["baseCMapHash"]:
            raise ValueError("cutting preview CMap basis is stale")
        edit = (self.workspace.raw_dir / "edit").resolve()
        for source in snapshot["sources"]:
            path = Path(source["locator"]).resolve()
            if path == edit or edit in path.parents:
                raise ValueError("cutting preview cannot use derived media")
            if file_fingerprint(path)["sha256"] != source["fingerprint"]["sha256"]:
                raise ValueError("cutting preview original fingerprint changed")

    def render(self, snapshot, *, proposal_ref, proposal):
        self._require_basis(snapshot, proposal)
        selection_hash = selection_graph_hash(snapshot)
        identity = content_hash(
            {"selection": selection_hash, "proposal": proposal_ref}
        )[:16]
        directory = self.directory / identity
        directory.mkdir(parents=True, exist_ok=True)
        view = _ProposedWorkspace(self.workspace, snapshot)
        request = initial_cut_proof_request(
            view,
            iteration_id=f"cutting-preview-{identity}",
            output=directory / "preview.mp4",
            frame_rate=proposal.get("frameRate") or {"num": 30, "den": 1},
        )
        joins = audit_joins(snapshot, request["output"]["frameRate"])
        windows = _group_windows(
            request, joins, proposal["occurrences"], proposal["edits"]
        )
        request["previewOnly"] = True
        request["validationPlan"]["microproof"] = [
            {key: window[key] for key in ("startFrame", "endFrameExclusive")}
            for window in windows
        ]
        request["validationPlan"]["cutting"] = {
            "required": True,
            "proposalRef": proposal_ref,
            "graphHash": selection_hash,
            "joinIds": [join["joinId"] for join in joins],
        }
        compiler = ProofPlanCompiler(self.workspace)
        plan = compiler.compile(
            request, regression_contract=_preview_contract(identity)
        )
        compiler.require_preflight(
            plan,
            media_inputs=canonical_proof_media_inputs(self.workspace, plan),
            tool_readiness=self.render_port.proof_tool_readiness(plan),
        )
        previews = []
        for ordinal, window in enumerate(windows, 1):
            frame_range = {
                key: window[key] for key in ("startFrame", "endFrameExclusive")
            }
            rendered = _proof_render(
                self.render_port,
                plan,
                directory / f"preview-{ordinal:03d}.mp4",
                window=frame_range,
            )
            previews.append(
                {
                    "output": rendered["output"],
                    "window": window,
                    "graphHash": rendered["graphHash"],
                    "clockMaps": self._clock_maps(plan, snapshot, frame_range),
                }
            )
        manifest = {
            "schemaVersion": "1.0.0",
            "mediaClass": "preview-package",
            "previewOnly": True,
            "proposalRef": proposal_ref,
            "selectionHash": selection_hash,
            "proofPlanRef": file_fingerprint(compiler.path(plan["proofPlanId"])),
            "snapshot": deepcopy(snapshot),
            "proposal": deepcopy(proposal),
            "alternativeReviewRefs": _alternative_review_refs(snapshot, proposal),
            "plan": plan,
            "previews": previews,
        }
        path = directory / "manifest.json"
        write_immutable_json(path, manifest)
        candidate = {"manifestRef": file_fingerprint(path), "previews": previews}
        return {
            "status": "rendered",
            "candidate": candidate,
            "previews": previews,
            "previewOnly": True,
            "verificationRequest": {"manifest_path": path},
        }

    @staticmethod
    def _clock_maps(plan, snapshot, window):
        fps = plan["output"]["frameRate"]
        rate = plan["audioGraph"]["sampleRate"]
        first = frame_to_sample(
            window["startFrame"],
            frame_rate_num=fps["num"],
            frame_rate_den=fps["den"],
            sample_rate=rate,
        )
        last = frame_to_sample(
            window["endFrameExclusive"],
            frame_rate_num=fps["num"],
            frame_rate_den=fps["den"],
            sample_rate=rate,
        )
        sources = {source["sourceId"]: source for source in snapshot["sources"]}
        trims = {
            operation["parameters"]["nodeId"]: operation
            for operation in plan["audioGraph"]["operations"]
            if operation["kind"] == "trim"
        }
        maps = []
        for node in plan["audioGraph"]["nodes"]:
            if node["nodeId"] not in trims:
                continue
            start = max(first, node["outputRange"]["startSample"])
            end = min(last, node["outputRange"]["endSampleExclusive"])
            if start >= end:
                continue
            operation = trims[node["nodeId"]]
            parameters = operation["parameters"]
            native = node["sourceSampleRate"]
            source_start = node["sourceRange"]["startSample"] + sample_rate_boundary(
                start - node["outputRange"]["startSample"],
                source_rate=rate,
                target_rate=native,
            )
            source_end = min(
                node["sourceRange"]["endSampleExclusive"],
                source_start
                + sample_rate_boundary(
                    end - start, source_rate=rate, target_rate=native
                ),
            )
            source_id = parameters["sourceId"]
            source = sources[source_id]
            maps.append(
                {
                    "sourceId": source_id,
                    "sourceRange": {
                        "sourceId": source_id,
                        "startTicks": source_start,
                        "endTicksExclusive": source_end,
                        "timebase": {"num": 1, "den": native},
                    },
                    "localStartSeconds": (start - first) / rate,
                    "localEndSeconds": (end - first) / rate,
                    "programStartSample": start,
                    "programEndSampleExclusive": end,
                    "source": source["locator"],
                    "selection": source["streamMetadata"]["audioSelection"],
                    "fingerprint": source["fingerprint"],
                    "parameters": parameters,
                    "node": deepcopy(node),
                    "fullNodeSourceRange": {
                        "sourceId": source_id,
                        "startTicks": node["sourceRange"]["startSample"],
                        "endTicksExclusive": node["sourceRange"]["endSampleExclusive"],
                        "timebase": {"num": 1, "den": native},
                    },
                    "windowOffsetSamples": start - node["outputRange"]["startSample"],
                    "windowLengthSamples": end - start,
                    "fadeInSeconds": parameters.get("fadeInSamples", 0) / rate
                    if start == node["outputRange"]["startSample"]
                    else 0,
                    "fadeOutSeconds": parameters.get("fadeOutSamples", 0) / rate
                    if end == node["outputRange"]["endSampleExclusive"]
                    else 0,
                }
            )
        return maps

    def _analysis_documents(self, proposal):
        store = CuttingStore(
            Path(self.workspace.timeline_dir) / "cutting",
            video_id=self.workspace.video_id,
            provider=self.workspace.project["provider"],
        )
        analyses = []
        refs = list(
            proposal.get("implementationBindings", {}).get("sourceAnalysisRefs", [])
        )
        refs.extend(
            ref
            for occurrence in proposal["occurrences"]
            for ref in occurrence.get("evidenceRefs", [])
        )
        for ref in {content_hash(ref): ref for ref in refs}.values():
            document = store.load_document(ref)
            if (
                document["documentType"] == "source-analysis"
                and document["payload"].get("syncRef") == proposal["syncRef"]
            ):
                analyses.append(document["payload"])
        return analyses

    @staticmethod
    def _mapped_words(mapping, analyses):
        interval = mapping["sourceRange"]
        base = interval["timebase"]
        first = interval["startTicks"] * base["num"] / base["den"]
        last = interval["endTicksExclusive"] * base["num"] / base["den"]
        node_range = mapping.get("fullNodeSourceRange", interval)
        _, node_first, node_last = source_interval(node_range)
        words = []
        for analysis in analyses:
            if (
                analysis["sourceRef"]["sha256"] != mapping["fingerprint"]["sha256"]
                or analysis.get("routing") != mapping["selection"]
            ):
                continue
            for word in analysis.get("words", []):
                if (
                    _retained_word(word, node_first, node_last)
                    and first <= word["start"] < word["end"] <= last
                ):
                    offset = mapping["localStartSeconds"] - first
                    words.append(
                        {
                            "text": word.get("text") or word.get("word"),
                            "start": offset + word["start"],
                            "end": offset + word["end"],
                            "observed": True,
                        }
                    )
        return words

    def _observed_words(self, maps, proposal):
        analyses = self._analysis_documents(proposal)
        words = [
            word for mapping in maps for word in self._mapped_words(mapping, analyses)
        ]
        return sorted(
            {
                (word["text"], word["start"], word["end"]): word for word in words
            }.values(),
            key=lambda word: word["start"],
        )

    def verify(self, candidate, *, proposal_ref, manifest_path):
        manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
        if (
            file_fingerprint(Path(manifest_path)) != candidate["manifestRef"]
            or manifest["proposalRef"] != proposal_ref
        ):
            raise ValueError("cutting preview package is stale")
        reports = []
        for preview in manifest["previews"]:
            if (
                file_fingerprint(Path(preview["output"]["locator"]))
                != preview["output"]
            ):
                raise ValueError("cutting preview bytes changed")
            maps = preview["clockMaps"]
            windows = self._verification_windows(preview, maps, manifest)
            reports.append(
                self.verifier.verify(
                    Path(preview["output"]["locator"]),
                    proposal_ref=proposal_ref,
                    proof_plan_ref=manifest["proofPlanRef"],
                    graph_hash=manifest["selectionHash"],
                    required_occurrences=preview["window"]["occurrenceIds"],
                    clock_maps=maps,
                    candidate_selection={
                        "streamIndex": 1,
                        "channels": [0],
                        "sourceLayout": "stereo",
                        "outputLayout": "dual-mono",
                    },
                    windows=windows,
                )
            )
        return self._package_report(candidate, proposal_ref, manifest, reports)

    @staticmethod
    def _reports_status(reports):
        statuses = [report["status"] for report in reports]
        if statuses and all(status == "pass" for status in statuses):
            return "pass"
        return "blocked" if "blocked" in statuses else "fail"

    @classmethod
    def _package_report(cls, candidate, proposal_ref, manifest, reports):
        return {
            "proposalRef": proposal_ref,
            "proofPlanRef": manifest["proofPlanRef"],
            "graphHash": manifest["selectionHash"],
            "candidateRef": candidate["manifestRef"],
            "clockMaps": [
                mapping
                for preview in manifest["previews"]
                for mapping in preview["clockMaps"]
            ],
            "occurrenceCoverage": sorted(
                {
                    identity
                    for report in reports
                    for identity in report.get("occurrenceCoverage", [])
                }
            ),
            "checks": [
                check for report in reports for check in report.get("checks", [])
            ],
            "status": cls._reports_status(reports),
            "claims": {
                "candidateKind": "preview-package",
                "fullProgramReviewed": False,
                "previewFiles": [preview["output"] for preview in manifest["previews"]],
                "alternativeReviewRefs": manifest.get("alternativeReviewRefs", []),
            },
        }

    def _verification_windows(self, preview, maps, manifest):
        expected = []
        fades = []
        for mapping in maps:
            item = {
                key: mapping[key]
                for key in (
                    "source",
                    "selection",
                    "fingerprint",
                    "fadeInSeconds",
                    "fadeOutSeconds",
                )
            }
            item.update(
                source_range=mapping["sourceRange"],
                sync_ref=manifest["proposal"]["syncRef"],
            )
            item["source_range"] = mapping["fullNodeSourceRange"]
            item["processing"] = {
                "recipe": "native-dialogue-v1",
                "node": mapping["node"],
                "dialogueNoiseReductionPolicy": mapping["parameters"].get(
                    "dialogueNoiseReductionPolicy"
                ),
                "fadeSamples": [
                    mapping["parameters"].get("fadeInSamples", 0),
                    mapping["parameters"].get("fadeOutSamples", 0),
                ],
                "windowOffsetSamples": mapping["windowOffsetSamples"],
                "windowLengthSamples": mapping["windowLengthSamples"],
            }
            expected.append(item)
            if mapping["fadeInSeconds"]:
                fades.append(
                    {
                        "start": mapping["localStartSeconds"],
                        "end": mapping["localStartSeconds"] + mapping["fadeInSeconds"],
                    }
                )
            if mapping["fadeOutSeconds"]:
                fades.append(
                    {
                        "start": mapping["localEndSeconds"] - mapping["fadeOutSeconds"],
                        "end": mapping["localEndSeconds"],
                    }
                )
        duration = maps[-1]["localEndSeconds"] if maps else 0
        try:
            words = self._observed_words(maps, manifest["proposal"])
        except CuttingWordBoundaryError:
            # Missing word-edge basis blocks physical QC. Never certify a cut recipe
            # that omitted an original word crossing its own selection boundary.
            words = []
        return [
            {
                "occurrenceId": identity,
                "localStartSeconds": 0,
                "localEndSeconds": duration,
                "expectedAudio": expected,
                "retainedWordEdges": words,
                "fadeRanges": fades,
            }
            for identity in preview["window"]["occurrenceIds"]
        ]

    def proof_tool_readiness(self, plan):
        return self.render_port.proof_tool_readiness(plan)

    def render_proof_plan(self, plan, output, *, window=None):
        return self.render_port.render_proof_plan(plan, output, window=window)

    def verify_cutting_window(self, plan, candidate, *, window):
        """Decode each current native window; approved previews are evidence only."""
        binding = plan["validationPlan"]["cutting"]
        store = self.workspace.store("cmap")
        snapshot = store.revision(store.load_index()["headRevisionId"])["snapshot"]
        if selection_graph_hash(snapshot) != binding["graphHash"]:
            raise ValueError("cutting selection changed before microproof verification")
        cutting = CuttingStore(
            Path(self.workspace.timeline_dir) / "cutting",
            video_id=self.workspace.video_id,
            provider=self.workspace.project["provider"],
        )
        proposal = cutting.load_document(binding["proposalRef"])["payload"]
        joins = audit_joins(snapshot, frame_rate=plan["output"]["frameRate"])
        identities = [
            join["joinId"]
            for join in joins
            if window["startFrame"]
            <= join["programFrame"]
            < window["endFrameExclusive"]
        ]
        maps = self._clock_maps(plan, snapshot, window)
        proof_ref = file_fingerprint(
            ProofPlanCompiler(self.workspace).path(plan["proofPlanId"])
        )
        preview = {
            "window": {
                **window,
                "occurrenceIds": identities
                or [f"window-{window['startFrame']}-{window['endFrameExclusive']}"],
            }
        }
        manifest = {"snapshot": snapshot, "proposal": proposal}
        report = self.verifier.verify(
            Path(candidate),
            proposal_ref=binding["proposalRef"],
            proof_plan_ref=proof_ref,
            graph_hash=binding["graphHash"],
            required_occurrences=preview["window"]["occurrenceIds"],
            clock_maps=maps,
            candidate_selection={
                "streamIndex": 1,
                "channels": [0],
                "sourceLayout": "stereo",
                "outputLayout": "dual-mono",
            },
            windows=self._verification_windows(preview, maps, manifest),
        )
        return {
            "status": report["status"],
            "candidateSha256": file_fingerprint(Path(candidate))["sha256"],
            "proofPlanHash": plan["proofPlanHash"],
            "graphHash": binding["graphHash"],
            "verifiedJoinIds": identities if report["status"] == "pass" else [],
            "checks": report.get("checks", []),
        }
