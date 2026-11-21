"""Validate the external source closure of a selected ArtCraft provider package."""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from tempfile import TemporaryDirectory

from avo.artcraft import ArtCraftError, validate_record
from avo.paths import repo_root

from .contracts import content_hash, file_fingerprint, fingerprint_stage
from .store import timeline_writer, write_immutable_json

_ROLES = frozenset(
    {
        "native-source",
        "recipe",
        "parameter-schema",
        "source-review",
        "design-review",
        "rights",
    }
)
_IDENTITY_ARTWORK = "identity-artwork"
_PACKAGE_STAGING_PREFIX = "artcraft-package-"


def verify_provider_package(
    package,
    source_root,
    *,
    provider,
    source_observer,
    file_limit=128,
    byte_limit=16_000_000,
):
    """Read the exact selected package without editing it or running native code."""
    package = validate_record("package", package)
    root = _require_external_root(source_root)
    if package["provider"] != provider or package["sourceRoot"] != str(root):
        raise ArtCraftError("ArtCraft package provider or selected source root differs")
    return _inspect_package_at(package, root, source_observer, file_limit, byte_limit)


def read_retained_provider_package(
    store_root, *, provider, package_hash, source_observer
):
    """Resolve one exact provider package from the separately owned source store."""
    if not _provider_slug(provider) or not re.fullmatch(r"[a-f0-9]{64}", package_hash):
        raise ArtCraftError("ArtCraft retained package has an invalid owner or hash")
    root = _require_external_root(store_root)
    target = root / provider / package_hash
    if target.resolve() != target:
        raise ArtCraftError("ArtCraft retained package escaped its selected store")
    package = _read_retained_manifest(target)
    if (package["provider"], package["packageHash"]) != (provider, package_hash):
        raise ArtCraftError("ArtCraft retained package identity changed")
    evidence = _inspect_package_at(
        package, target / "files", source_observer, 128, 16_000_000
    )
    return package, evidence


def _inspect_package_at(package, root, source_observer, file_limit, byte_limit):
    with fingerprint_stage(reuse_current=True, verify_on_exit=True):
        files, roles = _verify_files(package, root, file_limit, byte_limit)
        observed = _observe_package(package, roles, source_observer, byte_limit)
    return {
        "files": files,
        **observed,
        "packageHash": package["packageHash"],
        "sourceRoot": root,
    }


def native_catalog_manifest(package, evidence):
    body = {
        "schemaVersion": "1.0.0",
        "kitId": package["componentId"],
        "version": package["componentVersion"],
        "nativePackage": {
            "app": package["app"],
            "packageHash": evidence["packageHash"],
        },
        "provenance": evidence["provenance"],
        "parameterSchema": evidence["parameterSchema"],
    }
    return {**body, "manifestSha256": content_hash(body)}


def retain_provider_package(package, evidence, store_root):
    """Keep an immutable, byte-exact source bundle outside the AVO repository."""
    package = validate_record("package", package)
    if evidence["packageHash"] != package["packageHash"]:
        raise ArtCraftError("ArtCraft package changed before publication")
    root = _require_external_root(store_root)
    reference = Path(package["provider"]) / package["packageHash"]
    target = root / reference
    if target.resolve() != target:
        raise ArtCraftError("ArtCraft package store escaped its selected directory")
    with timeline_writer(target.parent):
        if target.exists():
            _verify_retained_package(package, target)
        else:
            _retain_new_package(package, evidence, target)
    return reference


def _verify_retained_package(package, target):
    if _read_retained_manifest(target) != package:
        raise ArtCraftError("Immutable ArtCraft package manifest has changed")
    root = target / "files"
    return [_verify_file(root / item["path"], root, item) for item in package["files"]]


def _read_retained_manifest(target):
    path = target / "manifest.json"
    if path.resolve() != path or not path.is_file():
        raise ArtCraftError("ArtCraft retained package manifest is missing or escaped")
    if path.stat().st_nlink != 1 or path.stat().st_size > 256 * 1024:
        raise ArtCraftError(
            "ArtCraft retained package manifest has an alias or exceeds its size limit"
        )
    return validate_record("package", _read_json({"locator": str(path)}, dict))


