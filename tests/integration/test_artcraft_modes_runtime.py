"""Opt-in native evidence for the selected AniCraft stdio handoff."""

import json
import os
import subprocess
from contextlib import contextmanager
from pathlib import Path
from queue import Queue
from threading import Thread

import pytest
from tests.artcraft_fixtures import picture_output, request
from tests.test_artcraft_jobs import _prepare, job_spec

from avo import artcraft, init_project
from avo.adapters.artcraft import SelectedArtCraftAdapter
from avo.timeline.contracts import file_fingerprint

pytestmark = [pytest.mark.integration, pytest.mark.native_artcraft]


def _installed_cli():
    entry = os.environ.get("AVO_ARTCRAFT_ANICRAFT_TEST_CLI")
    if not entry:
        pytest.skip("set AVO_ARTCRAFT_ANICRAFT_TEST_CLI to the installed 0.2.1 CLI")
    return Path(entry).resolve(strict=True)


def _label_spec(workspace, cli, mode):
    return job_spec(
        workspace,
        jobId=f"speaker-label-{mode}",
        mode=mode,
        cliPath=str(cli),
        authoringParameters={"primaryText": "Clara Caf\u00e9", "font": "Arial"},
        output=picture_output(
            width=640,
            height=360,
            frameCount=24,
            frameRate={"numerator": 24, "denominator": 1},
        ),
        budget={"seconds": 60, "files": 128, "bytes": 16_000_000},
    )


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
    cli = _installed_cli()
    monkeypatch.setattr(init_project, "load_provider", lambda slug: {"slug": slug})
    spec = _label_spec(tmp_path, cli, "host-mcp")
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


class _FixtureStream:
    def __init__(self, process):
        self._process = process

    def read_line(self, *, max_bytes, timeout):
        lines = Queue(maxsize=1)
        reader = Thread(
            target=lambda: lines.put(self._process.stdout.readline(max_bytes)),
            daemon=True,
        )
        reader.start()
        return lines.get(timeout=timeout)

    def send_line(self, message, *, timeout):
        assert timeout > 0
        self._process.stdin.write(message)
        self._process.stdin.flush()


def _fixture_command(binary, roots, directory, arguments, *, env, timeout):
    assert directory.is_relative_to(roots["write"][0])
    return subprocess.run(
        [binary["locator"], *map(str, arguments)],
        cwd=directory,
        env=env,
        capture_output=True,
        check=True,
        timeout=timeout,
    ).stdout


@contextmanager
def _fixture_stream(binary, roots, directory, arguments, *, env, timeout):
    assert directory.is_relative_to(roots["write"][0])
    command, document = arguments
    assert command == "serve"
    assert document.parent == directory
    assert document.name in {"empty.anicraft", "original.anicraft"}
    with subprocess.Popen(
        [binary["locator"], *map(str, arguments)],
        cwd=directory,
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    ) as process:
        try:
            yield _FixtureStream(process)
        finally:
            process.stdin.close()
            try:
                process.wait(timeout=min(timeout, 3))
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)


def test_installed_anicraft_json_lines_and_cli_produce_the_same_export(
    tmp_path, monkeypatch
):
    cli = _installed_cli()
    monkeypatch.setattr(init_project, "load_provider", lambda slug: {"slug": slug})
    store = artcraft.ArtCraftJobStore(tmp_path)
    adapter = SelectedArtCraftAdapter(
        observe_confinement=lambda _installed, roots: roots,
        run_confined=_fixture_command,
        open_confined=_fixture_stream,
    )
    exported = {}
    original = None
    for mode in ("cli", "json-lines"):
        spec = _label_spec(tmp_path, cli, mode)
        prepared = _prepare(artcraft, request(), spec, adapter)
        result = artcraft.run_authoring(
            prepared["jobRef"], expected_head=prepared["head"], adapter=adapter
        )
        assert result["state"] == "exported"
        event = store.head(spec["jobId"])
        assert event["eventHash"] == result["head"]
        assert len(event["outputs"]) == 24
        exported[mode] = [frame["sha256"] for frame in event["outputs"]]
        if mode == "cli":
            original = event["saved"]
    assert exported["cli"] == exported["json-lines"]
    assert original is not None
    retained = Path(original["locator"])
    revised = {
        **_label_spec(tmp_path, cli, "json-lines"),
        "jobId": "speaker-label-json-lines-revision",
        "document": {"state": "saved", "source": str(retained)},
        "readRoots": [str(retained.parent)],
        "authoringParameters": {"primaryText": "Updated label", "font": "Arial"},
    }
    prepared = _prepare(artcraft, request(), revised, adapter)
    result = artcraft.run_authoring(
        prepared["jobRef"], expected_head=prepared["head"], adapter=adapter
    )
    assert result["state"] == "exported"
    event = store.head(revised["jobId"])
    assert len(event["outputs"]) == 24
    assert prepared["job"]["inputs"] == [original]
    assert len(event["revisionCommandSchemaHash"]) == 64
    assert file_fingerprint(retained) == original
    details = adapter.inspect_returned_source(
        prepared["job"], Path(event["saved"]["locator"])
    )
    assert details["editableText"] == "Updated label"
