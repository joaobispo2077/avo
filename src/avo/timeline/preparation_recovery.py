"""Explicit source recovery with immutable alternatives and crash-consumed attempts."""

import sys
from copy import deepcopy
from fractions import Fraction
from itertools import pairwise
from math import isfinite
from pathlib import Path

from avo.editing_craft import validate_editing_craft_selection

from .cmap_service import CMapService
from .contracts import content_hash, file_fingerprint, validate_document
from .cutting_contracts import make_document, source_interval, validate_source_range
from .cutting_store import CuttingStore, CuttingStoreError
from .motion_metadata import METADATA_LIMITS, _check_budget
from .preparation import inspect_speech_coverage

SCHEMA = "avo.preparation.schema.json"


class PreparationError(ValueError):
    """A selected preparation operation cannot be executed faithfully."""


def _options(selection):
    validate_editing_craft_selection(selection)
    options = selection["effective"]["speechRecovery"]
    if not options["enabled"]:
        raise PreparationError("Speech recovery must be explicitly enabled")
    return options


def validate_recovery_scope(ranges, source_range, selection):
    options = _options(selection)
    validate_source_range(source_range)
    source_id, first, end = source_interval(source_range)
    durations, intervals = [], []
    if not isinstance(ranges, list) or not 1 <= len(ranges) <= 128:
        raise PreparationError("Recovery needs 1..128 explicit source intervals")
    for interval in ranges:
        identity, start, finish = source_interval(interval)
        if identity != source_id or not first <= start < finish <= end:
            raise PreparationError(
                "Recovery interval is outside its original source unit"
            )
        duration = finish - start
        if duration > options["maxIntervalSeconds"]:
            raise PreparationError(
                "Recovery interval budget exceeded; no scope was clipped"
            )
        durations.append(duration)
        intervals.append((start, finish))
    ordered = sorted(intervals)
    if any(left[1] > right[0] for left, right in pairwise(ordered)):
        raise PreparationError("Selected recovery intervals overlap")
    if sum(durations, Fraction()) > options["maxTotalSeconds"]:
        raise PreparationError("Recovery total budget exceeded; no scope was clipped")
    return deepcopy(ranges)


def _execution_hash():
    if getattr(sys, "frozen", False):
        return file_fingerprint(Path(sys.executable))["sha256"]
    root = Path(__file__).resolve().parents[1]
    names = [
        "timeline/preparation.py",
        "timeline/preparation_recovery.py",
        "timeline/cutting_store.py",
        "timeline/cutting_contracts.py",
        "transcribe.py",
        "speech_dependencies.py",
        "adapters/media/cutting_analysis.py",
        "adapters/media/cutting_acoustics.py",
        "adapters/media/cutting_audio.py",
        "adapters/understand/cutting_alignment.py",
        "adapters/understand/cutting_alignment_worker.py",
    ]
    files = {name: file_fingerprint(root / name)["sha256"] for name in names}
    for name in ("avo.cutting.schema.json", "avo.preparation.schema.json"):
        files[name] = file_fingerprint(root.parent.parent / "schemas" / name)["sha256"]
    return content_hash(files)


def _result_row(
    index,
    interval,
    status,
    *,
    attempt_ref=None,
    result_ref=None,
    reused=False,
    issues=None,
):
    return {
        "intervalIndex": index,
        "sourceRange": deepcopy(interval),
        "status": status,
        "attemptRef": attempt_ref,
        "resultRef": result_ref,
        "reused": reused,
        "issues": issues or [],
    }


def _response(request_ref, rows, *, status=None):
    statuses = {row["status"] for row in rows}
    return {
        "status": status or (next(iter(statuses)) if len(statuses) == 1 else "partial"),
        "requestRef": request_ref,
        "results": rows,
        "approval": "not-granted",
    }


def _scope_response(reference, ranges, status, issue):
    return _response(
        reference,
        [
            _result_row(i, interval, status, issues=[issue])
            for i, interval in enumerate(ranges)
        ],
    )


