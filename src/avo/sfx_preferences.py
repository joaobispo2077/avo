"""Explicit provider sound identities; no project media, rights or approval transfer."""

import hashlib
import json
import re
from copy import deepcopy

from avo.direction.sources import normalize_text
from avo.editing_craft import _save_preference
from avo.editing_craft_requests import MAX_REQUEST_BYTES, read_craft_request
from avo.motion import _motion_schema_check, _provider_motion_target
from avo.paths import repo_root
from avo.sfx_catalog import _validate
from avo.sfx_contracts import SfxCatalogError
from avo.timeline.contracts import content_hash
from avo.timeline.store import timeline_writer
from avo.timeline.workspace import TimelineWorkspace

SCHEMA = "avo.sfx-provider.schema.json#/$defs/"
PRIVATE_LOCATION = re.compile(
    r"(?i)(?:\bfile:|(?<![\w:/])(?:[a-z]:[\\/]|\\\\|//|/(?!/)[\w.~]))"
)


def _favorite_id(library, digest):
    return content_hash({"libraryId": library, "sourceSha256": digest})


def _portable(value):
    if isinstance(value, str) and (
        PRIVATE_LOCATION.search(value)
        or normalize_text(value) != " ".join(value.split())
    ):
        raise SfxCatalogError(
            "Provider sound descriptors must be portable and exclude private paths or secrets"
        )
    if isinstance(value, dict):
        for item in value.values():
            _portable(item)
    elif isinstance(value, list):
        for item in value:
            _portable(item)


def validate_favorites(value):
    _validate(value, SCHEMA + "inspection")
    if value["favorites"] and value["documentSha256"] == "absent":
        raise SfxCatalogError(
            "Provider favorites require an existing exact document identity"
        )
    seen = set()
    for favorite in value["favorites"]:
        identity = _favorite_id(favorite["libraryId"], favorite["sourceSha256"])
        if favorite["favoriteId"] != identity or identity in seen:
            raise SfxCatalogError("Provider favorite identity is duplicate or changed")
        seen.add(identity)
        _portable(favorite["curation"])
        _portable([favorite["actor"], favorite["reason"], favorite["operationId"]])
    return deepcopy(value)


def _provider(workspace, root, selected=None):
    root = repo_root(root)
    current = TimelineWorkspace.from_project(
        workspace.project_path, video_id=workspace.video_id
    )
    provider = current.project["provider"]
    if current.raw_dir != workspace.raw_dir or selected not in (None, provider):
        raise SfxCatalogError(
            "Provider favorite target differs from the current project"
        )
    target = _provider_motion_target(provider, root)
    if target != (root / "providers" / provider / "avo.provider.json").absolute():
        raise SfxCatalogError("Provider favorite target cannot use linked paths")
    if not target.exists():
        return (
            root,
            target,
            {},
            None,
            {
                "contractVersion": "1.0.0",
                "provider": provider,
                "documentSha256": "absent",
                "favorites": [],
            },
        )
    with target.open("rb") as stream:
        raw = stream.read(MAX_REQUEST_BYTES + 1)
    if len(raw) > MAX_REQUEST_BYTES:
        raise SfxCatalogError("Provider preferences exceed the 1 MiB document budget")
    digest = hashlib.sha256(raw).hexdigest()
    document = read_craft_request(target, expected_sha256=digest)
    _motion_schema_check(document, "provider", root)
    if document["name"] != provider:
        raise SfxCatalogError("Provider document changes its declared identity")
    favorites = (document.get("routingOverrides") or {}).get("sfxFavorites", [])
    view = validate_favorites(
        {
            "contractVersion": "1.0.0",
            "provider": provider,
            "documentSha256": digest,
            "favorites": favorites,
        }
    )
    return root, target, document, raw, view


def inspect_sfx_favorites(workspace, *, root=None):
    return _provider(workspace, root)[-1]


def _target_for_request(workspace, request, root):
    from avo.timeline.command_registry import authorize

    _validate(request, SCHEMA + "request")
    authorize("provider", mutation="provider-sfx-favorites")
    result = _provider(workspace, root, request["provider"])
    if result[-1]["documentSha256"] != request["expectedProviderDocument"]:
        raise SfxCatalogError(
            "Provider preferences changed; inspect their current document identity"
        )
    return result


