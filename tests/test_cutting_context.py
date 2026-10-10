from pathlib import Path

from avo.adapters.understand.cutting_context import CuttingContextAdapter


def test_missing_configured_context_capability_remains_unknown(tmp_path):
    adapter = CuttingContextAdapter(tmp_path, {})
    result = adapter.analyze_pause(
        {"locator": "original.mkv", "fingerprint": {"sha256": "a" * 64}},
        {"pauseId": "p"},
        {
            "sourceRef": {"locator": "original.mkv", "sha256": "a" * 64},
            "routing": {"streamIndex": 0},
        },
        sync_ref={"locator": "sync.json", "sha256": "b" * 64},
    )
    assert result["context"]["dispensable"] is None
    assert result["modelIdentity"] is None
    assert result["status"] == "unknown"


def test_configured_context_is_source_bound_and_never_certifies_audio(tmp_path):
    from avo.timeline.contracts import file_fingerprint

    source_path = tmp_path / "original.mkv"
    source_path.write_bytes(b"original")
    sha = file_fingerprint(source_path)["sha256"]
    candidate = {
        "pauseId": "p",
        "sourceRange": {
            "sourceId": "s",
            "startTicks": 100,
            "endTicksExclusive": 500,
            "timebase": {"num": 1, "den": 1000},
        },
        "adjacentWords": {"before": "Uma", "after": "ideia"},
    }

    class Watch:
        def review(self, source, **request):
            assert Path(source) == source_path
            assert request["scope"] == "windows"
            return {
                "status": "pass",
                "model": {"id": "configured"},
                "promptSha256": "c" * 64,
                "findings": [{"observed": "pauseId=p; decision=dispensable"}],
            }

    adapter = CuttingContextAdapter(
        tmp_path,
        {},
        watch=Watch(),
        raw_dir=tmp_path,
        watch_request={
            "model_pin": {"modelId": "configured"},
            "policy": {"concurrency": 1, "vramCeilingBytes": 7 * 1024**3},
        },
    )
    result = adapter.analyze_pause(
        {"locator": str(source_path), "fingerprint": {"sha256": sha}},
        candidate,
        {
            "sourceRef": {"locator": str(source_path), "sha256": sha},
            "routing": {"streamIndex": 0},
        },
        sync_ref={"locator": "sync.json", "sha256": "b" * 64},
    )
    assert result["context"]["dispensable"] is True
    assert result["sourceRef"]["sha256"] == sha
    assert "acousticComplete" not in result
    assert result["status"] == "inferred"


def test_native_pause_candidate_without_id_uses_bound_hash():
    from avo.adapters.understand.cutting_context import _pause_id
    from avo.timeline.contracts import content_hash

    candidate = {
        "sourceRange": {
            "sourceId": "s",
            "startTicks": 10,
            "endTicksExclusive": 20,
            "timebase": {"num": 1, "den": 1000},
        },
        "evidence": {"adjacentWords": {"before": "Uma", "after": "ideia"}},
    }
    assert _pause_id(candidate) == "pause-" + content_hash(candidate)[:16]


def test_configured_watch_unavailable_preserves_unknown_pause_context(tmp_path):
    from avo.timeline.contracts import file_fingerprint
    from avo.timeline.ports import ToolError

    source = tmp_path / "original.mkv"
    source.write_bytes(b"original")
    sha = file_fingerprint(source)["sha256"]

    class Watch:
        def review(self, *args, **kwargs):
            raise ToolError("WATCH_UNAVAILABLE", "endpoint offline")

    adapter = CuttingContextAdapter(
        tmp_path,
        {},
        watch=Watch(),
        raw_dir=tmp_path,
        watch_request={
            "model_pin": {"id": "configured"},
            "policy": {"concurrency": 1, "vramCeilingBytes": 7 * 1024**3},
        },
    )
    result = adapter.analyze_pause(
        {"locator": str(source), "fingerprint": {"sha256": sha}},
        {
            "sourceRange": {
                "sourceId": "one",
                "startTicks": 10,
                "endTicksExclusive": 20,
                "timebase": {"num": 1, "den": 1000},
            }
        },
        {
            "sourceRef": {"locator": str(source), "sha256": sha},
            "routing": {"streamIndex": 0},
        },
    )
    assert result["status"] == "unknown"
    assert result["context"]["dispensable"] is None
    assert result["modelIdentity"] is None
    assert "endpoint offline" in result["uncertainty"][0]
