"""Explicit portable provider favorites never carry project rights or approvals."""

import hashlib
import json
from copy import deepcopy

import pytest

from avo.sfx_catalog import SfxCatalogError, SfxCatalogService
from avo.sfx_preferences import (
    inspect_sfx_favorites,
    promote_sfx_favorite,
    remove_sfx_favorite,
)
from avo.timeline.workspace import TimelineWorkspace
from tests.test_motion_preferences import context as preference_context
from tests.test_sfx_catalog import Facts, annotate, scan

context = pytest.fixture(name="context")(preference_context.__wrapped__)


def prepared(context):
    workspace = TimelineWorkspace.from_project(context.project)
    library = context.raw.parent / "library"
    library.mkdir()
    (library / "private-project-name.wav").write_bytes(b"same sound")
    service = SfxCatalogService(workspace, roots={"test": library}, analyzer=Facts())
    original = scan(service)
    generation = annotate(
        service,
        original["generationId"],
        original["entries"][0]["entryId"],
        {
            "curation": {"description": "Airy confirmation", "category": "interface"},
            "rights": {
                "status": "licensed",
                "license": "Fixture",
                "evidenceRef": "private-license",
            },
            "marker": {"sample": 1200, "reviewerRef": "project-listening"},
        },
    )
    view = inspect_sfx_favorites(workspace, root=context.root)
    entry = generation["entries"][0]
    request = {
        "contractVersion": "1.0.0",
        "operation": "favorite-promote",
        "operationId": "favorite-one",
        "actor": "creator",
        "reason": "Reuse this sound identity and selected descriptors",
        "provider": "sample",
        "expectedProviderDocument": view["documentSha256"],
        "expectedGeneration": generation["generationId"],
        "selection": {
            "entryId": entry["entryId"],
            "entryRevision": entry["entryRevision"],
        },
        "fields": ["description", "category"],
    }
    return workspace, service, generation, request


def test_explicit_promotion_preserves_project_and_only_shares_selected_portable_metadata(
    context,
):
    workspace, service, generation, request = prepared(context)
    project_before = {p: p.read_bytes() for p in context.raw.rglob("*") if p.is_file()}
    provider_before = json.loads(context.provider.read_text(encoding="utf-8"))
    result = promote_sfx_favorite(service, request, root=context.root)
    favorite = result["favorite"]
    assert favorite["curation"] == {
        "description": "Airy confirmation",
        "category": "interface",
        "favorite": True,
    }
    assert favorite["sourceSha256"] == generation["entries"][0]["source"]["sha256"]
    serialized = json.dumps(favorite)
    for private in (
        str(context.raw),
        "private-project-name",
        "private-license",
        "project-listening",
    ):
        assert private not in serialized
    assert "rights" not in favorite and "marker" not in favorite
    provider_after = json.loads(context.provider.read_text(encoding="utf-8"))
    assert provider_after["routingOverrides"].pop("sfxFavorites") == [favorite]
    assert provider_after == provider_before
    assert {
        p: p.read_bytes() for p in context.raw.rglob("*") if p.is_file()
    } == project_before
    assert service.show() == generation
    assert inspect_sfx_favorites(workspace, root=context.root)["favorites"] == [
        favorite
    ]


@pytest.mark.parametrize(
    "change", ["provider", "document", "generation", "entry", "fields"]
)
def test_promotion_rejects_wrong_scope_or_stale_inputs_without_a_provider_write(
    context, change
):
    _, service, _, request = prepared(context)
    original = context.provider.read_bytes()
    if change == "provider":
        request["provider"] = "another"
    elif change == "document":
        request["expectedProviderDocument"] = "0" * 64
    elif change == "generation":
        request["expectedGeneration"] = "0" * 64
    elif change == "entry":
        request["selection"]["entryRevision"] = "0" * 64
    else:
        request["fields"] = ["rights"]
    with pytest.raises(SfxCatalogError):
        promote_sfx_favorite(service, request, root=context.root)
    assert context.provider.read_bytes() == original


def test_provider_removal_is_explicit_and_does_not_remove_project_curation(context):
    workspace, service, generation, request = prepared(context)
    promoted = promote_sfx_favorite(service, request, root=context.root)
    remove_sfx_favorite(
        workspace,
        {
            "contractVersion": "1.0.0",
            "operation": "favorite-remove",
            "operationId": "remove-one",
            "actor": "creator",
            "reason": "Stop recommending this shared favorite",
            "provider": "sample",
            "expectedProviderDocument": promoted["documentSha256"],
            "favoriteId": promoted["favorite"]["favoriteId"],
        },
        root=context.root,
    )
    assert inspect_sfx_favorites(workspace, root=context.root)["favorites"] == []
    assert service.show() == generation


def test_explicit_scan_seeds_only_new_matching_bytes_and_never_inherits_rights(
    context, tmp_path
):
    workspace, service, _, request = prepared(context)
    promote_sfx_favorite(service, request, root=context.root)
    preferences = inspect_sfx_favorites(workspace, root=context.root)
    library = tmp_path / "second-library"
    library.mkdir()
    (library / "different-locator.wav").write_bytes(b"same sound")
    (library / "changed.wav").write_bytes(b"different sound")
    second = deepcopy(workspace)
    second.raw_dir = tmp_path / "second-project"
    catalogue = SfxCatalogService(
        second, roots={"test": library}, analyzer=Facts(), favorites=preferences
    )
    generation = scan(catalogue)
    matched = next(
        e for e in generation["entries"] if e["relativePath"] == "different-locator.wav"
    )
    other = next(e for e in generation["entries"] if e["relativePath"] == "changed.wav")
    assert matched["curation"]["description"] == "Airy confirmation"
    assert matched["curation"]["favorite"] is True
    assert matched["rights"]["status"] == "unknown" and matched["marker"] is None
    assert matched["curationOrigin"]["documentSha256"] == preferences["documentSha256"]
    result = catalogue.search("airy confirmation")
    assert result["results"][0]["curationOrigin"] == matched["curationOrigin"]
    assert other["curation"]["favorite"] is False
    assert "curationOrigin" not in other
    annotated = annotate(
        catalogue,
        generation["generationId"],
        matched["entryId"],
        {"curation": {"favorite": False}},
    )
    assert scan(catalogue, annotated["generationId"])["entries"] == annotated["entries"]


