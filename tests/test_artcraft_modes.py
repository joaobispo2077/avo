"""The selected AniCraft operator modes stage exact work for an external host."""

import json
from pathlib import Path
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


@pytest.mark.parametrize(
    "reply",
    [
        b'{"id":1,"ok":false,"error":"failed command"}\n',
        b'{"id":2,"ok":true,"result":{}}\n',
        b'{"id":1,"ok":true,"ok":false,"result":{}}\n',
        b'{"id":1,"ok":true}\n',
    ],
)
def test_native_json_lines_stops_before_sending_next_command(tmp_path, reply):
    from contextlib import contextmanager
    from time import monotonic

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
            read_line=lambda **_: next(responses),
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
