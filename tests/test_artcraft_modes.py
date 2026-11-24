"""The selected AniCraft operator modes stage exact work for an external host."""

import json
from pathlib import Path
from time import monotonic
from types import SimpleNamespace

import pytest

from avo import artcraft, init_project
from avo.adapters import artcraft as native
from avo.timeline.contracts import file_fingerprint
from tests.artcraft_fixtures import locked_tool_observation, picture_output, request
from tests.test_artcraft_jobs import _prepare, job_spec

HEADLESS = b"  anicraft-cli mcp [file|--sample] Model Context Protocol on stdin/stdout"


@pytest.fixture
def operator_profile(tmp_path, monkeypatch):
    cli = tmp_path / "anicraft-cli.exe"
    application = tmp_path / "anicraft.exe"
    cli.write_bytes(b"selected CLI fixture")
    application.write_bytes(b"selected application fixture")
    installed = {
        "platform": "windows",
        "release": "0.2.1",
        "executable": file_fingerprint(cli),
        "application": file_fingerprint(application),
    }
    observed = []
    monkeypatch.setattr(native, "_installed_anicraft", lambda *_: installed)
    monkeypatch.setattr(native, "_command_schema_hash", lambda _: "a" * 64)
    monkeypatch.setattr(init_project, "load_provider", lambda slug: {"slug": slug})
    monkeypatch.setenv("ANICRAFT_TEST_TOKEN", "fixture-token")

    def advertise(stdout):
        def verify(argv, **kwargs):
            assert argv == [installed["executable"]["locator"], "--help"]
            assert "ANICRAFT_TEST_TOKEN" not in kwargs["env"]
            assert kwargs["shell"] is False
            observed.append(argv)
            return SimpleNamespace(stdout=stdout)

        monkeypatch.setattr(native.subprocess, "run", verify)

    return installed, observed, advertise


def test_selected_host_mcp_stages_only_the_owned_document_and_script(
    tmp_path, operator_profile
):
    installed, observed, advertise = operator_profile
    advertise(HEADLESS)
    adapter = native.SelectedArtCraftAdapter()
    spec = job_spec(
        tmp_path,
        mode="host-mcp",
        authoringParameters={"primaryText": "Speaker", "font": "Arial"},
        output=picture_output(
            width=640,
            height=360,
            frameCount=24,
            frameRate={"numerator": 24, "denominator": 1},
        ),
    )
    spec["budget"]["files"] = spec["output"]["frameCount"] + 4
    prepared = _prepare(artcraft, request(), spec, adapter)
    observation = prepared["job"]["observation"]
    assert observation["authority"] == "operator"
    assert observation["hostTransport"] == "stdio"
    assert "effectiveRoots" not in observation
    ready = artcraft.run_authoring(
        prepared["jobRef"], expected_head=prepared["head"], adapter=adapter
    )
    assert ready["state"] == "ready"
    handoff = Path(ready["handoff"]["locator"])
    manifest = json.loads(handoff.read_text(encoding="utf-8"))
    assert manifest["mode"] == "host-mcp"
    assert manifest["artifactState"] == "reference-only"
    assert manifest["operatorRoots"]["write"] == [str(handoff.parent)]
    assert manifest["operatorBudget"] == spec["budget"]
    assert manifest["commands"][0][:4] == [
        installed["executable"]["locator"],
        "new",
        "--out",
        str(handoff.parent / "empty.anicraft"),
    ]
    assert len(manifest["commands"]) == 1
    host = manifest["host"]
    assert host["transport"] == "stdio"
    assert host["argv"] == [
        installed["executable"]["locator"],
        "mcp",
        str(handoff.parent / "empty.anicraft"),
    ]
    assert host["cwd"] == str(handoff.parent)
    assert host["enforceOperatorRoots"] is True
    assert host["unsetEnvironmentPrefixes"] == ["ANICRAFT_"]
    assert host["scriptTool"] == "anicraft_run_script"
    recipe = Path(manifest["recipe"]["locator"])
    recipe_steps = json.loads(recipe.read_text(encoding="utf-8"))
    assert set(host["allowedCommandIds"]) == {step["command"] for step in recipe_steps}
    assert "file.open" not in host["allowedCommandIds"]
    assert not (handoff.parent / "empty.anicraft").exists()
    assert not Path(manifest["nativeDocument"]).exists()
    assert "fixture-token" not in handoff.read_text(encoding="utf-8")
    assert (
        artcraft.run_authoring(
            prepared["jobRef"], expected_head=ready["head"], adapter=adapter
        )
        == ready
    )
    assert (
        artcraft.recover_authoring(prepared["jobRef"], expected_head=ready["head"])[
            "recovery"
        ]["nextAction"]
        == "inspect-operator-return"
    )
    assert len(observed) == 1


