"""Read selected source facts; recovery text never becomes cut approval."""

from copy import deepcopy

from .contracts import content_hash, validate_document
from .cutting_contracts import source_interval
from .motion_metadata import METADATA_LIMITS, _check_budget
from .preparation import _seconds, _source_range, _uncovered, _union
from .preparation_facts import merge_selected_measurements


def _intersection(interval, bounds):
    _, first, end = source_interval(interval)
    first, end = max(first, bounds[0]), min(end, bounds[1])
    return (first, end) if first < end else None


def _word_interval(word):
    try:
        start, end = _seconds(word["start"]), _seconds(word["end"])
        return (start, end) if start <= end else None
    except (ValueError, TypeError, KeyError):
        return None


def _inside_selection(word, bounds):
    interval = _word_interval(word)
    if interval is None:
        raise ValueError("Unlocated words require source evidence review")
    inside = bounds[0] <= interval[0] <= interval[1] <= bounds[1]
    overlaps = max(interval[0], bounds[0]) < min(interval[1], bounds[1])
    if overlaps and not inside:
        raise ValueError("Selected evidence crosses a word boundary")
    return inside


def _selected_words(base, incoming, bounds):
    retained = [deepcopy(word) for word in base if not _inside_selection(word, bounds)]
    selected = [deepcopy(word) for word in incoming if _inside_selection(word, bounds)]
    return sorted(
        retained + selected,
        key=lambda word: (_seconds(word["start"]), _seconds(word["end"])),
    )


class _Selection:
    def __init__(self, service, source, interval, routing, sync_ref):
        self.service, self.source = service, source
        self.interval, self.routing, self.sync_ref = interval, routing, sync_ref
        self.bounds = source_interval(interval)[1:]
        self.requests, self.choices, self.results = [], [], []
        self.protected, self.resolved, self.issues = [], [], []
        self.analysis, self.original_ref = None, None
        self.stale = False

    def collect(self):
        snapshot = self.service.store._snapshot()
        _check_budget(snapshot, METADATA_LIMITS)
        for reference in snapshot.get("preparationRequests", []):
            frozen = self.service.store.load_document(reference)["payload"]
            original = frozen["binding"]["sourceRange"]
            if original["sourceId"] != self.interval["sourceId"]:
                continue
            ranges = [
                value
                for row in frozen["input"]["ranges"]
                if (value := _intersection(row, self.bounds)) is not None
            ]
            if ranges:
                self.requests.append((reference, frozen, ranges))
        request_keys = {content_hash(reference) for reference, _, _ in self.requests}
        self.choices = [
            (reference, value)
            for reference, value in self.service.store.active_recovery_decisions()
            if content_hash(value["input"]["requestRef"]) in request_keys
            and _intersection(value["sourceRange"], self.bounds)
        ]

    def _binding_matches(self, frozen):
        binding = frozen["binding"]
        return (
            binding["sourceRef"]
            == {
                "locator": self.source["locator"],
                "sha256": self.source["fingerprint"]["sha256"],
            }
            and binding["routingHash"] == content_hash(self.routing)
            and binding["syncRef"] == self.sync_ref
            and source_interval(binding["sourceRange"])
            == source_interval(self.interval)
        )

    def _frozen(self, reference):
        return next(frozen for ref, frozen, _ in self.requests if ref == reference)

    def original(self):
        priority = [
            self._frozen(value["input"]["requestRef"])
            for _, value in reversed(self.choices)
        ]
        priority.extend(frozen for _, frozen, _ in self.requests)
        for frozen in priority:
            if not self._binding_matches(frozen):
                continue
            self.original_ref = frozen["input"]["analysisRef"]
            self.analysis = deepcopy(self.service._analysis(self.original_ref))
            return
        if self.requests:
            self.stale = True
            self.protected.append(self.bounds)
            self.issues.append("Source/routing/Sync or source-analysis unit changed")

    def _result(self, request, frozen):
        if request["resultRef"] is None:
            return None
        result = self.service.store.load_document(request["resultRef"])
        if result["documentType"] != "speech-recovery-result":
            raise ValueError("Selected source result has the wrong document type")
        payload = result["payload"]
        if (
            payload["requestRef"] != request["requestRef"]
            or payload["intervalIndex"] != request["intervalIndex"]
            or not self.service._still_current(frozen, frozen["input"])
        ):
            raise ValueError("Selected recovered evidence is stale")
        if payload["status"] != "pending-review" or payload["recovered"] is None:
            raise ValueError("Selected recovered evidence is unavailable")
        self.results.append(request["resultRef"])
        return payload

    def apply(self, value):
        request = value["input"]
        bounds = _intersection(value["sourceRange"], self.bounds)
        frozen = self._frozen(request["requestRef"])
        if request["choice"] == "defer":
            return
        if not self._binding_matches(frozen):
            raise ValueError("Selected source choice has stale source bindings")
        chosen = self.service._analysis(frozen["input"]["analysisRef"])
        eligible = self.service._word_eligibility(chosen)
        if request["choice"] == "recovered":
            result = self._result(request, frozen)
            if result is None:
                raise ValueError("Selected recovered evidence has no retained result")
            chosen = result["recovered"]["analysis"]
            eligible = result["wordAnchorsEligible"]
        analysis = deepcopy(self.analysis)
        if request["choice"] != "reject":
            analysis["words"] = _selected_words(
                analysis.get("words", []), chosen.get("words", []), bounds
            )
        if request["choice"] == "recovered":
            eligible = self._apply_recovered(analysis, chosen, bounds) and eligible
        self.resolved.append(bounds)
        if not eligible:
            self.protected.append(bounds)
        self.analysis = analysis

    @staticmethod
    def _apply_recovered(analysis, chosen, bounds):
        measured = merge_selected_measurements(analysis, chosen, bounds)
        analysis.setdefault("tools", []).extend(deepcopy(chosen.get("tools", [])))
        alignment = analysis.setdefault("alignment", {"status": "missing"})
        alignment["characters"] = _selected_words(
            alignment.get("characters", []),
            chosen.get("alignment", {}).get("characters", []),
            bounds,
        )
        if measured and chosen.get("alignment", {}).get("status") == "pass":
            alignment["status"] = "pass"
        analysis["pauseCandidates"] = [
            row
            for row in analysis.get("pauseCandidates", [])
            if (span := source_interval(row["sourceRange"])[1:])[1] < bounds[0]
            or span[0] > bounds[1]
        ]
        analysis.setdefault("uncertainty", []).append(
            "Selected transcript evidence does not certify affected pause edges"
        )
        return measured

    def result(self):
        if self.analysis is not None:
            for _, choice in self.choices:
                try:
                    self.apply(choice)
                except (OSError, ValueError, KeyError) as error:
                    self.stale = True
                    self.issues.append(str(error))
                    self.protected.append(
                        _intersection(choice["sourceRange"], self.bounds)
                    )
        requested = _union([row for _, _, ranges in self.requests for row in ranges])
        pending = list(_uncovered(requested, _union(self.resolved)))
        protected = _union([*pending, *self.protected])
        evidence = {
            "contractVersion": "1.0.0",
            "status": self.status(pending),
            "originalAnalysisRef": deepcopy(self.original_ref),
            "requestRefs": [ref for ref, _, _ in self.requests],
            "resultRefs": self.results,
            "decisionRefs": [ref for ref, _ in self.choices],
            "protectedRanges": [
                _source_range(span, self.interval) for span in protected
            ],
            "issues": self.issues,
        }
        evidence["selectionHash"] = content_hash(
            {
                "sourceRef": self.source["fingerprint"]["sha256"],
                "sourceRange": self.interval,
                "routing": self.routing,
                "syncRef": self.sync_ref,
                **evidence,
            }
        )
        if self.analysis is not None:
            self.analysis["preparationEvidence"] = deepcopy(evidence)
        response = {**evidence, "analysis": self.analysis}
        _check_budget(response, METADATA_LIMITS)
        return response

    def status(self, pending):
        if self.stale:
            return "stale"
        if not self.requests:
            return "absent"
        choices = {value["input"]["choice"] for _, value in self.choices}
        if choices == {"defer"}:
            return "deferred"
        if pending:
            return "partial" if choices else "pending"
        return "rejected" if choices == {"reject"} else "selected"


