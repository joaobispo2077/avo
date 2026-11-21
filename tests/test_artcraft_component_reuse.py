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
from avo.timeline.contracts import content_hash
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


def _published_native_library(tmp_path, provider, source_bytes):
    from avo.artcraft import seal_record

    source = tmp_path / "native-source"
    source.mkdir(parents=True)
    native = source / "component.anicraft"
    native.write_bytes(source_bytes)
    (source / "recipe.json").write_text("{}", encoding="utf-8")
    package = _package_from_retained_source(
        native, picture_output(), {"primaryText": "Fixture", "font": "Arial"}
    )
    if package["provider"] != provider:
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
