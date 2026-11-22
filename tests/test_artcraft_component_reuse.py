"""Native provider copies retain their exact source and version per video."""

import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from avo.timeline.component_instances import (
    ComponentInstanceError,
    ComponentInstanceService,
)
from avo.timeline.contracts import content_hash, file_fingerprint
from avo.timeline.provider_animation import ProviderAnimationService
from tests.artcraft_fixtures import picture_output
from tests.test_artcraft_provider_packages import (
    _native_pattern,
    _observe_fixture,
    _package_from_retained_source,
)


@pytest.fixture
def native_library(tmp_path):
    return _published_native_library(
        tmp_path, "first-channel", b"\x00\xffeditable-provider-file"
    )


def _published_native_library(tmp_path, provider, source_bytes, *, share_with=()):
    from avo.artcraft import seal_record

    source = tmp_path / "native-source"
    source.mkdir(parents=True)
    native = source / "component.anicraft"
    native.write_bytes(source_bytes)
    (source / "recipe.json").write_text("{}", encoding="utf-8")
    package = _package_from_retained_source(
        native, picture_output(), {"primaryText": "Fixture", "font": "Arial"}
    )
    if share_with:
        rights = source / package["rightsRef"]
        entries = json.loads(rights.read_text(encoding="utf-8"))
        entries[0]["sharing"] = {
            "providers": list(share_with),
            "evidenceRef": "fixture-license",
        }
        rights.write_text(json.dumps(entries), encoding="utf-8")
        fingerprint = file_fingerprint(rights)
        manifest_entry = next(
            item for item in package["files"] if item["path"] == rights.name
        )
        manifest_entry.update(
            {key: fingerprint[key] for key in ("sha256", "sizeBytes")}
        )
    if package["provider"] != provider or share_with:
        package = seal_record(
            "package",
            {
                **{
                    key: value for key, value in package.items() if key != "packageHash"
                },
                "provider": provider,
            },
        )
    store = tmp_path / "native-store"
    store.mkdir()
    service = ProviderAnimationService(
        tmp_path / "catalog" / "library.json", provider=provider
    )
    pattern = _native_pattern()
    for key in ("nativePackage", "provenance", "promotionEventId"):
        del pattern[key]
    source_options = {
        "package": package,
        "source_root": source,
        "source_observer": _observe_fixture,
    }
    proposal = service.propose_native_package(
        pattern,
        actor="creator-fixture",
        intent_reference="design",
        **source_options,
    )
    event = service.publish_native_package(
        proposal["path"],
        native_store=store,
        actor="creator-fixture",
        reason="fixture",
        expected_catalog_sha256=content_hash(service.initialize()),
        **source_options,
    )
    return service, store, event["manifestSha256"], native


def _video_components(directory, provider="first-channel"):
    directory.mkdir()
    return ComponentInstanceService(
        SimpleNamespace(
            raw_dir=directory,
            timeline_dir=directory / "edit" / "timeline",
            project={"provider": provider},
        )
    )


def _resolve(
    service,
    library,
    *,
    text="Sample label",
    instance_id="speaker-first-use",
    **overrides,
):
    catalog, store, manifest_hash, _ = library
    options = {
        "catalog_path": catalog.path,
        "native_store": store,
        "kit_id": "speaker-label",
        "version": "1.0.0",
        "manifest_hash": manifest_hash,
        "instance_id": instance_id,
        "parameters": {"primaryText": text},
        "asset_bindings": [],
        "event_bindings": [],
        "safe_area_bindings": {"faces": [], "captions": [], "evidence": [], "ui": []},
        "source_observer": _observe_fixture,
    }
    return service.resolve_native_provider_kit(**{**options, **overrides})


def test_pinned_native_instances_copy_owned_source_and_keep_parameter_revisions_isolated(
    tmp_path, native_library
):
    first = _video_components(tmp_path / "first-video")
    second = _video_components(tmp_path / "second-video")
    original = native_library[3]
    trusted_bytes = original.read_bytes()
    original.write_bytes(b"revised private draft")
    one = _resolve(first, native_library, text="Clara")
    two = _resolve(second, native_library, text="Mar\u00eda")
    assert one["nativePackage"] == two["nativePackage"]
    assert one["instanceHash"] != two["instanceHash"]
    assert one["parameters"] == {"primaryText": "Clara", "font": "Arial"}
    for item in (one, two):
        native = next(
            Path(ref["path"])
            for ref in item["generatedFiles"]
            if ref["path"].endswith(".anicraft")
        )
        assert native.read_bytes() == trusted_bytes
    assert _resolve(first, native_library, text="Clara") == one
    with pytest.raises(ComponentInstanceError, match="immutable instance"):
        _resolve(first, native_library, text="Different label")
    assert first.load(one["instanceId"]) == one
    with pytest.raises(ComponentInstanceError, match="ArtCraft proof"):
        first.implementation_reference(one["instanceId"], adapter_id="hyperframes")


