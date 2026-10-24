"""Selected past entries narrow evidence without opening excluded projects."""

from __future__ import annotations

import json

import pytest

from avo.direction.rules import DirectionError
from avo.direction.sources import collect_sources
from tests.test_direction_sources import _legacy, _write


def test_subset_accounts_every_entry_but_consumes_only_selected_documents(tmp_path):
    root = tmp_path / "neutral"
    _legacy(root, "selected", "Z:/neutral/selected")
    _write(root / "learndowns/excluded/learndown.json", "{malformed-excluded-content")
    result = collect_sources(root, "neutral", entries=["selected"])
    rows = {entry["entryId"]: entry for entry in result["entries"]}
    assert rows["excluded"]["disposition"] == "excluded"
    assert rows["excluded"]["documents"] == []
    assert result["coverage"]["discovered"] == 2
    assert result["coverage"]["excluded"] == 1
    assert result["coverage"]["unavailable"] == 0
    assert {record["entryId"] for record in result["evidenceRecords"]} == {"selected"}


def test_duplicate_selected_entries_are_not_additional_votes(tmp_path):
    root = tmp_path / "neutral"
    _legacy(root, "selected", "Z:/neutral/selected")
    result = collect_sources(root, "neutral", entries=["selected", "selected"])
    assert result["coverage"]["distinctProjects"] == 1
    assert result["coverage"]["included"] == 1


@pytest.mark.parametrize(
    "selection", [["../outside"], ["missing"], ["other-provider/entry"]]
)
def test_invalid_or_foreign_subset_is_rejected_without_writes(tmp_path, selection):
    root = tmp_path / "neutral"
    _legacy(root, "selected", "Z:/neutral/selected")
    before = {
        str(path.relative_to(root)): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }
    with pytest.raises(DirectionError):
        collect_sources(root, "neutral", entries=selection)
    after = {
        str(path.relative_to(root)): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }
    assert after == before


def test_declared_continuation_keeps_original_identity_when_new_alias_sorts_first(
    tmp_path,
):
    root = tmp_path / "neutral"
    _legacy(root, "original", "Z:/neutral/original")
    first = collect_sources(root, "neutral")
    identity = first["entries"][0]["sourceProjectId"]
    _write(
        root / "learndowns/aaa-continuation/catalogo.json",
        {
            "provider": "neutral",
            "entryId": "aaa-continuation",
            "baseEntryId": "original",
            "videoId": "aaa-new-alias",
            "rawDir": "A:/a-different-archival-locator",
            "techniques": [
                {"id": "example", "summary": "One more record from the same film."}
            ],
        },
    )
    second = collect_sources(root, "neutral")
    assert {entry["sourceProjectId"] for entry in second["entries"]} == {identity}
    assert second["coverage"]["distinctProjects"] == 1
    assert "Z:/neutral/original" not in json.dumps(second)
