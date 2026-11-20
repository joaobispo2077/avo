"""Provider-authored metadata and exact version pins for native components."""

from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from avo.timeline.contracts import ContractError, validate_document

PROVIDERS = Path(__file__).resolve().parents[1] / "providers"


def _native_package():
    return {"app": "anicraft", "packageHash": "a" * 64}


def _native_pattern():
    return {
        "patternId": "speaker-label",
        "name": "Speaker label",
        "version": "1.0.0",
        "behavior": {},
        "contexts": ["speaker introduction"],
        "exclusions": [],
        "requiredAssets": [],
        "accessibility": {"reducedMotion": True, "flashingSafe": True},
        "provenance": {
            "origin": "provider-authored",
            "sourceReviewSha256": "b" * 64,
            "designReviewSha256": "c" * 64,
            "rightsSha256": "d" * 64,
        },
        "promotionEventId": "animation-event-0001",
        "nativePackage": _native_package(),
    }


def _validate_pattern(pattern):
    validate_document(
        pattern, "avo.animation-library.schema.json#/$defs/pattern", root=PROVIDERS
    )


def test_provider_authored_metadata_uses_review_and_rights_identity_without_fabricated_video():
    pattern = _native_pattern()
    _validate_pattern(pattern)
    for key, value in (
        ("sourceVideoId", "invented-video"),
        ("sourceReviewSha256", "ambiguous"),
    ):
        bad = deepcopy(pattern)
        bad["provenance"][key] = value
        with pytest.raises(ContractError):
            _validate_pattern(bad)


def test_native_catalog_metadata_cannot_expose_package_storage_or_claim_legacy_origin():
    with pytest.raises(ContractError):
        _validate_pattern(
            {
                **_native_pattern(),
                "nativePackage": {
                    **_native_package(),
                    "path": "native/component.anicraft",
                },
            }
        )
    with pytest.raises(ContractError):
        _validate_pattern(
            {
                **_native_pattern(),
                "provenance": {
                    "sourceVideoId": "legacy-project",
                    "candidateSha256": "e" * 64,
                    "sectionRefs": [],
                },
            }
        )
    unbound = _native_pattern()
    del unbound["nativePackage"]
    with pytest.raises(ContractError):
        _validate_pattern(unbound)


def test_native_instance_records_provider_app_and_exact_package_hash(tmp_path):
    from avo.timeline.component_instances import (
        ComponentInstanceError,
        ComponentInstanceService,
    )

    instance = {
        "schemaVersion": "1.0.0",
        "instanceId": "speaker-first-use",
        "kitId": "speaker-label",
        "kitVersion": "1.0.0",
        "kitManifestHash": "e" * 64,
        "instanceHash": "f" * 64,
        "parameters": {},
        "assetBindings": [],
        "eventBindings": [],
        "safeAreaBindings": {"faces": [], "captions": [], "evidence": [], "ui": []},
        "generatedFiles": [],
        "reviewRefs": [],
        "nativePackage": {**_native_package(), "provider": "first-channel"},
    }
    validate_document(instance, "avo.component-instance.schema.json")
    absent = {**instance, "nativePackage": _native_package()}
    with pytest.raises(ContractError):
        validate_document(absent, "avo.component-instance.schema.json")
    service = ComponentInstanceService(SimpleNamespace(timeline_dir=tmp_path))
    with pytest.raises(ComponentInstanceError, match="verified ArtCraft instantiation"):
        service.register(instance)


def test_legacy_component_proposal_cannot_publish_a_native_declaration(tmp_path):
    from avo.artcraft import ArtCraftError, guard_legacy_component_request
    from avo.timeline.animation import AnimationError
    from avo.timeline.provider_animation import ProviderAnimationService

    pattern = _native_pattern()
    with pytest.raises(ArtCraftError, match="qualified admission"):
        guard_legacy_component_request({"instance": pattern})
    service = ProviderAnimationService(
        tmp_path / "animation-library.json", provider="first-channel"
    )
    with pytest.raises(AnimationError, match="verified ArtCraft publication"):
        service.propose(pattern, actor="fixture", intent_reference="fixture-decision")
    assert not service.path.exists()