@pytest.mark.parametrize("mode", ["guided", "host-mcp"])
def test_operator_handoff_rejects_insufficient_files_before_planning(
    tmp_path, monkeypatch, operator_profile, mode
):
    _, _, advertise = operator_profile
    advertise(HEADLESS)
    adapter = native.SelectedArtCraftAdapter()
    spec = job_spec(
        tmp_path,
        mode=mode,
        authoringParameters={"primaryText": "Speaker", "font": "Arial"},
    )
    spec["budget"]["files"] = spec["output"]["frameCount"] + 3
    prepared = _prepare(artcraft, request(), spec, adapter)

    def unexpected_plan(*_args):
        pytest.fail("An undersized file budget must fail before planning the handoff")

    monkeypatch.setattr(adapter, "plan_lower_third", unexpected_plan)
    with pytest.raises(
        artcraft.ArtCraftError, match="operator handoff.*file budget"
    ) as failure:
        artcraft.run_authoring(
            prepared["jobRef"], expected_head=prepared["head"], adapter=adapter
        )
    assert failure.value.code == "ARTCRAFT_NOT_READY"
    workspace = Path(prepared["job"]["roots"]["write"][0])
    assert not (workspace / "recipe.json").exists()
    assert not (workspace / "handoff.json").exists()
    assert (
        artcraft.inspect_authoring(prepared["jobRef"], expected_head=prepared["head"])[
            "state"
        ]
        == "prepared"
    )


@pytest.mark.parametrize("mode", ["guided", "host-mcp"])
def test_operator_handoff_rejects_insufficient_bytes_before_writing(
    tmp_path, operator_profile, mode
):
    _, _, advertise = operator_profile
    advertise(HEADLESS)
    adapter = native.SelectedArtCraftAdapter()
    spec = job_spec(
        tmp_path,
        mode=mode,
        authoringParameters={"primaryText": "Café", "font": "Arial"},
    )
    spec["budget"]["bytes"] = 1
    prepared = _prepare(artcraft, request(), spec, adapter)

    with pytest.raises(
        artcraft.ArtCraftError, match="operator handoff.*byte budget"
    ) as exc:
        artcraft.run_authoring(
            prepared["jobRef"], expected_head=prepared["head"], adapter=adapter
        )

    assert exc.value.code == "ARTCRAFT_NOT_READY"
    workspace = Path(prepared["job"]["roots"]["write"][0])
    assert not (workspace / "recipe.json").exists()
    assert not (workspace / "handoff.json").exists()
    assert (
        artcraft.inspect_authoring(prepared["jobRef"], expected_head=prepared["head"])[
            "state"
        ]
        == "prepared"
    )


def test_guided_handoff_reuses_recipe_after_interrupted_staging(
    tmp_path, operator_profile, monkeypatch
):
    adapter = native.SelectedArtCraftAdapter()
    spec = job_spec(
        tmp_path,
        mode="guided",
        authoringParameters={"primaryText": "Café", "font": "Arial"},
    )
    prepared = _prepare(artcraft, request(), spec, adapter)
    write = artcraft.write_immutable_json

    def interrupt_handoff(path, value):
        if path.name == "handoff.json":
            raise OSError("fixture interrupted the handoff write")
        return write(path, value)

    def run():
        return artcraft.run_authoring(
            prepared["jobRef"], expected_head=prepared["head"], adapter=adapter
        )

    with monkeypatch.context() as interrupted:
        interrupted.setattr(artcraft, "write_immutable_json", interrupt_handoff)
        with pytest.raises(OSError, match="interrupted"):
            run()

    recipe = Path(prepared["job"]["roots"]["write"][0]) / "recipe.json"
    fingerprint = file_fingerprint(recipe)
    ready = run()
    descriptor = json.loads(
        Path(ready["handoff"]["locator"]).read_text(encoding="utf-8")
    )
    assert ready["state"] == "ready"
    assert descriptor["recipe"] == fingerprint == file_fingerprint(recipe)


