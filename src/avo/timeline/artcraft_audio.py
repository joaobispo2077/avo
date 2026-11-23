"""Verify an explicitly placed, generated SoundCraft cue on the proof clock."""

from fractions import Fraction
from pathlib import Path

from avo.artcraft import (
    ArtCraftError,
    read_authoring_export,
    require_artcraft_export_environment,
)

from .artcraft_binding import require_artcraft_media_scope
from .contracts import content_hash, file_fingerprint, validate_document
from .event_clock import frame_range_to_samples
from .media_admission import FORBIDDEN_OUTPUT_CLASSES

_REF = "avo.artcraft.schema.json#/$defs/generatedAudioRef"
_PREFIX = "generated-audio:"
KIT_SOUND_SLOT = "sound-cue"


def resolve_generated_audio(reference):
    validate_document(reference, _REF)
    expected = reference["job"]
    path = Path(expected["locator"])
    if (
        not path.is_absolute()
        or path.resolve() != path
        or file_fingerprint(path) != expected
    ):
        raise ValueError("Generated audio job receipt changed or uses an alias")
    job, event = read_authoring_export(path, expected_head=reference["exportHead"])
    if (
        job["output"]["role"] != "generated-audio"
        or job["observation"]["app"] != "soundcraft"
    ):
        raise ValueError("Generated audio requires a verified SoundCraft cue export")
    require_artcraft_export_environment(job["observation"])
    return job, event


def require_generated_audio_layer(layer, *, workspace=None):
    source = layer["source"]
    if layer["role"] != "sfx" or "locator" not in source:
        raise ValueError("Generated audio must be placed on its own SFX layer")
    if (layer.get("provenance") or {}).get("soundSelection") is not None:
        raise ValueError("Generated audio conflicts with a separate sound selection")
    job, event = resolve_generated_audio(layer["generatedAudioRef"])
    if source != event["outputs"][0]:
        raise ValueError("Tracks generated audio differs from its verified export")
    if workspace is not None:
        require_artcraft_media_scope(workspace, job, "Generated audio")
    return job, event


def _region_samples(region, rate):
    ticks = region.get("timebase") or {"num": rate["den"], "den": rate["num"]}
    scale = Fraction(ticks["num"] * rate["num"], ticks["den"] * rate["den"])
    start, end = (scale * region[key] for key in ("startTicks", "endTicks"))
    if start.denominator != 1 or end.denominator != 1 or end <= start:
        raise ValueError(
            "Generated audio region must align to program frame boundaries"
        )
    return frame_range_to_samples(
        int(start), int(end), frame_rate_num=rate["num"], frame_rate_den=rate["den"]
    )


def select_kit_sound(workspace, instance, output):
    """Check one opt-in kit association against existing canonical cue placement."""
    selections = [
        item for item in instance["eventBindings"] if item["slot"] == KIT_SOUND_SLOT
    ]
    if not selections:
        return None
    if len(selections) != 1:
        raise ArtCraftError("Select one provider kit sound cue")
    selected = selections[0]
    tracks = _active_revision(workspace, "tracks")
    if tracks["contentHash"] != selected["revisionHash"]:
        raise ArtCraftError(
            "The selected provider kit sound cue uses a stale Tracks revision"
        )
    layer, region = _kit_sound_region(tracks["snapshot"], selected["eventId"])
    cue = _kit_picture_cue(workspace, instance["kitId"], region)
    job, event = require_generated_audio_layer(layer)
    _require_cue_scope(workspace, job, event)
    rate = output["frameRate"]
    start, end = _region_samples(
        region, {"num": rate["numerator"], "den": rate["denominator"]}
    )
    if end - start > event["audioEvidence"]["sampleCount"]:
        raise ArtCraftError(
            "The selected provider kit sound cue exceeds the verified export"
        )
    return {
        "tracksRevisionHash": tracks["contentHash"],
        "layerId": layer["layerId"],
        "regionId": region["regionId"],
        "cueId": cue["cueId"],
        "startSample": start,
        "endSampleExclusive": end,
        "generatedAudioRef": layer["generatedAudioRef"],
        "source": event["outputs"][0],
    }


