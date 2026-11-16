"""Descriptor ranking is transparent, deterministic metadata work."""

from __future__ import annotations

import pytest

from avo.sfx_catalog import SfxCatalogError
from avo.timeline.contracts import validate_document
from test_sfx_catalog import annotate, make_service, scan


def searchable(tmp_path):
    service, _ = make_service(
        tmp_path, {"b-whoosh.wav": b"b", "a-whoosh.wav": b"a", "silence.wav": b"s"}
    )
    result = scan(service)
    for entry in result["entries"]:
        if "silence" in entry["relativePath"]:
            continue
        result = annotate(
            service,
            result["generationId"],
            entry["entryId"],
            {
                "curation": {
                    "material": "metallic",
                    "tags": ["bright", "whoosh", "short"],
                },
                "rights": {
                    "status": "licensed",
                    "license": "MIT",
                    "evidenceRef": "fixture",
                },
            },
        )
    return service, result


def test_descriptor_explanations_rights_audition_and_stable_ties(tmp_path):
    service, generation = searchable(tmp_path)
    result = service.search(
        "short bright metallic whoosh", filters={"rights": ["licensed"]}
    )
    validate_document(result, "avo.sfx-search.schema.json")
    assert result["status"] == "ok"
    assert result["mode"] == "descriptor"
    assert result["generationId"] == generation["generationId"]
    assert [row["relativePath"] for row in result["results"]] == [
        "a-whoosh.wav",
        "b-whoosh.wav",
    ]
    assert result["results"][0]["score"] == result["results"][1]["score"]
    assert result["results"][0]["reasons"]
    assert result["results"][0]["audition"]["startSample"] == 1200
    assert result["results"][0]["rightsState"] == "licensed"
    assert result["counts"]["unknownRights"] == 1


def test_warm_search_does_not_analyze_hash_scan_or_load_models(tmp_path, monkeypatch):
    service, _ = searchable(tmp_path)

    def forbidden(*args, **kwargs):
        raise AssertionError("warm metadata search attempted source work")

    monkeypatch.setattr(type(service.analyzer), "__call__", forbidden)
    monkeypatch.setattr("avo.sfx_catalog.file_fingerprint", forbidden)
    from avo.sfx_catalog import os

    original_scandir = os.scandir

    def guarded(path):
        if str(path).startswith(str(service.roots["test"])):
            forbidden()
        return original_scandir(path)

    monkeypatch.setattr("avo.sfx_catalog.os.scandir", guarded)
    assert service.search("whoosh")["status"] == "ok"
    semantic = service.search("whoosh", mode="semantic")
    assert semantic["status"] == "unavailable"
    assert semantic["mode"] == "semantic"
    assert semantic["results"] == []


def test_generation_bound_paging_and_query_binding(tmp_path):
    service, old = searchable(tmp_path)
    page = service.search("whoosh", limit=1)
    assert page["nextCursor"]
    second = service.search("whoosh", limit=1, cursor=page["nextCursor"])
    assert second["results"][0]["entryId"] != page["results"][0]["entryId"]
    with pytest.raises(SfxCatalogError, match="cursor"):
        service.search("metal", limit=1, cursor=page["nextCursor"])
    scan(service, old["generationId"])
    with pytest.raises(SfxCatalogError, match="cursor|generation"):
        service.search("whoosh", limit=1, cursor=page["nextCursor"])
    historical = service.search(
        "whoosh", generation=old["generationId"], limit=1, cursor=page["nextCursor"]
    )
    assert historical["generationId"] == old["generationId"]


@pytest.mark.parametrize(
    "query,limit",
    [("", 20), (" ", 20), ("a" * 513, 20), ("x", 0), ("x", 101), ("x", True)],
)
def test_query_and_limit_bounds(tmp_path, query, limit):
    service, _ = make_service(tmp_path)
    with pytest.raises(SfxCatalogError):
        service.search(query, limit=limit)


def test_no_match_feature_filters_and_plain_query_text(tmp_path):
    service, _ = searchable(tmp_path)
    assert service.search("explosion")["status"] == "no-match"
    assert (
        service.search("whoosh", filters={"maxDurationSeconds": 0.1})["status"]
        == "no-match"
    )
    assert service.search("whoosh OR 1=1; DROP TABLE sounds")["status"] == "no-match"
    with pytest.raises(SfxCatalogError):
        service.search("whoosh", filters={"rawSql": "select 1"})


def test_explicit_semantic_injection_is_filtered_bound_and_disclosed(tmp_path):
    from avo.sfx_catalog import SfxCatalogService

    service, document = searchable(tmp_path)

    class Ranker:
        calls = []

        def rank(self, generation, request):
            self.calls.append(request)
            entries = [
                entry
                for entry in generation["entries"]
                if entry["entryId"] in request["entryIds"]
            ]
            return {
                "status": "ready",
                "jointSpace": {
                    "id": "local-fixture",
                    "dimension": 2,
                    "normalization": "l2",
                    "modelDigest": "a" * 64,
                    "preprocessingDigest": "b" * 64,
                    "runtimeDigest": "c" * 64,
                },
                "scores": [
                    {
                        "entryId": entry["entryId"],
                        "entryRevision": entry["entryRevision"],
                        "score": 0.8,
                    }
                    for entry in entries
                ],
                "warnings": [],
            }

    ranker = Ranker()
    selected = SfxCatalogService(
        service.workspace,
        roots=service.roots,
        analyzer=service.analyzer,
        semantic=ranker,
    )
    assert selected.search("whoosh")["mode"] == "descriptor"
    assert ranker.calls == []
    result = selected.search(
        "sound of bright fast movement",
        mode="semantic",
        filters={"rights": ["licensed"]},
    )
    validate_document(result, "avo.sfx-search.schema.json")
    assert result["status"] == "ok"
    assert result["mode"] == "semantic"
    assert result["jointSpace"]["modelDigest"] == "a" * 64
    assert len(result["results"]) == 2
    assert len(ranker.calls[0]["entryIds"]) == 2
    assert result["generationId"] == document["generationId"]


def test_semantic_ranker_cannot_inject_stale_revisions_or_nonfinite_scores(tmp_path):
    from avo.sfx_catalog import SfxCatalogService

    service, _ = searchable(tmp_path)

    class Forged:
        def rank(self, document, request):
            return {
                "status": "ready",
                "jointSpace": {
                    "id": "fake",
                    "dimension": 2,
                    "normalization": "l2",
                    "modelDigest": "a" * 64,
                    "preprocessingDigest": "b" * 64,
                    "runtimeDigest": "c" * 64,
                },
                "scores": [
                    {
                        "entryId": request["entryIds"][0],
                        "entryRevision": "0" * 64,
                        "score": float("nan"),
                    }
                ],
                "warnings": [],
            }

    selected = SfxCatalogService(
        service.workspace, roots=service.roots, semantic=Forged()
    )
    with pytest.raises(SfxCatalogError):
        selected.search("whoosh", mode="semantic")
