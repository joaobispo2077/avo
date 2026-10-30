"""Offline review treats names as data and never grants approval."""

from avo.library.review import render_review


def test_offline_review_escapes_names_and_keeps_all_mappings(tmp_path):
    proposal = {
        "proposalId": "sample",
        "revision": 1,
        "summary": {"total": 250},
        "groups": [
            {
                "id": "g",
                "label": "xpto",
                "path": "xpto",
                "rationale": "Filename evidence",
                "evidence": [],
            }
        ],
        "actions": [
            {
                "actionId": str(i),
                "recordingId": str(i),
                "from": f"clip-{i}</script>.mp4",
                "to": f"xpto/clip-{i}.mp4",
                "groupId": "g",
                "status": "move",
                "reason": "Filename",
            }
            for i in range(250)
        ],
    }
    context = {
        "root": str(tmp_path),
        "provider": "example",
        "libraryId": "lib",
        "headHash": "a" * 64,
        "proposalRef": {"id": "b" * 64, "sha256": "b" * 64},
    }
    result = render_review(tmp_path, proposal, context)
    html = result["html"].read_text(encoding="utf-8")
    text = result["text"].read_text(encoding="utf-8")
    assert "clip-0</script>" not in html
    assert "Content-Security-Policy" in html and "connect-src 'none'" in html
    assert "current-tree" in html and "proposed-tree" in html
    assert "inspector" in html and "Export requested changes" in html
    assert "clip-249" in text and "xpto/clip-249.mp4" in text
    assert "http://" not in html and "https://" not in html


def test_review_has_no_native_mutation_authority(tmp_path):
    proposal = {
        "proposalId": "empty",
        "revision": 1,
        "groups": [],
        "actions": [],
        "summary": {},
    }
    paths = render_review(
        tmp_path,
        proposal,
        {
            "root": str(tmp_path),
            "provider": "example",
            "libraryId": "lib",
            "headHash": "a",
            "proposalRef": {"id": "b", "sha256": "b"},
        },
    )
    html = paths["html"].read_text(encoding="utf-8")
    assert "fetch(" not in html
    assert "showDirectoryPicker" not in html
    assert "createWritable" not in html
    assert "Snapshot" in html


def test_review_retains_nested_paths_and_unknown_observations_in_snapshot(tmp_path):
    import json
    import re

    proposal = {
        "proposalId": "nested",
        "revision": 1,
        "summary": {},
        "groups": [
            {
                "id": "g",
                "label": "XPTO",
                "path": "xpto/project",
                "rationale": "Explicit grouping",
                "evidence": [],
            }
        ],
        "actions": [
            {
                "actionId": "a",
                "recordingId": "recording",
                "from": "camera/day/take.mp4",
                "to": "xpto/project/take.mp4",
                "groupId": "g",
                "status": "move",
                "reason": "Explicit grouping",
                "sizeBytes": 100,
                "durationSeconds": None,
            }
        ],
    }
    paths = render_review(
        tmp_path,
        proposal,
        {
            "root": str(tmp_path),
            "provider": "example",
            "libraryId": "lib",
            "headHash": "a",
            "proposalRef": {"id": "b", "sha256": "b"},
        },
    )
    html = paths["html"].read_text(encoding="utf-8")
    match = re.search(
        r'<script id="library-data" type="application/json">(.*?)</script>', html
    )
    snapshot = json.loads(match.group(1))

    assert snapshot["proposal"]["actions"] == proposal["actions"]
    text = paths["text"].read_text(encoding="utf-8")
    assert "camera/day/take.mp4 -> xpto/project/take.mp4" in text