def retain_native_instance_sources(package, evidence, *, project_root, target):
    root = _require_external_root(project_root)
    if target.resolve() != target or not target.is_relative_to(
        root / "edit" / "derived" / "provider-components"
    ):
        raise ArtCraftError("ArtCraft instance source escaped its owning video")
    if target.exists():
        _verify_retained_package(package, target)
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        _retain_new_package(package, evidence, target)


def native_instance_identity(package, recipient):
    pin = {key: package[key] for key in ("provider", "app", "packageHash")}
    if recipient != pin["provider"]:
        pin["sharedWith"] = recipient
    return pin


def require_native_sharing(owner, recipient, rights):
    if owner != recipient and not (
        rights and all(recipient in _sharing_providers(entry) for entry in rights)
    ):
        raise ArtCraftError(
            "Native package has no sharing rights for this video provider"
        )


def retained_native_instance_files(instance, project_root, provider):
    """Verify the video-local copy of the exact pinned native package."""
    _, manifest, sources = _retained_native_instance_package(
        instance, project_root, provider
    )
    return [manifest, *sources]


def _retained_native_instance_package(instance, project_root, provider):
    raw = _require_external_root(project_root)
    base = raw / "edit" / "derived" / "provider-components"
    target = base / instance["instanceId"]
    if target.resolve() != target or not target.is_relative_to(base):
        raise ArtCraftError("ArtCraft instance source escaped its owning video")
    package = _read_retained_manifest(target)
    pin = instance["nativePackage"]
    identity = native_instance_identity(package, provider)
    selected_kit = (instance["kitId"], instance["kitVersion"])
    if pin != identity or selected_kit != (
        package["componentId"],
        package["componentVersion"],
    ):
        raise ArtCraftError("ArtCraft package differs from the pinned video instance")
    with fingerprint_stage(reuse_current=True, verify_on_exit=True):
        sources = _verify_retained_package(package, target)
        if "sharedWith" in identity or any(
            entry["role"] == _IDENTITY_ARTWORK for entry in package["files"]
        ):
            _verify_retained_rights(package, sources, provider)
        manifest = file_fingerprint(target / "manifest.json")
    declared = [{"path": item["locator"], "sha256": item["sha256"]} for item in sources]
    if declared != instance["generatedFiles"]:
        raise ArtCraftError(
            "ArtCraft package file list differs from the pinned video instance"
        )
    return package, manifest, sources


def _verify_retained_rights(package, sources, recipient):
    roles = {
        entry["role"]: (entry, fingerprint)
        for entry, fingerprint in zip(package["files"], sources, strict=True)
    }
    reference = _selected_evidence(package, roles, "rightsRef", "rights")
    rights = _check_rights(reference, roles)
    require_native_sharing(package["provider"], recipient, rights)


def native_instance_artwork_inputs(workspace, request, selection, source, settings):
    """Select the exact marked kit copied into this video's canonical instance."""
    with fingerprint_stage(reuse_current=True, verify_on_exit=True):
        record, instance = _read_artwork_instance(workspace, selection)
        if (instance["kitId"], instance["parameters"]) != (
            request["componentId"],
            settings["authoringParameters"],
        ):
            raise ArtCraftError(
                "ArtCraft artwork differs from the selected kit instance"
            )
        package, manifest, files = _retained_native_instance_package(
            instance, workspace.raw_dir, request["provider"]
        )
        roles = {
            entry["role"]: fingerprint
            for entry, fingerprint in zip(package["files"], files, strict=True)
        }
        artwork = roles.get(_IDENTITY_ARTWORK)
        if (
            artwork is None
            or roles["native-source"] != source
            or package["output"] != settings["output"]
        ):
            raise ArtCraftError("ArtCraft kit artwork, native source or output differs")
    return [
        artwork,
        record,
        manifest,
        *(item for item in files if item not in (source, artwork)),
    ]


