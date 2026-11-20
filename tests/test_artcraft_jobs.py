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
    from avo.adapters.artcraft_anicraft import LOWER_THIRD_COMMANDS

    api, workspace, _ = authoring
    suffix = ".exe" if os.name == "nt" else ""
    cli, app = [workspace / f"{name}{suffix}" for name in ("anicraft-cli", "anicraft")]
    for executable in (cli, app):
        executable.write_bytes(b"synthetic installed binary")
        executable.chmod(0o700)
    calls, boundaries = [], []

    def run(argv, **kwargs):
        assert kwargs["shell"] is False
        calls.append((argv[0], argv[1]))
        if argv[1:] == ["commands"]:
            assert kwargs["timeout"] == 7
            return SimpleNamespace(
                stdout=json.dumps(
                    [
                        {"id": name, "params": "{}"}
                        for name in sorted(LOWER_THIRD_COMMANDS)
                    ]
                ).encode()
            )
        assert argv[1:] == ["--version"] and kwargs["timeout"] == 5
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
        assert len(observation["commandSchemaHash"]) == 64
    else:
        with pytest.raises(ArtCraftError, match="different releases"):
            _prepare(api, request(), spec, adapter)
        assert boundaries == [] and not (workspace / "artcraft-jobs").exists()
    expected = [(str(cli), "--version"), (str(app), "--version")]
    if app_release == "0.4.1":
        expected.append((str(cli), "commands"))
    assert calls == expected


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


class AuthoringApp(SelectedApp):
    def __init__(self, workspace):
        super().__init__(workspace)
        self.executions = []

    def validate_run(self, job):
        self.executions.append(("validate", job["jobId"]))

    def author_lower_third(self, job, directory):
        self.executions.append(("author", job["jobId"]))
        directory.mkdir(parents=True)
        native = directory / "component.anicraft"
        recipe = directory / "recipe.json"
        native.write_bytes(b"synthetic editable source")
        recipe.write_bytes(b"synthetic recipe")
        alpha = directory / "alpha"
        alpha.mkdir()
        frames = []
        for index in range(1, job["output"]["frameCount"] + 1):
            target = alpha / f"frame_{index:05d}.png"
            target.write_bytes(f"fixture alpha frame {index}".encode("ascii"))
            frames.append(file_fingerprint(target))
        return {
            "nativeSource": file_fingerprint(native),
            "recipe": file_fingerprint(recipe),
            "frames": frames,
        }


def test_run_commits_current_native_source_and_stops_exact_repeat(authoring):
    api, workspace, _ = authoring
    adapter = AuthoringApp(workspace)
    spec = job_spec(
        workspace, authoringParameters={"primaryText": "Speaker", "font": "Arial"}
    )
    before = _prepare(api, request(), spec, adapter)
    performed = api.run_authoring(
        before["jobRef"], expected_head=before["head"], adapter=adapter
    )
    assert performed["state"] == "exported"
    assert performed["checks"]["nativeDocument"] == "current"
    assert performed["checks"]["outputs"] == "current"
    assert performed["head"] != before["head"]
    assert adapter.executions == [
        ("validate", "speaker-label-preview"),
        ("author", "speaker-label-preview"),
    ]
    assert (
        api.run_authoring(
            before["jobRef"], expected_head=performed["head"], adapter=adapter
        )
        == performed
    )
    assert len(adapter.executions) == 2


def test_run_refuses_changed_document_before_any_selected_tool_work(authoring):
    api, workspace, _ = authoring
    adapter = AuthoringApp(workspace)
    spec = job_spec(
        workspace, authoringParameters={"primaryText": "Speaker", "font": "Arial"}
    )
    prepared = _prepare(api, request(), spec, adapter)
    document = workspace / prepared["job"]["document"]
    document.parent.mkdir(parents=True)
    document.write_bytes(b"external edit")
    with pytest.raises(ArtCraftError, match="stale"):
        api.run_authoring(
            prepared["jobRef"], expected_head=prepared["head"], adapter=adapter
        )
    assert adapter.executions == []
    assert document.read_bytes() == b"external edit"


def test_run_records_unknown_outcome_and_refuses_to_repeat_a_partial_write(authoring):
    api, workspace, _ = authoring

    class Interrupted(AuthoringApp):
        def author_lower_third(self, job, directory):
            super().author_lower_third(job, directory)
            raise RuntimeError("fixture process stopped after writing")

    adapter = Interrupted(workspace)
    spec = job_spec(
        workspace, authoringParameters={"primaryText": "Speaker", "font": "Arial"}
    )
    prepared = _prepare(api, request(), spec, adapter)
    with pytest.raises(ArtCraftError) as failure:
        api.run_authoring(
            prepared["jobRef"], expected_head=prepared["head"], adapter=adapter
        )
    assert failure.value.code == "ARTCRAFT_OUTCOME_UNKNOWN"
    event = api.ArtCraftJobStore(workspace).head(spec["jobId"])
    assert event["state"] == "outcome-unknown"
    assert event["eventHash"] in failure.value.remediation
    assert (
        workspace / prepared["job"]["document"]
    ).read_bytes() == b"synthetic editable source"
    with pytest.raises(ArtCraftError):
        api.run_authoring(
            prepared["jobRef"], expected_head=event["eventHash"], adapter=adapter
        )
    assert len(adapter.executions) == 2


