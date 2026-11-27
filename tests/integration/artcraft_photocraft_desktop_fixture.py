"""Own an opt-in, disposable PhotoCraft desktop and its test-only MCP bridges."""

import csv
import json
import os
import socket
import subprocess
from contextlib import contextmanager
from pathlib import Path
from queue import Empty
from secrets import token_hex
from tempfile import TemporaryDirectory
from time import monotonic, sleep
from types import SimpleNamespace

import pytest
from tests.integration.test_artcraft_modes_runtime import _FixtureStream, _rpc

VERSION = "0.23.1"
_PROTOCOL = "2025-06-18"


def require(condition, message):
    if not condition:
        pytest.fail(message, pytrace=False)


def names_selected_file(reported, expected):
    return isinstance(reported, str) and (
        reported == expected.name or Path(reported).resolve() == expected
    )


def _launch_options():
    startup = subprocess.STARTUPINFO()
    startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startup.wShowWindow = subprocess.SW_HIDE
    return {"startupinfo": startup, "creationflags": subprocess.CREATE_NO_WINDOW}


def _capture(argv):
    try:
        result = subprocess.run(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=5,
            **_launch_options(),
        )
    except (OSError, subprocess.SubprocessError):
        pytest.fail("A PhotoCraft fixture command did not complete.", pytrace=False)
    require(result.returncode == 0, "A PhotoCraft fixture command failed.")
    return result.stdout


def _windows_tool(program, *arguments):
    executable = Path(os.environ["SystemRoot"]) / "System32" / f"{program}.exe"
    return _capture([executable, *arguments])


def _private_token(directory):
    directory.mkdir()
    identity = _windows_tool("whoami", "/user", "/fo", "csv", "/nh")
    row = next(csv.reader(identity.decode("ascii", errors="replace").splitlines()), [])
    sid = row[-1].strip() if row else ""
    require(
        sid.startswith("S-1-") and all(part.isdigit() for part in sid[2:].split("-")),
        "The fixture could not identify the Windows user for the credential ACL.",
    )
    _windows_tool(
        "icacls", directory, "/inheritance:r", "/grant:r", f"*{sid}:(OI)(CI)F"
    )
    path = directory / "control.token"
    path.write_text(token_hex(32), encoding="ascii")
    return path


def _owns_listener(port, process):
    address = [b"TCP", f"127.0.0.1:{port}".encode(), b"0.0.0.0:0"]
    rows = _windows_tool("netstat", "-ano", "-p", "tcp").splitlines()
    owners = [row[-1] for line in rows if (row := line.split())[:3] == address]
    require(
        not owners or owners == [str(process.pid).encode()],
        "The selected loopback listener belongs to another process.",
    )
    return bool(owners) and process.poll() is None


@contextmanager
def _owned_process(argv, root, environment, *, bridge=False):
    process = subprocess.Popen(
        argv,
        cwd=root,
        env=environment,
        stdin=subprocess.PIPE if bridge else subprocess.DEVNULL,
        stdout=subprocess.PIPE if bridge else subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        **_launch_options(),
    )
    try:
        yield process
    finally:
        if process.poll() is None:
            process.terminate()
        process.wait(timeout=4)
        if bridge:
            process.stdin.close()
            process.stdout.close()


class _Bridge:
    def __init__(self, process):
        self.process = process
        self.stream = _FixtureStream(process)
        self.request_id = 0
        self.deadline = monotonic() + 35

    def _request(self, method, params=None):
        self.request_id += 1
        notification = method == "notifications/initialized"
        request_id = None if notification else self.request_id
        message = _rpc(method, request_id=request_id, params=params)
        self.stream.send_line(json.dumps(message).encode() + b"\n", timeout=1)
        if not notification:
            return self._response(request_id)
        return None

    def _response(self, request_id):
        limit = 2 * 1024 * 1024
        while (remaining := self.deadline - monotonic()) > 0:
            raw = self.stream.read_line(max_bytes=limit + 1, timeout=remaining)
            require(
                raw.endswith(b"\n") and len(raw) <= limit,
                "The MCP bridge returned an invalid frame.",
            )
            reply = json.loads(raw)
            if "id" not in reply and "method" in reply:
                continue
            require(
                type(reply.get("id")) is int
                and reply["id"] == request_id
                and isinstance(reply.get("result"), dict),
                "The MCP bridge returned an unexpected response.",
            )
            return reply["result"]
        pytest.fail("The MCP bridge exceeded its deadline.", pytrace=False)

    def initialize(self):
        result = self._request(
            "initialize",
            {
                "protocolVersion": _PROTOCOL,
                "capabilities": {},
                "clientInfo": {"name": "AVO PhotoCraft fixture", "version": "1"},
            },
        )
        require(result.get("protocolVersion") == _PROTOCOL, "Unexpected MCP version.")
        self._request("notifications/initialized")

    def call(self, tool, arguments=None, *, expect_busy=False):
        result = self._request(
            "tools/call", {"name": tool, "arguments": arguments or {}}
        )
        if expect_busy:
            require(
                result.get("isError") is True,
                "Inconclusive interruption fixture: the second save was accepted.",
            )
            error = " ".join(
                item.get("text", "") for item in result.get("content", [])
            ).lower()
            require(
                "still running" in error or ("sav" in error and "busy" in error),
                "The competing client did not receive the native document-busy refusal.",
            )
            return None
        require(not result.get("isError"), f"The selected desktop tool failed: {tool}.")
        if (data := result.get("structuredContent")) is not None:
            return data
        [content] = result["content"]
        return json.loads(content["text"])

    def begin_save(self, name, *, expect_busy=False):
        return self.call(
            "control_call",
            {"method": "app.save", "params": {"path": name, "wait": False}},
            expect_busy=expect_busy,
        )

    def job(self, identifier):
        report = self.call("jobs_list")
        rows = report["jobs"] if isinstance(report, dict) else report
        return next(
            (item for item in rows if item.get("id", item.get("job")) == identifier),
            {},
        )