def _read_artwork_instance(workspace, selection):
    from .component_instances import ComponentInstanceService

    service = ComponentInstanceService(workspace)
    path = service.path(selection["instanceId"])
    if (
        path.resolve() != path
        or not path.is_file()
        or path.stat().st_nlink != 1
        or path.stat().st_size > 256 * 1024
    ):
        raise ArtCraftError(
            "ArtCraft artwork requires an exact component instance record"
        )
    record = file_fingerprint(path)
    instance = service.load(selection["instanceId"])
    if (
        instance["instanceId"],
        instance["instanceHash"],
        instance.get("nativePackage", {}).get("app"),
    ) != (selection["instanceId"], selection["instanceHash"], "anicraft"):
        raise ArtCraftError("ArtCraft artwork differs from the selected kit instance")
    return record, instance


def shared_native_package_paths(edit_directory):
    """Find verified immutable provider packages stored inside a cleanup tree."""
    root = Path(edit_directory)
    if root.resolve() != root:
        raise ArtCraftError(
            "Native library scan requires an unaliased cleanup directory"
        )
    _reject_unsealed_shared_versions(root)
    for manifest in sorted(root.rglob("manifest.json")):
        target = manifest.parent
        if not re.fullmatch(r"[a-f0-9]{64}", target.name):
            continue
        package = _shared_package_manifest(manifest)
        if package is None:
            continue
        yield manifest
        yield from (
            Path(item["locator"]) for item in _verify_retained_package(package, target)
        )


def _reject_unsealed_shared_versions(root):
    for files in root.rglob("files"):
        target = files.parent
        if (
            not re.fullmatch(r"[a-f0-9]{64}", target.name)
            or not files.is_dir()
            or (target / "manifest.json").is_file()
        ):
            continue
        if _contains_native_source(files):
            raise ArtCraftError(
                f"Shared native version is missing its manifest: {target}"
            )


def _contains_native_source(files):
    return any(entry.suffix.casefold() == ".anicraft" for entry in files.rglob("*"))


def _shared_package_manifest(manifest):
    if (
        manifest.resolve() != manifest
        or not manifest.is_file()
        or manifest.stat().st_size > 256 * 1024
    ):
        raise ArtCraftError(
            "Possible ArtCraft library manifest is missing, oversized or escaped"
        )
    document = json.loads(manifest.read_text(encoding="utf-8"))
    markers = {"packageHash", "sourceReviewRef", "designReviewRef"}
    if not isinstance(document, dict) or not markers <= document.keys():
        if _contains_native_source(manifest.parent / "files"):
            raise ArtCraftError(
                f"Shared native version has an invalid manifest: {manifest}"
            )
        return None
    target = manifest.parent
    package = _read_retained_manifest(target)
    if (package["provider"], package["packageHash"]) != (
        target.parent.name,
        target.name,
    ):
        raise ArtCraftError(
            "ArtCraft provider library path differs from its immutable package"
        )
    return package


def is_native_publication_stage(relative_path):
    return any(
        part.startswith(_PACKAGE_STAGING_PREFIX) for part in relative_path.parts[:-1]
    )


def _retain_new_package(package, evidence, target):
    source_root = evidence["sourceRoot"]
    with TemporaryDirectory(
        prefix=_PACKAGE_STAGING_PREFIX, dir=target.parent
    ) as directory:
        stage = Path(directory)
        if stage.resolve() != stage or stage.parent != target.parent:
            raise ArtCraftError(
                "ArtCraft package staging escaped its selected directory"
            )
        for item in package["files"]:
            relative = item["path"]
            source = evidence["files"][relative]
            _verify_file(source, source_root, item)
            destination = stage / "files" / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)
        write_immutable_json(stage / "manifest.json", package)
        _verify_retained_package(package, stage)
        stage.rename(target)


