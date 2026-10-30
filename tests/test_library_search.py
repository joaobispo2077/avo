"""Library search is bounded discovery over canonical, source-bound evidence."""

from __future__ import annotations

import hashlib
import json
import shutil
from copy import deepcopy
from pathlib import Path

import pytest

from avo.library import search
from avo.library.rules import LibraryError, observation
from avo.library.service import LibraryService
from library_fixtures import install_provider, make_library, transcript_payload


@pytest.fixture
def library(tmp_path, monkeypatch, repo_root):
    install = tmp_path / "install"
    install_provider(install)
    (install / "schemas").mkdir(exist_ok=True)
    shutil.copyfile(
        repo_root / "schemas/avo.library.schema.json",
        install / "schemas/avo.library.schema.json",
    )
    monkeypatch.setenv("AVO_ROOT", str(install))
    fixture = make_library(tmp_path / "footage")
    fixture.probe.results = {
        p: {"durationSeconds": 10.0, "audio": True} for p in fixture.files
    }
    service = LibraryService(fixture.root, "example", probe=fixture.probe)
    service.scan(recursive=True)
    return service, fixture


def set_records(service, mutate):
    head = service.store.head()
    inventory = deepcopy(service.store.get(head["inventoryRef"]))
    mutate(inventory["recordings"])
    ref = service.store.put("inventory", inventory)
    with service.store.exclusive():
        service.store.publish({**head, "inventoryRef": ref}, head["headHash"])