def test_guided_handoff_accepts_exact_file_budget(tmp_path, operator_profile):
    adapter = native.SelectedArtCraftAdapter()
    spec = job_spec(
        tmp_path,
        mode="guided",
        authoringParameters={"primaryText": "Speaker", "font": "Arial"},
    )
    spec["budget"]["files"] = spec["output"]["frameCount"] + 4
    prepared = _prepare(artcraft, request(), spec, adapter)
    ready = artcraft.run_authoring(
        prepared["jobRef"], expected_head=prepared["head"], adapter=adapter
    )
    assert ready["state"] == "ready"
    manifest = json.loads(Path(ready["handoff"]["locator"]).read_text(encoding="utf-8"))
    assert manifest["operatorBudget"] == spec["budget"]
    assert "host" not in manifest
    assert (
        artcraft.run_authoring(
            prepared["jobRef"], expected_head=ready["head"], adapter=adapter
        )
        == ready
    )


def test_missing_headless_mcp_capability_does_not_fall_back(tmp_path, operator_profile):
    _, observed, advertise = operator_profile
    advertise(b"anicraft-cli serve [file|--sample] on stdin/stdout")
    adapter = native.SelectedArtCraftAdapter()
    with pytest.raises(artcraft.ArtCraftError, match="headless stdio MCP") as failure:
        _prepare(
            artcraft,
            request(),
            job_spec(tmp_path, mode="host-mcp"),
            adapter,
        )
    assert failure.value.code == "ARTCRAFT_NOT_READY"
    assert len(observed) == 1
    assert not list(tmp_path.glob("**/job.json"))


def test_verified_json_lines_can_register_only_the_selected_lower_third(tmp_path):
    observation = {
        **locked_tool_observation(tmp_path, "anicraft"),
        "app": "anicraft",
        "operations": ["lower-third"],
        "mode": "json-lines",
        "platform": "windows",
        "release": "0.2.1",
        "effectiveRoots": {"read": [], "write": [str(tmp_path)]},
    }
    assert artcraft.require_artcraft_export_environment(observation) == observation
    for different in (
        {"mode": "host-mcp"},
        {"app": "vectorcraft"},
        {"operations": ["animate-vector-emblem"]},
        {"release": "0.2.2"},
        {"platform": "linux"},
        {"effectiveRoots": None},
    ):
        with pytest.raises(artcraft.ArtCraftError, match="native command observations"):
            artcraft.require_artcraft_export_environment({**observation, **different})
    Path(observation["executable"]["locator"]).write_bytes(b"changed CLI fixture")
    with pytest.raises(artcraft.ArtCraftError, match="installation has changed"):
        artcraft.require_artcraft_export_environment(observation)


def test_json_lines_requires_its_own_confined_stream(tmp_path, operator_profile):
    _, observed, advertise = operator_profile
    advertise(b"anicraft-cli serve [file|--sample] on stdin/stdout")
    adapter = native.SelectedArtCraftAdapter(
        observe_confinement=lambda _, roots: roots,
        run_confined=lambda *_: pytest.fail("batch is not the selected transport"),
    )
    with pytest.raises(
        artcraft.ArtCraftError, match="confined stdio runner"
    ) as failure:
        _prepare(artcraft, request(), job_spec(tmp_path, mode="json-lines"), adapter)
    assert failure.value.code == "ARTCRAFT_NOT_READY"
    assert observed == []


def test_cli_requires_a_confined_runner_before_observing_roots(
    tmp_path, operator_profile
):
    _, observed, _ = operator_profile

    def unexpected_observation(*_):
        pytest.fail("Root observations alone cannot make a CLI job ready")

    adapter = native.SelectedArtCraftAdapter(observe_confinement=unexpected_observation)
    with pytest.raises(
        artcraft.ArtCraftError, match="confined command runner"
    ) as failure:
        _prepare(artcraft, request(), job_spec(tmp_path, mode="cli"), adapter)
    assert failure.value.code == "ARTCRAFT_NOT_READY"
    assert observed == []
    assert not list(tmp_path.rglob("job.json"))


@pytest.mark.parametrize("mode", ["live", "script", "action"])
def test_unqualified_transport_refuses_before_native_probe(
    tmp_path, monkeypatch, operator_profile, mode
):
    def unexpected(*_args, **_kwargs):
        pytest.fail("An unqualified transport attempted native discovery")

    monkeypatch.setattr(native, "_installed_anicraft", unexpected)
    with pytest.raises(artcraft.ArtCraftError, match="no qualified profile"):
        _prepare(
            artcraft,
            request(),
            job_spec(tmp_path, mode=mode),
            native.SelectedArtCraftAdapter(),
        )
    assert not list(tmp_path.rglob("job.json"))