def test_guided_job_returns_replayable_native_steps_without_starting_authoring(
    authoring,
):
    api, workspace, _ = authoring

    class Guided(AuthoringApp):
        def observe(self, **arguments):
            observed = super().observe(**arguments)
            observed.pop("effectiveRoots")
            return {**observed, "mode": "guided", "authority": "operator"}

        def plan_lower_third(self, job, directory):
            self.executions.append(("plan", job["jobId"]))
            return {
                "steps": [
                    {
                        "cmd": "file.save_as",
                        "params": {"path": str(directory / "component.anicraft")},
                    }
                ],
                "commands": [["gui-managed"]],
            }

    adapter = Guided(workspace)
    spec = job_spec(
        workspace,
        mode="guided",
        authoringParameters={"primaryText": "Speaker", "font": "Arial"},
    )
    prepared = _prepare(api, request(), spec, adapter)
    handoff = api.run_authoring(
        prepared["jobRef"], expected_head=prepared["head"], adapter=adapter
    )
    assert handoff["state"] == "ready"
    assert handoff["status"] == "current"
    details = json.loads(
        Path(handoff["handoff"]["locator"]).read_text(encoding="utf-8")
    )
    assert details["mode"] == "guided"
    assert details["artifactState"] == "reference-only"
    assert adapter.executions == [("plan", "speaker-label-preview")]
    assert (
        api.run_authoring(
            prepared["jobRef"], expected_head=handoff["head"], adapter=adapter
        )
        == handoff
    )
    assert adapter.executions == [("plan", "speaker-label-preview")]


def _overlay_snapshots(*, width=1920, height=1080, start_frame=18, frame_count=72):
    clock = {"num": 1, "den": 24}
    start = {"ticks": start_frame, "timebase": clock, "domain": "cmap-output"}
    end_frame = start_frame + frame_count
    return {
        "animation": {"components": [{"componentId": "speaker-label"}]},
        "cmap": {
            "segments": [],
            "renderOutput": {
                "width": width,
                "height": height,
                "frameRate": {"num": 24, "den": 1},
            },
        },
        "bmap": {
            "cues": [
                {
                    "cueId": "speaker-cue",
                    "targetLayerId": "speaker-overlay",
                    "componentRef": "speaker-label",
                    "intent": "Identify the speaker",
                    "reason": "Introduce the speaker",
                    "start": start,
                    "end": {**start, "ticks": end_frame},
                }
            ]
        },
        "tracks": {
            "videoTracks": {
                "layers": [
                    {
                        "layerId": "speaker-overlay",
                        "role": "overlay",
                        "order": 2,
                        "zOrder": 2,
                        "animationRef": "speaker-label",
                        "generator": {
                            "adapterId": "artcraft.anicraft",
                            "componentId": "speaker-label",
                        },
                        "placement": {"x": 0, "y": 0, "width": width, "height": height},
                        "regions": [
                            {
                                "startTicks": start_frame,
                                "endTicks": end_frame,
                                "timebase": clock,
                                "cueIds": ["speaker-cue"],
                            }
                        ],
                    }
                ]
            }
        },
    }


