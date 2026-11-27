"""Retain real installed-editor outputs after a lost authoring response."""

import json
import os
import subprocess
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from hashlib import sha256
from pathlib import Path
from threading import Event, Lock
from time import monotonic, sleep
from types import SimpleNamespace

import pytest
from PIL import Image
from tests.artcraft_fixtures import request
from tests.integration.artcraft_photocraft_desktop_fixture import (
    VERSION as PHOTOCRAFT_VERSION,
)
from tests.integration.artcraft_photocraft_desktop_fixture import (
    names_selected_file,
    photocraft_desktop,
    require,
)
from tests.integration.test_artcraft_lower_third_runtime import _job_contract
from tests.integration.test_artcraft_modes_runtime import (
    _fixture_command,
    _fixture_stream,
)
from tests.test_artcraft_jobs import _prepare, job_spec
from tests.test_artcraft_profiles import effect_spec, prepare_effect
from tests.test_reconstruction_bundle import canonical_project

from avo import artcraft, init_project
from avo.adapters.artcraft import SelectedArtCraftAdapter, _runtime_environment
from avo.adapters.artcraft_anicraft import inspect_lower_third_source
from avo.mcp.bridge import run_cli
from avo.timeline.contracts import file_fingerprint
from avo.timeline.reconstruction import (
    build_reconstruction_bundle,
    verify_reconstruction_bundle,
)

pytestmark = [pytest.mark.integration, pytest.mark.native_artcraft]


def _installed_cli():
    executable = os.environ.get("AVO_ARTCRAFT_ANICRAFT_TEST_CLI")
    if not executable:
        pytest.skip("Select the installed AniCraft 0.2.1 CLI")
    return Path(executable).resolve(strict=True)


def test_installed_anicraft_save_is_retained_when_the_runner_loses_its_reply(
    tmp_path, monkeypatch
):
    cli = _installed_cli()
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


def test_installed_anicraft_json_lines_disconnect_preserves_the_saved_revision(
    tmp_path, monkeypatch
):
    cli = _installed_cli()
    monkeypatch.setattr(init_project, "load_provider", lambda slug: {"slug": slug})
    batch_adapter = SelectedArtCraftAdapter(
        observe_confinement=lambda _tool, roots: roots, run_confined=_fixture_command
    )
    output = _job_contract()
    baseline_spec = job_spec(
        tmp_path,
        cliPath=str(cli),
        output=output,
        authoringParameters={"primaryText": "Approved speaker", "font": "Arial"},
    )
    baseline = _prepare(artcraft, request(), baseline_spec, batch_adapter)
    baseline_export = artcraft.run_authoring(
        baseline["jobRef"], expected_head=baseline["head"], adapter=batch_adapter
    )
    _, previous = artcraft.read_authoring_export(
        baseline_export["jobRef"], expected_head=baseline_export["head"]
    )
    original = Path(previous["saved"]["locator"])
    calls, commands, disconnected = [], [], []

    def record_command(*args, **kwargs):
        calls.append(args[3][0])
        return _fixture_command(*args, **kwargs)

    @contextmanager
    def disconnect_after_save(*args, **kwargs):
        directory = args[2]
        calls.append("serve")
        with _fixture_stream(*args, **kwargs) as stream:
            native = directory / "component.anicraft"

            def send_line(message, *, timeout):
                commands.append(json.loads(message))
                stream.send_line(message, timeout=timeout)

            def read_line(*, max_bytes, timeout):
                reply = stream.read_line(max_bytes=max_bytes, timeout=timeout)
                if not commands or commands[-1]["cmd"] != "file.save_as":
                    return reply
                assert commands[-1]["params"]["path"] == str(native)
                receipt = json.loads(reply)
                assert receipt["id"] == commands[-1]["id"] and receipt["ok"] is True
                assert native.is_file()
                process = stream._process
                assert process.poll() is None
                process.terminate()
                process.wait(timeout=min(timeout, 3))
                disconnected.append((native, process.returncode))
                return stream.read_line(max_bytes=max_bytes, timeout=timeout)

            yield SimpleNamespace(send_line=send_line, read_line=read_line)

    adapter = SelectedArtCraftAdapter(
        observe_confinement=lambda _tool, roots: roots,
        run_confined=record_command,
        open_confined=disconnect_after_save,
    )
    revised = {
        **baseline_spec,
        "jobId": "speaker-label-disconnected",
        "mode": "json-lines",
        "document": {"state": "saved", "source": str(original)},
        "readRoots": [str(original.parent)],
        "authoringParameters": {"primaryText": "Revised speaker", "font": "Arial"},
    }
    prepared = _prepare(artcraft, request(), revised, adapter)
    with pytest.raises(artcraft.ArtCraftError) as interrupted:
        artcraft.run_authoring(
            prepared["jobRef"], expected_head=prepared["head"], adapter=adapter
        )
    assert interrupted.value.code == "ARTCRAFT_OUTCOME_UNKNOWN"
    assert "JSON-lines reply" in str(interrupted.value.__cause__)
    ((native, returncode),) = disconnected
    assert returncode != 0 and commands[-1]["cmd"] == "file.save_as"
    store = artcraft.ArtCraftJobStore(tmp_path)
    pending = store.head(revised["jobId"])
    assert pending["state"] == "outcome-unknown" and "outputs" not in pending
    inspected = inspect_lower_third_source(
        native,
        output,
        revised["authoringParameters"],
        max_bytes=revised["budget"]["bytes"],
    )
    assert inspected["editableText"] == "Revised speaker"
    recovery = artcraft.recover_authoring(
        prepared["jobRef"], expected_head=pending["eventHash"]
    )["recovery"]
    assert inspected["fingerprint"] in recovery["retainedFiles"]
    assert recovery["artifactState"] == "reference-only"
    dispatches = list(calls)
    with pytest.raises(artcraft.ArtCraftError, match="requires reconciliation"):
        artcraft.recover_authoring(
            prepared["jobRef"],
            expected_head=pending["eventHash"],
            action="retry",
            adapter=adapter,
        )
    assert calls == dispatches and store.head(revised["jobId"]) == pending
    assert (
        artcraft.read_authoring_export(
            baseline_export["jobRef"], expected_head=baseline_export["head"]
        )[1]
        == previous
    )