def _require_external_root(value):
    root = Path(value)
    repository = repo_root().resolve()
    if (
        not root.is_absolute()
        or root.resolve() != root
        or not root.is_dir()
        or root.is_relative_to(repository)
        or repository.is_relative_to(root)
    ):
        raise ArtCraftError("ArtCraft packages require an exact external directory")
    return root


def _verify_files(package, root, file_limit, byte_limit):
    entries = package["files"]
    if (
        len(entries) > file_limit
        or sum(item["sizeBytes"] for item in entries) > byte_limit
    ):
        raise ArtCraftError("ArtCraft package exceeds its selected file or byte limit")
    if len({item["path"].casefold() for item in entries}) != len(entries):
        raise ArtCraftError("ArtCraft package has conflicting file aliases")
    selected_roles = {item.get("role") for item in entries}
    if (
        len(entries) != len(selected_roles)
        or selected_roles - {_IDENTITY_ARTWORK} != _ROLES
    ):
        raise ArtCraftError(
            "ArtCraft lower-third package requires the exact supported source roles"
        )
    files, roles = {}, {}
    for item in entries:
        path = root / item["path"]
        observed = _verify_file(path, root, item)
        files[item["path"]] = path
        roles[item["role"]] = (item, observed)
    return files, roles


def _verify_file(path, root, expected):
    if path.resolve() != path or not path.is_relative_to(root) or not path.is_file():
        raise ArtCraftError(
            "ArtCraft package source is missing or escaped its workspace"
        )
    if path.stat().st_nlink != 1 or path.stat().st_size != expected["sizeBytes"]:
        raise ArtCraftError(
            "ArtCraft package source has changed or has an external alias"
        )
    observed = file_fingerprint(path)
    if observed["sha256"] != expected["sha256"]:
        raise ArtCraftError("ArtCraft package file fingerprint changed")
    return observed


def _observe_package(package, roles, source_observer, byte_limit):
    if package["app"] != "anicraft":
        raise ArtCraftError(
            "The selected ArtCraft package has no qualified source profile"
        )
    native = roles["native-source"][1]
    recipe = roles["recipe"][1]
    parameters = roles["parameter-schema"][1]
    if (recipe["sha256"], parameters["sha256"]) != (
        package["recipeHash"],
        package["parameterSchemaHash"],
    ):
        raise ArtCraftError("ArtCraft package recipe or parameter schema changed")
    source_ref = _selected_evidence(package, roles, "sourceReviewRef", "source-review")
    design_ref = _selected_evidence(package, roles, "designReviewRef", "design-review")
    rights_ref = _selected_evidence(package, roles, "rightsRef", "rights")
    artwork_entry = roles.get(_IDENTITY_ARTWORK)
    artwork = artwork_entry[1] if artwork_entry else None
    if artwork and Path(artwork["locator"]).suffix.lower() != ".svg":
        raise ArtCraftError("ArtCraft package identity artwork must be an SVG")
    fixture = _source_review(source_ref, native, recipe)
    _design_review(design_ref, native, artwork)
    rights = _check_rights(rights_ref, roles)
    parameter_schema = _parameter_schema(parameters, fixture)
    observed = source_observer(
        Path(native["locator"]),
        package["output"],
        fixture,
        max_bytes=byte_limit,
        **({"artwork": artwork} if artwork else {}),
    )
    if observed.get("fingerprint") != native:
        raise ArtCraftError("ArtCraft source observation refers to other bytes")
    provenance = {
        "origin": "provider-authored",
        "sourceReviewSha256": source_ref["sha256"],
        "designReviewSha256": design_ref["sha256"],
        "rightsSha256": rights_ref["sha256"],
    }
    return {
        "provenance": provenance,
        "parameterSchema": parameter_schema,
        "fixtureParameters": fixture,
        "rights": rights,
    }


def _selected_evidence(package, roles, reference_key, role):
    entry, fingerprint = roles[role]
    if package[reference_key] != entry["path"]:
        raise ArtCraftError(
            "ArtCraft package review or rights reference differs from its source"
        )
    return fingerprint


