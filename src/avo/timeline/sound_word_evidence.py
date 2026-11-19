"""Resolve explicitly selected retained words without source inference or publication."""

from copy import deepcopy

from avo.speech_dependencies import workspace_speech_dependencies

from .contracts import content_hash, file_fingerprint, validate_document
from .mapping import _time
from .motion_metadata import METADATA_LIMITS, _check_budget
from .preparation import _seconds
from .preparation_recovery import PreparationService
from .preparation_retention import _Evidence
from .preparation_words import word_source_time
from .sound_anchors import _source_occurrence


def _word_hash(analysis, index):
    words = analysis.get("words") or []
    if type(index) is not int or not 0 <= index < len(words):
        raise ValueError("Pinned word is unavailable")
    return content_hash(words[index])


def _unique_word(analysis, digest):
    matches = [
        index
        for index, word in enumerate(analysis.get("words") or [])
        if content_hash(word) == digest
    ]
    if len(matches) != 1:
        raise ValueError("Selected current word is unavailable or ambiguous")
    return matches[0]


def _frozen_word_anchor(anchor, point, digest, selection_hash):
    result = deepcopy(anchor)
    result["sourceTime"] = point
    spoken = anchor["spokenEvidence"]
    result["spokenEvidence"].update(wordHash=digest, selectionHash=selection_hash)
    if "sourceTime" in anchor and anchor["sourceTime"] != point:
        raise ValueError("Declared word source time changed")
    for key in ("wordHash", "selectionHash"):
        if key in spoken and result["spokenEvidence"][key] != spoken[key]:
            raise ValueError("Declared word or transcript selection changed")
    return result


class WordEvidenceReader:
    def __init__(self, workspace, *, model_bindings=None):
        self.workspace = workspace
        self.injected = model_bindings is not None
        self.models = deepcopy(
            model_bindings
            if self.injected
            else workspace_speech_dependencies(workspace)
        )
        self.service = PreparationService(workspace, recovery_port=self)
        self.evidence = _Evidence(workspace)
        self.views = {}
        self.analyses = {}
        self.ledger_head = self.service.store.head_hash()

    def dependency_bindings(self):
        return deepcopy(self.models)

    def recheck(self):
        if self.service.store.head_hash() != self.ledger_head:
            raise ValueError("Transcript selection changed during word resolution")
        for path, (_, digest) in self.evidence.files.items():
            if file_fingerprint(path)["sha256"] != digest:
                raise ValueError("Immutable word evidence changed during resolution")
        if (
            not self.injected
            and workspace_speech_dependencies(self.workspace) != self.models
        ):
            raise ValueError("Word evidence model/runtime changed during resolution")

    def _analysis(self, reference):
        key = content_hash(reference)
        if key in self.analyses:
            return self.analyses[key]
        document = self.evidence.document(reference)
        if document["documentType"] != "source-analysis":
            raise ValueError("Spoken evidence requires immutable source analysis")
        self.analyses[key] = document["payload"]
        return self.analyses[key]

    def _view(self, baseline):
        interval = self.service._original_range(baseline)
        cmap, source, routing, sync_ref = self.service._canonical_source(interval)
        key = content_hash([source, interval, routing, sync_ref])
        if key not in self.views:
            head = self.service.store.head_hash()
            view = self.service.source_evidence(
                source, source_range=interval, routing=routing, sync_ref=sync_ref
            )
            if self.service.store.head_hash() != head:
                raise ValueError("Transcript selection changed during word resolution")
            self.views[key] = view
        return cmap, source, routing, sync_ref, self.views[key]

    def _models_for_word(self, baseline, view, digest):
        candidates = []
        for reference in view["resultRefs"]:
            result = self.evidence.document(reference)
            if result["documentType"] != "speech-recovery-result":
                raise ValueError("Selected word result has the wrong evidence type")
            result = result["payload"]
            analysis = (result.get("recovered") or {}).get("analysis") or {}
            if any(content_hash(word) == digest for word in analysis.get("words", [])):
                frozen = self.evidence.document(result["requestRef"])
                if frozen["documentType"] != "speech-recovery-request":
                    raise ValueError(
                        "Selected word request has the wrong evidence type"
                    )
                candidates.append(frozen["payload"]["modelBindings"])
        if len(candidates) > 1:
            raise ValueError("Selected word model provenance is ambiguous")
        if candidates:
            return candidates[0]
        _unique_word(baseline, digest)
        return baseline.get("speechDependencies")

    def anchor(self, anchor, *, frame_rate, expected_audio=None):
        _check_budget(anchor, METADATA_LIMITS)
        validate_document(anchor, "avo.sound-selection.schema.json#/$defs/sourceAnchor")
        spoken = anchor["spokenEvidence"]
        self.evidence.closure(references=[spoken["analysisRef"]])
        pinned = self._analysis(spoken["analysisRef"])
        digest = _word_hash(pinned, spoken["wordIndex"])
        preparation = pinned.get("preparationEvidence") or {}
        baseline = (
            self._analysis(preparation["originalAnalysisRef"])
            if preparation.get("originalAnalysisRef")
            else pinned
        )
        cmap, source, routing, sync_ref, view = self._view(baseline)
        if expected_audio is not None:
            _require_word_audio(routing, expected_audio)
        if preparation and preparation["selectionHash"] != view["selectionHash"]:
            raise ValueError("Pinned transcript selection changed")
        if (
            source["sourceId"] != anchor["sourceId"]
            or source["fingerprint"]["sha256"] != anchor["sourceSha256"]
        ):
            raise ValueError("Selected word original source changed")
        analysis = view["analysis"] if view["analysis"] is not None else baseline
        index = _unique_word(analysis, digest)
        point = word_source_time(
            analysis,
            source_ref={
                "locator": source["locator"],
                "sha256": source["fingerprint"]["sha256"],
            },
            source_range=self.service._original_range(baseline),
            routing=routing,
            sync_ref=sync_ref,
            model_bindings=self._models_for_word(baseline, view, digest),
            current_bindings=self.models,
            word_index=index,
            word_hash=digest,
            frame_rate=frame_rate,
            protected_ranges=view["protectedRanges"],
        )
        word = analysis["words"][index]
        occurrence = _source_occurrence(anchor, cmap)
        if (
            not _time(occurrence["in"])
            <= _seconds(word["start"])
            < _seconds(word["end"])
            <= _time(occurrence["out"])
        ):
            raise ValueError("Selected word crosses its retained source occurrence")
        return _frozen_word_anchor(anchor, point, digest, view["selectionHash"])


