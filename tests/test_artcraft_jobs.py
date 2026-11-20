"""Preparation closes provider, project, source and runtime scope before writing."""

import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from avo.artcraft import ArtCraftError, ArtCraftIntent, assess_request
from avo.timeline.contracts import file_fingerprint
from tests.artcraft_fixtures import executable_observation, picture_output, request


def job_spec(workspace, **changes):
    return {
        "version": 1,
        "jobId": "speaker-label-preview",
        "provider": "neutral-channel",
        "workspace": str(workspace),
        "mode": "cli",
        "document": {"state": "empty"},
        "readRoots": [],
        "output": picture_output(frameRate={"numerator": 24, "denominator": 1}),
        "budget": {"seconds": 60, "files": 128, "bytes": 4_000_000},
        **changes,
    }


class SelectedApp:
    def __init__(self, workspace):
        self.workspace = workspace
        self.calls = []

    def observe(self, *, scope, mode, roots, cli_path, app_path):
        self.calls.append((scope, mode, roots, cli_path, app_path))
        return {
            **executable_observation(self.workspace / "anicraft-cli.exe"),
            "effectiveRoots": roots,
        }


@pytest.fixture
def authoring(tmp_path, monkeypatch):
    from avo import artcraft, init_project

    workspace = tmp_path / "external-workspace"
    workspace.mkdir()

    def get_provider(slug):
        assert slug == "neutral-channel"
        return {"slug": slug}

    monkeypatch.setattr(init_project, "load_provider", get_provider)
    return artcraft, workspace, SelectedApp(workspace)


def _prepare(api, brief, spec, adapter, intent=None, decision=None):
    intent = intent or ArtCraftIntent("explicit", "anicraft", ("lower-third",))
    if decision is None:
        decision = assess_request(brief, intent=intent)
    return api.prepare_authoring(
        brief, spec, decision=decision, intent=intent, adapter=adapter
    )


def test_provider_only_preparation_persists_exact_job_and_retries(authoring):
    api, workspace, adapter = authoring
    brief = request()
    spec = job_spec(workspace)
    first = _prepare(api, brief, spec, adapter)
    assert first["status"] == "prepared"
    stored = first["job"]
    assert stored["request"]["context"] == {"kind": "provider-only"}
    assert "videoId" not in stored
    assert stored["documentState"] == "empty"
    assert stored["request"]["provider"] == "neutral-channel"
    assert len(adapter.calls) == 1
    assert adapter.calls[0][0] == {"app": "anicraft", "operations": ["lower-third"]}
    assert adapter.calls[0][2]["write"] == [
        str((workspace / stored["document"]).parent)
    ]
    assert not (workspace / stored["document"]).exists()
    assert Path(first["jobRef"]).is_file()
    assert _prepare(api, brief, spec, adapter) == first


def test_external_saved_source_is_preserved_in_a_job_owned_copy(authoring):
    api, workspace, adapter = authoring
    source = workspace / "original.anicraft"
    source.write_bytes(b"synthetic native source")
    brief = request()
    spec = job_spec(
        workspace,
        document={"state": "saved", "source": str(source)},
        readRoots=[str(workspace)],
    )
    result = _prepare(api, brief, spec, adapter)
    job = result["job"]
    copy = workspace / job["document"]
    assert copy != source
    assert copy.read_bytes() == source.read_bytes()
    assert job["documentState"] == "saved"
    assert job["inputs"] == [file_fingerprint(source)]
    copy.write_bytes(b"edited independent revision")
    assert source.read_bytes() == b"synthetic native source"


def test_invalid_paths_and_freshness_stop_before_adapter_io(authoring, tmp_path):
    api, workspace, adapter = authoring
    brief = request()
    source = tmp_path / "outside.anicraft"
    source.write_bytes(b"unselected")
    with pytest.raises(ArtCraftError, match="read root"):
        _prepare(
            api,
            brief,
            job_spec(workspace, document={"state": "saved", "source": str(source)}),
            adapter,
        )
    offered = ArtCraftIntent("explicit", "effectcraft", ("lower-third",))
    with pytest.raises(ArtCraftError, match="scope"):
        _prepare(
            api,
            brief,
            job_spec(workspace),
            adapter,
            decision=assess_request(brief, intent=offered),
        )
    assert adapter.calls == []
    assert list(workspace.iterdir()) == []