def _read_json(reference, expected_type):
    try:
        value = json.loads(Path(reference["locator"]).read_bytes())
    except (OSError, ValueError) as exc:
        raise ArtCraftError("ArtCraft package metadata must be valid JSON") from exc
    if not isinstance(value, expected_type):
        raise ArtCraftError("ArtCraft package metadata has an unsupported shape")
    return value


def _source_review(reference, native, recipe):
    value = _read_json(reference, dict)
    expected = {
        "version": 1,
        "app": "anicraft",
        "nativeSha256": native["sha256"],
        "recipeSha256": recipe["sha256"],
        "release": "0.2.1",
    }
    if any(value.get(key) != fact for key, fact in expected.items()) or not isinstance(
        value.get("fixtureParameters"), dict
    ):
        raise ArtCraftError(
            "ArtCraft source review differs from the selected qualified source"
        )
    return value["fixtureParameters"]


def _design_review(reference, native, artwork):
    value = _read_json(reference, dict)
    expected = {"version": 1, "decision": "approved", "nativeSha256": native["sha256"]}
    if artwork:
        expected["identityArtworkSha256"] = artwork["sha256"]
    if any(value.get(key) != fact for key, fact in expected.items()) or not all(
        isinstance(value.get(key), str) and value[key].strip()
        for key in ("actor", "reference")
    ):
        raise ArtCraftError(
            "ArtCraft design review does not approve these exact native bytes"
        )


def _check_rights(reference, roles):
    from .animation import AnimationError
    from .provider_animation import ProviderAnimationService

    rights = _read_json(reference, list)
    if not all(isinstance(item, dict) for item in rights):
        raise ArtCraftError("ArtCraft package rights must be typed records")
    for item in rights:
        _sharing_providers(item)
    try:
        ProviderAnimationService.validate_rights(rights)
    except AnimationError as exc:
        raise ArtCraftError(str(exc)) from exc
    expected = {
        (entry["path"], entry["sha256"])
        for role, (entry, _) in roles.items()
        if role in {"native-source", _IDENTITY_ARTWORK}
    }
    if {(item["dependencyId"], item["sha256"]) for item in rights} != expected:
        raise ArtCraftError(
            "ArtCraft rights must cover the package's exact native source and any identity artwork"
        )
    return rights


def _sharing_providers(entry):
    if "sharing" not in entry:
        return ()
    sharing = entry["sharing"]
    if not isinstance(sharing, dict) or sharing.keys() != {"providers", "evidenceRef"}:
        raise ArtCraftError("ArtCraft sharing rights need named providers and evidence")
    providers, evidence = sharing["providers"], sharing["evidenceRef"]
    if (
        not isinstance(providers, list)
        or not providers
        or not all(map(_provider_slug, providers))
    ):
        raise ArtCraftError("ArtCraft sharing rights need exact provider names")
    if (
        len(set(providers)) != len(providers)
        or not isinstance(evidence, str)
        or not evidence.strip()
    ):
        raise ArtCraftError(
            "ArtCraft sharing rights need unique providers and evidence"
        )
    return providers


def _provider_slug(value):
    return isinstance(value, str) and bool(re.fullmatch(r"[a-z0-9][a-z0-9-]*", value))


def _parameter_schema(reference, fixture):
    from jsonschema import Draft202012Validator, SchemaError, ValidationError

    schema = _read_json(reference, dict)
    if schema.get("type") != "object" or _has_schema_reference(schema):
        raise ArtCraftError("ArtCraft parameter schema must be a local object contract")
    try:
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema).validate(fixture)
    except (SchemaError, ValidationError) as exc:
        raise ArtCraftError(
            "ArtCraft reviewed fixture does not match its parameter schema"
        ) from exc
    return schema


def _has_schema_reference(value):
    if isinstance(value, dict):
        return bool({"$ref", "$dynamicRef", "$recursiveRef"} & value.keys()) or any(
            _has_schema_reference(child) for child in value.values()
        )
    if isinstance(value, list):
        return any(_has_schema_reference(child) for child in value)
    return False