@contextmanager
def _bridge(cli, port, token, root, environment):
    argv = [cli, "mcp", "--bridge", f"127.0.0.1:{port}", "--control-token-file", token]
    with _owned_process(argv, root, environment, bridge=True) as process:
        connection = _Bridge(process)
        connection.initialize()
        yield connection


@contextmanager
def photocraft_desktop():
    app = os.environ.get("AVO_ARTCRAFT_PHOTOCRAFT_TEST_APP")
    cli = os.environ.get("AVO_ARTCRAFT_PHOTOCRAFT_TEST_CLI")
    if os.name != "nt" or not (app and cli):
        pytest.skip("Select the installed Windows PhotoCraft 0.23.1 app and CLI")
    try:
        with TemporaryDirectory(prefix="avo-photocraft-live-") as work:
            with _desktop(
                Path(work).resolve(), Path(app).resolve(), Path(cli).resolve()
            ) as session:
                yield session
    except (
        OSError,
        subprocess.SubprocessError,
        ValueError,
        Empty,
        KeyError,
        TypeError,
    ):
        pytest.fail("The isolated PhotoCraft fixture did not complete.", pytrace=False)


@contextmanager
def _desktop(root, app, cli):
    """Keep native preferences, recovery files and credentials in disposable storage."""
    require(app.is_file() and cli.is_file(), "The selected PhotoCraft pair is missing.")
    version = _capture([cli, "--version"]).split()
    require(
        version[:2] == [b"photocraft-cli", VERSION.encode()],
        "The selected PhotoCraft CLI release differs.",
    )
    inputs, outputs, config, scratch = (
        root / name for name in ("input", "output", "config", "scratch")
    )
    for directory in (inputs, outputs, config, scratch):
        directory.mkdir()
    prefs = {
        "general": {"automaticallyCheckUpdates": False},
        "integrations": {"allowAgentControl": True, "controlPort": 0},
    }
    (config / "preferences.json").write_text(json.dumps(prefs), encoding="utf-8")
    token = _private_token(root / "private")
    environment = {
        name: os.environ[name]
        for name in os.environ
        if not name.upper().startswith("PHOTOCRAFT_")
    }
    environment.update(
        PHOTOCRAFT_CONFIG_DIR=str(config), TEMP=str(scratch), TMP=str(scratch)
    )
    with socket.socket() as reserve:
        reserve.bind(("127.0.0.1", 0))
        port = reserve.getsockname()[1]
    argv = [
        app,
        "--new-instance",
        "--safe-gpu",
        "--control",
        str(port),
        "--control-token-file",
        token,
        "--automation-read-root",
        inputs,
        "--automation-write-root",
        outputs,
    ]
    with _owned_process(argv, root, environment) as process:
        deadline = monotonic() + 20
        while monotonic() < deadline and not _owns_listener(port, process):
            require(
                process.poll() is None,
                "The owned PhotoCraft desktop exited at startup.",
            )
            sleep(0.25)
        require(
            _owns_listener(port, process),
            "The owned PhotoCraft listener was unavailable.",
        )
        yield SimpleNamespace(
            inputs=inputs,
            outputs=outputs,
            owned_listener=lambda: _owns_listener(port, process),
            bridge=lambda: _bridge(cli, port, token, root, environment),
        )