@pytest.mark.parametrize("conflict", ["effective-roots", "owned-document"])
def test_changed_authority_or_document_refuses_before_dispatch(
    tmp_path, operator_profile, conflict
):
    expanded = False

    def confinement(_installed, roots):
        if expanded:
            return {**roots, "read": [str(tmp_path)]}
        return roots

    def unexpected(*_args, **_kwargs):
        pytest.fail("A changed authority or occupied document dispatched a command")

    adapter = native.SelectedArtCraftAdapter(
        observe_confinement=confinement, run_confined=unexpected
    )
    spec = job_spec(
        tmp_path,
        authoringParameters={"primaryText": "Speaker", "font": "Arial"},
        output=picture_output(
            width=640,
            height=360,
            frameCount=24,
            frameRate={"numerator": 24, "denominator": 1},
        ),
    )
    prepared = _prepare(artcraft, request(), spec, adapter)
    if conflict == "effective-roots":
        expanded = True
        message = "exact qualified"
    else:
        document = tmp_path / prepared["job"]["document"]
        document.parent.mkdir(parents=True, exist_ok=True)
        document.write_bytes(b"owned by another writer")
        message = "stale"

    with pytest.raises(artcraft.ArtCraftError, match=message):
        artcraft.run_authoring(
            prepared["jobRef"], expected_head=prepared["head"], adapter=adapter
        )
    current = artcraft.inspect_authoring(
        prepared["jobRef"], expected_head=prepared["head"]
    )
    assert current["state"] == "prepared"


def test_occupied_saved_revision_refuses_before_tool_validation(
    tmp_path, monkeypatch, operator_profile
):
    def unexpected(*_args, **_kwargs):
        pytest.fail("An occupied saved revision must not reach native validation")

    source = tmp_path / "source.anicraft"
    source.write_bytes(b"selected editable source")
    adapter = native.SelectedArtCraftAdapter(
        observe_confinement=lambda _installation, roots: roots,
        run_confined=unexpected,
    )
    spec = job_spec(
        tmp_path,
        document={"state": "saved", "source": str(source)},
        readRoots=[str(tmp_path)],
        authoringParameters={"primaryText": "Speaker", "font": "Arial"},
        output=picture_output(),
    )
    prepared = _prepare(artcraft, request(), spec, adapter)
    document = tmp_path / prepared["job"]["document"]
    occupied = document.parent / "revision" / "component.anicraft"
    occupied.parent.mkdir()
    occupied.write_bytes(b"owned by another writer")
    prior = file_fingerprint(occupied)
    monkeypatch.setattr(adapter, "validate_run", unexpected)

    current = artcraft.inspect_authoring(
        prepared["jobRef"], expected_head=prepared["head"]
    )
    with pytest.raises(artcraft.ArtCraftError, match="stale"):
        artcraft.run_authoring(
            prepared["jobRef"], expected_head=prepared["head"], adapter=adapter
        )

    assert current["status"] == "stale"
    assert current["checks"]["nativeDocument"] == "changed"
    head = artcraft.ArtCraftJobStore(tmp_path).head(spec["jobId"])
    assert head["state"] == "prepared" and head["eventHash"] == prepared["head"]
    assert file_fingerprint(occupied) == prior
    assert document.read_bytes() == source.read_bytes() == b"selected editable source"


@pytest.mark.parametrize(
    "reply",
    [
        b'{"id":1,"ok":false,"error":"failed command"}\n',
        b'{"id":2,"ok":true,"result":{}}\n',
        b'{"id":1,"ok":true,"ok":false,"result":{}}\n',
        b'{"id":1,"ok":true}\n',
        b'{"id":1,"ok":true,"result":null}\n',
        b'{"id":1,"ok":true,"result":{"error":"failed command"}}\n',
    ],
)
def test_native_json_lines_stops_before_sending_next_command(tmp_path, reply):
    from contextlib import contextmanager

    from avo.adapters.artcraft_anicraft import _run_json_lines

    source = tmp_path / "empty.anicraft"
    target = tmp_path / "component.anicraft"
    source.write_bytes(b"native fixture")
    responses = iter([b'{"app":"AniCraft","ready":true,"version":"0.2.1"}\n', reply])
    sent = []

    @contextmanager
    def open_stream(document, *, timeout):
        assert document == source
        assert 0 < timeout <= 5
        yield SimpleNamespace(
            read_line=lambda **_: next(responses, b""),
            send_line=lambda message, **_: sent.append(json.loads(message)),
        )

    steps = [
        {"cmd": "layer.new", "params": {"name": "Label"}},
        {"cmd": "file.save_as", "params": {"path": str(target)}},
    ]
    with pytest.raises(artcraft.ArtCraftError, match="AniCraft JSON-lines"):
        _run_json_lines(
            open_stream,
            source,
            target,
            steps,
            budget={"files": 12, "bytes": 4096},
            deadline=monotonic() + 5,
        )
    assert sent == [{"id": 1, **steps[0]}]
    assert not target.exists()


