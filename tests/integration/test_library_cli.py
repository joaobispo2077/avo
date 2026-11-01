"""The public native command preserves the complete reviewed-move lifecycle."""

import hashlib
import json
import os
import subprocess
import sys

import pytest
from tests.test_library_moves import decision_request, proposal_identifier, selection
from tests.test_library_proposals import edit_request

from avo.adapters.media.library_moves import capability
from avo.library.service import LibraryService
from library_fixtures import install_provider, make_library

pytestmark = pytest.mark.integration


def test_native_preview_approve_apply_and_separately_approve_reversal(
    tmp_path, monkeypatch, repo_root
):
    install = tmp_path / "install"
    install_provider(install)
    monkeypatch.setenv("AVO_ROOT", str(install))
    fixture = make_library(tmp_path / "footage", count=6, playable=True)
    if not capability(fixture.root)["available"]:
        pytest.skip("Actual native lifecycle requires supported local Windows NTFS")
    service = LibraryService(fixture.root, "example")
    original = {
        path: hashlib.sha256(path.read_bytes()).hexdigest() for path in fixture.files
    }
    environment = {**os.environ, "PYTHONPATH": str(repo_root / "src")}

    def invoke(*arguments):
        process = subprocess.run(
            [
                sys.executable,
                "-m",
                "avo.cli",
                "organize",
                *arguments,
                "--root",
                str(fixture.root),
                "--provider",
                "example",
                "--json",
            ],
            cwd=tmp_path,
            env=environment,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert process.returncode == 0, process.stdout + process.stderr
        return json.loads(process.stdout)

    def input_file(name, value):
        path = tmp_path / f"{name}.json"
        raw = json.dumps(value).encode()
        path.write_bytes(raw)
        return str(path), hashlib.sha256(raw).hexdigest()

    def apply_selected(proposal_ref, label):
        actions = [
            a
            for a in service.store.get(proposal_ref)["actions"]
            if a["status"] == "move"
        ]
        selected, _ = input_file(label + "-selection", selection(actions))
        packet = invoke(
            "prepare",
            "--proposal",
            proposal_identifier(service, proposal_ref),
            "--selection",
            selected,
        )["packetRef"]
        request, digest = input_file(
            label + "-decision", decision_request(service, packet)
        )
        decision = invoke("approve", "--request", request, "--request-sha256", digest)
        return invoke("apply", "--approval", decision["decisionRef"]["id"])

    scanned = invoke("scan", "--recursive")
    proposal = service.store.get(scanned["proposalRef"])
    group = next(g for g in proposal["groups"] if g["path"] == "camera-a")
    request, digest = input_file(
        "edits",
        edit_request(
            service,
            scanned["proposalRef"],
            [{"type": "rename-group", "groupId": group["id"], "label": "organized-a"}],
        ),
    )
    reviewed = invoke("propose", "--request", request, "--request-sha256", digest)
    assert all(path.exists() for path in original), "Preview moved a source"
    initial_ids = {
        r["id"]
        for r in service.store.get(service.store.head()["inventoryRef"])["recordings"]
    }
    moved = apply_selected(reviewed["proposalRef"], "forward")
    assert moved["summary"]["completed"] == 2
    inverse = invoke("reverse", "--operation", moved["operationId"])
    assert not (fixture.root / "camera-a/take-0000.mp4").exists(), (
        "Reverse proposal applied itself"
    )
    apply_selected(inverse["proposalRef"], "reverse")
    assert all(
        hashlib.sha256(path.read_bytes()).hexdigest() == digest
        for path, digest in original.items()
    )
    final_ids = {
        r["id"]
        for r in service.store.get(service.store.head()["inventoryRef"])["recordings"]
    }
    assert final_ids == initial_ids