def _active_revision(workspace, artifact):
    index = workspace.require_active(artifact)
    return workspace.store(artifact).revision(index["headRevisionId"])


def _kit_sound_region(snapshot, region_id):
    matches = [
        (layer, region)
        for layer in (snapshot.get("audioTracks") or {}).get("layers", [])
        for region in layer["regions"]
        if region["regionId"] == region_id
    ]
    if len(matches) != 1:
        raise ArtCraftError(
            "The selected provider kit sound cue region is missing or ambiguous"
        )
    ((layer, region),) = matches
    if layer.get("mute") or layer.get("generatedAudioRef") is None:
        raise ArtCraftError(
            "The selected provider kit sound cue needs an unmuted generated SFX layer"
        )
    return layer, region


def _kit_picture_cue(workspace, component_id, region):
    bmap = _active_revision(workspace, "bmap")["snapshot"]
    matches = [
        cue
        for cue in bmap["cues"]
        if cue["cueId"] in region.get("cueIds", [])
        and cue.get("componentRef") == component_id
    ]
    if len(matches) != 1:
        raise ArtCraftError(
            "The selected provider kit sound cue needs one BMap cue for its component"
        )
    return matches[0]


def _cue_placements(workspace, rate):
    tracks = workspace.store("tracks")
    index = tracks.load_index()
    if index["headRevisionId"] is None:
        return {}, set()
    snapshot = tracks.revision(index["headRevisionId"])["snapshot"]
    items, declared = {}, set()
    for layer in (snapshot.get("audioTracks") or {}).get("layers", []):
        reference = layer.get("generatedAudioRef")
        if reference is None:
            continue
        declared.add(layer["source"]["sha256"])
        if layer.get("mute", False):
            continue
        job, event = require_generated_audio_layer(layer)
        _require_cue_scope(workspace, job, event)
        digest = content_hash(reference)
        for region in layer["regions"]:
            start, end = _region_samples(region, rate)
            key = (digest, start, end)
            _require_nonoverlapping_cue(items, key, event["outputs"][0]["sha256"])
            items[key] = event
    return items, declared


def _require_nonoverlapping_cue(items, key, sha256):
    _, start, end = key
    if any(
        previous_start < end
        and start < previous_end
        and prior["outputs"][0]["sha256"] == sha256
        for (_, previous_start, previous_end), prior in items.items()
    ):
        raise ValueError("Duplicate or overlapping generated audio Tracks placement")


def _require_cue_scope(workspace, job, event):
    require_artcraft_media_scope(workspace, job, "Generated audio")
    source = job["inputs"][0]
    inputs = (source, event["outputs"][0])
    for item in inputs:
        _reject_forbidden_path(item["locator"])
    from .migration import inventory_historical_output_fingerprints

    known = inventory_historical_output_fingerprints(
        workspace.raw_dir,
        timeline_dir=workspace.timeline_dir,
        candidate_sizes=frozenset(item["sizeBytes"] for item in inputs),
    )
    protected = {
        item["sha256"] for item in known if item["role"] in FORBIDDEN_OUTPUT_CLASSES
    }
    if any(item["sha256"] in protected for item in inputs):
        raise ValueError("Generated audio depends on prohibited proof output ancestry")


def _reject_forbidden_path(locator):
    if FORBIDDEN_OUTPUT_CLASSES.intersection(
        part.casefold() for part in Path(locator).parts
    ):
        raise ValueError(f"Generated audio has prohibited proof ancestry: {locator}")


