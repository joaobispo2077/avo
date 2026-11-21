"""Retain real installed-editor outputs after a lost authoring response."""

import os
import subprocess
from pathlib import Path

import pytest
from tests.artcraft_fixtures import request
from tests.integration.test_artcraft_lower_third_runtime import _job_contract
from tests.test_artcraft_jobs import _prepare, job_spec

from avo import artcraft, init_project
from avo.adapters.artcraft import SelectedArtCraftAdapter
from avo.adapters.artcraft_anicraft import inspect_lower_third_source

pytestmark = pytest.mark.integration


def test_installed_anicraft_save_is_retained_when_the_runner_loses_its_reply(
    tmp_path, monkeypatch
):
    executable = os.environ.get("AVO_ARTCRAFT_ANICRAFT_TEST_CLI")
    if not executable:
        pytest.skip("Select the installed AniCraft 0.2.1 CLI")
    cli = Path(executable).resolve(strict=True)
    monkeypatch.setattr(init_project, "load_provider", lambda slug: {"slug": slug})
    calls = []

    def drop_save_reply(binary, roots, directory, arguments, *, env, timeout):
        assert binary["locator"] == str(cli)
        assert roots["write"] == [str(directory)] and directory.is_relative_to(tmp_path)
        calls.append(arguments[0])
        written = subprocess.run(
            [str(cli), *map(str, arguments)],
            cwd=directory,
            env=env,
            timeout=timeout,
            capture_output=True,
            check=True,
        )
        if arguments[0] == "run":
            assert (directory / "component.anicraft").is_file()
            raise ConnectionError(
                "fixture dropped the result after the real native save"
            )
        return written.stdout

    adapter = SelectedArtCraftAdapter(
        observe_confinement=lambda _tool, roots: roots, run_confined=drop_save_reply
    )
    output = _job_contract()
    parameters = {"primaryText": "Retained speaker", "font": "Arial"}
    spec = job_spec(
        tmp_path, cliPath=str(cli), output=output, authoringParameters=parameters
    )
    prepared = _prepare(artcraft, request(), spec, adapter)
    with pytest.raises(artcraft.ArtCraftError) as interrupted:
        artcraft.run_authoring(
            prepared["jobRef"], expected_head=prepared["head"], adapter=adapter
        )
    assert interrupted.value.code == "ARTCRAFT_OUTCOME_UNKNOWN"
    assert calls == ["new", "exec", "run"]
    pending = artcraft.ArtCraftJobStore(tmp_path).head(spec["jobId"])
    assert pending["state"] == "outcome-unknown" and "outputs" not in pending
    native = tmp_path / prepared["job"]["document"]
    inspected = inspect_lower_third_source(
        native, output, parameters, max_bytes=spec["budget"]["bytes"]
    )
    assert inspected["editableText"] == parameters["primaryText"]
    recovery = artcraft.recover_authoring(
        prepared["jobRef"], expected_head=pending["eventHash"]
    )["recovery"]
    assert recovery["retainedFiles"][0] == inspected["fingerprint"]
    assert recovery["artifactState"] == "reference-only"
    with pytest.raises(artcraft.ArtCraftError, match="requires reconciliation"):
        artcraft.recover_authoring(
            prepared["jobRef"],
            expected_head=prepared["head"],
            action="retry",
            adapter=None,
        )
    assert calls == ["new", "exec", "run"]
