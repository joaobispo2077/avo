from __future__ import annotations

import json
import os
import subprocess
from urllib.parse import quote

import pytest

from avo.timeline import import_relink
from avo.timeline.contracts import file_fingerprint

REFERENCE = "/tracks/children/0/children/0/media_reference"


def _ref(target="file:///lost/take.mov", *, pointer=REFERENCE, active=True, **extra):
    return {"pointer": pointer, "targetUrl": target, "active": active, **extra}


def _probe(paths):
    return {
        "sources": [
            {
                "locator": str(path),
                "fingerprint": file_fingerprint(path),
                "durationSeconds": 3.0,
                "streams": {"video": [{"index": 0, "frameRate": "24/1"}], "audio": []},
            }
            for path in paths
        ]
    }


def _file(root, name="take.mov", content=b"original bytes"):
    root.mkdir(parents=True, exist_ok=True)
    path = root / name
    path.write_bytes(content)
    return path


def test_matching_file_is_fingerprinted_evidence_without_selection(tmp_path):
    path = _file(tmp_path / "declared")
    mappings, findings = import_relink.discover_candidates(
        [_ref()], [path.parent], probe=_probe
    )
    mapping = mappings[REFERENCE]
    assert mapping["status"] == "unresolved"
    assert "selected" not in mapping
    assert mapping["candidates"] == [
        {
            "path": str(path.resolve()),
            "fingerprint": {
                "path": str(path.resolve()),
                "sha256": file_fingerprint(path)["sha256"],
                "sizeBytes": len(b"original bytes"),
            },
            "properties": {
                "durationSeconds": 3.0,
                "streams": {"video": [{"index": 0, "frameRate": "24/1"}], "audio": []},
            },
            "matchBasis": "filename-only",
        }
    ]
    assert findings and all(item["blocking"] for item in findings)
    assert all(
        set(item)
        == {"code", "scope", "message", "blocking", "evidenceOrigin", "remediation"}
        for item in findings
    )


def test_search_has_no_implicit_root_or_target_path_access(tmp_path):
    outside = _file(tmp_path / "not-declared")
    probed = []
    mappings, _ = import_relink.discover_candidates(
        [_ref(outside.as_uri())], [], probe=lambda paths: probed.extend(paths)
    )
    assert mappings[REFERENCE] == {"status": "unresolved", "candidates": []}
    assert probed == []


def test_duplicate_filenames_retain_distinct_current_byte_identities(tmp_path):
    first = _file(tmp_path / "first", content=b"first camera")
    second = _file(tmp_path / "second", content=b"second camera")
    mappings, findings = import_relink.discover_candidates(
        [_ref()], [first.parent, second.parent], probe=_probe
    )
    assert mappings[REFERENCE]["status"] == "ambiguous"
    assert {item["path"] for item in mappings[REFERENCE]["candidates"]} == {
        str(first),
        str(second),
    }
    assert (
        len(
            {
                item["fingerprint"]["sha256"]
                for item in mappings[REFERENCE]["candidates"]
            }
        )
        == 2
    )
    assert any(
        item["code"] == "OTIO_MEDIA_AMBIGUOUS" and item["scope"] == REFERENCE
        for item in findings
    )


@pytest.mark.parametrize(
    "target",
    [
        "file:///D:/old/" + quote("ação café #1.mov"),
        "file://localhost/D:/old/" + quote("ação café #1.mov"),
        "D:\\old\\ação café #1.mov",
        "/mnt/d/old/ação café #1.mov",
    ],
)
def test_decoded_unicode_basename_supports_local_uri_native_and_wsl_forms(
    tmp_path, target
):
    path = _file(tmp_path / "declared", "ação café #1.mov")
    mappings, _ = import_relink.discover_candidates(
        [_ref(target)], [path.parent], probe=_probe
    )
    assert [item["path"] for item in mappings[REFERENCE]["candidates"]] == [str(path)]


@pytest.mark.parametrize(
    "name,target",
    [
        ("take-%04d.mov", "C:\\old\\take-%04d.mov"),
        ("literal%20.mov", "C:\\old\\literal%20.mov"),
    ],
)
def test_native_filename_percent_spelling_is_literal_not_glob_or_uri(
    tmp_path, name, target
):
    path = _file(tmp_path / "declared", name)
    _file(path.parent, "take-0001.mov")
    _file(path.parent, "literal .mov")
    mappings, _ = import_relink.discover_candidates(
        [_ref(target)], [path.parent], probe=_probe
    )
    assert [item["path"] for item in mappings[REFERENCE]["candidates"]] == [str(path)]


