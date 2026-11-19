"""The SFX catalogue owns metadata, never the selected source library."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from avo.sfx_catalog import SfxCatalogError, SfxCatalogService
from avo.timeline.contracts import validate_document


class Facts:
    identity = {"id": "test-facts", "version": "1", "maxSeconds": 30}

    def __init__(self):
        self.calls = []

    def __call__(self, path, *, source_sha256):
        self.calls.append(Path(path))
        return {
            "sourceSha256": source_sha256,
            "analyzer": self.identity,
            "sampleRate": 48000,
            "channels": 2,
            "sourceSamples": 48000,
            "analyzedSamples": 48000,
            "coverage": "complete",
            "durationSeconds": 1.0,
            "usefulRange": {"startSample": 1200, "endSampleExclusive": 24000},
            "onsets": [1200],
            "onsetCount": 1,
            "onsetCoverage": "complete",
            "energyPeaks": [2400],
            "attackSeconds": 0.025,
            "decaySeconds": 0.45,
            "rms": 0.1,
            "peak": 0.5,
            "spectralCentroidHz": 4200.0,
            "silence": False,
        }


def make_service(tmp_path, files=None, analyzer=None):
    root = tmp_path / "sounds"
    root.mkdir(exist_ok=True)
    for name, data in (files or {"whoosh.wav": b"sound"}).items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    workspace = SimpleNamespace(raw_dir=tmp_path / "project")
    service = SfxCatalogService(
        workspace, roots={"test": root}, analyzer=analyzer or Facts()
    )
    return service, root


def scan(service, expected=None, **kwargs):
    return service.scan(
        expected_generation=expected, actor="test", reason="catalogue fixture", **kwargs
    )


def annotate(service, generation, entry, patch):
    return service.annotate(
        entry,
        patch,
        expected_generation=generation,
        actor="test",
        reason="fixture note",
    )


def test_empty_reads_and_constructor_never_initialize_or_analyze(tmp_path):
    facts = Facts()
    service, _ = make_service(tmp_path, analyzer=facts)
    assert not service.directory.exists()
    assert service.show()["generationId"] is None
    assert service.search("whoosh")["status"] == "no-match"
    assert not service.directory.exists()
    assert facts.calls == []


def test_scan_is_immutable_byte_locked_and_reuses_measurements(tmp_path):
    facts = Facts()
    service, root = make_service(tmp_path, analyzer=facts)
    before = (root / "whoosh.wav").read_bytes()
    first = scan(service)
    validate_document(first, "avo.sfx-catalog.schema.json")
    entry = first["entries"][0]
    assert entry["source"]["sha256"] == hashlib.sha256(before).hexdigest()
    assert first["coverage"]["complete"] is True
    assert entry["rights"]["status"] == "unknown"
    assert "reviewed" not in entry["measurement"]
    again = scan(service, first["generationId"])
    assert len(facts.calls) == 1
    assert service.show(first["generationId"]) == first
    assert again["entries"][0]["entryRevision"] == entry["entryRevision"]
    assert (root / "whoosh.wav").read_bytes() == before
    assert sorted(path.name for path in root.iterdir()) == ["whoosh.wav"]


def test_duplicate_bytes_keep_locator_specific_rights_and_annotations(tmp_path):
    facts = Facts()
    service, _ = make_service(tmp_path, {"a.wav": b"same", "b.wav": b"same"}, facts)
    first = scan(service)
    a, b = first["entries"]
    assert a["entryId"] != b["entryId"]
    assert len(facts.calls) == 1
    changed = annotate(
        service,
        first["generationId"],
        a["entryId"],
        {
            "rights": {
                "status": "licensed",
                "license": "MIT",
                "evidenceRef": "fixture",
            },
            "curation": {
                "material": "metallic",
                "tags": ["bright", "whoosh"],
                "favorite": True,
                "variantGroup": "set-a",
            },
        },
    )
    assert changed["entries"][0]["rights"]["status"] == "licensed"
    assert changed["entries"][1]["rights"]["status"] == "unknown"
    refreshed = scan(service, changed["generationId"])
    assert refreshed["entries"][0]["curation"] == changed["entries"][0]["curation"]
    assert len(facts.calls) == 1


def test_changed_and_missing_sources_preserve_but_stale_manual_evidence(tmp_path):
    facts = Facts()
    service, root = make_service(tmp_path, analyzer=facts)
    first = scan(service)
    entry = first["entries"][0]
    noted = annotate(
        service,
        first["generationId"],
        entry["entryId"],
        {
            "rights": {
                "status": "licensed",
                "license": "MIT",
                "evidenceRef": "fixture",
            },
            "marker": {"sample": 1200, "reviewerRef": "human-review-fixture"},
        },
    )
    (root / "whoosh.wav").write_bytes(b"new bytes")
    changed = scan(service, noted["generationId"])
    updated = changed["entries"][0]
    assert updated["entryId"] == entry["entryId"]
    assert updated["entryRevision"] != entry["entryRevision"]
    assert updated["marker"]["sourceSha256"] == entry["source"]["sha256"]
    assert updated["conflicts"][0]["kind"] == "source-changed"
    assert (
        service.search("whoosh", filters={"rights": ["licensed"]})["status"]
        == "no-match"
    )
    (root / "whoosh.wav").unlink()
    missing = scan(service, changed["generationId"])
    assert missing["entries"][0]["source"]["state"] == "missing"
    assert service.search("whoosh")["status"] == "no-match"
    assert len(facts.calls) == 2


def test_bounded_scan_resume_and_cancel_do_not_claim_missing_or_full_coverage(tmp_path):
    service, _ = make_service(tmp_path, {f"{i}.wav": str(i).encode() for i in range(4)})
    partial = scan(service, budget={"maxFiles": 1})
    assert partial["coverage"]["complete"] is False
    assert partial["coverage"]["processed"] == 1
    assert partial["resume"]
    stopped = scan(
        service,
        partial["generationId"],
        resume=partial["resume"],
        cancelled=lambda: True,
    )
    assert stopped["coverage"]["reason"] == "cancelled"
    assert stopped["entries"][0]["source"]["state"] == "available"
    done = scan(service, stopped["generationId"], resume=stopped["resume"])
    assert len(done["entries"]) == 4
    assert done["coverage"]["complete"] is True


def test_compare_and_swap_retains_concurrent_manual_note(tmp_path):
    service, _ = make_service(tmp_path)
    initial = scan(service)
    entry_id = initial["entries"][0]["entryId"]
    updated = annotate(
        service, initial["generationId"], entry_id, {"curation": {"tags": ["kept"]}}
    )
    with pytest.raises(SfxCatalogError, match="generation"):
        annotate(
            service, initial["generationId"], entry_id, {"curation": {"tags": ["lost"]}}
        )
    with pytest.raises(SfxCatalogError, match="generation"):
        scan(service, initial["generationId"])
    assert service.show() == updated


def test_scan_cannot_overwrite_an_annotation_written_during_analysis(tmp_path):
    facts = Facts()
    service, root = make_service(tmp_path, analyzer=facts)
    initial = scan(service)
    entry_id = initial["entries"][0]["entryId"]
    (root / "whoosh.wav").write_bytes(b"changed")

    class ConcurrentFacts(Facts):
        def __call__(self, path, *, source_sha256):
            annotate(
                service,
                initial["generationId"],
                entry_id,
                {"curation": {"tags": ["concurrent-note"]}},
            )
            return super().__call__(path, source_sha256=source_sha256)

    service.analyzer = ConcurrentFacts()
    with pytest.raises(SfxCatalogError, match="generation"):
        scan(service, initial["generationId"])
    assert service.show()["entries"][0]["curation"]["tags"] == ["concurrent-note"]


def test_source_changed_during_decode_is_not_advertised_available(tmp_path):
    class MutatingFacts(Facts):
        def __call__(self, path, *, source_sha256):
            info = path.stat()
            path.write_bytes(b"other")
            os.utime(path, ns=(info.st_atime_ns, info.st_mtime_ns))
            return super().__call__(path, source_sha256=source_sha256)

    service, _ = make_service(tmp_path, analyzer=MutatingFacts())
    result = scan(service)
    assert result["entries"][0]["source"]["state"] == "unavailable"
    assert result["warnings"][0]["kind"] == "analysis-unavailable"


def test_out_of_range_measured_facts_are_not_published_as_available(tmp_path):
    class ImpossibleFacts(Facts):
        def __call__(self, path, *, source_sha256):
            result = super().__call__(path, source_sha256=source_sha256)
            result["usefulRange"]["endSampleExclusive"] = 48001
            return result

    service, _ = make_service(tmp_path, analyzer=ImpossibleFacts())
    result = scan(service)
    assert result["entries"][0]["source"]["state"] == "unavailable"
    assert result["entries"][0]["measurement"] is None


def test_unsafe_roots_and_symlink_sources_are_never_opened(tmp_path):
    service, root = make_service(tmp_path)
    facts = service.analyzer
    outside = tmp_path / "outside.wav"
    outside.write_bytes(b"private")
    try:
        (root / "escape.wav").symlink_to(outside)
    except OSError:
        pytest.skip("symlinks require platform permission")
    result = scan(service)
    assert result["coverage"]["skipped"] == 1
    assert all(path.name != "escape.wav" for path in facts.calls)
    alias = tmp_path / "alias"
    alias.symlink_to(root, target_is_directory=True)
    bad = SfxCatalogService(
        SimpleNamespace(raw_dir=tmp_path / "other-project"),
        roots={"test": alias},
        analyzer=facts,
    )
    with pytest.raises(SfxCatalogError, match="root|link"):
        scan(bad)


def test_scan_requires_declared_roots_and_metadata_cannot_overlap_source_tree(tmp_path):
    workspace = SimpleNamespace(raw_dir=tmp_path / "project")
    empty = SfxCatalogService(workspace, roots={})
    assert empty.show()["generationId"] is None
    with pytest.raises(SfxCatalogError, match="root"):
        scan(empty)
    root = tmp_path / "project"
    root.mkdir()
    (root / "sound.wav").write_bytes(b"sound")
    overlap = SfxCatalogService(workspace, roots={"test": root}, analyzer=Facts())
    with pytest.raises(SfxCatalogError, match="overlap|read.only"):
        scan(overlap)
    assert not overlap.directory.exists()


def test_byte_budget_stops_before_source_read_and_can_resume(tmp_path):
    facts = Facts()
    service, _ = make_service(tmp_path, analyzer=facts)
    first = scan(service, budget={"maxBytes": 1})
    assert first["coverage"]["reason"] == "byte-budget"
    assert first["coverage"]["processed"] == 0
    assert first["entries"] == []
    assert facts.calls == []
    done = scan(service, first["generationId"], resume=first["resume"])
    assert done["coverage"]["complete"] is True
    assert len(facts.calls) == 1


def test_invalid_annotations_cannot_modify_facts_or_invent_review(tmp_path):
    service, _ = make_service(tmp_path)
    initial = scan(service)
    entry_id = initial["entries"][0]["entryId"]
    for patch in (
        {"measurement": {}},
        {"rights": {"status": "approved"}},
        {"marker": {"sample": 1}},
        {"curation": {"favorite": "yes"}},
    ):
        with pytest.raises(SfxCatalogError):
            annotate(service, initial["generationId"], entry_id, patch)
    assert service.show() == initial


def test_corrupt_oversized_or_escaping_metadata_is_rejected(tmp_path):
    service, _ = make_service(tmp_path)
    initial = scan(service)
    path = service.directory / "generations" / f"{initial['generationId']}.json"
    path.write_text('{"generationId":"forged"}', encoding="utf-8")
    with pytest.raises(SfxCatalogError, match="invalid|hash|generation"):
        service.show()
    with pytest.raises(SfxCatalogError):
        service.show("../../outside")


def test_metadata_reader_bounds_deep_or_oversized_documents(tmp_path, monkeypatch):
    service, _ = make_service(tmp_path)
    initial = scan(service)
    path = service.directory / "generations" / f"{initial['generationId']}.json"
    monkeypatch.setattr("avo.sfx_catalog.MAX_DOCUMENT_BYTES", 100)
    with pytest.raises(SfxCatalogError, match="byte budget"):
        service.show()
    monkeypatch.setattr("avo.sfx_catalog.MAX_DOCUMENT_BYTES", 16384)
    path.write_text("[" * 2000 + "0" + "]" * 2000, encoding="utf-8")
    with pytest.raises(SfxCatalogError, match="invalid"):
        service.show()