def test_video_export_binding_freezes_exact_source_parameters_and_current_inputs(
    authoring, monkeypatch
):
    from avo.timeline.artcraft_binding import (
        build_artcraft_asset_record,
        freeze_export_binding,
        verify_artcraft_asset_record,
    )
    from avo.timeline.store import write_immutable_json
    from avo.timeline.workspace import TimelineWorkspace

    api, directory, _ = authoring
    project = directory / "avo.project.json"
    project.write_text(
        json.dumps(
            {
                "provider": "neutral-channel",
                "videoId": "source-episode",
                "rawDir": str(directory),
            }
        ),
        encoding="utf-8",
    )
    active_heads = dict(
        zip(
            ("cmap", "tracks", "bmap", "animation", "sync-map"),
            (letter * 64 for letter in "abcde"),
            strict=True,
        )
    )
    monkeypatch.setattr(
        TimelineWorkspace,
        "active_dependency_snapshot",
        lambda _self: dict(active_heads),
    )
    from avo import motion

    snapshots = _overlay_snapshots()
    monkeypatch.setattr(
        motion, "_canonical_drawing_heads", lambda _workspace: (snapshots, active_heads)
    )
    cli = directory / "anicraft-cli.exe"
    app = directory / "anicraft.exe"
    cli.write_bytes(b"selected cli build")
    app.write_bytes(b"selected app build")

    class Exporter(AuthoringApp):
        def observe(self, **arguments):
            identity = super().observe(**arguments)
            return {
                **identity,
                "executable": file_fingerprint(cli),
                "application": file_fingerprint(app),
                "commandSchemaHash": "c" * 64,
            }

    adapter = Exporter(directory)
    brief = request(
        context={"kind": "video", "project": str(project), "videoId": "source-episode"}
    )
    prepared = _prepare(
        api,
        brief,
        job_spec(
            directory, authoringParameters={"primaryText": "Speaker", "font": "Arial"}
        ),
        adapter,
    )
    rendered = api.run_authoring(
        prepared["jobRef"], expected_head=prepared["head"], adapter=adapter
    )
    workspace = TimelineWorkspace.from_project(project)
    locked = freeze_export_binding(
        workspace, job_ref=prepared["jobRef"], expected_head=rendered["head"]
    )
    assert locked["canonical"]["heads"] == active_heads
    assert locked["canonical"]["videoId"] == "source-episode"
    native = directory / prepared["job"]["document"]
    assert locked["nativeSource"] == file_fingerprint(native)
    assert len(locked["frames"]) == prepared["job"]["output"]["frameCount"]
    assert len(locked["bindingHash"]) == 64
    assert (
        freeze_export_binding(
            workspace, job_ref=prepared["jobRef"], expected_head=rendered["head"]
        )
        == locked
    )

    derived = directory / "edit" / "derived"
    derived.mkdir()
    alpha_clip = derived / "artcraft-title.mkv"
    alpha_clip.write_bytes(b"synthetic packed alpha observations fixture")
    input_lock = derived / "artcraft-title.source.json"
    write_immutable_json(input_lock, locked)
    observations = {
        "fingerprint": file_fingerprint(alpha_clip),
        "frameRate": locked["outputContract"]["frameRate"],
        "rgbaFrameHashes": ["a" * 64] * len(locked["frames"]),
    }
    record = build_artcraft_asset_record(
        locked, file_fingerprint(input_lock), observations, asset_id="artcraft-title"
    )
    assert verify_artcraft_asset_record(workspace, record, observations) == record
    assert (
        record["parameters"]["artcraft"]["nativeRevisionHash"]
        == locked["nativeRevisionHash"]
    )
    from avo.timeline.generated_assets import GeneratedAssetError, GeneratedAssetService

    service = GeneratedAssetService(workspace)
    known_outputs = []
    monkeypatch.setattr(
        GeneratedAssetService,
        "_context",
        lambda _self: {
            "generated_assets": {},
            "registered_originals": [],
            "known_outputs": known_outputs,
        },
    )
    registered = service.register(record, artcraft_observations=observations)
    assert (
        service.admit(registered["assetId"], artcraft_observations=observations)
        == registered
    )
    with pytest.raises(GeneratedAssetError, match="independent native observations"):
        service.admit(registered["assetId"])
    known_outputs.append({**record["inputs"][0]["fingerprint"], "mediaClass": "proof"})
    with pytest.raises(GeneratedAssetError, match="PROOF_FORBIDDEN_ANCESTOR"):
        service.admit(registered["assetId"], artcraft_observations=observations)
    known_outputs.clear()

    from avo.adapters import artcraft_anicraft
    from avo.adapters.media import artcraft_alpha
    from avo.mcp.bridge import run_cli
    from avo.proof_composition import create_generated_asset_validator

    monkeypatch.setattr(
        artcraft_anicraft,
        "inspect_lower_third_source",
        lambda path, *_args, **_kwargs: {"fingerprint": file_fingerprint(path)},
    )
    for name in ("observe_alpha_sequence", "pack_alpha_sequence"):
        monkeypatch.setattr(
            artcraft_alpha, name, lambda *_args, **_kwargs: observations
        )
    cli_registration = run_cli(
        [
            "artcraft",
            "register",
            "--project",
            str(project),
            "--job",
            prepared["jobRef"],
            "--expected-head",
            rendered["head"],
            "--asset-id",
            registered["assetId"],
            "--output",
            str(alpha_clip),
            "--json",
        ]
    )
    assert cli_registration.ok, cli_registration.stderr
    assert cli_registration.parsed_json == registered
    validate = create_generated_asset_validator(workspace)
    reference = {
        "assetId": registered["assetId"],
        "recordHash": registered["recordHash"],
        "locator": str(service.path(registered["assetId"])),
    }
    lock_ref = {
        "path": str(input_lock),
        "sha256": file_fingerprint(input_lock)["sha256"],
    }
    assert validate(reference, lock_ref, active_heads) == registered
    with pytest.raises(ValueError, match="canonical inputs"):
        validate(reference, lock_ref, {**active_heads, "tracks": "f" * 64})
    with pytest.raises(ValueError, match="input-lock reference"):
        validate(reference, {**lock_ref, "sha256": "f" * 64}, active_heads)
    _assert_artcraft_proof_binding(
        workspace, registered, reference, lock_ref, active_heads
    )

    receipt = record["parameters"]["artcraft"]
    receipt["parameterHash"] = "f" * 64
    receipt["receiptHash"] = api.seal_record(
        "receipt", {k: v for k, v in receipt.items() if k != "receiptHash"}
    )["receiptHash"]
    with pytest.raises(ArtCraftError, match="frozen source and output evidence"):
        verify_artcraft_asset_record(workspace, record, observations)

    cli.write_bytes(b"changed cli build")
    with pytest.raises(ArtCraftError, match="installation"):
        freeze_export_binding(
            workspace, job_ref=prepared["jobRef"], expected_head=rendered["head"]
        )
    cli.write_bytes(b"selected cli build")
    active_heads["cmap"] = "d" * 64
    with pytest.raises(ArtCraftError, match="stale"):
        freeze_export_binding(
            workspace, job_ref=prepared["jobRef"], expected_head=rendered["head"]
        )