def test_same_named_native_kits_resolve_within_their_approved_provider(
    tmp_path, native_library
):
    first = _video_components(tmp_path / "first-channel-video")
    other = _video_components(
        tmp_path / "second-channel-video", provider="other-channel"
    )
    other_library = _published_native_library(
        tmp_path / "other-library", "other-channel", b"\x00\xffanother-author-native"
    )
    first_pin = _resolve(first, native_library)
    other_pin = _resolve(other, other_library)
    assert (first_pin["kitId"], first_pin["kitVersion"]) == (
        other_pin["kitId"],
        other_pin["kitVersion"],
    )
    assert first_pin["nativePackage"]["provider"] == "first-channel"
    assert other_pin["nativePackage"]["provider"] == "other-channel"
    assert (
        first_pin["nativePackage"]["packageHash"]
        != other_pin["nativePackage"]["packageHash"]
    )
    with pytest.raises(ComponentInstanceError, match="another provider"):
        _resolve(first, other_library, instance_id="foreign-version")
    with pytest.raises(ComponentInstanceError, match="manifest hash"):
        _resolve(
            first,
            native_library,
            instance_id="foreign-hash",
            manifest_hash=other_library[2],
        )
    assert not first.path("foreign-version").exists()
    assert not first.path("foreign-hash").exists()


def test_cross_provider_pin_requires_explicit_origin_and_fingerprinted_rights(tmp_path):
    from avo.artcraft import ArtCraftError
    from avo.timeline.artcraft_packages import retained_native_instance_files

    shared = _published_native_library(
        tmp_path / "original",
        "first-channel",
        b"published native bytes",
        share_with=("second-channel",),
    )
    recipient = _video_components(tmp_path / "recipient", provider="second-channel")
    outsider = _video_components(tmp_path / "outsider", provider="third-channel")
    with pytest.raises(ComponentInstanceError, match="provider"):
        _resolve(recipient, shared)
    with pytest.raises(ComponentInstanceError, match="sharing rights"):
        _resolve(outsider, shared, source_provider="first-channel")
    assert not outsider.directory.exists()

    instance = _resolve(recipient, shared, source_provider="first-channel")
    assert instance["nativePackage"]["provider"] == "first-channel"
    assert instance["nativePackage"]["sharedWith"] == "second-channel"
    assert instance["reviewRefs"] == []
    assert _resolve(recipient, shared, source_provider="first-channel") == instance
    retained = retained_native_instance_files(
        instance, recipient.workspace.raw_dir, "second-channel"
    )
    rights = next(
        Path(item["locator"])
        for item in retained
        if item["locator"].endswith("rights.json")
    )
    assert json.loads(rights.read_bytes())[0]["sharing"]["providers"] == [
        "second-channel"
    ]
    assert _resolve(_video_components(tmp_path / "original-project"), shared)[
        "nativePackage"
    ] == {
        key: value
        for key, value in instance["nativePackage"].items()
        if key != "sharedWith"
    }
    with pytest.raises(ArtCraftError, match="pinned video instance"):
        retained_native_instance_files(
            instance, recipient.workspace.raw_dir, "third-channel"
        )
    rights.write_bytes(rights.read_bytes() + b"\n")
    with pytest.raises(ArtCraftError, match="source has changed"):
        retained_native_instance_files(
            instance, recipient.workspace.raw_dir, "second-channel"
        )


def test_provider_package_rejects_wildcard_sharing(tmp_path):
    from avo.artcraft import ArtCraftError

    with pytest.raises(ArtCraftError, match="exact provider names"):
        _published_native_library(
            tmp_path, "first-channel", b"test fixture", share_with=("*",)
        )