@pytest.mark.parametrize(
    ("partial", "save_name"),
    [
        (None, "component.anicraft"),
        ({"error": "failed command"}, "component.anicraft"),
        ({"index": 0}, "different.anicraft"),
    ],
)
def test_native_batch_rejects_invalid_partial_result_even_with_saved_file(
    tmp_path, partial, save_name
):
    from avo.adapters.artcraft_anicraft import _apply_recipe

    source = tmp_path / "empty.anicraft"
    target = tmp_path / "component.anicraft"
    recipe = tmp_path / "recipe.json"
    steps = [
        {"cmd": "layer.new", "params": {"name": "Label"}},
        {"cmd": "file.save_as", "params": {"path": str(target)}},
    ]

    def call(command, document, script):
        assert (command, document, script) == ("run", source, recipe)
        target.write_bytes(b"partial native document")
        return json.dumps([partial, {"saved": str(tmp_path / save_name)}]).encode(
            "utf-8"
        )

    with pytest.raises(artcraft.ArtCraftError, match="AniCraft"):
        _apply_recipe(call, source, target, recipe, steps, None, {}, monotonic() + 5)


def test_native_json_lines_stops_before_export_when_save_reply_names_another_file(
    tmp_path,
):
    from contextlib import contextmanager

    from avo.adapters.artcraft_anicraft import _run_json_lines

    source = tmp_path / "empty.anicraft"
    source.write_bytes(b"native fixture")
    target = tmp_path / "component.anicraft"
    other = tmp_path / "different.anicraft"
    reply = {"id": 1, "ok": True, "result": {"saved": str(other)}}
    steps = [
        {"cmd": "file.save_as", "params": {"path": str(target)}},
        {
            "cmd": "file.export_png_sequence",
            "params": {"dir": str(tmp_path / "white"), "from": 0, "to": 23},
        },
    ]
    sent = []

    def send_line(message, **_):
        sent.append(json.loads(message))
        if len(sent) == 1:
            target.write_bytes(b"partial native document")

    @contextmanager
    def open_stream(document, *, timeout):
        assert document == source
        assert 0 < timeout <= 5
        replies = iter(
            [
                b'{"app":"AniCraft","ready":true,"version":"0.2.1"}\n',
                json.dumps(reply).encode("utf-8") + b"\n",
            ]
        )
        yield SimpleNamespace(
            read_line=lambda **_: next(replies, b""), send_line=send_line
        )

    with pytest.raises(artcraft.ArtCraftError, match="AniCraft JSON-lines"):
        _run_json_lines(
            open_stream,
            source,
            target,
            steps,
            budget={"files": 12, "bytes": 4096},
            deadline=monotonic() + 5,
        )
    assert sent == [{"id": 1, **steps[0]}]
    assert target.is_file()


@pytest.mark.parametrize(
    "row",
    [
        {"command": "develop.set", "ok": True, "result": {"error": "failed"}},
        {"command": "develop.set", "ok": True, "result": None, "error": "failed"},
        {"command": "develop.set", "ok": True},
        {"command": "develop.get", "ok": True, "result": None},
    ],
)
def test_lightcraft_rejects_incomplete_or_failed_command_results(row):
    from avo.adapters.artcraft_lightcraft import _receipts

    with pytest.raises(artcraft.ArtCraftError, match="every selected command"):
        _receipts(json.dumps(row).encode("utf-8"), (row["command"],))


@pytest.mark.parametrize("result", [None, {"error": "failed"}])
def test_soundcraft_rejects_failed_session_creation_receipts(result):
    from avo.adapters.artcraft_soundcraft import _run_results

    reply = f"session.new: {json.dumps(result)}\n".encode()
    with pytest.raises(artcraft.ArtCraftError, match="invalid command result"):
        _run_results(reply, ("session.new",))


@pytest.mark.parametrize("result", [None, {"error": "failed"}])
def test_vectorcraft_rejects_failed_intermediate_command_receipts(tmp_path, result):
    from avo.adapters.artcraft_vectorcraft import _card_invocation

    def invoke(directory, *arguments, timeout):
        assert directory == tmp_path
        assert arguments == ("--safe-mode", "run")
        assert timeout > 0
        return json.dumps(
            {"step": "cmd", "command": "paint.setFill", "result": result}
        ).encode("utf-8")

    call = _card_invocation(tmp_path, {"bytes": 1024, "files": 2, "seconds": 5}, invoke)
    with pytest.raises(artcraft.ArtCraftError, match="invalid command result"):
        call("run")
