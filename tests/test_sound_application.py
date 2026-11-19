"""Explicit sound application publishes through current canonical owners only."""

from copy import deepcopy

import pytest

from avo.editing_craft import resolve_editing_craft_selection
from avo.timeline.contracts import file_fingerprint
from avo.timeline.sound_planning import SoundPlanningError, SoundPlanningService
from tests.test_sfx_catalog import annotate, scan
from tests.test_sound_proposals import prepared


class SourceProbe:
    def __init__(self):
        self.calls = []

    def __call__(self, path, *, expected_sha256):
        self.calls.append(path)
        assert file_fingerprint(path)["sha256"] == expected_sha256
        return {
            "sourceSha256": expected_sha256,
            "streamIndex": 0,
            "sampleRate": 48000,
            "channels": 2,
        }


def application(tmp_path):
    workspace, catalogue, propose = prepared(tmp_path)
    generation = catalogue.show()
    generation = annotate(
        catalogue,
        generation["generationId"],
        generation["entries"][0]["entryId"],
        {"marker": {"sample": 1200, "reviewerRef": "fixture-marker-review"}},
    )
    propose["expectedGeneration"] = generation["generationId"]
    probe = SourceProbe()
    service = SoundPlanningService(workspace, catalogue=catalogue, source_probe=probe)
    shown = service.propose(propose)
    event = shown["proposal"]["opportunities"][0]["opportunity"]
    request = {
        "contractVersion": "1.0.0",
        "operation": "apply",
        "operationId": "sound-apply-first",
        "actor": "creator",
        "reason": "Select one reviewed comparison accent",
        "proposalHash": shown["proposalRef"]["sha256"],
        "expectedBasis": shown["proposal"]["basisHeads"],
        "expectedGeneration": generation["generationId"],
        "choices": [
            {
                "eventId": event["eventId"],
                "entryId": generation["entries"][0]["entryId"],
                "trimRange": {"startSample": 0, "endSampleExclusive": 24000},
                "mix": {
                    "sourceLayout": "stereo",
                    "targetLayout": "stereo",
                    "channelMap": [0, 1],
                    "gainDb": -12,
                    "peakCeilingDbfs": -3,
                    "fadeInSamples": 0,
                    "fadeOutSamples": 0,
                    "ducking": None,
                },
            }
        ],
        "contexts": [
            {
                "cueId": event["cueId"],
                "role": "authored-graphic",
                "orderedEventIds": [],
                "syntheticEffectApproved": False,
            }
        ],
    }
    return workspace, catalogue, service, probe, request, shown


def test_sound_application_binds_current_source_and_preserves_original_picture(
    tmp_path,
):
    workspace, _, service, probe, request, shown = application(tmp_path)
    original = workspace.store("bmap").load()["revisions"][-1]["snapshot"]["cues"][0]
    result = service.apply(request)
    assert result["status"] == "applied"
    assert result["receipt"]["state"] == "committed"
    assert set(result["committedHeads"]) == {"bmap", "tracks"}
    assert (
        workspace.store("cmap").head_hash()
        == shown["proposal"]["basisHeads"]["cmap"]["sha256"]
    )
    cues = workspace.store("bmap").load()["revisions"][-1]["snapshot"]["cues"]
    assert next(c for c in cues if c["cueId"] == original["cueId"]) == original
    assert len([c for c in cues if c["kind"] == "sfx"]) == 1
    store = workspace.store("tracks")
    layer = store.load()["revisions"][-1]["snapshot"]["audioTracks"]["layers"][0]
    selected = layer["provenance"]["soundSelection"]
    assert selected["choice"]["fit"]["status"] == "fit"
    assert selected["sourceRef"]["streamIndex"] == 0
    assert selected["sourceRef"]["sha256"] == layer["source"]["sha256"]
    assert store.load_index()["requiredReaderCapabilities"] == ["sound-selection-v1"]
    assert result["acceptance"] == "pending-listening"
    assert len(probe.calls) == 1


@pytest.mark.parametrize("problem", ["head", "generation", "source", "probe"])
def test_invalid_sound_application_has_no_publication_side_effects(tmp_path, problem):
    workspace, catalogue, service, _, request, _ = application(tmp_path)
    if problem == "head":
        request["expectedBasis"]["bmap"]["sha256"] = "f" * 64
    elif problem == "generation":
        request["expectedGeneration"] = "f" * 64
    elif problem == "source":
        (catalogue.roots["test"] / "whoosh.wav").write_bytes(b"changed source")
    else:
        service.source_probe = None
    before = {p: p.read_bytes() for p in workspace.raw_dir.rglob("*") if p.is_file()}
    with pytest.raises(SoundPlanningError):
        service.apply(request)
    assert {
        p: p.read_bytes() for p in workspace.raw_dir.rglob("*") if p.is_file()
    } == before