def test_installed_anicraft_refuses_a_revision_saved_by_another_headless_process(
    tmp_path, monkeypatch
):
    cli = _installed_cli()
    monkeypatch.setattr(init_project, "load_provider", lambda slug: {"slug": slug})
    adapter = SelectedArtCraftAdapter(
        observe_confinement=lambda _tool, roots: roots, run_confined=_fixture_command
    )
    source = tmp_path / "selected-original.anicraft"
    binary = {"locator": str(cli)}
    environment = _runtime_environment()
    _fixture_command(
        binary,
        {"write": [str(tmp_path)]},
        tmp_path,
        ("new", "--out", source),
        env=environment,
        timeout=10,
    )
    original = file_fingerprint(source)
    spec = job_spec(
        tmp_path,
        cliPath=str(cli),
        document={"state": "saved", "source": str(source)},
        readRoots=[str(tmp_path)],
        output=_job_contract(),
        authoringParameters={"primaryText": "Speaker", "font": "Arial"},
    )
    prepared = _prepare(artcraft, request(), spec, adapter)
    workspace = tmp_path / prepared["job"]["document"]
    revision = workspace.parent / "revision"
    revision.mkdir()
    other_source = revision / "original.anicraft"
    other_source.write_bytes(source.read_bytes())
    occupied = revision / "component.anicraft"
    command = {"id": 1, "cmd": "file.save_as", "params": {"path": str(occupied)}}

    def unexpected(*_args, **_kwargs):
        pytest.fail("The occupied revision must not reach native validation")

    monkeypatch.setattr(adapter, "validate_run", unexpected)
    with _fixture_stream(
        binary,
        {"write": [str(revision)]},
        revision,
        ("serve", other_source),
        env=environment,
        timeout=10,
    ) as writer:
        assert writer.read_line(max_bytes=65536, timeout=10)
        writer.send_line(json.dumps(command).encode("utf-8") + b"\n", timeout=10)
        receipt = json.loads(writer.read_line(max_bytes=65536, timeout=10))
        assert receipt["id"] == 1 and receipt["ok"] is True
        saved = file_fingerprint(occupied)

        with pytest.raises(artcraft.ArtCraftError, match="stale"):
            artcraft.run_authoring(
                prepared["jobRef"], expected_head=prepared["head"], adapter=adapter
            )

        assert writer._process.poll() is None
        assert file_fingerprint(occupied) == saved
    head = artcraft.ArtCraftJobStore(tmp_path).head(spec["jobId"])
    assert head["state"] == "prepared" and head["eventHash"] == prepared["head"]
    assert not (revision / "recipe.json").exists()
    assert file_fingerprint(source) == original
    assert workspace.read_bytes() == source.read_bytes()