def _require_word_audio(routing, selection):
    if (
        routing["streamIndex"] != selection["streamIndex"]
        or selection["channelIndex"] not in routing["channels"]
    ):
        raise ValueError("Prepared word uses a different original audio route")


def word_intent_anchors(intents):
    return {
        content_hash(anchor): anchor
        for intent in intents
        if "spokenEvidence" in (anchor := intent.get("sourceAnchor") or {})
    }


def load_word_anchors(workspace, intents, frame_rate):
    anchors = word_intent_anchors(intents)
    if not anchors:
        return None
    try:
        reader = WordEvidenceReader(workspace)
    except (ValueError, RuntimeError, OSError, KeyError, TypeError) as error:
        return {key: {"error": str(error)[:300]} for key in anchors}
    result = {}
    for key, anchor in anchors.items():
        try:
            result[key] = {"anchor": reader.anchor(anchor, frame_rate=frame_rate)}
        except (ValueError, RuntimeError, OSError, KeyError, TypeError) as error:
            result[key] = {"error": str(error)[:300]}
    try:
        reader.recheck()
    except (ValueError, RuntimeError, OSError, KeyError, TypeError) as error:
        return {key: {"error": str(error)[:300]} for key in anchors}
    return result


def _word_publications(request, proposal):
    selected = {
        choice["eventId"]
        for choice in request["choices"]
        if choice["entryId"] is not None
    }
    return [
        record
        for record in proposal["opportunities"]
        if record["eventId"] in selected
        and "spokenEvidence" in (record["intent"].get("sourceAnchor") or {})
    ]


def require_word_publication(workspace, request, proposal):
    from fractions import Fraction

    records = _word_publications(request, proposal)
    if not records:
        return None
    fps = proposal["clock"]["frameRate"]
    reader = WordEvidenceReader(workspace)
    for record in records:
        anchor = reader.anchor(
            record["intent"]["sourceAnchor"],
            frame_rate=Fraction(fps["num"], fps["den"]),
        )
        if anchor != (record["opportunity"] or {}).get("sourceAnchor"):
            raise ValueError(
                "Selected spoken-word opportunity changed before publication"
            )
    return reader
