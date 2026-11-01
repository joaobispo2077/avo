"""Proposal edits change reviewable authority, never recordings or approval."""

from __future__ import annotations

import shutil
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

import pytest

from avo.library.rules import LibraryError
from avo.library.service import LibraryService
from library_fixtures import install_provider, make_library


@pytest.fixture
def library(tmp_path, monkeypatch):
    installation = tmp_path / "installation"
    install_provider(installation)
    schemas = installation / "schemas"
    schemas.mkdir(exist_ok=True)
    shutil.copyfile(
        Path(__file__).resolve().parents[1] / "schemas" / "avo.library.schema.json",
        schemas / "avo.library.schema.json",
    )
    monkeypatch.setenv("AVO_ROOT", str(installation))
    fixture = make_library(tmp_path / "footage")
    return LibraryService(fixture.root, "example", probe=fixture.probe), fixture


def source_snapshot(root):
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file() and "edit" not in path.relative_to(root).parts
    }


def edit_request(service, proposal_ref, edits):
    head = service.store.head()
    proposal = service.store.get(proposal_ref)
    return {
        "schemaVersion": 1,
        "kind": "edits",
        "requestId": uuid4().hex,
        "libraryId": head["libraryId"],
        "expectedHeadHash": head["headHash"],
        "baseProposalId": proposal["proposalId"],
        "baseRevision": proposal["revision"],
        "baseProposalHash": proposal_ref["sha256"],
        "edits": edits,
    }


def test_initial_proposal_exposes_every_mapping_and_retains_source_bytes(library):
    service, fixture = library
    before = source_snapshot(fixture.root)
    result = service.scan(recursive=True)
    proposal = service.store.get(result["proposalRef"])
    inventory = service.store.get(result["inventoryRef"])

    assert proposal["revision"] == 1
    assert proposal["parent"] is None
    assert proposal["inventoryRef"] == result["inventoryRef"]
    assert len(proposal["actions"]) == len(inventory["recordings"]) == 6
    assert len({action["actionId"] for action in proposal["actions"]}) == 6
    assert {action["recordingId"] for action in proposal["actions"]} == {
        recording["id"] for recording in inventory["recordings"]
    }
    assert {action["from"] for action in proposal["actions"]} == set(before)
    assert all("to" in action and action["reason"] for action in proposal["actions"])
    assert all(
        {"id", "label", "path", "rationale", "evidence"} <= set(group)
        for group in proposal["groups"]
    )
    assert source_snapshot(fixture.root) == before
    assert service.store.head()["activeOperation"] is None


def test_opaque_root_recording_stays_unresolved_without_content_analysis(
    library, monkeypatch
):
    service, fixture = library

    def unexpected_transcription(*args, **kwargs):
        pytest.fail("A metadata proposal started transcription")

    monkeypatch.setattr("avo.transcribe.transcribe_one", unexpected_transcription)
    result = service.scan(recursive=True)
    proposal = service.store.get(result["proposalRef"])
    root_action = next(
        action
        for action in proposal["actions"]
        if action["from"] == fixture.files[0].name
    )

    assert root_action["status"] == "unresolved"
    assert root_action["reason"]
    assert not (fixture.root / "edit" / "library" / "transcripts").exists()


def test_group_rename_publishes_successor_and_preserves_old_revision(library):
    service, fixture = library
    initial = service.scan(recursive=True)
    old_ref = initial["proposalRef"]
    old = deepcopy(service.store.get(old_ref))
    group = old["groups"][0]
    before = source_snapshot(fixture.root)
    request = edit_request(
        service,
        old_ref,
        [{"type": "rename-group", "groupId": group["id"], "label": "XPTO"}],
    )

    result = service.propose(request=request)
    revised = service.store.get(result["proposalRef"])
    renamed = next(item for item in revised["groups"] if item["id"] == group["id"])

    assert result["proposalRef"]["sha256"] != old_ref["sha256"]
    assert revised["proposalId"] == old["proposalId"]
    assert revised["revision"] == old["revision"] + 1
    assert revised["parent"] == old_ref
    assert renamed["label"] == "XPTO"
    assert renamed["path"] != group["path"]
    assert service.store.get(old_ref) == old
    assert source_snapshot(fixture.root) == before
    assert service.store.head()["proposalRef"] == result["proposalRef"]
    assert service.store.head()["activeOperation"] is None


