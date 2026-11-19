"""Scoped sound publication through existing canonical owners and writer guards."""

import hashlib
import json
from copy import deepcopy

from avo.library.rules import safe_path

from .bmap_service import BMapService
from .cmap_service import CMapService
from .command_registry import authorize
from .contracts import content_hash, file_fingerprint, fingerprint_stage
from .lineage import stale_descendants
from .motion_metadata import _basis_matches
from .sound_choices import (
    _check_sound_roles,
    _sound_choice_advisories,
    _sound_document,
    _unique_sound_ids,
    freeze_sound_choices,
    require_native_mix_support,
)
from .sound_fitting import SoundPlanningError
from .sound_tracks import validate_sound_bindings
from .store import (
    StoreError,
    atomic_write_json,
    motion_application_access,
    timeline_writer,
    write_immutable_json,
)
from .tracks import TracksService

OWNERS = {"bmap": BMapService, "tracks": TracksService}


class SoundApplicationError(SoundPlanningError):
    def __init__(
        self,
        message,
        *,
        receipt_ref=None,
        committed_heads=None,
        publication_state="recovery-needed",
    ):
        super().__init__(message)
        self.receipt_ref = receipt_ref
        self.committed_heads = committed_heads or {}
        self.publication_state = publication_state

    def to_dict(self):
        return {
            "code": "SFX_APPLICATION_RECOVERY_REQUIRED",
            "message": str(self),
            "blocking": True,
            "remediation": "Retry the exact saved sound request to reconcile its actual publication.",
            "receiptRef": self.receipt_ref,
            "committedHeads": self.committed_heads,
            "publicationState": self.publication_state,
        }


def _encoded(value):
    return (
        json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    ).encode("utf-8")


def _sound_layer_content(layer):
    provenance = layer["provenance"]
    selection = {
        key: value
        for key, value in provenance["soundSelection"].items()
        if key not in {"proposalRef", "applicationRef"}
    }
    return {**layer, "provenance": {**provenance, "soundSelection": selection}}


def _require_mix_admission(choices, tracks):
    dialogue = {
        layer["layerId"]
        for layer in tracks["audioTracks"]["layers"]
        if layer["role"] == "dialogue" and not layer.get("mute", False)
    }
    for choice in choices:
        if choice["fit"]["status"] != "fit":
            continue
        mix = choice["mix"]
        require_native_mix_support(mix)
        ducking = mix["ducking"]
        if ducking is not None and ducking["sidechainLayerId"] not in dialogue:
            raise SoundPlanningError(
                "Sound ducking requires a current unmuted dialogue layer"
            )