def test_reuse_refuses_wrong_provider_manifest_and_unbounded_parameters(
    tmp_path, native_library
):
    other = _video_components(tmp_path / "other-video", provider="other-channel")
    with pytest.raises(ComponentInstanceError, match="another provider"):
        _resolve(other, native_library)
    own = _video_components(tmp_path / "already-owned-video")
    with pytest.raises(ComponentInstanceError, match="manifest hash"):
        _resolve(own, native_library, manifest_hash="f" * 64)
    bounds = {"primaryText": "speaking" * 90}
    with pytest.raises(ComponentInstanceError, match="parameter contract"):
        _resolve(own, native_library, parameters=deepcopy(bounds))
    with pytest.raises(ComponentInstanceError, match="reviewed with this font"):
        _resolve(
            own, native_library, parameters={"primaryText": "Sample", "font": "Other"}
        )
    with pytest.raises(ComponentInstanceError, match="nonempty lower-third label"):
        _resolve(own, native_library, parameters={"primaryText": " "})
    assert not own.path("speaker-first-use").exists()


def _observe_with_bounds(path, contract, parameters, *, max_bytes):
    return {
        **_observe_fixture(path, contract, parameters, max_bytes=max_bytes),
        "occupiedBounds": (20, 800, 800, 980),
    }


@pytest.mark.parametrize(
    ("category", "region", "message"),
    [
        ("faces", {"x": 22, "y": 810, "width": 20, "height": 20}, "overlaps"),
        ("captions", {"x": 0, "y": 970, "width": 200, "height": 30}, "overlaps"),
        ("evidence", {"x": 1900, "y": 0, "width": 21, "height": 20}, "outside"),
        ("ui", {"x": False, "y": 0, "width": 20, "height": 20}, "pixel rectangle"),
        ("ui", {"x": 0, "y": 0, "width": 0, "height": 20}, "pixel rectangle"),
    ],
)
def test_native_kit_rejects_invalid_or_covered_protected_regions(
    tmp_path, native_library, category, region, message
):
    service = _video_components(tmp_path / "protected-video")
    protected = {key: [] for key in ("faces", "captions", "evidence", "ui")}
    protected[category] = [region]
    with pytest.raises(ComponentInstanceError, match=message):
        _resolve(
            service,
            native_library,
            safe_area_bindings=protected,
            source_observer=_observe_with_bounds,
        )
    assert not service.path("speaker-first-use").exists()
    assert not (service.workspace.raw_dir / "edit/derived/provider-components").exists()


def test_native_kit_pins_protected_regions_only_with_inspected_clearance(
    tmp_path, native_library
):
    service = _video_components(tmp_path / "clearance-video")
    reserved = {
        "faces": [{"x": 20, "y": 0, "width": 20, "height": 800}],
        "captions": [{"x": 0, "y": 980, "width": 1920, "height": 100}],
        "evidence": [],
        "ui": [],
    }
    with pytest.raises(ComponentInstanceError, match="inspected overlay bounds"):
        _resolve(service, native_library, safe_area_bindings=reserved)
    instance = _resolve(
        service,
        native_library,
        safe_area_bindings=reserved,
        source_observer=_observe_with_bounds,
    )
    assert instance["safeAreaBindings"] == reserved


def _sound_selection(service, monkeypatch, *, track_hash, component="speaker-label"):
    from avo.timeline import artcraft_audio

    reference = {"job": {"sha256": "b" * 64}, "exportHead": "c" * 64}
    source = {"sha256": "d" * 64, "locator": "selected-cue.wav", "sizeBytes": 48}
    region = {
        "regionId": "label-sound",
        "cueIds": ["speaker-cue"],
        "startTicks": 0,
        "endTicks": 30,
        "timebase": {"num": 1001, "den": 24000},
    }
    layer = {
        "layerId": "sound-layer",
        "role": "sfx",
        "generatedAudioRef": reference,
        "source": source,
        "regions": [region],
    }
    revisions = {
        "tracks": {
            "contentHash": track_hash,
            "snapshot": {"audioTracks": {"layers": [layer]}},
        },
        "bmap": {
            "snapshot": {"cues": [{"cueId": "speaker-cue", "componentRef": component}]}
        },
    }
    service.workspace.require_active = lambda name: {"headRevisionId": name}
    service.workspace.store = lambda name: SimpleNamespace(
        revision=lambda revision_id: revisions[revision_id]
    )
    monkeypatch.setattr(
        artcraft_audio,
        "require_generated_audio_layer",
        lambda selected: (
            {},
            {"outputs": [selected["source"]], "audioEvidence": {"sampleCount": 96_000}},
        ),
    )
    monkeypatch.setattr(artcraft_audio, "_require_cue_scope", lambda *_: None)
    return layer, region


