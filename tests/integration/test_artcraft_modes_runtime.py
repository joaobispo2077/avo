"""Opt-in native evidence for the selected AniCraft stdio handoff."""

import json
import os
import subprocess
from pathlib import Path

import pytest
from tests.artcraft_fixtures import picture_output, request
from tests.test_artcraft_jobs import _prepare, job_spec

from avo import artcraft, init_project
from avo.adapters.artcraft import SelectedArtCraftAdapter
from avo.timeline.contracts import file_fingerprint

pytestmark = pytest.mark.integration


def _rpc(method, *, request_id=None, params=None):
    return {
        "jsonrpc": "2.0",
        "method": method,
        **({"id": request_id} if request_id is not None else {}),
        **({"params": params} if params is not None else {}),
    }


def test_installed_anicraft_mcp_handoff_writes_an_inspectable_headless_source(
    tmp_path, monkeypatch
):
    entry = os.environ.get("AVO_ARTCRAFT_ANICRAFT_TEST_CLI")
    if not entry:
        pytest.skip("set AVO_ARTCRAFT_ANICRAFT_TEST_CLI to the installed 0.2.1 CLI")
    cli = Path(entry).resolve(strict=True)
    monkeypatch.setattr(init_project, "load_provider", lambda slug: {"slug": slug})
    spec = job_spec(
        tmp_path,
        mode="host-mcp",
        cliPath=str(cli),
        authoringParameters={"primaryText": "Clara Caf\u00e9", "font": "Arial"},
        output=picture_output(
            width=640,
            height=360,
            frameCount=24,
            frameRate={"numerator": 24, "denominator": 1},
        ),
    )
    adapter = SelectedArtCraftAdapter()
    prepared = _prepare(artcraft, request(), spec, adapter)
    ready = artcraft.run_authoring(
        prepared["jobRef"], expected_head=prepared["head"], adapter=adapter
    )
    handoff = Path(ready["handoff"]["locator"])
    details = json.loads(handoff.read_text(encoding="utf-8"))
    host = details["host"]
    assert host["enforceOperatorRoots"] is True
    assert details["operatorRoots"] == {
        "read": [str(handoff.parent)],
        "write": [str(handoff.parent)],
    }
    recipe = Path(details["recipe"]["locator"])
    assert file_fingerprint(recipe) == details["recipe"]
    steps = json.loads(recipe.read_text(encoding="utf-8"))
    environment = {
        key: value
        for key, value in os.environ.items()
        if not any(
            key.upper().startswith(prefix)
            for prefix in host["unsetEnvironmentPrefixes"]
        )
    }
    for command in details["commands"]:
        subprocess.run(command, cwd=host["cwd"], env=environment, timeout=7, check=True)
    messages = [
        _rpc(
            "initialize",
            request_id=1,
            params={
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "AVO native test", "version": "1"},
            },
        ),
        _rpc("notifications/initialized"),
        _rpc("tools/list", request_id=2),
        _rpc(
            "tools/call",
            request_id=3,
            params={"name": host["scriptTool"], "arguments": {"steps": steps}},
        ),
    ]
    process = subprocess.run(
        host["argv"],
        cwd=host["cwd"],
        env=environment,
        input="".join(json.dumps(message) + "\n" for message in messages),
        text=True,
        encoding="utf-8",
        capture_output=True,
        timeout=30,
        check=True,
    )
    replies = {
        item["id"]: item for item in map(json.loads, process.stdout.splitlines())
    }
    assert replies[1]["result"]["protocolVersion"] == "2024-11-05"
    assert host["scriptTool"] in {
        tool["name"] for tool in replies[2]["result"]["tools"]
    }
    assert "error" not in replies[3], replies[3]
    assert not replies[3]["result"].get("isError"), replies[3]
    result = artcraft.inspect_authoring(
        prepared["jobRef"],
        expected_head=ready["head"],
        source_inspector=adapter.inspect_returned_source,
    )
    assert result["state"] == "ready"
    assert result["checks"]["nativeDocument"] == "returned-unverified"
    assert result["sourceObservations"]["editableText"] == "Clara Caf\u00e9"
    assert len(list((handoff.parent / "white").glob("*.png"))) == 24