def _assert_artcraft_proof_binding(workspace, registered, reference, lock_ref, heads):
    from avo.adapters.media import proof_generated
    from avo.proof_composition import create_generated_asset_validator
    from avo.timeline.proof_plan import ProofPlanCompiler

    compiler = ProofPlanCompiler(workspace)
    output = {"width": 640, "height": 360, "frameRate": {"num": 24, "den": 1}}
    operation = {
        "kind": "overlay-video",
        "outputRange": {"startFrame": 18, "endFrameExclusive": 90},
        "parameters": {
            "generatedAssetRef": reference,
            "inputLockRef": lock_ref,
            "sourceFingerprint": registered["output"],
            "sourceRange": {"startFrame": 0, "endFrameExclusive": 72},
            "alphaMode": "straight",
            "layerRole": "overlay",
            "zOrder": 2,
            "placement": {"x": 0, "y": 0, "width": 640, "height": 360},
        },
    }
    locks = compiler._generated_lock({"operations": [operation]}, output)
    assert locks["generated:artcraft-title"] == registered["recordHash"]
    receipt = registered["parameters"]["artcraft"]
    assert locks["input-lock:artcraft-title"] == receipt["bindingHash"]
    from avo.timeline.materialize import _generated_proof_inputs

    inputs = _generated_proof_inputs(workspace, locks)
    assert inputs["generated:artcraft-title"]["inputLockRef"] == lock_ref
    validator = create_generated_asset_validator(workspace)
    assert (
        proof_generated.verify(
            operation, {**heads, **locks}, validator, lambda _: None
        )["record"]
        == registered
    )
    with pytest.raises(RuntimeError, match="requires current admission observations"):
        proof_generated.verify(operation, {**heads, **locks}, None, lambda _: None)
    moved = {**operation, "outputRange": {"startFrame": 17, "endFrameExclusive": 89}}
    with pytest.raises(ValueError, match="canonical overlay and phases"):
        compiler._generated_lock({"operations": [moved]}, output)
    with pytest.raises(ValueError, match="canonical overlay and phases"):
        proof_generated.verify(moved, {**heads, **locks}, validator, lambda _: None)
    with pytest.raises(ValueError, match="full canvas geometry"):
        compiler._generated_lock({"operations": [operation]}, {**output, "width": 600})


def test_selected_registry_cache_requires_exact_installation_scope_and_mode(
    monkeypatch,
):
    from avo.adapters import artcraft as adapter

    installed = {
        "executable": {"sha256": "a" * 64},
        "application": {"sha256": "b" * 64},
        "release": "0.2.1",
        "platform": "windows",
    }
    calls = []

    def read_registry(executable):
        calls.append(executable)
        return str(len(calls))

    monkeypatch.setattr(adapter, "_command_schema_hash", read_registry)
    selected = adapter.SelectedArtCraftAdapter()
    scope = {"app": "anicraft", "operations": ["lower-third"]}
    assert selected._selected_registry(installed, scope, "guided") == "1"
    assert selected._selected_registry(installed, scope, "guided") == "1"
    assert selected._selected_registry(installed, scope, "cli") == "2"
    changed = {**installed, "application": {"sha256": "c" * 64}}
    assert selected._selected_registry(changed, scope, "cli") == "3"
    alternate_scope = {**scope, "operations": ["other-operation"]}
    assert selected._selected_registry(changed, alternate_scope, "cli") == "4"
