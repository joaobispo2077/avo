"""Selection revalidates exact sources without starting a composition."""

import pytest

from avo.library.rules import LibraryError
from avo.library.service import LibraryService
from library_fixtures import install_provider, transcript_payload

pytestmark = pytest.mark.integration


def test_existing_transcript_and_bounded_exact_handoff(tmp_path, monkeypatch):
    import json
    from uuid import uuid4

    install_provider(tmp_path / "install")
    monkeypatch.setenv("AVO_ROOT", str(tmp_path / "install"))
    root = tmp_path / "footage"
    root.mkdir()
    source = root / "xpto-01.mp4"
    source.write_bytes(b"raw evidence")
    service = LibraryService(root, "example", probe=lambda _: {"durationSeconds": 20})
    record = service.store.get(service.scan()["inventoryRef"])["recordings"][0]
    path = root / "edit/transcripts/xpto-01.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(transcript_payload(source, text="existing footage evidence")),
        encoding="utf-8",
    )
    service.admit_transcript(record["id"], "edit/transcripts/xpto-01.json")
    matches = service.search("evidence", mode="speech")
    assert matches["results"] and matches["results"][0]["start"] >= 0
    head = service.store.head()
    request = {
        "schemaVersion": 1,
        "kind": "handoffRequest",
        "requestId": uuid4().hex,
        "libraryId": head["libraryId"],
        "expectedHeadHash": head["headHash"],
        "generation": matches["generation"],
        "recordingIds": [record["id"]],
        "ranges": {record["id"]: {"start": 0.0, "end": 1.0}},
    }
    result = service.select(request)
    handoff = service.store.get(result["refs"]["handoff"])
    assert len(handoff["recordings"]) == 1
    assert handoff["recordings"][0]["fingerprint"]["sha256"]
    source.write_bytes(b"changed after discovery")
    with pytest.raises(LibraryError):
        service.select(request)
    assert not (root / "edit/edl.draft.json").exists()


def test_handoff_rejects_unselected_library_and_out_of_range(tmp_path, monkeypatch):
    install_provider(tmp_path / "install")
    monkeypatch.setenv("AVO_ROOT", str(tmp_path / "install"))
    root = tmp_path / "footage"
    root.mkdir()
    service = LibraryService(root, "example")
    service.scan()
    with pytest.raises(LibraryError):
        service.select({"libraryId": "different"})