def _verified_trim(event, source, node):
    expected = event["outputs"][0]
    descriptor = {
        "locator": expected["locator"],
        "sha256": expected["sha256"],
        "mediaClass": "generated-asset",
        "streamIndex": 0,
        "ancestry": [],
    }
    if source != descriptor:
        raise ValueError("Generated audio trim misstates its source or provenance")
    sample_range = node["sourceRange"]
    if (
        node["kind"] != "sfx"
        or node["sourceSampleRate"] != 48000
        or node["sourceLayout"] != "stereo"
        or sample_range["endSampleExclusive"] > event["audioEvidence"]["sampleCount"]
    ):
        raise ValueError("Generated audio trim exceeds its isolated PCM contract")
    output = node["outputRange"]
    length = sample_range["endSampleExclusive"] - sample_range["startSample"]
    if length <= 0 or length != output["endSampleExclusive"] - output["startSample"]:
        raise ValueError("Generated audio trim must preserve its exact sample duration")
    return expected


def lock_generated_audio(workspace, execution, *, require_applied):
    """Freeze exact cue receipts after canonical sound compilation."""
    graph = execution["audioGraph"]
    trims = [op["parameters"] for op in graph["operations"] if op["kind"] == "trim"]
    references = [item for item in trims if item.get("generatedAudioRef") is not None]
    lock = execution["canonicalInputLock"]
    if execution.get("checkpoint") == "cut-proof" or "tracks" not in lock:
        if references or any(key.startswith(_PREFIX) for key in lock):
            raise ValueError("Generated audio requires current sound-enabled Tracks")
        return execution
    placements, declared = _cue_placements(workspace, execution["output"]["frameRate"])
    _require_unaliased_trims(trims, declared)
    frozen = _receipt_locks(references, graph, placements)
    _apply_receipt_locks(lock, frozen, require_applied)
    return execution


def _apply_receipt_locks(lock, frozen, require_applied):
    if require_applied:
        existing = {key for key in lock if key.startswith(_PREFIX)}
        if frozen != {key: lock.get(key) for key in frozen.keys() | existing}:
            raise ValueError("Proof generated audio receipt lock changed")
        return
    if any(key in lock and lock[key] != value for key, value in frozen.items()):
        raise ValueError("Generated audio conflicts with a locked input identity")
    lock.update(frozen)


def _require_unaliased_trims(trims, declared):
    if any(
        item.get("generatedAudioRef") is None
        and (item.get("source") or {}).get("sha256") in declared
        for item in trims
    ):
        raise ValueError("Proof cannot relabel generated audio as original media")


def _receipt_locks(references, graph, placements):
    nodes = {node["nodeId"]: node for node in graph["nodes"]}
    result = {}
    for item in references:
        reference = item["generatedAudioRef"]
        node = nodes[item["nodeId"]]
        output = node["outputRange"]
        key = (
            content_hash(reference),
            output["startSample"],
            output["endSampleExclusive"],
        )
        event = placements.pop(key, None)
        if event is None:
            raise ValueError(
                "Generated audio trim is duplicated or has no exact Tracks placement"
            )
        source = _verified_trim(event, item["source"], node)
        source_id = "artcraft-audio-" + key[0][:24]
        if item["sourceId"] != source_id:
            raise ValueError(
                "Generated audio trim requires its exact receipt source ID"
            )
        result["source:" + source_id] = source["sha256"]
        result[_PREFIX + source_id] = key[0]
    if placements:
        raise ValueError("Proof omits a selected generated audio Tracks placement")
    return result


def resolve_generated_audio_trim(parameters, lock, node):
    reference = parameters["generatedAudioRef"]
    source_id = parameters["sourceId"]
    digest = content_hash(reference)
    if (
        source_id != "artcraft-audio-" + digest[:24]
        or lock.get(_PREFIX + source_id) != digest
    ):
        raise ValueError("Generated audio proof receipt is unlocked")
    _, event = resolve_generated_audio(reference)
    expected = _verified_trim(event, parameters["source"], node)
    if lock.get("source:" + source_id) != expected["sha256"]:
        raise ValueError("Generated audio proof fingerprint changed")
    _reject_forbidden_path(expected["locator"])
    return expected