@pytest.mark.parametrize(
    "fault", [None, "stale", "muted", "unlinked", "wrong-component", "duplicate"]
)
def test_native_kit_pins_only_a_current_sound_region_for_its_picture_cue(
    tmp_path, native_library, monkeypatch, fault
):
    service = _video_components(tmp_path / "sound-video")
    track_hash = "a" * 64
    layer, region = _sound_selection(
        service,
        monkeypatch,
        track_hash=track_hash,
        component="other-label" if fault == "wrong-component" else "speaker-label",
    )
    binding = {
        "slot": "sound-cue",
        "eventId": "label-sound",
        "revisionHash": track_hash,
    }
    if fault == "stale":
        binding["revisionHash"] = "f" * 64
    if fault == "muted":
        layer["mute"] = True
    if fault == "unlinked":
        region["cueIds"] = []
    if fault == "duplicate":
        layer["regions"].append(deepcopy(region))
    if fault:
        with pytest.raises(ComponentInstanceError, match="sound cue"):
            _resolve(service, native_library, event_bindings=[binding])
        assert not service.path("speaker-first-use").exists()
    else:
        result = _resolve(service, native_library, event_bindings=[binding])
        assert result["eventBindings"] == [binding]


@pytest.mark.parametrize("change", [None, "wrong-cue", "stale-tracks", "starts-after"])
def test_pinned_kit_proof_checks_the_sound_cue_against_picture_placement(
    tmp_path, native_library, monkeypatch, change
):
    from avo.artcraft import ArtCraftError
    from avo.timeline.artcraft_binding import _pinned_kit_sound

    service = _video_components(tmp_path / "sound-proof")
    track_hash = "a" * 64
    _, audio_region = _sound_selection(service, monkeypatch, track_hash=track_hash)
    instance = _resolve(
        service,
        native_library,
        event_bindings=[
            {"slot": "sound-cue", "eventId": "label-sound", "revisionHash": track_hash}
        ],
    )
    job = {
        "artworkRef": {key: instance[key] for key in ("instanceId", "instanceHash")},
        "output": picture_output(),
        "roots": {"read": [str(service.workspace.raw_dir)]},
    }
    placement = {
        "cueId": "different-cue" if change == "wrong-cue" else "speaker-cue",
        "range": {"startFrame": 0, "endFrameExclusive": 72},
    }
    heads = {"tracks": "b" * 64 if change == "stale-tracks" else track_hash}
    if change == "starts-after":
        audio_region.update(startTicks=72, endTicks=101)

    if change:
        with pytest.raises(ArtCraftError, match="start during its BMap placement"):
            _pinned_kit_sound(service.workspace, job, placement, heads)
    else:
        bound = _pinned_kit_sound(service.workspace, job, placement, heads)
        assert bound["regionId"] == "label-sound"
        assert bound["startSample"] == 0
        assert bound["source"]["sha256"] == "d" * 64


@pytest.mark.parametrize(
    "fault", [None, "wrong-source", "wrong-output", "outside-roots"]
)
def test_plain_kit_proof_selects_exact_native_package_without_artwork(
    tmp_path, native_library, fault
):
    from avo.artcraft import ArtCraftError
    from avo.timeline.artcraft_binding import _explicit_kit_source

    service = _video_components(tmp_path / "plain-proof")
    instance = _resolve(service, native_library)
    kept = next(
        item
        for item in instance["generatedFiles"]
        if item["path"].endswith(".anicraft")
    )
    original = file_fingerprint(Path(kept["path"]))
    ref = {key: instance[key] for key in ("instanceId", "instanceHash")}
    owned = service.workspace.raw_dir
    job = {
        "documentState": "saved",
        "request": {"componentId": "speaker-label", "provider": "first-channel"},
        "authoringParameters": instance["parameters"],
        "output": picture_output(),
        "inputs": [original],
        "roots": {"read": [str(owned)]},
    }
    if fault == "wrong-source":
        job["inputs"] = [file_fingerprint(native_library[3])]
    elif fault == "wrong-output":
        job["output"] = picture_output(width=1080, height=1920)
    elif fault == "outside-roots":
        job["roots"]["read"] = [str(Path(kept["path"]).parent)]
    source = {"inputSources": job["inputs"]}
    if fault:
        with pytest.raises(ArtCraftError, match="kit.*(differs|read roots)"):
            _explicit_kit_source(service.workspace, job, ref, source)
    else:
        assert _explicit_kit_source(service.workspace, job, ref, source) == instance
        assert source["kitInstanceRef"] == ref
        inputs = source["inputSources"]
        assert inputs[0] == original
        assert any(
            x["locator"] == str(service.path(instance["instanceId"])) for x in inputs
        )
        assert any(Path(x["locator"]).name == "manifest.json" for x in inputs)
        assert len({item["locator"] for item in inputs}) == len(inputs)