def test_provider_mismatch_blocks_before_selected_app_discovery(authoring):
    api, workspace, adapter = authoring
    with pytest.raises(ArtCraftError, match="provider"):
        _prepare(
            api, request(), job_spec(workspace, provider="foreign-channel"), adapter
        )
    assert adapter.calls == []


def test_real_video_scope_binds_project_and_persists_under_its_edit_dir(authoring):
    api, workspace, adapter = authoring
    project = workspace / "avo.project.json"
    project.write_text(
        json.dumps(
            {
                "provider": "neutral-channel",
                "videoId": "source-episode",
                "rawDir": str(workspace),
            }
        ),
        encoding="utf-8",
    )
    brief = request(
        context={"kind": "video", "project": str(project), "videoId": "source-episode"}
    )
    prepared = _prepare(api, brief, job_spec(workspace), adapter)
    assert Path(prepared["jobRef"]).is_relative_to(workspace / "edit" / "timeline")
    job = prepared["job"]
    assert Path(job["roots"]["write"][0]).is_relative_to(workspace / "edit")
    assert job["projectFingerprint"] == file_fingerprint(project)


def test_unqualified_effective_roots_block_without_creating_a_job(authoring):
    api, workspace, _ = authoring

    class BroadApp(SelectedApp):
        def observe(self, **kwargs):
            result = super().observe(**kwargs)
            result["effectiveRoots"] = {
                "read": [str(workspace.parent)],
                "write": [str(workspace.parent)],
            }
            return result

    with pytest.raises(ArtCraftError, match="effective roots"):
        _prepare(api, request(), job_spec(workspace), BroadApp(workspace))
    assert list(workspace.iterdir()) == []


def test_selected_missing_cli_returns_separate_installation_guidance(
    authoring, monkeypatch
):
    from avo.adapters.artcraft import SelectedArtCraftAdapter

    api, workspace, _ = authoring

    def forbid_launcher(*args, **kwargs):
        pytest.fail("missing selected tool must not start a process")

    monkeypatch.setattr("subprocess.Popen", forbid_launcher)
    missing = (
        workspace
        / "selected-bin"
        / ("anicraft-cli.exe" if os.name == "nt" else "anicraft-cli")
    )
    spec = job_spec(workspace, cliPath=str(missing))
    with pytest.raises(ArtCraftError) as raised:
        _prepare(api, request(), spec, SelectedArtCraftAdapter())
    detail = raised.value.to_dict()
    assert detail["code"] == "ARTCRAFT_NOT_READY"
    assert "anicraft-cli" in detail["message"]
    assert "https://getartcraft.com/apps/anicraft" in detail["remediation"]
    assert list(workspace.iterdir()) == []


def test_prepare_command_reaches_the_same_selected_readiness_boundary(authoring):
    from avo.mcp.bridge import run_cli

    _, workspace, _ = authoring
    missing = (
        workspace
        / "selected-bin"
        / ("anicraft-cli.exe" if os.name == "nt" else "anicraft-cli")
    )
    result = run_cli(
        [
            "artcraft",
            "prepare",
            "--request-json",
            json.dumps(request()),
            "--job-spec-json",
            json.dumps(job_spec(workspace, cliPath=str(missing))),
            "--app",
            "anicraft",
            "--operation",
            "lower-third",
            "--provider",
            "neutral-channel",
            "--workspace",
            str(workspace),
            "--mode",
            "cli",
            "--cli",
            str(missing),
            "--json",
        ]
    )
    assert not result.ok
    assert json.loads(result.stderr)["code"] == "ARTCRAFT_NOT_READY"
    assert list(workspace.iterdir()) == []


