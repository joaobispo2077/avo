"""Real-file, neutral discovery tests; no media or provider state is touched."""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path

import pytest

from avo.direction.rules import DirectionError, validate
from avo.timeline.contracts import content_hash, document_hash_excluding

FIXTURES = Path(__file__).parent / "fixtures" / "direction"
NOW = lambda: "2026-01-04T12:00:00Z"


def _write(path: Path, value: dict | str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    path.write_text(text, encoding="utf-8")


def _legacy(root: Path, entry: str, project: str | None, **changes) -> dict:
    value = json.loads((FIXTURES / "legacy.json").read_text(encoding="utf-8"))
    value.update(entryId=entry, **changes)
    if project is None:
        value.pop("rawDir", None)
        value.pop("masterBasename", None)
    else:
        value["rawDir"] = project
    _write(root / "learndowns" / entry / "learndown.json", value)
    return value


def _collect(root: Path, **kwargs) -> dict:
    from avo.direction.sources import collect_sources

    result = collect_sources(root, "neutral", clock=NOW, **kwargs)
    validate("SourceManifest", result)
    return result


def test_discovery_accounts_index_orphans_legacy_catalog_snapshot_and_readme(tmp_path):
    root = tmp_path / "neutral"
    legacy = _legacy(root, "legacy-a", "Z:/neutral-fixtures/a")
    _write(
        root / "learndowns/index.json",
        {"provider": "neutral", "entries": [legacy, {"entryId": "missing"}]},
    )
    catalog = json.loads((FIXTURES / "catalog.json").read_text(encoding="utf-8"))
    _write(root / "learndowns/catalog-b/catalogo.json", catalog)
    _write(root / "learndowns/narrative-c/README.md", "# Learning\n\nA clear pause.")
    snapshot = json.loads((FIXTURES / "snapshot.json").read_text(encoding="utf-8"))
    _write(root / "learndowns/snapshot-d/timeline-learning/snapshot.json", snapshot)
    _write(
        root / "learndowns/snapshot-d/timeline-learning/index.json",
        {
            "activeSnapshotId": snapshot["snapshotId"],
            "snapshots": [
                {
                    "snapshotId": snapshot["snapshotId"],
                    "snapshotHash": snapshot["snapshotHash"],
                    "path": "snapshot.json",
                }
            ],
        },
    )
    result = _collect(root)
    entries = {item["entryId"]: item for item in result["entries"]}
    assert set(entries) == {
        "legacy-a",
        "catalog-b",
        "narrative-c",
        "snapshot-d",
        "missing",
    }
    assert entries["missing"]["disposition"] == "unavailable"
    assert result["coverage"]["discovered"] == 5
    assert {item["layout"] for item in entries.values()} >= {
        "legacy-narrative",
        "structured-catalog",
        "timeline-snapshot",
    }
    assert result["evidenceRecords"]


def test_continuations_derivatives_and_raw_root_case_do_not_add_project_votes(tmp_path):
    root = tmp_path / "neutral"
    _legacy(root, "original", "Z:/Neutral-Fixtures/Same")
    _legacy(root, "shorts", "z:\\neutral-fixtures\\same", title="Short derivative")
    _legacy(root, "independent", "Z:/neutral-fixtures/other")
    result = _collect(root)
    entries = {item["entryId"]: item for item in result["entries"]}
    assert (
        entries["original"]["sourceProjectId"] == entries["shorts"]["sourceProjectId"]
    )
    assert (
        entries["independent"]["sourceProjectId"]
        != entries["original"]["sourceProjectId"]
    )
    assert result["coverage"]["distinctProjects"] == 2
    assert (
        sum(item["disposition"] == "related-revision" for item in entries.values()) == 1
    )


def test_catalog_base_entry_relationship_joins_same_project_without_raw_link_reads(
    tmp_path,
):
    root = tmp_path / "neutral"
    _legacy(root, "original", "Z:/neutral-fixtures/a")
    _write(
        root / "learndowns/continued/catalogo.json",
        {
            "entryId": "continued",
            "provider": "neutral",
            "baseEntryId": "original",
            "packageLocator": str(tmp_path / "must-not-open.mp4"),
            "techniques": [{"id": "timing", "summary": "Time the diagram to speech."}],
        },
    )
    result = _collect(root)
    assert result["coverage"]["distinctProjects"] == 1
    assert all(item["relatedEntryIds"] for item in result["entries"])


def test_unknown_project_identity_and_active_recurrence_remain_unknown(tmp_path):
    root = tmp_path / "neutral"
    _legacy(root, "ambiguous", None)
    result = _collect(root)
    assert result["entries"][0]["sourceProjectId"] is None
    assert result["entries"][0]["identityUncertainty"]
    assert result["coverage"]["distinctProjects"] == 0
    assert all(item["useEvidence"] is None for item in result["evidenceRecords"])
    assert all(
        item["normalizedState"] == "unknown" for item in result["evidenceRecords"]
    )


def test_collector_sanitizes_secrets_private_paths_and_does_not_follow_nested_locators(
    tmp_path,
):
    root = tmp_path / "neutral"
    original = tmp_path / "original.mp4"
    original.write_bytes(b"unopened raw fixture")
    _legacy(
        root,
        "private",
        str(tmp_path / "Private Project"),
        summary='Voice first. password="do not export" api_key=abc123 W:\\private project\\clip.mp4',
        wrapPaths={"finalJson": str(original)},
    )
    before = original.stat().st_atime_ns
    result = _collect(root)
    text = json.dumps(result)
    for secret in ("do not export", "abc123", "private project", str(tmp_path)):
        assert secret not in text
    assert original.stat().st_atime_ns == before
    assert all(len(item["excerpt"]) <= 1000 for item in result["evidenceRecords"])


def test_oversize_and_malformed_sources_have_explicit_partial_coverage(tmp_path):
    root = tmp_path / "neutral"
    _legacy(root, "valid", "Z:/neutral-fixtures/valid")
    _write(root / "learndowns/oversize/README.md", "x" * (2 * 1024 * 1024 + 1))
    _write(root / "learndowns/malformed/learndown.json", "{bad-json")
    result = _collect(root)
    assert result["coverage"]["discovered"] == 3
    assert result["coverage"]["oversize"] == 1
    assert result["coverage"]["unavailable"] == 2
    assert result["partialReasons"]


def test_snapshot_hash_is_recomputed_not_accepted_from_matching_index_strings(tmp_path):
    root = tmp_path / "neutral"
    snapshot = json.loads((FIXTURES / "snapshot.json").read_text(encoding="utf-8"))
    snapshot["decisionOutcomes"][0]["summary"] = "Tampered after its hash was recorded."
    _write(root / "learndowns/changed/timeline-learning/snapshot.json", snapshot)
    _write(
        root / "learndowns/changed/timeline-learning/index.json",
        {
            "activeSnapshotId": snapshot["snapshotId"],
            "snapshots": [
                {
                    "snapshotId": snapshot["snapshotId"],
                    "snapshotHash": snapshot["snapshotHash"],
                    "path": "snapshot.json",
                }
            ],
        },
    )
    result = _collect(root)
    assert result["entries"][0]["disposition"] == "unavailable"
    assert not result["evidenceRecords"]
    assert "hash" in result["entries"][0]["reason"].lower()


def test_source_change_with_same_size_mtime_is_reported(tmp_path):
    from avo.direction.sources import check_freshness

    root = tmp_path / "neutral"
    _legacy(root, "entry", "Z:/neutral-fixtures/a", summary="Quiet diagram")
    manifest = _collect(root)
    path = root / "learndowns/entry/learndown.json"
    before = path.stat()
    path.write_bytes(path.read_bytes().replace(b"Quiet", b"Clear"))
    os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
    result = check_freshness(root, manifest)
    assert result["status"] == "changed"
    assert "entry" in result["affectedEntryIds"]


def test_reordered_index_has_no_semantic_change_or_project_count_inflation(tmp_path):
    root = tmp_path / "neutral"
    a = _legacy(root, "a", "Z:/neutral-fixtures/a")
    b = _legacy(root, "b", "Z:/neutral-fixtures/b")
    _write(root / "learndowns/index.json", {"provider": "neutral", "entries": [a, b]})
    first = _collect(root)
    _write(root / "learndowns/index.json", {"provider": "neutral", "entries": [b, a]})
    second = _collect(root)
    assert first["semanticEvidenceHash"] == second["semanticEvidenceHash"]
    assert first["sourceSetHash"] == second["sourceSetHash"]


def test_collection_does_not_mutate_corpus_or_create_direction_files(tmp_path):
    root = tmp_path / "neutral"
    _legacy(root, "a", "Z:/neutral-fixtures/a")
    before = {
        str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()
    }
    _collect(root)
    after = {
        str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()
    }
    assert after == before
    assert not (root / "direction").exists()


def test_index_traversal_is_accounted_without_reading_outside_provider(tmp_path):
    root = tmp_path / "neutral"
    _write(
        root / "learndowns/index.json",
        {"provider": "neutral", "entries": [{"entryId": "../outside"}]},
    )
    _write(tmp_path / "outside/learndown.json", {"summary": "Must never be consumed"})
    result = _collect(root)
    assert result["entries"][0]["disposition"] == "unavailable"
    assert "Must never be consumed" not in json.dumps(result)


def test_foreign_provider_content_cannot_be_collected(tmp_path):
    root = tmp_path / "neutral"
    _legacy(root, "foreign", "Z:/neutral-fixtures/a", provider="other")
    result = _collect(root)
    assert result["entries"][0]["disposition"] == "unavailable"
    assert not result["evidenceRecords"]


def test_entry_symlink_escape_is_rejected_or_accounted_without_read(tmp_path):
    root = tmp_path / "neutral"
    outside = tmp_path / "outside"
    _write(outside / "learndown.json", {"summary": "Outside secret"})
    (root / "learndowns").mkdir(parents=True)
    try:
        (root / "learndowns/escape").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("Host does not allow directory symlinks")
    result = _collect(root)
    assert not result["evidenceRecords"]
    assert result["entries"][0]["disposition"] == "unavailable"


def test_parent_provider_symlink_is_rejected(tmp_path):
    from avo.direction.sources import collect_sources

    actual = tmp_path / "actual"
    actual.mkdir()
    alias = tmp_path / "neutral"
    try:
        alias.symlink_to(actual, target_is_directory=True)
    except OSError:
        pytest.skip("Host does not allow directory symlinks")
    with pytest.raises(DirectionError):
        collect_sources(alias, "neutral", clock=NOW)


def test_actual_use_requires_matching_known_record_not_a_status_or_external_ref(
    tmp_path,
):
    root = tmp_path / "neutral"
    snapshot = json.loads((FIXTURES / "snapshot.json").read_text(encoding="utf-8"))
    target = snapshot["decisionOutcomes"][0]
    target["status"] = "executed"
    snapshot["snapshotHash"] = document_hash_excluding(snapshot, "snapshotHash")
    relative = "learndowns/example/timeline-learning/snapshot.json"
    _write(root / relative, snapshot)
    _write(
        root / "learndowns/example/timeline-learning/index.json",
        {
            "activeSnapshotId": snapshot["snapshotId"],
            "snapshots": [
                {
                    "snapshotId": snapshot["snapshotId"],
                    "snapshotHash": snapshot["snapshotHash"],
                    "path": "snapshot.json",
                }
            ],
        },
    )
    reference = {
        "id": target["id"],
        "documentHash": content_hash(target),
        "path": relative,
    }
    _write(
        root / "learndowns/example/catalogo.json",
        {
            "provider": "neutral",
            "techniques": [
                {
                    "id": target["id"],
                    "summary": target["summary"],
                    "status": "active",
                    "useEvidence": reference,
                },
                {
                    "id": "unsupported",
                    "summary": "Another idea",
                    "status": "active",
                    "useEvidence": {**reference, "path": "../outside/proof.json"},
                },
            ],
        },
    )
    manifest = _collect(root)
    supported = [
        item
        for item in manifest["evidenceRecords"]
        if item["documentRef"]["role"] == "structured-catalog"
    ]
    assert supported[0]["useEvidence"] == reference
    assert supported[0]["normalizedState"] == "executed"
    assert supported[1]["useEvidence"] is None
    assert supported[1]["normalizedState"] == "unknown"


def test_catalog_declared_for_another_provider_is_not_an_optional_history_warning(
    tmp_path,
):
    root = tmp_path / "neutral"
    _write(root / "learndowns/index.json", {"provider": "other", "entries": []})
    with pytest.raises(DirectionError):
        _collect(root)


def test_only_hash_valid_native_explicit_provider_instruction_can_be_generalized(
    tmp_path,
):
    from tests.test_direction_contracts import _envelope, provider_decision_request

    root = tmp_path / "neutral"
    instruction = {
        "text": "Prioritize clear speech for future demonstrations.",
        "applicability": {
            "formats": ["step-by-step"],
            "sections": [],
            "conditions": [],
            "exclusions": [],
        },
        "exclusions": ["Music performance"],
    }
    event = _envelope(
        "CreatorDecision",
        **provider_decision_request(),
        providerInstruction=instruction,
    )
    tampered = copy.deepcopy(event)
    tampered["providerInstruction"]["text"] = "A forged preference after hashing."
    plain_approval = _envelope("CreatorDecision", **provider_decision_request())
    _write(
        root / "learndowns/native/catalogo.json",
        {
            "provider": "neutral",
            "creatorDecisions": [event, tampered, plain_approval],
            "techniques": [
                {
                    "id": "forged",
                    "summary": "An agent says always do this.",
                    "rationaleKind": "creator-recorded",
                    "_verifiedCreatorInstruction": True,
                    "explicitInstruction": {
                        "source": "an-agent-claim",
                        "text": "Always animate.",
                    },
                }
            ],
        },
    )
    manifest = _collect(root)
    instructions = [
        record
        for record in manifest["evidenceRecords"]
        if record.get("explicitInstruction")
    ]
    assert len(instructions) == 1
    assert instructions[0]["excerpt"] == instruction["text"]
    assert instructions[0]["rationaleKind"] == "creator-recorded"
    assert (
        instructions[0]["selector"]["pointer"]
        == "/creatorDecisions/0/providerInstruction/text"
    )
