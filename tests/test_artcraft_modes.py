"""The selected AniCraft operator modes stage exact work for an external host."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from avo import artcraft, init_project
from avo.adapters import artcraft as native
from avo.timeline.contracts import file_fingerprint
from tests.artcraft_fixtures import picture_output, request
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