def test_assign_exclude_and_keep_update_only_selected_mappings(library):
    service, fixture = library
    initial = service.scan(recursive=True)
    old = service.store.get(initial["proposalRef"])
    assigned, excluded, kept = old["actions"][:3]
    target = next(
        group for group in old["groups"] if group["id"] != assigned["groupId"]
    )
    before = source_snapshot(fixture.root)
    request = edit_request(
        service,
        initial["proposalRef"],
        [
            {
                "type": "assign-recording",
                "recordingId": assigned["recordingId"],
                "groupId": target["id"],
            },
            {"type": "exclude-recording", "recordingId": excluded["recordingId"]},
            {"type": "keep-recording", "recordingId": kept["recordingId"]},
        ],
    )

    result = service.propose(request=request)
    revised = service.store.get(result["proposalRef"])
    actions = {action["recordingId"]: action for action in revised["actions"]}

    assert actions[assigned["recordingId"]]["groupId"] == target["id"]
    assert actions[assigned["recordingId"]]["to"] == (
        f"{target['path']}/{Path(assigned['from']).name}"
    )
    assert actions[excluded["recordingId"]]["status"] == "exclude"
    assert actions[kept["recordingId"]]["status"] == "keep"
    assert actions[kept["recordingId"]]["to"] == kept["from"]
    for untouched in old["actions"][3:]:
        assert actions[untouched["recordingId"]] == untouched
    assert source_snapshot(fixture.root) == before


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("expectedHeadHash", "0" * 64),
        ("baseProposalId", "not-the-current-proposal"),
        ("baseRevision", 999),
        ("baseProposalHash", "0" * 64),
    ],
)
def test_stale_base_rejected_without_publishing_or_changing_media(
    library, field, value
):
    service, fixture = library
    initial = service.scan(recursive=True)
    proposal = service.store.get(initial["proposalRef"])
    request = edit_request(
        service,
        initial["proposalRef"],
        [
            {
                "type": "rename-group",
                "groupId": proposal["groups"][0]["id"],
                "label": "XPTO",
            }
        ],
    )
    request[field] = value
    head_before = service.store.head()
    sources_before = source_snapshot(fixture.root)

    with pytest.raises(LibraryError) as error:
        service.propose(request=request)

    assert error.value.code == "LIB_STALE_PROPOSAL"
    assert service.store.head() == head_before
    assert source_snapshot(fixture.root) == sources_before


def test_duplicate_stems_assigned_to_one_group_are_blocked(library):
    service, fixture = library
    initial = service.scan(recursive=True)
    proposal = service.store.get(initial["proposalRef"])
    duplicates = [
        action
        for action in proposal["actions"]
        if Path(action["from"]).name == fixture.files[0].name
    ]
    target = proposal["groups"][0]
    request = edit_request(
        service,
        initial["proposalRef"],
        [
            {
                "type": "assign-recording",
                "recordingId": action["recordingId"],
                "groupId": target["id"],
            }
            for action in duplicates
        ],
    )
    before = source_snapshot(fixture.root)

    result = service.propose(request=request)
    revised = service.store.get(result["proposalRef"])
    conflicts = [
        action
        for action in revised["actions"]
        if action["recordingId"] in {item["recordingId"] for item in duplicates}
    ]

    assert len(conflicts) >= 2
    assert len({action["to"].casefold() for action in conflicts}) == 1
    assert all(
        action["status"] == "blocked" and action["reason"] for action in conflicts
    )
    assert source_snapshot(fixture.root) == before


def test_case_folded_group_destinations_expose_conflicting_actions(library):
    service, fixture = library
    initial = service.scan(recursive=True)
    proposal = service.store.get(initial["proposalRef"])
    first, second = proposal["groups"][:2]
    request = edit_request(
        service,
        initial["proposalRef"],
        [
            {"type": "rename-group", "groupId": first["id"], "label": "Camera"},
            {"type": "rename-group", "groupId": second["id"], "label": "camera"},
        ],
    )
    before = source_snapshot(fixture.root)

    result = service.propose(request=request)
    revised = service.store.get(result["proposalRef"])
    by_destination = {}
    for action in revised["actions"]:
        if action["groupId"] in {first["id"], second["id"]}:
            by_destination.setdefault(action["to"].casefold(), []).append(action)
    conflicts = [items for items in by_destination.values() if len(items) > 1]

    assert conflicts
    assert all(
        action["status"] == "blocked" and action["reason"]
        for items in conflicts
        for action in items
    )
    assert source_snapshot(fixture.root) == before


@pytest.mark.parametrize(
    "label", ["../outside", "nested/../../outside", "C:/outside", "CON", "folder:ads"]
)
def test_group_rename_rejects_unsafe_folder_names(library, label):
    service, fixture = library
    initial = service.scan(recursive=True)
    proposal = service.store.get(initial["proposalRef"])
    request = edit_request(
        service,
        initial["proposalRef"],
        [
            {
                "type": "rename-group",
                "groupId": proposal["groups"][0]["id"],
                "label": label,
            }
        ],
    )
    before = service.store.head()
    sources_before = source_snapshot(fixture.root)

    with pytest.raises(LibraryError) as error:
        service.propose(request=request)

    assert error.value.code in {"LIB_ROOT_UNSAFE", "LIB_INVALID_REQUEST"}
    assert service.store.head() == before
    assert source_snapshot(fixture.root) == sources_before


@pytest.mark.parametrize(
    "edit",
    [
        {"type": "rename-group", "groupId": "unknown", "label": "XPTO"},
        {"type": "keep-recording", "recordingId": "unknown"},
        {"type": "exclude-recording", "recordingId": "unknown"},
    ],
)
def test_unknown_edit_ids_cannot_publish_a_revision(library, edit):
    service, fixture = library
    initial = service.scan(recursive=True)
    request = edit_request(service, initial["proposalRef"], [edit])
    before = service.store.head()
    sources_before = source_snapshot(fixture.root)

    with pytest.raises(LibraryError) as error:
        service.propose(request=request)

    assert error.value.code == "LIB_INVALID_REQUEST"
    assert service.store.head() == before
    assert source_snapshot(fixture.root) == sources_before
