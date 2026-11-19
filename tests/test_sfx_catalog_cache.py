"""Warm validation reuse still checks exact bytes and isolates caller mutations."""

from __future__ import annotations

import os
import shutil

import pytest

from avo import sfx_catalog
from avo.sfx_catalog import SCHEMA, SfxCatalogError
from test_sfx_catalog import annotate, make_service, scan


def test_warm_generation_reuses_validation_and_returns_independent_values(
    tmp_path, monkeypatch
):
    service, _ = make_service(tmp_path)
    generation = scan(service)
    shown = service.show()
    shown["entries"][0]["rights"]["status"] = "licensed"
    shown["entries"][0]["curation"]["tags"].append("poison")

    def forbidden(_document, schema=SCHEMA):
        raise AssertionError("unchanged exact generation bytes were validated again")

    monkeypatch.setattr("avo.sfx_catalog._validate", forbidden)
    fresh = type(service)(service.workspace, roots=service.roots).show()
    assert fresh["generationId"] == generation["generationId"]
    assert fresh["entries"][0]["rights"]["status"] == "unknown"
    assert fresh["entries"][0]["curation"]["tags"] == []


def test_same_size_and_timestamp_changed_bytes_never_hit_the_validation_cache(tmp_path):
    service, _ = make_service(tmp_path)
    generation = scan(service)
    service.show()
    path = service.directory / "generations" / f"{generation['generationId']}.json"
    stat = path.stat()
    payload = path.read_bytes()
    changed = payload.replace(b"whoosh.wav", b"wHoosh.wav")
    assert changed != payload and len(changed) == len(payload)
    path.write_bytes(changed)
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    assert (path.stat().st_size, path.stat().st_mtime_ns) == (
        stat.st_size,
        stat.st_mtime_ns,
    )
    with pytest.raises(SfxCatalogError, match="hash|identity|entry"):
        service.show()


def test_validation_reuse_keeps_at_most_two_generation_values(tmp_path):
    service, _ = make_service(tmp_path)
    generation = scan(service)
    identifiers = [generation["generationId"]]
    entry = generation["entries"][0]["entryId"]
    for index in range(3):
        generation = annotate(
            service,
            generation["generationId"],
            entry,
            {"curation": {"tags": [f"tag-{index}"]}},
        )
        identifiers.append(generation["generationId"])
    for identifier in identifiers:
        assert service.show(identifier)["generationId"] == identifier
    assert len(sfx_catalog._VALIDATED_GENERATIONS) <= 2


def test_identical_bytes_at_another_project_path_require_own_validation(
    tmp_path, monkeypatch
):
    first_root = tmp_path / "first"
    first_root.mkdir()
    service, _ = make_service(first_root)
    generation = scan(service)
    service.show()
    second_root = tmp_path / "second"
    second_root.mkdir()
    other, _ = make_service(second_root)
    shutil.copytree(service.directory, other.directory)
    original, calls = sfx_catalog._validate, []

    def tracked(value, schema=SCHEMA):
        calls.append(schema)
        return original(value, schema)

    monkeypatch.setattr(sfx_catalog, "_validate", tracked)
    assert other.show()["generationId"] == generation["generationId"]
    assert SCHEMA in calls