def _save(result, favorites):
    root, target, original, raw, view = result
    validate_favorites({**view, "favorites": favorites})
    candidate = deepcopy(original)
    routing = candidate.setdefault("routingOverrides", {})
    if favorites:
        routing["sfxFavorites"] = sorted(favorites, key=lambda row: row["favoriteId"])
    else:
        routing.pop("sfxFavorites", None)
        if not routing:
            candidate.pop("routingOverrides", None)
    if (
        len(json.dumps(candidate, ensure_ascii=False, indent=2).encode("utf-8")) + 1
        > MAX_REQUEST_BYTES
    ):
        raise SfxCatalogError("Provider preferences exceed the 1 MiB document budget")
    digest = _save_preference(target, original, raw, candidate, "provider", root)
    return {
        **view,
        "documentSha256": digest,
        "favorites": routing.get("sfxFavorites", []),
    }


def _selected_entry(catalogue, request):
    generation = catalogue.show()
    if generation["generationId"] != request["expectedGeneration"]:
        raise SfxCatalogError("Sound catalogue generation changed")
    entry = next(
        (
            row
            for row in generation["entries"]
            if row["entryId"] == request["selection"]["entryId"]
        ),
        None,
    )
    if (
        not entry
        or entry["entryRevision"] != request["selection"]["entryRevision"]
        or entry["source"]["state"] != "available"
    ):
        raise SfxCatalogError(
            "Favorite source entry is changed, missing or unavailable"
        )
    return generation, entry


def promote_sfx_favorite(catalogue, request, *, root=None):
    result = _target_for_request(catalogue.workspace, request, root)
    if request["operation"] != "favorite-promote":
        raise SfxCatalogError("Favorite promotion requires its exact operation")
    _selected_entry(catalogue, request)
    catalogue._path(".mutation.lock")
    with timeline_writer(catalogue.directory):
        with timeline_writer(result[1].parent):
            result = _target_for_request(catalogue.workspace, request, root)
            return _publish_favorite(catalogue, request, result)


def _publish_favorite(catalogue, request, result):
    generation, entry = _selected_entry(catalogue, request)
    favorite = {
        "favoriteId": _favorite_id(entry["libraryId"], entry["source"]["sha256"]),
        "libraryId": entry["libraryId"],
        "sourceSha256": entry["source"]["sha256"],
        "curation": {
            **{
                key: deepcopy(entry["curation"][key])
                for key in request["fields"]
                if key in entry["curation"]
            },
            "favorite": True,
        },
        "provenance": {
            "generationId": generation["generationId"],
            "entryId": entry["entryId"],
            "entryRevision": entry["entryRevision"],
        },
        "actor": request["actor"],
        "reason": request["reason"],
        "operationId": request["operationId"],
    }
    favorites = [
        row
        for row in result[-1]["favorites"]
        if row["favoriteId"] != favorite["favoriteId"]
    ]
    return {**_save(result, [*favorites, favorite]), "favorite": favorite}


def remove_sfx_favorite(workspace, request, *, root=None):
    result = _target_for_request(workspace, request, root)
    if request["operation"] != "favorite-remove":
        raise SfxCatalogError("Favorite removal requires its exact operation")
    with timeline_writer(result[1].parent):
        result = _target_for_request(workspace, request, root)
        return _remove_favorite(request, result)


def _remove_favorite(request, result):
    favorites = [
        row
        for row in result[-1]["favorites"]
        if row["favoriteId"] != request["favoriteId"]
    ]
    if len(favorites) == len(result[-1]["favorites"]):
        raise SfxCatalogError("Selected provider favorite is unavailable")
    return _save(result, favorites)


def seed_favorite(entry, preferences):
    identity = _favorite_id(entry["libraryId"], entry["source"]["sha256"])
    favorite = next(
        (row for row in preferences["favorites"] if row["favoriteId"] == identity), None
    )
    if favorite:
        entry["curation"].update(deepcopy(favorite["curation"]))
        entry["curationOrigin"] = {
            "provider": preferences["provider"],
            "documentSha256": preferences["documentSha256"],
            "favoriteId": identity,
        }