def test_explicit_basename_and_repeated_references_reuse_probe_and_paths(tmp_path):
    path = _file(tmp_path / "declared")
    calls = []

    def probe(paths):
        calls.extend(paths)
        return _probe(paths)

    second = REFERENCE + "-repeat"
    mappings, _ = import_relink.discover_candidates(
        [
            _ref(basename="take.mov"),
            _ref("unsupported://original", basename="take.mov", pointer=second),
        ],
        [path.parent, path.parent],
        probe=probe,
    )
    assert calls == [path.resolve()]
    assert mappings[REFERENCE] == mappings[second]
    mappings[REFERENCE]["candidates"][0]["properties"]["streams"]["video"].clear()
    assert mappings[second]["candidates"][0]["properties"]["streams"]["video"]


def test_inactive_references_do_not_trigger_search_or_probe(tmp_path):
    path = _file(tmp_path / "declared")
    mappings, findings = import_relink.discover_candidates(
        [_ref(active=False), _ref(active=None, pointer="/unknown")],
        [path.parent],
        probe=lambda _: pytest.fail("inactive references cannot probe"),
    )
    assert mappings == {}
    assert findings == []


@pytest.mark.parametrize("directory", [False, True])
def test_symlinks_cannot_escape_or_recurse_into_undeclared_media(tmp_path, directory):
    root = tmp_path / "declared"
    root.mkdir()
    outside = _file(tmp_path / "outside")
    link = root / ("linked-folder" if directory else "take.mov")
    try:
        link.symlink_to(
            outside.parent if directory else outside, target_is_directory=directory
        )
    except OSError:
        pytest.skip("symlink creation unavailable")
    probed = []
    mappings, _ = import_relink.discover_candidates(
        [_ref()], [root], probe=lambda paths: probed.extend(paths)
    )
    assert mappings[REFERENCE]["candidates"] == []
    assert probed == []


def test_prohibited_subtrees_are_never_probed(tmp_path):
    root = tmp_path / "declared"
    allowed = _file(root / "raw")
    prohibited = _file(root / "edit", content=b"derived proof")
    calls = []

    def probe(paths):
        calls.extend(paths)
        return _probe(paths)

    mappings, _ = import_relink.discover_candidates(
        [_ref()], [root], probe=probe, prohibited_roots=[prohibited.parent]
    )
    assert [item["path"] for item in mappings[REFERENCE]["candidates"]] == [
        str(allowed)
    ]
    assert calls == [allowed]


def test_scan_entry_limit_counts_nonmatching_entries_and_all_roots(
    tmp_path, monkeypatch
):
    roots = [tmp_path / "one", tmp_path / "two"]
    for root in roots:
        for index in range(5):
            _file(root, f"unrelated-{index}.txt")
    monkeypatch.setattr(import_relink, "MAX_SCAN_ENTRIES", 5)
    mappings, findings = import_relink.discover_candidates(
        [_ref()], roots, probe=lambda _: pytest.fail("no matching media")
    )
    assert mappings[REFERENCE]["candidates"] == []
    assert any(item["code"] == "OTIO_INPUT_LIMIT" for item in findings)


def test_candidate_cap_limits_probes_and_emits_blocking_truncation(
    tmp_path, monkeypatch
):
    root = tmp_path / "declared"
    for index in range(4):
        _file(root / str(index))
    monkeypatch.setattr(import_relink, "MAX_CANDIDATES", 2)
    calls = []

    def probe(paths):
        calls.extend(paths)
        return _probe(paths)

    mappings, findings = import_relink.discover_candidates(
        [_ref()], [root], probe=probe
    )
    assert len(mappings[REFERENCE]["candidates"]) == len(calls) == 2
    assert any(
        item["code"] == "OTIO_INPUT_LIMIT" and item["blocking"] for item in findings
    )