def test_native_instance_applies_an_approved_secondary_slot_default(tmp_path):
    service = _video_components(tmp_path / "second-line-video")
    evidence = {
        "fixtureParameters": {
            "primaryText": "Clara",
            "font": "Arial",
            "secondaryText": "Producer",
        },
        "parameterSchema": {
            "type": "object",
            "properties": {
                "primaryText": {"type": "string"},
                "secondaryText": {"type": "string", "maxLength": 48},
            },
            "additionalProperties": False,
        },
    }
    assert service._native_instance_parameters({"primaryText": "Carlos"}, evidence) == {
        "primaryText": "Carlos",
        "font": "Arial",
        "secondaryText": "Producer",
    }
    with pytest.raises(
        ComponentInstanceError, match="nonempty secondary lower-third label"
    ):
        service._native_instance_parameters({"secondaryText": " "}, evidence)


def test_provider_pin_uses_the_reviewed_motion_variant(tmp_path):
    service = _video_components(tmp_path / "fixed-hold")
    evidence = {
        "fixtureParameters": {"primaryText": "Host", "font": "Arial", "motion": "hold"},
        "parameterSchema": {
            "type": "object",
            "properties": {
                "primaryText": {"type": "string"},
                "motion": {"type": "string"},
            },
        },
    }
    assert service._native_instance_parameters({"primaryText": "Clara"}, evidence) == {
        "primaryText": "Clara",
        "font": "Arial",
        "motion": "hold",
    }
    slide_review = {
        **evidence,
        "fixtureParameters": {"primaryText": "Host", "font": "Arial"},
    }
    with pytest.raises(ComponentInstanceError, match="reviewed with this motion"):
        service._native_instance_parameters({"motion": "hold"}, slide_review)


def test_native_upgrade_is_explicit_and_keeps_the_original_pin(
    tmp_path, native_library
):
    from avo.artcraft import seal_record

    video = _video_components(tmp_path / "upgrade-video")
    first = _resolve(video, native_library)
    with pytest.raises(ComponentInstanceError, match="newer pinned version"):
        _resolve(
            video,
            native_library,
            instance_id="same-version-trial",
            supersedes_instance_id=first["instanceId"],
        )

    catalog, store, _, native = native_library
    original = _package_from_retained_source(
        native, picture_output(), {"primaryText": "Fixture", "font": "Arial"}
    )
    package = seal_record(
        "package",
        {
            **{key: value for key, value in original.items() if key != "packageHash"},
            "componentVersion": "1.1.0",
        },
    )
    pattern = _native_pattern()
    for key in ("provenance", "nativePackage", "promotionEventId"):
        del pattern[key]
    pattern["version"] = "1.1.0"
    options = {
        "package": package,
        "source_root": native.parent,
        "source_observer": _observe_fixture,
    }
    proposal = catalog.propose_native_package(
        pattern,
        actor="creator-fixture",
        intent_reference="design",
        change_type="minor",
        **options,
    )
    published = catalog.publish_native_package(
        proposal["path"],
        native_store=store,
        actor="creator-fixture",
        reason="fixture",
        expected_catalog_sha256=content_hash(catalog.load()),
        **options,
    )
    second = _resolve(
        video,
        native_library,
        instance_id="speaker-upgraded",
        version="1.1.0",
        manifest_hash=published["manifestSha256"],
        supersedes_instance_id=first["instanceId"],
    )
    assert second["supersedesInstanceId"] == first["instanceId"]
    assert second["kitVersion"] == "1.1.0"
    assert second["reviewRefs"] == []
    assert video.load(first["instanceId"]) == first
    assert _resolve(video, native_library) == first


def test_native_retry_preserves_an_earlier_pin_with_an_implicit_font(
    tmp_path, native_library
):
    video = _video_components(tmp_path / "earlier-provider-pin")
    current = _resolve(video, native_library, text="Clara")
    earlier = video._seal({**current, "parameters": {"primaryText": "Clara"}})
    path = video.path(current["instanceId"])
    path.write_text(
        json.dumps(earlier, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    before = path.read_bytes()
    assert _resolve(video, native_library, text="Clara") == earlier
    assert path.read_bytes() == before