def admit_transcript(service, source, *, text="ação rápida xpto", mutate=None):
    payload = transcript_payload(source, text=text)
    source_hash = payload["source"]["sha256"]
    if mutate:
        mutate(payload)
    output = (
        service.root
        / "edit"
        / "library"
        / "transcripts"
        / f"{source.parent.name}-{source.stem}.json"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    output.write_bytes(data)
    ref = {
        "path": output.relative_to(service.root).as_posix(),
        "sha256": hashlib.sha256(data).hexdigest(),
        "sourceSha256": source_hash,
        "model": payload["model"],
        "requestedLanguage": "en",
        "observation": observation(source),
    }
    relative = source.relative_to(service.root).as_posix()
    set_records(
        service,
        lambda rows: next(row for row in rows if row["path"] == relative).update(
            transcript=ref
        ),
    )
    return output, ref


def test_metadata_search_is_literal_case_accent_folded_and_scoped(library):
    service, _fixture = library
    result = search.search_library(service, "CAMERA-A", mode="metadata")
    assert result["status"] == "ok"
    assert len(result["results"]) == 2
    assert all(row["path"].startswith("camera-a/") for row in result["results"])
    assert all(
        row["metadataOnly"] and row["start"] is None and row["end"] is None
        for row in result["results"]
    )
    assert result["coverage"]["unsearchedSpeech"] == 6
    for query in ("camera OR take", "' OR 1=1 --", "%", '"'):
        assert search.search_library(service, query)["results"] == []


def test_cold_projection_reports_bounded_actual_item_progress(library, monkeypatch):
    service, _fixture = library
    head, states, generation, _stamp = search._snapshot(service)
    states *= 35
    calls = []
    monkeypatch.setattr(
        service, "activity", lambda *args, **kwargs: calls.append((args, kwargs))
    )
    search._projection_rows(service, head, states, generation)
    assert [args[0] for args, _kwargs in calls] == [0, 100, 200, 210]
    assert all(args[1] == 210 for args, _kwargs in calls)
    assert calls[0][0][2] == states[0]["recording"]["path"]
    assert calls[-1][0][2] == states[-1]["recording"]["path"]
    assert all(kwargs == {"phase": "building-search"} for _args, kwargs in calls)


def test_speech_match_has_original_time_range_and_bounded_evidence(library):
    service, fixture = library
    _, ref = admit_transcript(service, fixture.files[1])
    result = search.search_library(service, "ACAO RAPIDA", mode="speech")
    assert len(result["results"]) == 1
    row = result["results"][0]
    assert row["path"] == fixture.files[1].relative_to(fixture.root).as_posix()
    assert row["matchType"] == "speech" and not row["metadataOnly"]
    assert row["start"] == 0.0 and row["end"] == pytest.approx(0.3)
    assert "ação rápida" in row["excerpt"] and len(row["excerpt"]) <= 240
    assert row["evidence"]["sha256"] == ref["sha256"]
    assert row["generation"] == result["generation"]
    assert result["coverage"]["speechSearchable"] == 1
    assert result["coverage"]["unsearchedSpeech"] == 5


def test_group_date_duration_and_transcript_filters(library):
    service, fixture = library
    admit_transcript(service, fixture.files[1])
    head = service.store.head()
    proposal = service.store.get(head["proposalRef"])
    group = next(group for group in proposal["groups"] if group["path"] == "camera-a")
    set_records(
        service,
        lambda rows: rows[0]["metadata"].update(
            durationSeconds=None, recordingDate=None
        ),
    )
    set_records(
        service,
        lambda rows: [
            row["metadata"].update(recordingDate="2026-10-29") for row in rows[1:]
        ],
    )
    result = search.search_library(
        service,
        "take",
        mode="metadata",
        filters={
            "group": group["id"],
            "minDuration": 5,
            "maxDuration": 15,
            "dateFrom": "2026-10-01",
            "dateTo": "2026-10-30",
            "transcriptStatus": "ready",
        },
    )
    assert [row["path"] for row in result["results"]] == [
        fixture.files[1].relative_to(fixture.root).as_posix()
    ]
    assert result["coverage"]["omittedUnknown"] == 1
    assert (
        search.search_library(service, "take", filters={"minDuration": 11})["results"]
        == []
    )


def test_pagination_is_deterministic_and_bound_to_query_and_generation(library):
    service, fixture = library
    first = search.search_library(service, "take", mode="metadata", limit=2)
    second = search.search_library(
        service, "take", mode="metadata", limit=2, cursor=first["nextCursor"]
    )
    third = search.search_library(
        service, "take", mode="metadata", limit=2, cursor=second["nextCursor"]
    )
    all_rows = first["results"] + second["results"] + third["results"]
    assert len({row["id"] for row in all_rows}) == 6
    assert [row["recordingId"] for row in all_rows] == sorted(
        row["recordingId"] for row in all_rows
    )
    assert third["nextCursor"] is None
    with pytest.raises(LibraryError):
        search.search_library(
            service, "camera", mode="metadata", limit=2, cursor=first["nextCursor"]
        )
    fixture.files[0].write_bytes(b"changed inventory source")
    service.scan(recursive=True)
    with pytest.raises(LibraryError):
        search.search_library(
            service, "take", mode="metadata", limit=2, cursor=first["nextCursor"]
        )


@pytest.mark.parametrize(
    "options",
    [
        {"query": ""},
        {"query": " "},
        {"query": "x" * 513},
        {"query": "take", "limit": 0},
        {"query": "take", "limit": 101},
        {"query": "take", "limit": True},
        {"query": "take", "mode": "raw"},
        {"query": "take", "filters": {"minDuration": -1}},
        {"query": "take", "filters": {"minDuration": 5, "maxDuration": 2}},
        {"query": "take", "filters": {"dateFrom": "bad"}},
        {"query": "take", "filters": {"unknown": "x"}},
    ],
)
def test_invalid_query_inputs_are_rejected(library, options):
    service, _ = library
    with pytest.raises(LibraryError):
        search.search_library(service, **options)


def test_source_change_invalidates_speech_without_hashing_media(library, monkeypatch):
    service, fixture = library
    admit_transcript(service, fixture.files[1])
    assert search.search_library(service, "xpto", mode="speech")["results"]
    fixture.files[1].write_bytes(b"changed source outside the last inventory")
    monkeypatch.setattr(
        "avo.library.rules.source_lock",
        lambda *_: pytest.fail("query hashed source media"),
    )
    monkeypatch.setattr(
        "avo.transcribe.source_fingerprint",
        lambda *_: pytest.fail("query hashed source media"),
    )
    result = search.search_library(service, "xpto", mode="speech")
    assert result["results"] == []
    assert result["coverage"]["staleTranscripts"] == 1
    metadata = search.search_library(service, "camera-a", mode="metadata")
    assert any(row["metadataFreshness"] == "stale" for row in metadata["results"])


@pytest.mark.parametrize(
    "damage",
    [
        "output-bytes",
        "source-hash",
        "negative-time",
        "outside-duration",
        "model",
        "schema",
    ],
)
def test_invalid_transcripts_do_not_contaminate_speech_results(library, damage):
    service, fixture = library

    def corrupt(payload):
        if damage == "source-hash":
            payload["source"]["sha256"] = "0" * 64
        elif damage == "negative-time":
            payload["words"][0]["start"] = -1
        elif damage == "outside-duration":
            payload["words"][-1]["end"] = 100
        elif damage == "schema":
            payload.pop("engine")

    output, _ = admit_transcript(service, fixture.files[1], mutate=corrupt)
    if damage == "output-bytes":
        output.write_bytes(b"not admitted output bytes")
    elif damage == "model":
        set_records(
            service,
            lambda rows: next(row for row in rows if row["transcript"])[
                "transcript"
            ].update(model="another-model"),
        )
    result = search.search_library(service, "xpto", mode="speech")
    assert result["results"] == []
    assert result["coverage"]["invalidTranscripts"] == 1
    assert len(search.search_library(service, "take", mode="metadata")["results"]) == 6


def test_projection_rebuilds_after_corruption_without_rewriting_authority(library):
    service, fixture = library
    before = service.store.head()
    first = search.search_library(service, "take", mode="metadata")
    cache = fixture.root / "edit/library/cache/search.sqlite"
    assert cache.is_file()
    cache.write_bytes(b"corrupted projection")
    rebuilt = search.search_library(service, "take", mode="metadata")
    assert rebuilt["results"] == first["results"]
    assert service.store.head() == before
    assert "cache-rebuilt" in rebuilt["coverage"]["limitations"]


@pytest.mark.parametrize("reason", ["fts5-unavailable", "network-storage"])
def test_projection_fallback_is_labeled_and_remains_literal(
    library, monkeypatch, reason
):
    service, fixture = library
    if reason == "fts5-unavailable":
        monkeypatch.setattr(search, "_supports_fts", lambda _connection: False)
    else:
        monkeypatch.setattr(search, "_network_storage", lambda _root: True)
    result = search.search_library(service, "take", mode="metadata")
    assert len(result["results"]) == 6
    assert reason in result["coverage"]["limitations"]
    assert search.search_library(service, "take OR camera")["results"] == []
    if reason == "network-storage":
        assert not (fixture.root / "edit/library/cache/search.sqlite").exists()


def test_closed_root_search_uses_memory_without_creating_metadata(library):
    service, fixture = library
    receipt = fixture.root / "edit/cleanup/preservation-result.json"
    receipt.parent.mkdir()
    receipt.write_text("{}", encoding="utf-8")
    result = search.search_library(service, "take", mode="metadata")
    assert len(result["results"]) == 6
    assert "closed-project" in result["coverage"]["limitations"]
    assert not (fixture.root / "edit/library/cache").exists()


@pytest.mark.parametrize("limit", ["bytes", "words"])
def test_transcript_admission_enforces_bounded_inputs(library, monkeypatch, limit):
    service, fixture = library
    admit_transcript(service, fixture.files[1])
    constant = "MAX_TRANSCRIPT_BYTES" if limit == "bytes" else "MAX_TRANSCRIPT_WORDS"
    monkeypatch.setattr(search, constant, 2)
    result = search.search_library(service, "xpto", mode="speech")
    assert result["results"] == []
    assert result["coverage"]["invalidTranscripts"] == 1


def test_warm_search_reuses_valid_projection_and_exposes_public_generation(
    library, monkeypatch
):
    service, fixture = library
    admit_transcript(service, fixture.files[1])
    first = search.search_library(service, "xpto", mode="speech")
    monkeypatch.setattr(
        search,
        "_projection_rows",
        lambda *_: pytest.fail("unchanged search rebuilt the whole projection"),
    )
    repeated = search.search_library(service, "xpto", mode="speech")
    assert repeated["results"] == first["results"]
    assert repeated["generation"] == search.generation_for(service)


def test_long_speech_matches_bound_excerpts_and_keep_valid_ranges(library):
    service, fixture = library
    admit_transcript(service, fixture.files[1], text=" ".join(["xpto"] * 50))
    result = search.search_library(service, "xpto", mode="speech")
    assert len(result["results"]) == 2
    assert all(
        len(row["excerpt"]) <= 240 and 0 <= row["start"] < row["end"] <= 10
        for row in result["results"]
    )


@pytest.mark.parametrize("parent_kind", ["source", "transcript"])
def test_new_parent_link_invalidates_warm_cache_even_when_leaf_identity_matches(
    library, tmp_path, parent_kind
):
    service, fixture = library
    output, _ = admit_transcript(service, fixture.files[1])
    assert search.search_library(service, "xpto", mode="speech")["results"]
    parent = fixture.files[1].parent if parent_kind == "source" else output.parent
    outside = tmp_path / f"outside-{parent_kind}"
    parent.rename(outside)
    try:
        parent.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("Native directory links require privileges")
    result = search.search_library(service, "xpto", mode="speech")
    assert result["results"] == []
    assert result["coverage"]["unsearchedSpeech"] == 6


def test_small_transcript_read_requests_are_proportional_to_actual_file(
    library, monkeypatch
):
    service, fixture = library
    output, _ = admit_transcript(service, fixture.files[1])
    original_open = Path.open
    requests = []

    class ObservedRead:
        def __init__(self, stream):
            self.stream = stream

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.stream.close()

        def fileno(self):
            return self.stream.fileno()

        def read(self, count=-1):
            requests.append(count)
            return self.stream.read(count)

    def observe(path, *args, **kwargs):
        stream = original_open(path, *args, **kwargs)
        return ObservedRead(stream) if path == output and args == ("rb",) else stream

    monkeypatch.setattr(Path, "open", observe)
    assert search.search_library(service, "xpto", mode="speech")["results"]
    assert requests and all(
        0 < count <= output.stat().st_size * 2 for count in requests
    )


def test_warm_search_refreshes_only_bounded_candidates_and_labels_index_coverage(
    library, monkeypatch
):
    service, fixture = library
    admit_transcript(service, fixture.files[1])
    search.search_library(service, "xpto", mode="speech")
    observed = search._observed
    paths = []

    def counted(service, path, parents):
        paths.append(path)
        return observed(service, path, parents)

    monkeypatch.setattr(search, "_observed", counted)
    result = search.search_library(service, "xpto", mode="speech", limit=1)
    assert len(result["results"]) == 1
    assert len(paths) <= 2
    assert result["coverage"]["freshnessScope"] == "returned-candidates"
    assert result["coverage"]["indexCoverage"] == "snapshot"
    assert result["coverage"]["observedRecordings"] == 1


def test_cached_speech_text_is_reconstructed_from_validated_transcript(library):
    import sqlite3

    service, fixture = library
    admit_transcript(service, fixture.files[1])
    first = search.search_library(service, "xpto", mode="speech")
    cache = fixture.root / "edit/library/cache/search.sqlite"
    with sqlite3.connect(cache) as connection:
        rowid, raw = connection.execute(
            "SELECT rowid,body FROM documents WHERE kind='speech'"
        ).fetchone()
        forged = json.loads(raw)
        forged["text"] = "fabricated quoted speech xpto"
        connection.execute(
            "UPDATE documents SET body=? WHERE rowid=?", (json.dumps(forged), rowid)
        )
    repeated = search.search_library(service, "xpto", mode="speech")
    assert repeated["results"][0]["excerpt"] == first["results"][0]["excerpt"]
    assert "fabricated" not in repeated["results"][0]["excerpt"]
