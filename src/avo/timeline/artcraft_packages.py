"""Validate the external source closure of a selected ArtCraft provider package."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from tempfile import TemporaryDirectory

from avo.artcraft import ArtCraftError, validate_record
from avo.paths import repo_root

from .contracts import file_fingerprint, fingerprint_stage
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
    with fingerprint_stage(reuse_current=True, verify_on_exit=True):
        files, roles = _verify_files(package, root, file_limit, byte_limit)
        provenance, parameter_schema, rights = _observe_package(
            package, roles, source_observer, byte_limit
        )
    return {
        "files": files,
        "provenance": provenance,
        "parameterSchema": parameter_schema,
        "rights": rights,
        "packageHash": package["packageHash"],
    }


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
    manifest = target / "manifest.json"
    if manifest.resolve() != manifest or json.loads(manifest.read_bytes()) != package:
        raise ArtCraftError("Immutable ArtCraft package manifest has changed")
    for item in package["files"]:
        root = target / "files"
        _verify_file(root / item["path"], root, item)


def _retain_new_package(package, evidence, target):
    source_root = Path(package["sourceRoot"])
    with TemporaryDirectory(prefix="artcraft-package-", dir=target.parent) as directory:
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
    if {item.get("role") for item in entries} != _ROLES or len(entries) != len(_ROLES):
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
    fixture = _source_review(source_ref, native, recipe)
    _design_review(design_ref, native)
    rights = _check_rights(rights_ref, roles["native-source"][0])
    parameter_schema = _parameter_schema(parameters, fixture)
    observed = source_observer(
        Path(native["locator"]), package["output"], fixture, max_bytes=byte_limit
    )
    if observed.get("fingerprint") != native:
        raise ArtCraftError("ArtCraft source observation refers to other bytes")
    provenance = {
        "origin": "provider-authored",
        "sourceReviewSha256": source_ref["sha256"],
        "designReviewSha256": design_ref["sha256"],
        "rightsSha256": rights_ref["sha256"],
    }
    return provenance, parameter_schema, rights


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


def _design_review(reference, native):
    value = _read_json(reference, dict)
    expected = {"version": 1, "decision": "approved", "nativeSha256": native["sha256"]}
    if any(value.get(key) != fact for key, fact in expected.items()) or not all(
        isinstance(value.get(key), str) and value[key].strip()
        for key in ("actor", "reference")
    ):
        raise ArtCraftError(
            "ArtCraft design review does not approve these exact native bytes"
        )


def _check_rights(reference, native):
    from .animation import AnimationError
    from .provider_animation import ProviderAnimationService

    rights = _read_json(reference, list)
    if not all(isinstance(item, dict) for item in rights):
        raise ArtCraftError("ArtCraft package rights must be typed records")
    try:
        ProviderAnimationService.validate_rights(rights)
    except AnimationError as exc:
        raise ArtCraftError(str(exc)) from exc
    if {(item["dependencyId"], item["sha256"]) for item in rights} != {
        (native["path"], native["sha256"])
    }:
        raise ArtCraftError(
            "ArtCraft rights must cover the package's exact native source"
        )
    return rights


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