def test_identical_sound_apply_replay_never_creates_duplicate_contributions(
    tmp_path, monkeypatch
):
    from avo.timeline.tracks import TracksService

    workspace, catalogue, service, _, request, _ = application(tmp_path)
    first = service.apply(request)

    def forbidden(*args, **kwargs):
        pytest.fail("Completed sound replay repeated source work or publication")

    monkeypatch.setattr(TracksService, "author", forbidden)
    replay = SoundPlanningService(
        workspace, catalogue=catalogue, source_probe=forbidden
    ).apply(request)
    assert replay["committedHeads"] == first["committedHeads"]
    assert replay["receiptRef"] == first["receiptRef"]
    assert len(workspace.store("tracks").load_index()["revisionRefs"]) == 1
    changed = deepcopy(request)
    changed["reason"] = "Different inputs require a different operation"
    with pytest.raises(SoundPlanningError):
        service.apply(changed)


def test_interrupted_sound_publication_resumes_in_a_new_service_without_duplicate_heads(
    tmp_path, monkeypatch
):
    from avo.timeline.tracks import TracksService

    workspace, catalogue, service, probe, request, _ = application(tmp_path)
    original = TracksService.author

    def unavailable(*args, **kwargs):
        raise OSError("fixture interrupted Tracks write")

    monkeypatch.setattr(TracksService, "author", unavailable)
    with pytest.raises(SoundPlanningError, match="recovery"):
        service.apply(request)
    assert len(workspace.store("bmap").load_index()["revisionRefs"]) == 2
    assert workspace.store("tracks").load_index()["headRevisionId"] is None
    assert service.authoring._pending.is_file()
    monkeypatch.setattr(TracksService, "author", original)
    result = SoundPlanningService(
        workspace, catalogue=catalogue, source_probe=probe
    ).apply(request)
    assert result["receipt"]["state"] == "committed"
    assert len(workspace.store("bmap").load_index()["revisionRefs"]) == 2
    assert len(workspace.store("tracks").load_index()["revisionRefs"]) == 1
    assert not service.authoring._pending.exists()


def repropose(service, request, *, identity="sound-next", intents=None):
    from avo.timeline.motion_review import MotionReviewService
    from tests.test_sound_opportunities import intent

    proposal = service.propose(
        {
            "contractVersion": "1.0.0",
            "operation": "propose",
            "operationId": identity,
            "actor": request["actor"],
            "reason": request["reason"],
            "expectedBasis": MotionReviewService(service.workspace).project()[
                "basisHeads"
            ],
            "expectedGeneration": request["expectedGeneration"],
            "selection": resolve_editing_craft_selection(),
            "clock": {
                "frameRate": {"num": 24, "den": 1},
                "sampleRate": 48000,
                "programEndFrame": 24,
            },
            "intents": [intent()] if intents is None else intents,
        }
    )
    result = deepcopy(request)
    result.update(
        operationId=identity + "-apply",
        proposalHash=proposal["proposalRef"]["sha256"],
        expectedBasis=proposal["proposal"]["basisHeads"],
    )
    return result


def test_per_event_level_then_silence_preserves_the_visual_and_original_cmap(tmp_path):
    workspace, _, service, probe, request, shown = application(tmp_path)
    first = service.apply(request)
    layer_before = workspace.store("tracks").load()["revisions"][-1]["snapshot"][
        "audioTracks"
    ]["layers"][0]
    changed = repropose(service, request)
    changed["choices"][0]["mix"]["gainDb"] = -18
    result = service.apply(changed)
    layer_after = workspace.store("tracks").load()["revisions"][-1]["snapshot"][
        "audioTracks"
    ]["layers"][0]
    assert layer_after["layerId"] == layer_before["layerId"]
    assert layer_after["regions"] == layer_before["regions"]
    assert layer_after["gainDb"] == -18
    assert result["changes"][0]["before"]["gainDb"] == -12
    assert result["changes"][0]["after"]["gainDb"] == -18
    silence = repropose(service, changed, identity="sound-silence")
    silence["choices"][0].update(entryId=None, trimRange=None, mix=None)
    count = len(probe.calls)
    service.apply(silence)
    assert len(probe.calls) == count
    assert not workspace.store("tracks").load()["revisions"][-1]["snapshot"][
        "audioTracks"
    ]["layers"]
    assert [
        c["kind"]
        for c in workspace.store("bmap").load()["revisions"][-1]["snapshot"]["cues"]
    ] == ["text"]
    assert (
        workspace.store("cmap").head_hash()
        == shown["proposal"]["basisHeads"]["cmap"]["sha256"]
    )
    replay = service.apply(request)
    assert replay["committedHeads"] == first["committedHeads"]
    assert replay["headsCurrent"] is False


