"""Provider-authored metadata and exact version pins for native components."""

import json
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


@pytest.fixture
def package_source(tmp_path):
    from tests.artcraft_fixtures import picture_output

    root = tmp_path / "approved-native-source"
    root.mkdir()
    native = root / "component.anicraft"
    native.write_bytes(b"\x00\xffneutral-editable-work")
    (root / "recipe.json").write_text('{"authoring":"lower-third"}', encoding="utf-8")
    return root, _package_from_retained_source(native, picture_output(), {})


def _package_from_retained_source(native, output, parameter_values):
    from avo.artcraft import seal_record
    from avo.timeline.contracts import file_fingerprint

    root = native.parent
    native_hash = file_fingerprint(native)["sha256"]
    recipe_hash = file_fingerprint(root / "recipe.json")["sha256"]
    files = {
        "parameters.json": (
            "parameter-schema",
            {
                "type": "object",
                "additionalProperties": False,
                "required": list(parameter_values),
                "properties": {
                    key: {"type": "string", "maxLength": 80} for key in parameter_values
                },
            },
        ),
        "source-review.json": (
            "source-review",
            {
                "version": 1,
                "app": "anicraft",
                "nativeSha256": native_hash,
                "recipeSha256": recipe_hash,
                "release": "0.2.1",
                "fixtureParameters": parameter_values,
            },
        ),
        "design-review.json": (
            "design-review",
            {
                "version": 1,
                "decision": "approved",
                "nativeSha256": native_hash,
                "actor": "creator-fixture",
                "reference": "design-decision-fixture",
            },
        ),
        "rights.json": (
            "rights",
            [
                {
                    "dependencyId": native.name,
                    "sha256": native_hash,
                    "owner": "fixture",
                    "source": "fixture",
                    "license": "project-owned",
                    "evidenceRef": "fixture-rights",
                    "derivativesAllowed": True,
                    "providerWide": True,
                    "commercialUse": True,
                    "attribution": "none",
                    "territory": "worldwide",
                    "termEndsAt": None,
                    "revoked": False,
                    "aiDisclosure": "none",
                }
            ],
        ),
    }
    entries = [
        {"path": native.name, "role": "native-source", **_bytes_identity(native)},
        {
            "path": "recipe.json",
            "role": "recipe",
            **_bytes_identity(root / "recipe.json"),
        },
    ]
    for name, (role, body) in files.items():
        path = root / name
        path.write_text(json.dumps(body), encoding="utf-8")
        entries.append({"path": name, "role": role, **_bytes_identity(path)})
    return seal_record(
        "package",
        {
            "version": 1,
            "provider": "first-channel",
            "componentId": "speaker-label",
            "componentVersion": "1.0.0",
            "app": "anicraft",
            "sourceRoot": str(root),
            "files": entries,
            "recipeHash": recipe_hash,
            "parameterSchemaHash": file_fingerprint(root / "parameters.json")["sha256"],
            "output": output,
            "sourceReviewRef": "source-review.json",
            "designReviewRef": "design-review.json",
            "rightsRef": "rights.json",
        },
    )


def _bytes_identity(path):
    from avo.timeline.contracts import file_fingerprint

    value = file_fingerprint(path)
    return {key: value[key] for key in ("sha256", "sizeBytes")}


def _observe_fixture(path, _contract, _parameters, *, max_bytes):
    from avo.timeline.contracts import file_fingerprint

    assert max_bytes >= path.stat().st_size
    return {"fingerprint": file_fingerprint(path)}


def test_provider_package_verifies_byte_exact_source_design_and_rights(package_source):
    from avo.timeline.artcraft_packages import verify_provider_package

    root, package = package_source
    evidence = verify_provider_package(
        package,
        root,
        provider="first-channel",
        source_observer=_observe_fixture,
    )
    assert (
        evidence["files"]["component.anicraft"].read_bytes()
        == b"\x00\xffneutral-editable-work"
    )
    assert evidence["provenance"]["origin"] == "provider-authored"
    assert (
        evidence["provenance"]["designReviewSha256"]
        == _bytes_identity(root / "design-review.json")["sha256"]
    )
    assert evidence["parameterSchema"]["type"] == "object"