class PreparationService:
    def decide(self, request):
        from .preparation_choices import decide_recovery

        return decide_recovery(self, request)

    def source_evidence(self, source, *, source_range, routing, sync_ref):
        from .preparation_selected import selected_source_evidence

        return selected_source_evidence(
            self, source, source_range=source_range, routing=routing, sync_ref=sync_ref
        )

    def __init__(self, workspace, *, recovery_port=None):
        self.workspace = workspace
        self.recovery_port = recovery_port
        self.store = CuttingStore(
            workspace.timeline_dir / "cutting",
            video_id=workspace.video_id,
            provider=workspace.project["provider"],
        )

    def _analysis(self, reference):
        path = (self.store.directory / reference["locator"]).resolve()
        if (
            not path.is_relative_to(self.store.directory.resolve())
            or path.stat().st_size > 32 * 1024 * 1024
        ):
            raise PreparationError(
                "Original analysis is outside its evidence tree or byte budget"
            )
        document = self.store.load_document(reference)
        if document["documentType"] != "source-analysis":
            raise PreparationError(
                "Recovery requires original source-analysis evidence"
            )
        return document["payload"]

    def _source_context(self, request):
        analysis = self._analysis(request["analysisRef"])
        saved = (analysis.get("speechCoverage") or {}).get("binding")
        original_range = self._original_range(analysis)
        validate_recovery_scope(request["ranges"], original_range, request["selection"])
        snapshot, source, routing, sync_ref = self._canonical_source(original_range)
        expected = {
            "locator": source["locator"],
            "sha256": source["fingerprint"]["sha256"],
        }
        if analysis["sourceRef"] != expected:
            raise PreparationError("Original analysis source changed")
        if saved:
            matches = (
                saved["routingHash"] == content_hash(routing)
                and saved["syncRef"] == sync_ref
            )
        else:
            matches = (
                analysis.get("routing") == routing
                and analysis.get("syncRef") == sync_ref
            )
        if not matches:
            raise PreparationError("Original source routing or Sync changed")
        CMapService(self.workspace)._verify_raw(snapshot)
        coverage = inspect_speech_coverage(
            analysis,
            source_ref=expected,
            source_range=original_range,
            routing=routing,
            sync_ref=sync_ref,
        )
        return {
            "source": source,
            "analysis": analysis,
            "binding": coverage["binding"],
            "routing": routing,
            "syncRef": sync_ref,
        }

    @staticmethod
    def _original_range(analysis):
        saved = (analysis.get("speechCoverage") or {}).get("binding") or {}
        interval = saved.get("sourceRange") or (
            analysis.get("preprocessing") or {}
        ).get("sourceRange")
        if interval is None:
            raise PreparationError("Original analysis has no bound source interval")
        return interval

    def _canonical_source(self, original_range):
        cmap = self.workspace.store("cmap")
        head = cmap.load_index()["headRevisionId"]
        if head is None:
            raise PreparationError(
                "Recovery requires a canonical original-source inventory"
            )
        snapshot = cmap.revision(head)["snapshot"]
        sources = [
            source
            for source in snapshot["sources"]
            if source["sourceId"] == original_range["sourceId"]
        ]
        if len(sources) != 1 or sources[0]["kind"] != "raw":
            raise PreparationError(
                "Recovery source is unavailable or is not an original"
            )
        source = sources[0]
        routing = source.get("streamMetadata", {}).get("audioSelection")
        validate_document(routing, "avo.cmap.schema.json#/$defs/layoutAudioSelection")
        basis = CMapService(self.workspace)._sync_basis()
        sync_ref = {"locator": basis["revisionId"], "sha256": basis["contentSha256"]}
        return snapshot, source, routing, sync_ref

    def coverage(self, request):
        """Reinspect retained facts against metadata heads; never open media or models."""
        _check_budget(request, METADATA_LIMITS)
        validate_document(request, SCHEMA + "#/$defs/coverageRequest")
        analysis = self._analysis(request["analysisRef"])
        interval = self._original_range(analysis)
        _, source, routing, sync_ref = self._canonical_source(interval)
        return {
            "effect": "metadata-read",
            "approval": "not-granted",
            "analysisRef": deepcopy(request["analysisRef"]),
            "coverage": inspect_speech_coverage(
                analysis,
                source_ref={
                    "locator": source["locator"],
                    "sha256": source["fingerprint"]["sha256"],
                },
                source_range=interval,
                routing=routing,
                sync_ref=sync_ref,
            ),
        }

    def _context(self, request):
        context = self._source_context(request)
        bindings = (
            self.recovery_port.dependency_bindings()
            if self.recovery_port
            else {
                "transcription": {
                    "status": "unknown",
                    "reason": "No selected local ASR port",
                }
            }
        )
        _check_budget(bindings, METADATA_LIMITS)
        context["modelBindings"] = bindings
        context["executionHash"] = _execution_hash()
        context["modelHash"] = content_hash(
            {"bindings": bindings, "execution": context["executionHash"]}
        )
        return context

    @staticmethod
    def _same_context(frozen, current):
        return (
            frozen["binding"] == current["binding"]
            and frozen["modelHash"] == current["modelHash"]
        )

    def _still_current(self, frozen, request):
        try:
            return self._same_context(frozen, self._context(request))
        except (OSError, ValueError, KeyError):
            return False

    def _frozen(self, request, context):
        return make_document(
            "speech-recovery-request",
            {
                "input": request,
                "requestHash": content_hash(request),
                "binding": context["binding"],
                "modelBindings": context["modelBindings"],
                "modelHash": context["modelHash"],
                "executionHash": context["executionHash"],
            },
        )

    def _saved_row(self, request_ref, attempt_ref, index, interval):
        saved = self.store.recovery_result(attempt_ref)
        if saved is None:
            return _result_row(
                index,
                interval,
                "interrupted",
                attempt_ref=attempt_ref,
                issues=[
                    "A prior attempt has no retained result; it will not run again automatically"
                ],
            )
        reference, document = saved
        reference = self.store.record_recovery_result(document)
        return _result_row(
            index,
            interval,
            document["payload"]["status"],
            attempt_ref=attempt_ref,
            result_ref=reference,
            reused=True,
            issues=document["payload"]["issues"],
        )

    def _recover_interval(self, request_ref, frozen, index, context):
        request = frozen["input"]
        interval = request["ranges"][index]
        try:
            with self.store.recovery_interval_lock(request_ref, index):
                attempt_ref, _, fresh = self.store.claim_recovery(request_ref, index)
                if not fresh:
                    return self._saved_row(request_ref, attempt_ref, index, interval)
                return self._execute(request_ref, attempt_ref, frozen, index, context)
        except BlockingIOError:
            return _result_row(
                index,
                interval,
                "running",
                issues=["The selected recovery interval is already running"],
            )

    def _execute(self, request_ref, attempt_ref, frozen, index, context):
        request, issues, recovered, status = frozen["input"], [], None, "pending-review"
        interval = request["ranges"][index]
        try:
            recovered = self.recovery_port.recover(
                Path(context["source"]["locator"]),
                selection=context["routing"],
                source_range=interval,
                fingerprint=context["source"]["fingerprint"],
                sync_ref=context["syncRef"],
                language=request["language"],
                output_dir=self.store.directory / "recovery-media",
            )
            _check_budget(recovered, METADATA_LIMITS)
            recovered = {
                **deepcopy(recovered),
                "transcriptHash": content_hash(recovered["transcript"]),
            }
            self._validate_output(recovered, context, interval)
            if not self._still_current(frozen, request):
                status, issues = (
                    "stale",
                    ["Source or model inputs changed during recovery"],
                )
        except (OSError, RuntimeError, ValueError, TypeError, KeyError) as error:
            status, issues = "failed", [str(error)[:1000] or type(error).__name__]
            recovered = None
        eligible = (
            status == "pending-review"
            and recovered is not None
            and self._word_eligibility(recovered["analysis"])
        )
        document = make_document(
            "speech-recovery-result",
            {
                "attemptRef": attempt_ref,
                "requestRef": request_ref,
                "intervalIndex": index,
                "sourceRange": interval,
                "status": status,
                "originalAnalysisRef": request["analysisRef"],
                "recovered": recovered,
                "wordAnchorsEligible": eligible,
                "selection": "pending",
                "issues": issues,
                "capturedAt": self.store.clock(),
            },
        )
        reference = self.store.record_recovery_result(document)
        return _result_row(
            index,
            interval,
            status,
            attempt_ref=attempt_ref,
            result_ref=reference,
            issues=issues,
        )

    @staticmethod
    def _validate_output(recovered, context, interval):
        validate_document(recovered, SCHEMA + "#/$defs/recoveredData")
        analysis = recovered["analysis"]
        expected = {
            "sourceRef": context["binding"]["sourceRef"],
            "routing": context["routing"],
            "syncRef": context["syncRef"],
        }
        if (
            any(analysis.get(key) != value for key, value in expected.items())
            or (analysis.get("preprocessing") or {}).get("sourceRange") != interval
        ):
            raise PreparationError(
                "Recovered evidence changed its source/routing/Sync/offset provenance"
            )
        _, first, end = source_interval(interval)
        # Native extraction may round outward by one sample; no other offset shift is accepted.
        rate = context["routing"]["sourceSampleRate"]
        tolerance = Fraction(1, rate)
        origin = recovered["transcript"].get("sourceStart")
        if (
            not _finite_time(origin)
            or not first - tolerance <= Fraction(str(origin)) <= first
        ):
            raise PreparationError("Recovered transcript has a different source offset")
        for words in (
            analysis.get("words", []),
            recovered["transcript"].get("words", []),
        ):
            _validate_word_times(words, first - tolerance, end + tolerance)

    @staticmethod
    def _word_eligibility(analysis):
        return (
            (analysis.get("alignment") or {}).get("status") == "pass"
            and bool(analysis.get("words"))
            and all(
                word.get("alignmentStatus") == "aligned"
                and word.get("eligibleEdge") is True
                for word in analysis["words"]
            )
        )

    def recover(self, request):
        try:
            _check_budget(request, METADATA_LIMITS)
            validate_document(request, SCHEMA + "#/$defs/recoverRequest")
            _options(request["selection"])
            existing = self.store.recovery_request(request["operationId"])
            if existing and existing[1]["payload"]["requestHash"] != content_hash(
                request
            ):
                raise PreparationError("Recovery operation ID changes request identity")
            try:
                context = self._context(request)
            except (OSError, ValueError, KeyError) as error:
                if existing:
                    return _scope_response(
                        existing[0], request["ranges"], "stale", str(error)[:1000]
                    )
                raise
            reference = self.store.register_recovery(self._frozen(request, context))
            frozen = self.store.load_document(reference)["payload"]
            if not self._same_context(frozen, context):
                return _scope_response(
                    reference,
                    request["ranges"],
                    "stale",
                    "Frozen recovery context changed",
                )
            if (
                context["modelBindings"].get("transcription", {}).get("status")
                != "observed"
            ):
                return _scope_response(
                    reference,
                    request["ranges"],
                    "unavailable",
                    "Selected local transcription is unavailable",
                )
            return _response(
                reference,
                [
                    self._recover_interval(reference, frozen, i, context)
                    for i in range(len(request["ranges"]))
                ],
            )
        except (ValueError, OSError, KeyError, TypeError, CuttingStoreError) as error:
            raise PreparationError(str(error)) from error


def _finite_time(value):
    return type(value) in (int, float) and isfinite(value)


def _untimed_word(word):
    return (
        word.get("start") is None
        and word.get("end") is None
        and word.get("eligibleEdge") is not True
    )


def _validate_word_times(words, first, end):
    if not isinstance(words, list):
        raise PreparationError("Recovered words must be a bounded list")
    for word in words:
        start, last = word.get("start"), word.get("end")
        if _untimed_word(word):
            continue
        if not (_finite_time(start) and _finite_time(last)):
            raise PreparationError(
                "Recovered word timing requires finite source seconds"
            )
        within = first <= Fraction(str(start)) <= Fraction(str(last)) <= end
        exact = (
            word.get("eligibleEdge") is True or word.get("alignmentStatus") == "aligned"
        )
        if not within or (exact and start == last):
            raise PreparationError(
                "Recovered word timing is outside its source interval"
            )