def test_probe_unavailability_is_scoped_and_cannot_make_candidate_evidence(tmp_path):
    path = _file(tmp_path / "declared")

    def unavailable(_):
        raise RuntimeError("ffprobe unavailable")

    mappings, findings = import_relink.discover_candidates(
        [_ref()], [path.parent], probe=unavailable
    )
    assert mappings[REFERENCE]["candidates"] == []
    assert any(
        item["code"] == "OTIO_RUNTIME_UNAVAILABLE" and item["scope"] == REFERENCE
        for item in findings
    )


@pytest.mark.parametrize(
    "fault",
    [
        "missing-sources",
        "missing-fingerprint",
        "wrong-locator",
        "malformed-streams",
        "malformed-stream-entry",
        "nonfinite-duration",
        "extreme-duration",
        "mismatched-fingerprint",
    ],
)
def test_malformed_or_unbound_probe_properties_fail_closed(tmp_path, fault):
    path = _file(tmp_path / "declared")

    def probe(paths):
        result = _probe(paths)
        source = result["sources"][0]
        if fault == "missing-sources":
            return {}
        if fault == "missing-fingerprint":
            source.pop("fingerprint")
        elif fault == "wrong-locator":
            source["locator"] = str(tmp_path / "outside.mov")
        elif fault == "malformed-streams":
            source["streams"] = []
        elif fault == "malformed-stream-entry":
            source["streams"]["video"] = ["not a stream object"]
        elif fault == "nonfinite-duration":
            source["durationSeconds"] = float("nan")
        elif fault == "extreme-duration":
            source["durationSeconds"] = 10**1000
        else:
            source["fingerprint"]["sha256"] = "0" * 64
        return result

    mappings, findings = import_relink.discover_candidates(
        [_ref()], [path.parent], probe=probe
    )
    assert mappings[REFERENCE]["candidates"] == []
    assert any(
        item["code"] in {"OTIO_INPUT_INVALID", "OTIO_SOURCE_CHANGED"}
        and item["scope"] == REFERENCE
        for item in findings
    )


def test_candidate_bytes_are_verified_again_after_probe(tmp_path):
    path = _file(tmp_path / "declared")

    def mutate(paths):
        result = _probe(paths)
        path.write_bytes(b"changed bytes")
        return result

    mappings, findings = import_relink.discover_candidates(
        [_ref()], [path.parent], probe=mutate
    )
    assert mappings[REFERENCE]["candidates"] == []
    assert any(item["code"] == "OTIO_SOURCE_CHANGED" for item in findings)


@pytest.mark.parametrize(
    "root", [r"\\server\share", "file://server/share", "https://example.test/media"]
)
def test_network_roots_are_rejected_without_probe(root):
    mappings, findings = import_relink.discover_candidates(
        [_ref()], [root], probe=lambda _: pytest.fail("network roots cannot probe")
    )
    assert mappings[REFERENCE]["candidates"] == []
    assert any(item["blocking"] for item in findings)


def test_global_output_budget_bounds_repeated_candidate_reports(tmp_path, monkeypatch):
    path = _file(tmp_path / "declared")
    monkeypatch.setattr(import_relink, "MAX_OUTPUT_BYTES", 2048)
    references = [_ref(pointer=f"/reference/{index}") for index in range(100)]
    mappings, findings = import_relink.discover_candidates(
        references, [path.parent], probe=_probe
    )
    encoded = json.dumps(
        {"mediaMappings": mappings, "findings": findings},
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode()
    assert len(encoded) <= 2048
    assert any(
        item["code"] == "OTIO_INPUT_LIMIT" and item["blocking"] for item in findings
    )


@pytest.mark.skipif(os.name != "nt", reason="Windows junction boundary")
def test_directory_junction_is_not_followed_outside_declared_root(tmp_path):
    root = tmp_path / "declared"
    root.mkdir()
    outside = _file(tmp_path / "outside")
    junction = root / "junction"
    result = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(junction), str(outside.parent)],
        capture_output=True,
    )
    if result.returncode:
        pytest.skip("junction creation unavailable")
    try:
        mappings, _ = import_relink.discover_candidates(
            [_ref()],
            [root],
            probe=lambda _: pytest.fail("junction target cannot be probed"),
        )
        assert mappings[REFERENCE]["candidates"] == []
    finally:
        junction.rmdir()
    assert outside.read_bytes() == b"original bytes"