@pytest.mark.parametrize("app_release", ["0.4.1", "0.4.2"])
def test_selected_identity_checks_only_matching_installed_tools(
    authoring, monkeypatch, app_release
):
    from avo.adapters.artcraft import SelectedArtCraftAdapter

    api, workspace, _ = authoring
    suffix = ".exe" if os.name == "nt" else ""
    cli, app = [workspace / f"{name}{suffix}" for name in ("anicraft-cli", "anicraft")]
    for executable in (cli, app):
        executable.write_bytes(b"synthetic installed binary")
        executable.chmod(0o700)
    calls, boundaries = [], []

    def run(argv, **kwargs):
        assert kwargs["shell"] is False and kwargs["timeout"] == 5
        assert argv[1:] == ["--version"]
        calls.append(argv[0])
        release = "0.4.1" if argv[0] == str(cli) else app_release
        qualifier = " (early alpha)" if argv[0] == str(app) else ""
        return SimpleNamespace(
            stdout=f"AniCraft {release}{qualifier}\n".encode("ascii")
        )

    def confinement(identity, roots):
        boundaries.append(identity)
        return roots

    monkeypatch.setattr("subprocess.run", run)
    spec = job_spec(workspace, cliPath=str(cli), appPath=str(app))
    adapter = SelectedArtCraftAdapter(confinement)
    if app_release == "0.4.1":
        result = _prepare(api, request(), spec, adapter)
        observation = result["job"]["observation"]
        assert observation["executable"] == file_fingerprint(cli)
        assert observation["application"] == file_fingerprint(app)
        assert observation["release"] == app_release and len(boundaries) == 1
    else:
        with pytest.raises(ArtCraftError, match="different releases"):
            _prepare(api, request(), spec, adapter)
        assert boundaries == [] and not (workspace / "artcraft-jobs").exists()
    assert calls == [str(cli), str(app)]


def test_inspect_reconciles_exact_saved_copy_from_a_fresh_entrypoint(authoring):
    from avo.mcp.bridge import run_cli

    api, workspace, adapter = authoring
    original = workspace / "original.anicraft"
    original.write_bytes(b"synthetic independent source")
    spec = job_spec(
        workspace,
        document={"state": "saved", "source": str(original)},
        readRoots=[str(workspace)],
    )
    prepared = _prepare(api, request(), spec, adapter)
    arguments = [
        "artcraft",
        "inspect",
        "--job",
        prepared["jobRef"],
        "--json",
        "--expected-head",
    ]
    current = run_cli([*arguments, prepared["head"]])
    assert current.ok, current.stderr
    assert current.parsed_json["status"] == "current"
    assert current.parsed_json["state"] == "prepared"
    assert current.parsed_json["checks"]["nativeDocument"] == "current"
    assert len(adapter.calls) == 1

    source = workspace / prepared["job"]["document"]
    source.write_bytes(b"changed independent copy")
    stale = run_cli([*arguments, prepared["head"]])
    assert stale.ok, stale.stderr
    assert stale.parsed_json["status"] == "stale"
    assert stale.parsed_json["checks"]["nativeDocument"] == "changed"
    assert original.read_bytes() == b"synthetic independent source"

    wrong = run_cli([*arguments, "a" * 64])
    assert not wrong.ok
    assert json.loads(wrong.stderr)["code"] == "ARTCRAFT_SCOPE_CHANGED"


def test_inspect_marks_video_scope_stale_when_project_identity_changes(authoring):
    api, workspace, adapter = authoring
    project = workspace / "avo.project.json"
    body = {
        "provider": "neutral-channel",
        "videoId": "source-episode",
        "rawDir": str(workspace),
    }
    project.write_text(json.dumps(body), encoding="utf-8")
    brief = request(
        context={"kind": "video", "project": str(project), "videoId": "source-episode"}
    )
    prepared = _prepare(api, brief, job_spec(workspace), adapter)
    project.write_text(json.dumps({**body, "title": "Changed scope"}), encoding="utf-8")
    result = api.inspect_authoring(prepared["jobRef"], expected_head=prepared["head"])
    assert result["status"] == "stale"
    assert result["checks"]["project"] == "changed"