@pytest.mark.parametrize(
    "location",
    [
        None,
        "/srv/creator/private.mov",
        r"\\host\private\file.wav",
        "file:///srv/private.mov",
        "api_key=secret",
    ],
)
def test_private_descriptors_cannot_enter_provider_preferences(context, location):
    _, service, generation, request = prepared(context)
    entry = generation["entries"][0]
    private = annotate(
        service,
        generation["generationId"],
        entry["entryId"],
        {"curation": {"description": location or str(context.raw / "private.wav")}},
    )
    request["expectedGeneration"] = private["generationId"]
    before = context.provider.read_bytes()
    with pytest.raises(SfxCatalogError, match="portable"):
        promote_sfx_favorite(service, request, root=context.root)
    assert context.provider.read_bytes() == before


def test_empty_inspection_does_not_create_provider_or_project_state(context):
    workspace = TimelineWorkspace.from_project(context.project)
    before = context.provider.read_bytes()
    shown = inspect_sfx_favorites(workspace, root=context.root)
    assert shown["favorites"] == []
    assert shown["documentSha256"] == hashlib.sha256(before).hexdigest()
    assert context.provider.read_bytes() == before
    assert not workspace.timeline_dir.exists()


@pytest.mark.parametrize("change", ["provider", "identity", "duplicate", "rights"])
def test_seed_context_cannot_adopt_foreign_forged_or_permission_metadata(
    context, change
):
    workspace, service, _, request = prepared(context)
    promote_sfx_favorite(service, request, root=context.root)
    view = inspect_sfx_favorites(workspace, root=context.root)
    if change == "provider":
        view["provider"] = "another"
    elif change == "identity":
        view["favorites"][0]["sourceSha256"] = "0" * 64
    elif change == "duplicate":
        view["favorites"].append(deepcopy(view["favorites"][0]))
    else:
        view["favorites"][0]["curation"]["rights"] = {"status": "licensed"}
    before = context.provider.read_bytes()
    with pytest.raises(SfxCatalogError):
        SfxCatalogService(workspace, roots=service.roots, favorites=view)
    assert context.provider.read_bytes() == before


def test_catalogue_change_between_preflight_and_publication_cannot_be_promoted(
    context, monkeypatch
):
    from avo import sfx_preferences

    _, service, _, request = prepared(context)
    original = sfx_preferences._selected_entry
    calls = []

    def raced(catalogue, selected):
        result = original(catalogue, selected)
        calls.append(True)
        if len(calls) == 1:
            generation, entry = result
            annotate(
                service,
                generation["generationId"],
                entry["entryId"],
                {"curation": {"description": "New current choice"}},
            )
        return result

    monkeypatch.setattr(sfx_preferences, "_selected_entry", raced)
    before = context.provider.read_bytes()
    with pytest.raises(SfxCatalogError, match="generation changed"):
        promote_sfx_favorite(service, request, root=context.root)
    assert context.provider.read_bytes() == before


def test_partial_scan_rejects_changed_favorite_inputs_on_resume(context, tmp_path):
    workspace, service, _, request = prepared(context)
    promote_sfx_favorite(service, request, root=context.root)
    preferences = inspect_sfx_favorites(workspace, root=context.root)
    library = tmp_path / "resume-library"
    library.mkdir()
    for name in ("a.wav", "b.wav"):
        (library / name).write_bytes(b"same sound")
    second = deepcopy(workspace)
    second.raw_dir = tmp_path / "resume-project"
    catalogue = SfxCatalogService(
        second, roots={"test": library}, analyzer=Facts(), favorites=preferences
    )
    partial = scan(catalogue, budget={"maxFiles": 1})
    assert partial["resume"]
    changed = deepcopy(preferences)
    changed["documentSha256"] = "1" * 64
    restarted = SfxCatalogService(
        second, roots={"test": library}, analyzer=Facts(), favorites=changed
    )
    with pytest.raises(SfxCatalogError, match="favorite"):
        scan(restarted, partial["generationId"], resume=partial["resume"])
    assert restarted.show() == partial
    assert len(restarted.analyzer.calls) == 0


def test_provider_change_during_publication_preserves_the_concurrent_preference(
    context, monkeypatch
):
    from avo import sfx_preferences

    _, service, _, request = prepared(context)
    original = sfx_preferences._save_preference

    def concurrent(target, document, raw, candidate, scope, root):
        latest = deepcopy(document)
        latest["displayName"] = "Concurrent creator choice"
        target.write_text(json.dumps(latest), encoding="utf-8")
        return original(target, document, raw, candidate, scope, root)

    monkeypatch.setattr(sfx_preferences, "_save_preference", concurrent)
    with pytest.raises(ValueError, match="changed"):
        promote_sfx_favorite(service, request, root=context.root)
    latest = json.loads(context.provider.read_text(encoding="utf-8"))
    assert latest["displayName"] == "Concurrent creator choice"
    assert "sfxFavorites" not in latest["routingOverrides"]