def test_installed_photocraft_reconnects_to_pending_save_after_bridge_loss():
    with photocraft_desktop() as desktop:
        size = (4096, 3072)
        source = desktop.inputs / "synthetic-predecessor.png"
        with Image.frombytes("RGB", size, os.urandom(size[0] * size[1] * 3)) as image:
            image.save(source, compress_level=1)
            expected_pixels = sha256(image.tobytes()).digest()
        original = file_fingerprint(source)
        target = desktop.outputs / "disconnected-save.psd"
        competing = desktop.outputs / "competing-save.psd"

        with desktop.bridge() as peer, desktop.bridge() as writer:
            initial = peer.call("ui_inspect")
            require(
                initial["updates"]["currentVersion"] == PHOTOCRAFT_VERSION
                and not initial["session"]["documents"],
                "The selected desktop release or initial document state differed.",
            )
            opened = writer.call("doc_open", {"path": source.name})
            require(
                names_selected_file(opened.get("path"), source),
                "The desktop opened a different source.",
            )
            document = writer.call("doc_inspect")
            require(
                (document.get("width"), document.get("height")) == size,
                "The opened synthetic document has unexpected dimensions.",
            )
            pending = writer.begin_save(target.name)
            job = pending.get("job")
            require(
                pending.get("pending") is True
                and type(job) is int
                and not target.exists(),
                "PhotoCraft did not return a dispatched, uncommitted save.",
            )
            # Terminate this owned bridge without waiting for the native job's outcome.
            require(writer.process.poll() is None, "The writer bridge exited early.")
            writer.process.terminate()
            writer.process.wait(timeout=4)
            require(
                not target.exists(),
                "Inconclusive interruption fixture: the save settled before disconnect.",
            )
            peer.begin_save(competing.name, expect_busy=True)
            require(not competing.exists(), "The competing client created an output.")

        require(
            desktop.owned_listener(),
            "The original desktop listener did not survive bridge loss.",
        )
        with desktop.bridge() as reconnected:
            deadline = monotonic() + 20
            observed = reconnected.job(job)
            while (
                observed.get("state") not in {"done", "failed", "cancelled"}
                and monotonic() < deadline
            ):
                sleep(0.1)
                observed = reconnected.job(job)
            require(
                observed.get("state") == "done",
                "The disconnected native save was not reconciled.",
            )
            receipt = observed.get("result")
            require(
                isinstance(receipt, dict)
                and names_selected_file(receipt.get("path"), target)
                and target.is_file(),
                "The recovered save did not identify its intended output.",
            )
        assert file_fingerprint(source) == original
        with Image.open(target, formats=["PSD"]) as saved:
            assert saved.size == size
            assert sha256(saved.convert("RGB").tobytes()).digest() == expected_pixels


def test_installed_anicraft_stale_source_reports_the_edited_title_through_cli(
    tmp_path, monkeypatch
):
    cli = _installed_cli()
    monkeypatch.setattr(init_project, "load_provider", lambda slug: {"slug": slug})
    adapter = SelectedArtCraftAdapter(
        observe_confinement=lambda _tool, roots: roots, run_confined=_fixture_command
    )
    spec = job_spec(
        tmp_path,
        cliPath=str(cli),
        output=_job_contract(),
        authoringParameters={"primaryText": "Original speaker", "font": "Arial"},
    )
    selection = _prepare(artcraft, request(), spec, adapter)
    rendered = artcraft.run_authoring(
        selection["jobRef"], expected_head=selection["head"], adapter=adapter
    )
    store = artcraft.ArtCraftJobStore(tmp_path)
    exported = store.head(spec["jobId"])
    native = Path(exported["saved"]["locator"])
    editable = json.loads(native.read_bytes())
    artwork = editable["document"]["library"][0]["timeline"]["layers"][0]["keyframes"][
        0
    ]["elements"]
    label = next(
        element["kind"]["Text"] for element in artwork if "Text" in element["kind"]
    )
    label["text"] = "Edited speaker"
    native.write_text(json.dumps(editable), encoding="utf-8")

    inspected = run_cli(
        [
            "artcraft",
            "inspect",
            "--job",
            rendered["jobRef"],
            "--expected-head",
            rendered["head"],
            "--json",
        ]
    )
    assert inspected.ok, inspected.stderr
    assert inspected.parsed_json["status"] == "stale"
    (change,) = inspected.parsed_json["changes"]
    assert change["recordedFiles"] == [exported["saved"]]
    assert change["parameterChanges"] == [
        {
            "name": "primaryText",
            "recorded": "Original speaker",
            "observed": "Edited speaker",
        }
    ]
    assert store.head(spec["jobId"]) == exported