def test_provider_publishes_exact_native_bytes_and_recovers_idempotently(
    tmp_path, package_source, monkeypatch
):
    from avo.adapters import artcraft_anicraft
    from avo.artcraft import ArtCraftError
    from avo.mcp.bridge import run_cli
    from avo.timeline.animation import AnimationError
    from avo.timeline.contracts import content_hash
    from avo.timeline.provider_animation import ProviderAnimationService

    root, package = package_source
    store = tmp_path / "external-library"
    store.mkdir()
    service = ProviderAnimationService(
        tmp_path / "metadata" / "catalog.json", provider="first-channel"
    )
    pattern = {
        key: value
        for key, value in _native_pattern().items()
        if key not in {"provenance", "nativePackage", "promotionEventId"}
    }
    source = {
        "package": package,
        "source_root": root,
        "source_observer": _observe_fixture,
    }
    manifest = tmp_path / "package.json"
    manifest.write_text(json.dumps(package), encoding="utf-8")
    monkeypatch.setattr(
        artcraft_anicraft, "inspect_lower_third_source", _observe_fixture
    )
    common = [
        "--provider",
        "first-channel",
        "--catalog",
        str(service.path),
        "--package",
        str(manifest),
        "--source-root",
        str(root),
        "--actor",
        "creator-fixture",
        "--json",
    ]
    proposed = run_cli(
        [
            "artcraft",
            "provider-propose",
            *common,
            "--pattern-json",
            json.dumps(pattern),
            "--intent-reference",
            "approved-design-fixture",
        ]
    )
    assert proposed.ok, proposed.stderr
    proposal = proposed.parsed_json
    proposal_path = Path(proposal["path"])
    assert str(root) not in proposal_path.read_text(encoding="utf-8")
    original = content_hash(service.initialize())
    with pytest.raises(
        AnimationError, match="Native packages require verified ArtCraft publication"
    ):
        service.decide(
            proposal_path,
            actor="creator-fixture",
            decision="approved",
            reason="fixture",
        )
    with pytest.raises(AnimationError, match="compare-and-swap"):
        service.publish_native_package(
            proposal_path,
            native_store=store,
            actor="creator-fixture",
            reason="fixture",
            expected_catalog_sha256="0" * 64,
            **source,
        )
    assert not list(store.iterdir())
    published = run_cli(
        [
            "artcraft",
            "provider-publish",
            *common,
            "--proposal",
            str(proposal_path),
            "--native-store",
            str(store),
            "--reason",
            "fixture",
            "--expected-catalog",
            original,
        ]
    )
    assert published.ok, published.stderr
    decision = published.parsed_json
    assert decision["type"] == "promotion-approved"
    target = store / decision["publishedPath"]
    assert (target / "files" / "component.anicraft").read_bytes() == (
        root / "component.anicraft"
    ).read_bytes()
    assert str(store) not in service.path.read_text(encoding="utf-8")
    assert (
        service.resolve_version("speaker-label", "1.0.0")["nativePackage"][
            "packageHash"
        ]
        == package["packageHash"]
    )
    again = service.publish_native_package(
        proposal_path,
        native_store=store,
        actor="creator-fixture",
        reason="fixture",
        expected_catalog_sha256=content_hash(service.load()),
        **source,
    )
    assert again["idempotent"] is True
    assert len(service.load()["events"]) == 1
    (target / "files" / "component.anicraft").write_bytes(b"unrelated native bytes")
    with pytest.raises(ArtCraftError, match="changed"):
        service.publish_native_package(
            proposal_path,
            native_store=store,
            actor="creator-fixture",
            reason="fixture",
            expected_catalog_sha256=content_hash(service.load()),
            **source,
        )
    assert len(service.load()["events"]) == 1


@pytest.mark.parametrize(
    "fault",
    [
        "missing-file",
        "replaced-source",
        "foreign-provider",
        "alias",
        "too-small",
        "unapproved-design",
        "revoked-rights",
        "binary-dependency",
    ],
)
def test_provider_package_rejects_stale_or_unowned_source_before_observation(
    package_source, fault
):
    from avo.artcraft import ArtCraftError, seal_record
    from avo.timeline.artcraft_packages import verify_provider_package

    root, package = package_source
    if fault == "missing-file":
        (root / "recipe.json").unlink()
    elif fault == "replaced-source":
        (root / "component.anicraft").write_bytes(b"different native source")
    elif fault == "alias":
        alias = {**package["files"][0], "path": "Component.anicraft"}
        package = seal_record(
            "package",
            {
                **{
                    key: value for key, value in package.items() if key != "packageHash"
                },
                "files": [*package["files"], alias],
            },
        )
    elif fault in {"unapproved-design", "revoked-rights", "binary-dependency"}:
        package = _change_package_evidence(root, package, fault)

    def unexpected(*_args, **_kwargs):
        pytest.fail("unverified sources reached the native inspection")

    with pytest.raises(ArtCraftError):
        verify_provider_package(
            package,
            root,
            provider="other-channel"
            if fault == "foreign-provider"
            else "first-channel",
            source_observer=unexpected,
            byte_limit=1 if fault == "too-small" else 16_000_000,
        )


def _change_package_evidence(root, package, fault):
    from avo.artcraft import seal_record

    body = deepcopy(
        {key: value for key, value in package.items() if key != "packageHash"}
    )
    if fault == "binary-dependency":
        path = root / "unsupported-plugin.dll"
        path.write_bytes(b"\x00\xffunsupported")
        body["files"].append(
            {"path": path.name, "role": "plugin", **_bytes_identity(path)}
        )
    else:
        name = "design-review.json" if fault == "unapproved-design" else "rights.json"
        path = root / name
        data = json.loads(path.read_text(encoding="utf-8"))
        if fault == "unapproved-design":
            data["decision"] = "pending"
        else:
            data[0]["revoked"] = True
        path.write_text(json.dumps(data), encoding="utf-8")
        selected = next(item for item in body["files"] if item["path"] == name)
        selected.update(_bytes_identity(path))
    return seal_record("package", body)