class _Application:
    def __init__(self, planning):
        self.planning = planning
        self.workspace = planning.workspace
        self.authoring = planning.authoring
        self.catalogue = planning.catalogue
        self.latest_receipt_ref = None
        self.operation_absent = False

    def _reference(self, collection, value, definition):
        value = _sound_document(value, definition)
        raw = _encoded(value)
        digest = hashlib.sha256(raw).hexdigest()
        path = self.planning._path(collection, digest)
        return value, self.authoring._ref(path, raw), path

    def _put(self, collection, value, definition):
        value, reference, path = self._reference(collection, value, definition)
        write_immutable_json(path, value)
        return reference

    def _load(self, reference, collection, definition):
        path = self.planning._path(collection, reference["sha256"])
        value, raw = self.authoring._read(path)
        if self.authoring._ref(path, raw) != reference:
            raise SoundPlanningError("Immutable sound application reference changed")
        return _sound_document(value, definition)

    def _operation_path(self, request, collection="operations"):
        return self.planning._path(
            collection, content_hash(["apply", request["operationId"]])
        )

    def _known(self, request):
        path = self._operation_path(request)
        if not path.exists():
            return self._orphaned_stage(request)
        record, _ = self.authoring._read(path)
        _sound_document(record, "applicationOperation")
        saved = self._load(record["requestRef"], "requests", "applyRequest")
        if saved != request or record["requestHash"] != content_hash(request):
            raise SoundPlanningError(
                "Sound operation identity records different inputs"
            )
        pointer, _ = self.authoring._read(self._operation_path(request, "applications"))
        receipt = self._load(pointer, "receipts", "applicationReceipt")
        self.latest_receipt_ref = pointer
        initial = self._load(
            record["initialReceiptRef"], "receipts", "applicationReceipt"
        )
        self._verify_recipe(request, receipt, initial)
        if (
            receipt["requestHash"] != record["requestHash"]
            or receipt["requestRef"] != record["requestRef"]
        ):
            raise SoundPlanningError("Sound receipt differs from its actual request")
        return receipt, pointer

    def _orphaned_stage(self, request):
        path = self._operation_path(request, "applications")
        if not path.exists():
            return None
        pointer, _ = self.authoring._read(path)
        receipt = self._load(pointer, "receipts", "applicationReceipt")
        saved = self._load(receipt["requestRef"], "requests", "applyRequest")
        if saved != request or receipt["requestHash"] != content_hash(request):
            raise SoundPlanningError(
                "Interrupted staged sound operation records different inputs"
            )
        self._verify_recipe(request, receipt, receipt)
        self.operation_absent = True
        self.latest_receipt_ref = pointer
        return receipt, pointer

    def _verify_recipe(self, request, receipt, initial):
        mutable = {"state", "committedHeads", "previousReceiptRef", "lastError"}
        if {k: v for k, v in receipt.items() if k not in mutable} != {
            k: v for k, v in initial.items() if k not in mutable
        }:
            raise SoundPlanningError(
                "Sound receipt recipe differs from its staged operation"
            )
        self._verify_initial(request, receipt, initial)
        self._verify_choice_recipe(request, receipt)
        for name, prepared in receipt["prepared"].items():
            self.workspace.store(name)._validate_revision(prepared)
        validate_sound_bindings(
            receipt["prepared"]["bmap"]["snapshot"],
            receipt["prepared"]["tracks"]["snapshot"],
        )

    @staticmethod
    def _verify_initial(request, receipt, initial):
        if (
            initial["state"] != "staged"
            or initial["committedHeads"]
            or initial["previousReceiptRef"] is not None
            or any(
                receipt[k] != request[k]
                for k in ("operationId", "actor", "reason", "expectedBasis")
            )
            or receipt["proposalRef"]["sha256"] != request["proposalHash"]
        ):
            raise SoundPlanningError(
                "Sound receipt recipe differs from its actual request"
            )

    def _verify_choice_recipe(self, request, receipt):
        proposal = self.planning.load(request["proposalHash"])["proposal"]
        entries = {
            c["sourceEntry"]["entryId"]: c["sourceEntry"]
            for c in receipt["choices"]
            if c["sourceEntry"] is not None
        }
        prepared = self._choices(
            request,
            proposal,
            {"entries": list(entries.values())},
            {"tracks": self._parent_tracks(request["expectedBasis"])},
        )
        if prepared["choices"] != receipt["choices"]:
            raise SoundPlanningError(
                "Sound receipt recipe changes its explicit selected choices"
            )
        if prepared.get("productionScope") != receipt.get("productionScope"):
            raise SoundPlanningError(
                "Sound receipt changes its exact production ownership"
            )

    def _parent_tracks(self, basis):
        head = basis["tracks"]
        if head is None:
            return {"audioTracks": {"layers": []}}
        revision = self.workspace.store("tracks").revision(head["revisionId"])
        if revision["contentHash"] != head["sha256"]:
            raise SoundPlanningError(
                "Sound request changes its immutable parent Tracks"
            )
        return revision["snapshot"]

    def _save(self, request, receipt):
        path = self._operation_path(request, "applications")
        previous = None
        if path.exists():
            previous, _ = self.authoring._read(path)
            old = self._load(previous, "receipts", "applicationReceipt")
            if {k: v for k, v in old.items() if k != "previousReceiptRef"} == {
                k: v for k, v in receipt.items() if k != "previousReceiptRef"
            }:
                self.latest_receipt_ref = previous
                return previous
        receipt["previousReceiptRef"] = previous
        reference = self._put("receipts", receipt, "applicationReceipt")
        atomic_write_json(path, reference)
        self.latest_receipt_ref = reference
        return reference

    def _snapshots(self):
        snapshots = {}
        for name in OWNERS:
            store = self.workspace.store(name)
            index = store.load_index()
            snapshots[name] = (
                deepcopy(store.revision(index["headRevisionId"])["snapshot"])
                if index["headRevisionId"]
                else {}
            )
        snapshots["tracks"].setdefault("audioTracks", {}).setdefault("layers", [])
        snapshots["tracks"].setdefault("videoTracks", {}).setdefault("layers", [])
        snapshots["bmap"].setdefault("cues", [])
        return snapshots

    def _check_requested_heads(self, request, committed):
        expected = {**request["expectedBasis"], **(committed or {})}
        current = self.authoring._heads()
        for parent in committed or {}:
            for name in stale_descendants(parent):
                head, actual = expected.get(name), current.get(name)
                if (
                    name not in committed
                    and head is not None
                    and head.get("activeState") == "valid"
                    and actual is not None
                    and actual.get("activeState") == "stale"
                ):
                    # Our published parent invalidates this unchanged descendant.
                    # Keep its identity and approval checks, and leave it stale.
                    expected[name] = {**head, "activeState": "stale"}
        self.authoring._check_heads(expected)

    def _basis(self, request, *, committed=None):
        self._check_requested_heads(request, committed)
        shown = self.planning.load(request["proposalHash"])
        proposal = shown["proposal"]
        if not proposal["options"]["effective"]["soundMatching"]["enabled"]:
            raise SoundPlanningError(
                "Selected sound matching is disabled for this proposal"
            )
        if proposal["basisHeads"] != request["expectedBasis"]:
            raise SoundPlanningError(
                "Sound proposal does not bind the requested canonical heads"
            )
        frozen = ((self.authoring._run() or {}).get("executionChoices") or {}).get(
            "editingCraft"
        )
        if not frozen or (
            frozen["requestId"],
            frozen["selection"],
            frozen["directionRef"],
        ) != (proposal["requestId"], proposal["options"], proposal["directionRef"]):
            raise SoundPlanningError(
                "Selected sound request differs from its frozen options/direction"
            )
        if self.authoring._direction_ref() != proposal["directionRef"]:
            raise SoundPlanningError("Selected sound direction changed")
        self.planning._program_clock(proposal["clock"])
        generation = self.catalogue.show()
        if (
            generation["generationId"] != request["expectedGeneration"]
            or proposal["generationId"] != request["expectedGeneration"]
        ):
            raise SoundPlanningError("Sound catalogue generation changed")
        return shown, generation

    def _source_path(self, entry, generation):
        root = self.catalogue.roots.get(entry["libraryId"])
        if root is None or generation["roots"].get(entry["libraryId"]) != str(root):
            raise SoundPlanningError(
                "Selected sound root differs from the catalogue generation"
            )
        if str(root).startswith(("\\\\", "//")) or "://" in str(root):
            raise SoundPlanningError("Selected sound requires a local library root")
        path = safe_path(root, entry["relativePath"])
        fingerprint = file_fingerprint(path)
        if any(
            fingerprint[key] != entry["source"][key] for key in ("sha256", "sizeBytes")
        ):
            raise SoundPlanningError("Selected sound source fingerprint changed")
        return path, fingerprint

    def _observed_source(self, entry, generation):
        path, fingerprint = self._source_path(entry, generation)
        observed = self.planning.source_probe(
            path, expected_sha256=fingerprint["sha256"]
        )
        facts = entry["measurement"]
        if (
            observed["sourceSha256"] != fingerprint["sha256"]
            or observed["sampleRate"] != facts["sampleRate"]
            or observed["channels"] != facts["channels"]
        ):
            raise SoundPlanningError(
                "Selected sound probe differs from its measured source"
            )
        source = {
            "locator": str(path),
            "sha256": fingerprint["sha256"],
            "mediaClass": "source",
            "streamIndex": observed["streamIndex"],
        }
        return _sound_document(source, "compileSource")

    def _source_refs(self, choices, generation):
        references = {}
        for choice in choices:
            if choice["fit"]["status"] == "silence":
                continue
            if choice["fit"]["status"] != "fit":
                raise SoundPlanningError("Unresolved sound choices cannot be published")
            if self.planning.source_probe is None:
                raise SoundPlanningError(
                    "Selected sound requires an explicit source probe"
                )
            references[choice["eventId"]] = self._observed_source(
                choice["sourceEntry"], generation
            )
        return references

    @staticmethod
    def _selected_layers(snapshot):
        return {
            layer["provenance"]["soundSelection"]["choice"]["eventId"]: layer
            for layer in snapshot["audioTracks"]["layers"]
            if "soundSelection" in (layer.get("provenance") or {})
        }

    @staticmethod
    def _opportunities(request, proposal):
        records = _unique_sound_ids(proposal["opportunities"], "eventId")
        for choice in request["choices"]:
            if (
                choice["eventId"] not in records
                or records[choice["eventId"]]["opportunity"] is None
            ):
                raise SoundPlanningError(
                    "Sound choice has no current resolved opportunity"
                )
        return [
            record["opportunity"]
            for record in records.values()
            if record["opportunity"] is not None
        ]

    @staticmethod
    def _selected_entries(request, generation):
        entries = {entry["entryId"]: entry for entry in generation["entries"]}
        selected = {
            c["entryId"] for c in request["choices"] if c["entryId"] is not None
        }
        if selected - set(entries):
            raise SoundPlanningError(
                "Selected sound is absent from the current catalogue"
            )
        return [entries[key] for key in sorted(selected)]

    def _choices(self, request, proposal, generation, snapshots):
        old = [
            layer["provenance"]["soundSelection"]["choice"]
            for layer in self._selected_layers(snapshots["tracks"]).values()
        ]
        _unique_sound_ids(request["choices"], "eventId")
        retired = self._retired_choices(request, proposal, old)
        current = {
            **request,
            "choices": [c for c in request["choices"] if c["eventId"] not in retired],
        }
        contexts = deepcopy(request["contexts"])
        changed = {c["eventId"] for c in request["choices"] if c["entryId"] is not None}
        for context in contexts:
            context["orderedEventIds"] = [
                key for key in context["orderedEventIds"] if key in changed
            ]
        prepared = freeze_sound_choices(
            self._opportunities(current, proposal),
            current["choices"],
            entries=self._selected_entries(current, generation),
            contexts=contexts,
            clock=proposal["clock"],
            previous=old,
        )
        prepared = self._restore_choice_order(prepared, retired, request["choices"])
        from .sound_scope import project_sound_scope

        scope = project_sound_scope(
            request, proposal["clock"], prepared["choices"], old
        )
        if scope is not None:
            prepared["productionScope"] = scope
        return prepared

    @staticmethod
    def _restore_choice_order(prepared, retired, choices):
        for field in ("choices", "changes"):
            combined = _unique_sound_ids(
                prepared[field] + [value[field][0] for value in retired.values()],
                "eventId",
            )
            prepared[field] = [combined[c["eventId"]] for c in choices]
        return prepared

    @staticmethod
    def _retired_choices(request, proposal, previous):
        records = _unique_sound_ids(proposal["opportunities"], "eventId")
        old = _unique_sound_ids(previous, "eventId")
        retired = {}
        for choice in request["choices"]:
            identity = choice["eventId"]
            if (records.get(identity) or {}).get("opportunity") is not None:
                continue
            if choice["entryId"] is not None or identity not in old:
                continue
            fit = old[identity]["fit"]
            # Historical timing identifies the removed contribution only. It
            # cannot schedule media or confer a current visual/mix approval.
            retired[identity] = freeze_sound_choices(
                [fit["opportunity"]],
                [choice],
                entries=[],
                contexts=[],
                clock=fit["clock"],
                previous=[old[identity]],
            )
        return retired

    @staticmethod
    def _visual_role(record, cue):
        if (record.get("origin") or {}).get("camera"):
            return "main-scene"
        declared = (cue.get("contentRef") or {}).get("role")
        if declared is not None:
            return declared
        if cue["kind"] in {"text", "caption", "card", "animation", "transition"}:
            return "authored-graphic"
        return None

    def _visual_contexts(self, request, proposal, snapshots):
        contexts = _unique_sound_ids(request["contexts"], "cueId")
        cues = {cue["cueId"]: cue for cue in snapshots["bmap"]["cues"]}
        for record in proposal["opportunities"]:
            opportunity = record["opportunity"]
            if opportunity is None or opportunity["cueId"] not in contexts:
                continue
            cue = cues.get(opportunity["cueId"])
            if cue is None:
                raise SoundPlanningError("Owning visual cue is absent")
            expected = self._visual_role(record, cue)
            if expected is None or contexts[cue["cueId"]]["role"] != expected:
                raise SoundPlanningError(
                    "Sound context differs from the current visual role"
                )
        return contexts

    def _layer(
        self,
        choice,
        source,
        context,
        proposal_ref,
        request_ref,
        generation,
        order,
        old=None,
    ):
        event_id = choice["eventId"]
        token = content_hash([self.workspace.video_id, event_id])[:24]
        selection = (old or {}).get("provenance", {}).get("soundSelection")
        layer_id = old["layerId"] if old else "sound-" + token
        cue_id = selection["cueId"] if selection else "sound-cue-" + token
        fit, mix = choice["fit"], choice["mix"]
        region = {
            "regionId": "sound-region-" + token,
            "timebase": {"num": 1, "den": fit["clock"]["sampleRate"]},
            "startTicks": fit["event"]["scheduledAudioStartSample"],
            "endTicks": fit["scheduledAudioEndSample"],
            "cueIds": [cue_id],
        }
        source_fingerprint = {
            "locator": source["locator"],
            "sha256": source["sha256"],
            "sizeBytes": choice["sourceEntry"]["source"]["sizeBytes"],
        }
        selected = {
            "contractVersion": "1.0.0",
            "choice": choice,
            "cueId": cue_id,
            "generationId": generation,
            "proposalRef": proposal_ref,
            "applicationRef": request_ref,
            "sourceRef": source,
            "context": {
                "cueId": context["cueId"],
                "role": context["role"],
                "syntheticEffectApproved": context["syntheticEffectApproved"],
                "orderedLayeringApproved": bool(context["orderedEventIds"]),
            },
        }
        layer = {
            "layerId": layer_id,
            "order": order,
            "role": "sfx",
            "source": source_fingerprint,
            "regions": [region],
            "channels": mix["channelMap"],
            "gainDb": mix["gainDb"],
            "mute": False,
            "status": "pending-listening",
            "provenance": {"soundSelection": selected},
        }
        time = lambda ticks: {
            "ticks": ticks,
            "timebase": region["timebase"],
            "domain": "cmap-output",
        }
        cue = {
            "cueId": cue_id,
            "start": time(region["startTicks"]),
            "end": time(region["endTicks"]),
            "kind": "sfx",
            "assetRef": source_fingerprint,
            "targetLayerId": layer_id,
            "contentRef": {
                "soundEventId": event_id,
                "linkedItemId": choice["itemId"],
                "choiceHash": choice["choiceHash"],
                "applicationRef": request_ref,
            },
            "audio": {"playbackOwner": "tracks-native", "eventId": event_id},
            "intent": fit["opportunity"]["purpose"],
            "reason": "Selected sound contribution",
            "reviewState": "pending",
        }
        return layer, cue

    @staticmethod
    def _remove_scope(snapshots, current, selected_ids):
        owned = [current[key] for key in selected_ids & set(current)]
        cue_ids = {layer["provenance"]["soundSelection"]["cueId"] for layer in owned}
        layer_ids = {layer["layerId"] for layer in owned}
        snapshots["tracks"]["audioTracks"]["layers"] = [
            layer
            for layer in snapshots["tracks"]["audioTracks"]["layers"]
            if layer["layerId"] not in layer_ids
        ]
        snapshots["bmap"]["cues"] = [
            cue for cue in snapshots["bmap"]["cues"] if cue["cueId"] not in cue_ids
        ]

    @staticmethod
    def _append_layer(snapshots, layer, cue):
        if any(
            existing["layerId"] == layer["layerId"]
            for existing in snapshots["tracks"]["audioTracks"]["layers"]
        ) or any(
            existing["cueId"] == cue["cueId"] for existing in snapshots["bmap"]["cues"]
        ):
            raise SoundPlanningError(
                "Selected sound identity collides with unrelated canonical content"
            )
        snapshots["tracks"]["audioTracks"]["layers"].append(layer)
        snapshots["bmap"]["cues"].append(cue)

    def _combined_roles(self, snapshots, choices, contexts, *, repetition_window_ms):
        layers = sorted(
            self._selected_layers(snapshots["tracks"]).values(),
            key=lambda layer: layer["order"],
        )
        combined = [layer["provenance"]["soundSelection"]["choice"] for layer in layers]
        affected = {
            choice["fit"]["opportunity"]["cueId"]
            for choice in choices
            if choice["fit"]["status"] == "fit"
        }
        self._check_preserved_contexts(layers, affected, contexts)
        _check_sound_roles(
            [
                choice
                for choice in combined
                if choice["fit"]["opportunity"]["cueId"] in affected
            ],
            contexts,
        )
        return _sound_choice_advisories(
            combined, repetition_window_ms=repetition_window_ms
        )

    @staticmethod
    def _check_preserved_contexts(layers, affected, contexts):
        for layer in layers:
            selected = layer["provenance"]["soundSelection"]
            cue_id = selected["choice"]["fit"]["opportunity"]["cueId"]
            if cue_id not in affected:
                continue
            context = contexts.get(cue_id)
            if context is None:
                raise SoundPlanningError("Current owning visual context is required")
            expected = {
                "cueId": cue_id,
                "role": context["role"],
                "syntheticEffectApproved": context["syntheticEffectApproved"],
                "orderedLayeringApproved": bool(context["orderedEventIds"]),
            }
            if selected.get("context") != expected:
                raise SoundPlanningError(
                    "Preserved sound requires explicit reselection to change its context"
                )

    def _append_choice(
        self,
        request,
        shown,
        choice,
        sources,
        snapshots,
        request_ref,
        contexts,
        old,
        order,
    ):
        if choice["fit"]["status"] == "silence":
            return
        context = contexts[choice["fit"]["opportunity"]["cueId"]]
        layer, cue = self._layer(
            choice,
            sources[choice["eventId"]],
            context,
            shown["proposalRef"],
            request_ref,
            request["expectedGeneration"],
            old["order"] if old else order,
            old,
        )
        self._append_layer(snapshots, layer, cue)

    def _authoring(
        self,
        request,
        shown,
        prepared,
        sources,
        snapshots,
        request_ref,
        contexts,
        *,
        repetition_window_ms=None,
    ):
        current = self._selected_layers(snapshots["tracks"])
        order = max(
            [
                layer.get("order", 0)
                for layer in snapshots["tracks"]["audioTracks"]["layers"]
            ]
            or [0]
        )
        self._remove_scope(
            snapshots, current, {choice["eventId"] for choice in prepared["choices"]}
        )
        for choice in prepared["choices"]:
            order += 1
            self._append_choice(
                request,
                shown,
                choice,
                sources,
                snapshots,
                request_ref,
                contexts,
                current.get(choice["eventId"]),
                order,
            )
        return snapshots, self._combined_roles(
            snapshots,
            prepared["choices"],
            contexts,
            repetition_window_ms=repetition_window_ms,
        )

    def _prepare(self, request):
        from .sound_scope import require_sound_scope_parent
        from .sound_word_evidence import require_word_publication

        shown, generation = self._basis(request)
        snapshots = self._snapshots()
        require_sound_scope_parent(request, snapshots)
        validate_sound_bindings(
            snapshots["bmap"],
            snapshots["tracks"],
            removing_event_ids={
                c["eventId"] for c in request["choices"] if c["entryId"] is None
            },
        )
        contexts = self._visual_contexts(request, shown["proposal"], snapshots)
        word_reader = require_word_publication(
            self.workspace, request, shown["proposal"]
        )
        choices = self._choices(request, shown["proposal"], generation, snapshots)
        _require_mix_admission(choices["choices"], snapshots["tracks"])
        sources = self._source_refs(choices["choices"], generation)
        _, request_ref, _ = self._reference("requests", request, "applyRequest")
        matching = shown["proposal"]["options"]["effective"]["soundMatching"]
        snapshots, advisories = self._authoring(
            request,
            shown,
            choices,
            sources,
            snapshots,
            request_ref,
            contexts,
            repetition_window_ms=matching.get("repetitionWindowMs"),
        )
        _, cmap, _ = BMapService(self.workspace).current_basis()
        CMapService(self.workspace)._verify_raw(cmap["snapshot"])
        evidence = [
            {
                "evidenceId": "sound-proposal:" + shown["proposalRef"]["sha256"],
                "kind": "sound-proposal",
                **shown["proposalRef"],
            },
            {
                "evidenceId": "sound-application:" + request_ref["sha256"],
                "kind": "sound-application",
                **request_ref,
            },
        ]
        revisions = {}
        for name, owner in OWNERS.items():
            kwargs = {} if name == "bmap" else {"parents": revisions}
            revisions[name] = owner(self.workspace).prepare_authoring(
                snapshots[name],
                actor=request["actor"],
                reason=request["reason"],
                evidence=evidence,
                **kwargs,
            )
        self._basis(request)
        if word_reader is not None:
            word_reader.recheck()
        receipt = {
            "contractVersion": "1.0.0",
            "operationId": request["operationId"],
            "requestHash": content_hash(request),
            "requestRef": request_ref,
            "proposalRef": shown["proposalRef"],
            "expectedBasis": request["expectedBasis"],
            "actor": request["actor"],
            "reason": request["reason"],
            "state": "staged",
            "prepared": revisions,
            "committedHeads": {},
            "choices": choices["choices"],
            "changes": choices["changes"],
            "sourceRefs": sources,
            "advisories": advisories,
            "previousReceiptRef": None,
            "lastError": None,
        }
        if "productionScope" in choices:
            receipt["productionScope"] = choices["productionScope"]
        return _sound_document(receipt, "applicationReceipt")

    def _review_scope(self, receipt):
        from .sound_scope import sound_review_scope

        scope = receipt.get("productionScope")
        if scope is None:
            return {}
        before = self._selected_layers(self._parent_tracks(receipt["expectedBasis"]))
        after = self._selected_layers(receipt["prepared"]["tracks"]["snapshot"])
        unchanged = {
            event
            for event in before.keys() & after.keys()
            if _sound_layer_content(before[event]) == _sound_layer_content(after[event])
        }
        return {"reviewScope": sound_review_scope(scope, unchanged_ids=unchanged)}

    def _result(self, receipt, reference):
        actual = self.authoring._actual_committed(receipt, require_active=False)
        if actual != receipt["committedHeads"] or set(actual) != set(OWNERS):
            raise SoundPlanningError(
                "Committed sound receipt differs from actual canonical history"
            )
        current = self.authoring._heads()
        return {
            "operation": "apply",
            "status": "applied",
            "receipt": receipt,
            "receiptRef": reference,
            "proposalRef": receipt["proposalRef"],
            "committedHeads": actual,
            "currentHeads": current,
            "headsCurrent": _basis_matches(actual, current),
            "changes": receipt["changes"],
            "advisories": receipt["advisories"],
            "acceptance": "pending-listening",
            **self._review_scope(receipt),
        }

    def _commit(self, request, receipt):
        try:
            receipt["state"] = "committing"
            self._save(request, receipt)
            with fingerprint_stage(verify_on_exit=True):
                self._basis(
                    request, committed=self.authoring._actual_committed(receipt)
                )
                validation = {
                    **request,
                    "authoring": {
                        name: body["snapshot"]
                        for name, body in receipt["prepared"].items()
                    },
                }
                self.authoring._verify_recovery_inputs(validation, receipt)
                self._commit_owners(request, receipt)
                self._basis(request, committed=receipt["committedHeads"])
            receipt["state"], receipt["lastError"] = "committed", None
            reference = self._save(request, receipt)
        except Exception as error:
            self._failed_commit(request, receipt, error)
        result = self._result(receipt, reference)
        self._clear_pending(receipt, reference)
        return result

    def _failed_commit(self, request, receipt, error):
        receipt["state"] = "recovery-needed"
        receipt["lastError"] = str(error)[:2048]
        diagnostics = []
        try:
            receipt["committedHeads"] = self.authoring._actual_committed(receipt)
        except Exception as inspection_error:
            diagnostics.append(
                "actual-head inspection failed: " + str(inspection_error)
            )
        try:
            self._save(request, receipt)
        except Exception as save_error:
            diagnostics.append("recovery receipt write failed: " + str(save_error))
        message = "Sound publication requires exact recovery: " + str(error)
        if diagnostics:
            message += "; " + "; ".join(diagnostics)
        raise SoundApplicationError(
            message,
            receipt_ref=self.latest_receipt_ref,
            committed_heads=receipt["committedHeads"],
        ) from error

    def _clear_pending(self, receipt, reference):
        try:
            self.authoring._pending.unlink(missing_ok=True)
        except OSError as error:
            raise SoundApplicationError(
                "Sound publication committed; exact retry is required to clear its recovery marker: "
                + str(error),
                receipt_ref=reference,
                committed_heads=receipt["committedHeads"],
                publication_state="committed",
            ) from error

    def _commit_owners(self, request, receipt):
        for name, owner in OWNERS.items():
            receipt["committedHeads"] = self.authoring._actual_committed(receipt)
            if name in receipt["committedHeads"]:
                continue
            expected = request["expectedBasis"][name]
            if self.workspace.store(name).head_hash() != (
                None if expected is None else expected["sha256"]
            ):
                raise SoundPlanningError(
                    "Uncommitted sound target changed during recovery"
                )
            body = receipt["prepared"][name]
            owner(self.workspace).author(
                body["snapshot"],
                actor=request["actor"],
                reason=request["reason"],
                prepared=body,
            )
            receipt["committedHeads"] = self.authoring._actual_committed(receipt)
            self._save(request, receipt)

    def apply(self, request):
        request = _sound_document(request, "applyRequest")
        for name in OWNERS:
            authorize("sound", mutation=name)
        with timeline_writer(self.workspace.timeline_dir, recovery=True):
            known = self._known(request)
            self.authoring._guard_pending(request)
            marker = {
                "operationId": request["operationId"],
                "requestHash": content_hash(request),
            }
            with motion_application_access(self.workspace.timeline_dir, marker):
                if known and known[0]["state"] == "committed":
                    result = self._result(*known)
                    self._clear_pending(*known)
                    return result
                receipt = self._stage(request, known)
                atomic_write_json(self.authoring._pending, marker)
                return self._commit(request, receipt)

    def _stage(self, request, known):
        if known:
            receipt = known[0]
            actual = self.authoring._actual_committed(receipt)
            _, generation = self._basis(request, committed=actual)
            self._recovery_entries(receipt, generation)
            sources = self._source_refs(receipt["choices"], generation)
            if sources != receipt["sourceRefs"]:
                raise SoundPlanningError(
                    "Sound source admission changed during recovery"
                )
            if self.operation_absent:
                self._record_operation(request, receipt["requestRef"], known[1])
            return receipt
        receipt = self._prepare(request)
        request_ref = self._put("requests", request, "applyRequest")
        reference = self._save(request, receipt)
        self._record_operation(request, request_ref, reference)
        return receipt

    def _record_operation(self, request, request_ref, reference):
        record = {
            "requestHash": content_hash(request),
            "requestRef": request_ref,
            "initialReceiptRef": reference,
        }
        _sound_document(record, "applicationOperation")
        write_immutable_json(self._operation_path(request), record)

    @staticmethod
    def _recovery_entries(receipt, generation):
        entries = {entry["entryId"]: entry for entry in generation["entries"]}
        for choice in receipt["choices"]:
            entry = choice["sourceEntry"]
            if entry is not None and entries.get(entry["entryId"]) != entry:
                raise SoundPlanningError("Selected sound entry changed during recovery")


def apply_sound_request(planning, request):
    try:
        return _Application(planning).apply(request)
    except SoundApplicationError:
        raise
    except (ValueError, TypeError, KeyError, OSError, StoreError) as error:
        raise SoundPlanningError(str(error)) from error


__all__ = ["SoundApplicationError", "apply_sound_request"]