def test_reconstruction_retains_native_source_for_a_fresh_installed_render(
    tmp_path, monkeypatch
):
    cli = _installed_cli()
    workspace, master = canonical_project(tmp_path)
    monkeypatch.setattr(init_project, "load_provider", lambda slug: {"slug": slug})
    adapter = SelectedArtCraftAdapter(
        observe_confinement=lambda _tool, roots: roots, run_confined=_fixture_command
    )
    context = {
        "kind": "video",
        "project": str(workspace.project_path),
        "videoId": workspace.video_id,
    }
    spec = job_spec(
        tmp_path,
        provider=workspace.project["provider"],
        cliPath=str(cli),
        output=_job_contract(),
        authoringParameters={"primaryText": "Retained speaker", "font": "Arial"},
    )
    selection = _prepare(
        artcraft, request(provider=spec["provider"], context=context), spec, adapter
    )
    rendered = artcraft.run_authoring(
        selection["jobRef"], expected_head=selection["head"], adapter=adapter
    )
    _, event = artcraft.read_authoring_export(
        rendered["jobRef"], expected_head=rendered["head"]
    )
    native = Path(event["saved"]["locator"])
    white = native.parent / "white"
    first = sorted(white.glob("frame_*.png"))
    bundle = build_reconstruction_bundle(
        workspace, master_basename=master, actor="fixture"
    )
    assert native.relative_to(tmp_path).as_posix() in {
        item["path"] for item in bundle["files"]
    }
    assert all(
        not item["path"].startswith(white.relative_to(tmp_path).as_posix())
        for item in bundle["files"]
    )

    expected = [_rgba_hash(path) for path in first]
    assert len(expected) == 24
    for path in first:
        path.unlink()
    white.rmdir()
    assert (
        verify_reconstruction_bundle(tmp_path)["bundleSha256"] == bundle["bundleSha256"]
    )
    fresh = native.parent / "fresh-render"
    subprocess.run(
        [
            str(cli),
            "render-seq",
            str(native),
            "--out-dir",
            str(fresh),
            "--from",
            "1",
            "--to",
            "24",
        ],
        cwd=native.parent,
        capture_output=True,
        check=True,
        timeout=25,
    )
    assert [_rgba_hash(path) for path in sorted(fresh.glob("frame_*.png"))] == expected


def _rgba_hash(path):
    with Image.open(path) as image:
        return sha256(image.convert("RGBA").tobytes()).hexdigest()