def selected_source_evidence(service, source, *, source_range, routing, sync_ref):
    selection = _Selection(service, source, source_range, routing, sync_ref)
    selection.collect()
    selection.original()
    return selection.result()


def selected_evidence_protections(analysis):
    evidence = analysis.get("preparationEvidence")
    if evidence is None:
        return ()
    validate_document(evidence, "avo.preparation.schema.json#/$defs/selectedEvidence")
    source = analysis["sourceRef"]
    interval = analysis["preprocessing"]["sourceRange"]
    expected = content_hash(
        {
            "sourceRef": source["sha256"],
            "sourceRange": interval,
            "routing": analysis["routing"],
            "syncRef": analysis["syncRef"],
            **{key: value for key, value in evidence.items() if key != "selectionHash"},
        }
    )
    if evidence["selectionHash"] != expected:
        raise ValueError("Selected source evidence identity changed")
    identity, first, end = source_interval(interval)
    protections = []
    for chosen in evidence["protectedRanges"]:
        source_id, start, finish = source_interval(chosen)
        if source_id != identity or not first <= start < finish <= end:
            raise ValueError("Selected source protection escapes its original unit")
        protections.append(
            {
                "eventId": "preparation-uncertainty-"
                + content_hash([source, chosen])[:24],
                "role": "uncertain-speech",
                "reason": "Transcript alternatives or exact word timing remain unresolved",
                "sourceRange": deepcopy(chosen),
                "sourceFingerprint": deepcopy(source),
            }
        )
    return tuple(protections)