def test_replacing_and_retiming_a_sound_reports_both_listening_ranges(tmp_path):
    from tests.test_sound_opportunities import intent

    workspace, catalogue, service, _, request, _ = application(tmp_path)
    first = service.apply(request)
    (catalogue.roots["test"] / "alternate.wav").write_bytes(b"alternate sound fixture")
    generation = scan(catalogue, expected=request["expectedGeneration"])
    replacement = next(
        entry
        for entry in generation["entries"]
        if entry["relativePath"] == "alternate.wav"
    )
    generation = annotate(
        catalogue,
        generation["generationId"],
        replacement["entryId"],
        {
            "rights": {
                "status": "licensed",
                "license": "fixture",
                "evidenceRef": "rights-fixture",
            },
            "marker": {"sample": 2400, "reviewerRef": "fixture-review"},
        },
    )
    current = repropose(
        service,
        {**request, "expectedGeneration": generation["generationId"]},
        intents=[intent(phase=0.75)],
    )
    current["choices"][0]["entryId"] = replacement["entryId"]
    result = service.apply(current)
    (change,) = result["changes"]
    assert change["before"]["entryId"] == request["choices"][0]["entryId"]
    assert change["after"]["entryId"] == replacement["entryId"]
    assert change["listeningRanges"] == {
        "before": {
            "sampleRate": 48000,
            "startSample": 10800,
            "endSampleExclusive": 34800,
        },
        "after": {
            "sampleRate": 48000,
            "startSample": 11600,
            "endSampleExclusive": 35600,
        },
    }
    old_bmap = first["receipt"]["prepared"]["bmap"]["snapshot"]["cues"]
    new_bmap = result["receipt"]["prepared"]["bmap"]["snapshot"]["cues"]
    old_visual, old_sound = old_bmap
    new_visual, new_sound = new_bmap
    assert new_visual == old_visual
    assert new_sound["cueId"] == old_sound["cueId"]
    assert new_sound["targetLayerId"] == old_sound["targetLayerId"]
    assert result["acceptance"] == "pending-listening"
    assert (
        workspace.store("tracks").head_hash()
        == result["committedHeads"]["tracks"]["sha256"]
    )
    assert service.apply(current)["changes"] == result["changes"]


def test_partial_sound_recovery_rejects_changed_rights(tmp_path, monkeypatch):
    from avo.timeline.tracks import TracksService

    _, catalogue, service, _, request, _ = application(tmp_path)
    author = TracksService.author
    monkeypatch.setattr(
        TracksService,
        "author",
        lambda *a, **k: (_ for _ in ()).throw(OSError("interrupted")),
    )
    with pytest.raises(SoundPlanningError, match="recovery"):
        service.apply(request)
    entry = catalogue.show()["entries"][0]
    annotate(
        catalogue,
        request["expectedGeneration"],
        entry["entryId"],
        {"rights": {"status": "unknown", "license": None, "evidenceRef": None}},
    )
    monkeypatch.setattr(TracksService, "author", author)
    with pytest.raises(SoundPlanningError, match="catalogue generation changed"):
        service.apply(request)
    assert service.authoring._pending.is_file()


def test_resealed_receipt_cannot_change_the_prepared_recipe(tmp_path):
    from avo.timeline.sound_application import _Application
    from avo.timeline.store import atomic_write_json

    _, _, service, _, request, _ = application(tmp_path)
    result = service.apply(request)
    internal = _Application(service)
    receipt = deepcopy(result["receipt"])
    receipt["advisories"] = [{"code": "forged receipt"}]
    ref = internal._put("receipts", receipt, "applicationReceipt")
    atomic_write_json(internal._operation_path(request, "applications"), ref)
    with pytest.raises(SoundPlanningError, match="recipe"):
        service.apply(request)


def test_staging_interruption_before_operation_record_can_resume_exactly(
    tmp_path, monkeypatch
):
    from avo.timeline import sound_application

    workspace, catalogue, service, probe, request, _ = application(tmp_path)
    write = sound_application.write_immutable_json

    def interrupted(path, value):
        if path.parent.name == "operations":
            raise OSError("fixture interrupted staged operation record")
        return write(path, value)

    monkeypatch.setattr(sound_application, "write_immutable_json", interrupted)
    with pytest.raises(SoundPlanningError, match="staged operation"):
        service.apply(request)
    assert workspace.store("tracks").load_index()["headRevisionId"] is None
    from avo.timeline.motion_retention import retained_motion_paths

    assert any(
        path.parent.name == "receipts" for path in retained_motion_paths(workspace)
    )
    monkeypatch.setattr(sound_application, "write_immutable_json", write)
    resumed = SoundPlanningService(workspace, catalogue=catalogue, source_probe=probe)
    first = resumed.apply(request)
    assert resumed.apply(request)["receiptRef"] == first["receiptRef"]
