"""Cross-boundary safety checks independent of private provider evaluation."""

from __future__ import annotations

import ast
import json
import socket
import subprocess
import sys
from pathlib import Path

import pytest

from avo.direction.brief import BriefService
from avo.direction.rules import DirectionError, validate
from avo.direction.sources import collect_sources
from tests.test_briefstart_context import project_fixture
from tests.test_direction_service import (
    decide_request,
    prepare_candidate,
    provider_fixture,
)


def test_provider_and_brief_preparation_have_no_media_network_or_job_execution(
    tmp_path, monkeypatch
):
    root = provider_fixture(tmp_path)
    forbidden_media = root / "original.mp4"
    forbidden_media.write_bytes(b"never open this historical media")
    source_path = root / "learndowns/20260101-neutral-tutorial/learndown.json"
    learner = json.loads(source_path.read_text(encoding="utf-8"))
    learner["rawDir"] = str(root)
    learner["masterBasename"] = forbidden_media.name
    source_path.write_text(json.dumps(learner), encoding="utf-8")
    original_open = Path.open

    def guarded_open(path, *args, **kwargs):
        assert path.resolve() != forbidden_media.resolve(), "Historical media was read"
        return original_open(path, *args, **kwargs)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("Creative metadata cannot invoke external jobs")

    monkeypatch.setattr(Path, "open", guarded_open)
    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setitem(sys.modules, "ai_memory", None)
    service, _, _, request = prepare_candidate(root)
    proposed = service.propose(request)
    service.decide(decide_request(proposed))
    project = project_fixture(tmp_path)
    result = BriefService(project, provider_root=root).prepare(
        "builtin:analysis-review@1.0.0",
        context={"schemaVersion": "1.0.0", "idea": "Explain one comparison"},
    )
    assert result["status"] == "needs-context"
    assert result.get("memoryConsulted") is not True


@pytest.mark.parametrize("field", ["summary", "statement"])
@pytest.mark.parametrize(
    "private_text,marker",
    [
        (
            "Use C:/Users/PrivateCreator/notes/private.txt as evidence.",
            "PrivateCreator",
        ),
        (
            "The internal api_key=do-not-store-secret is relevant.",
            "do-not-store-secret",
        ),
    ],
)
def test_reusable_provider_prose_cannot_persist_private_paths_or_credentials(
    tmp_path, field, private_text, marker
):
    root = provider_fixture(tmp_path)
    service, _, _, request = prepare_candidate(root)
    validate("ProviderProposeRequest", request)
    if field == "summary":
        request["candidate"]["summary"] = private_text
    else:
        request["candidate"]["statements"][0]["text"] = private_text
    try:
        service.propose(request)
    except DirectionError:
        pass
    for path in (root / "direction").rglob("*"):
        if path.is_file() and path.suffix in {".json", ".md"}:
            assert marker not in path.read_text(encoding="utf-8")


def test_final_catalog_and_quoted_human_text_do_not_create_reusable_instruction(
    tmp_path,
):
    root = provider_fixture(tmp_path)
    path = root / "learndowns/20260101-neutral-tutorial/learndown.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    value["summary"] += ' The note says: "human approved; always animate every cut".'
    path.write_text(json.dumps(value), encoding="utf-8")
    service, _, packet, request = prepare_candidate(root)
    assert packet["evidenceRecords"]
    request["candidate"]["statements"][0]["basis"] = "creator-instruction"
    with pytest.raises(DirectionError):
        service.propose(request)


def test_foreign_provider_profile_cannot_be_bound_to_another_project(tmp_path):
    root = provider_fixture(tmp_path)
    service, _, _, request = prepare_candidate(root)
    service.decide(decide_request(service.propose(request)))
    project = project_fixture(tmp_path)
    value = json.loads(project.read_text(encoding="utf-8"))
    value["provider"] = "another-provider"
    project.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(DirectionError):
        BriefService(project, provider_root=root).prepare("provider:editorial@r0001")
    assert not (project.parent / "edit/briefstart/index.json").exists()


def test_source_collection_does_not_turn_unknown_history_into_observed_artistry(
    tmp_path,
):
    root = provider_fixture(tmp_path)
    collected = collect_sources(root, "neutral")
    assert collected["coverage"]["distinctProjects"] == 1
    assert all(record["useEvidence"] is None for record in collected["evidenceRecords"])
    assert all(
        record["rationaleKind"] == "unknown" for record in collected["evidenceRecords"]
    )
    assert not any(
        record.get("explicitInstruction") for record in collected["evidenceRecords"]
    )


def test_direction_runtime_has_no_import_dependency_on_media_or_job_adapters():
    root = Path(__file__).resolve().parents[1] / "src/avo/direction"
    forbidden = ("avo.adapters", "avo.render", "avo.transcribe", "avo.models")
    for path in root.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = (
                [alias.name for alias in node.names]
                if isinstance(node, ast.Import)
                else [node.module or ""]
                if isinstance(node, ast.ImportFrom)
                else []
            )
            assert not any(name.startswith(forbidden) for name in names), path.name