def test_owned_effectcraft_render_stops_with_partial_evidence(tmp_path, monkeypatch):
    entry = os.environ.get("AVO_ARTCRAFT_EFFECTCRAFT_TEST_CLI")
    if not entry:
        pytest.skip("Select the installed EffectCraft 0.24.1 CLI")
    executable = Path(entry).resolve(strict=True)
    font = (Path(os.environ["SystemRoot"]) / "Fonts" / "arial.ttf").resolve(strict=True)
    monkeypatch.setattr(init_project, "load_provider", lambda slug: {"slug": slug})
    runner = _OwnedEffectRunner(executable, tmp_path)
    adapter = SelectedArtCraftAdapter(
        observe_confinement=lambda _installed, roots: roots,
        run_confined=runner.run,
        claim_confined_cancellation=runner.claim,
    )
    defaults = {
        "cliPath": str(executable),
        "effectFont": str(font),
        "readRoots": [str(font.parent)],
    }
    baseline = prepare_effect(
        effect_spec(tmp_path, jobId="effect-predecessor", **defaults), adapter
    )
    verified = artcraft.run_authoring(
        baseline["jobRef"], expected_head=baseline["head"], adapter=adapter
    )
    _, previous = artcraft.read_authoring_export(
        baseline["jobRef"], expected_head=verified["head"]
    )
    interrupted = prepare_effect(
        effect_spec(
            tmp_path,
            jobId="effect-interrupted",
            budget={"seconds": 25, "files": 1024, "bytes": 32_000_000},
            **defaults,
        ),
        adapter,
    )
    store = artcraft.ArtCraftJobStore(tmp_path)
    with ThreadPoolExecutor(max_workers=1) as executor:
        rendering = executor.submit(
            artcraft.run_authoring,
            interrupted["jobRef"],
            expected_head=interrupted["head"],
            adapter=adapter,
        )
        try:
            runner.wait_for_partial_frame()
            running = store.head("effect-interrupted")
            stopped = artcraft.recover_authoring(
                interrupted["jobRef"],
                expected_head=running["eventHash"],
                action="cancel",
                adapter=adapter,
            )
            assert stopped["state"] == "cancelled"
            assert rendering.result(timeout=5)["state"] in {
                "cancel-requested",
                "cancelled",
            }
        finally:
            runner.stop_if_running()
    canceled = store.head("effect-interrupted")
    assert "outputs" not in canceled
    retained = {Path(item["locator"]).name for item in canceled["partialFiles"]}
    assert "component.ecproj" in retained and any(
        name.startswith("partial_") for name in retained
    )
    assert runner.signals == 1
    assert (
        artcraft.read_authoring_export(
            baseline["jobRef"], expected_head=verified["head"]
        )[1]
        == previous
    )


class _OwnedEffectRunner:
    def __init__(self, executable, workspace):
        self.executable = executable
        self.workspace = workspace
        self.started = Event()
        self.lock = Lock()
        self.active = None
        self.cancelled = False
        self.signals = 0

    def run(self, binary, roots, directory, arguments, *, env, timeout):
        assert Path(binary["locator"]) == self.executable
        assert roots["write"] == [str(directory)] and directory.is_relative_to(
            self.workspace
        )
        args = [str(self.executable), *map(str, arguments)]
        options = {
            "cwd": directory,
            "env": env,
            "stdin": subprocess.DEVNULL,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
        }
        if self.cancelled:
            raise RuntimeError("The test writer is already stopped")
        if directory.name != "job-effect-interrupted" or arguments[2] != "render":
            return subprocess.run(args, timeout=timeout, check=True, **options).stdout
        # Widen only the synthetic source so an owned process is still writing
        # after the test has observed a frame and reached the cancellation CAS.
        expanded = directory / "interruption-fixture.ecproj"
        subprocess.run(
            [
                str(self.executable),
                "--project",
                str(arguments[1]),
                "run",
                "comp.settings",
                '{"width":1920,"height":1080,"duration":20}',
                "--save-as",
                str(expanded),
            ],
            timeout=5,
            check=True,
            **options,
        )
        args[args.index("--project") + 1] = str(expanded)
        for option, value in (("--start", "0.05"), ("--end", "20"), ("--fps", "60")):
            args[args.index(option) + 1] = value
        with self.lock:
            process = subprocess.Popen(args, **options)
            self.active = process, directory, binary
            self.started.set()
        try:
            stdout, stderr = process.communicate(timeout=timeout)
            if process.returncode:
                raise subprocess.CalledProcessError(
                    process.returncode, args, stdout, stderr
                )
            return stdout
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate(timeout=5)

    def wait_for_partial_frame(self):
        assert self.started.wait(10)
        process, directory, _ = self.active
        deadline = monotonic() + 5
        while monotonic() < deadline and process.poll() is None:
            if any((directory / "alpha").glob("partial_*.png")):
                return
            sleep(0.02)
        pytest.fail(
            "The installed renderer did not leave an observable active partial write"
        )

    def claim(self, job, running, directory):
        with self.lock:
            if self.active is None or running["jobHash"] != job["jobHash"]:
                return None
            process, workdir, binary = self.active
            if (workdir, binary) != (
                directory,
                job["observation"]["executable"],
            ) or process.poll() is not None:
                return None

        def stop(timeout):
            with self.lock:
                self.cancelled = True
                self.signals += 1
                process.terminate()
            process.wait(timeout=timeout)
            return "settled"

        return stop

    def stop_if_running(self):
        if self.active is not None:
            process, _, _ = self.active
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)
