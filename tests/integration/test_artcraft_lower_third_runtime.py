"""Opt-in Windows AniCraft evidence using the user's installed release."""

import json
import os
import subprocess
from pathlib import Path

import pytest
from PIL import Image, ImageDraw
from tests.artcraft_fixtures import picture_output, request

from avo.timeline.contracts import file_fingerprint

pytestmark = pytest.mark.integration


def _job_contract():
    return picture_output(
        width=640,
        height=360,
        frameCount=24,
        frameRate={"numerator": 24, "denominator": 1},
    )


def _busy_background():
    canvas = Image.new("RGBA", (640, 360), "#17334f")
    draw = ImageDraw.Draw(canvas)
    for column in range(0, 640, 30):
        for row in range(0, 360, 30):
            if (column + row) % 60:
                draw.rectangle((column, row, column + 29, row + 29), fill="#f2cd78")
    return canvas


def test_installed_anicraft_saves_reopens_and_reconstructs_a_transparent_label(
    tmp_path,
):
    from avo.adapters.artcraft_anicraft import run_lower_third

    entry = os.environ.get("AVO_ARTCRAFT_ANICRAFT_TEST_CLI")
    if not entry:
        pytest.skip(
            "set AVO_ARTCRAFT_ANICRAFT_TEST_CLI to the installed AniCraft 0.2.1 CLI"
        )
    cli = Path(entry).resolve(strict=True)
    assert cli.is_file()
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.upper().startswith("ANICRAFT_")
    }

    def invoke(directory, *argv, timeout=5):
        result = subprocess.run(
            [str(cli), *map(str, argv)],
            capture_output=True,
            check=True,
            env=environment,
            timeout=timeout,
            cwd=directory,
        )
        return result.stdout

    assert invoke(tmp_path, "--version").strip() == b"anicraft-cli 0.2.1"
    output = _job_contract()
    budget = {"seconds": 60, "files": 128, "bytes": 16_000_000}
    first_dir = tmp_path / "first"
    result = run_lower_third(
        output,
        {"primaryText": "Clara Caf\u00e9", "font": "Arial"},
        directory=first_dir,
        budget=budget,
        invoke=invoke,
    )
    assert result["freshSessionDecodedRgbaMatched"]
    assert result["maxMatteError"] <= 1
    assert len(result["frames"]) == 24
    assert result["layers"] == ["Speaker label", "Layer 1"]
    native = Path(result["nativeSource"]["locator"])
    original = file_fingerprint(native)
    from avo.adapters.artcraft_anicraft import inspect_lower_third_source

    source = inspect_lower_third_source(
        native,
        output,
        {"primaryText": "Clara Caf\u00e9", "font": "Arial"},
        max_bytes=budget["bytes"],
    )
    assert source["fingerprint"] == original
    assert source["editableText"] == "Clara Caf\u00e9"
    assert source["fontFamily"] == "Arial"
    from avo.adapters.media.artcraft_alpha import pack_alpha_sequence

    packed_path = tmp_path / "component.mkv"
    packed = pack_alpha_sequence(
        result["frames"], output, packed_path, output_root=tmp_path
    )
    assert packed["fingerprint"] == file_fingerprint(packed_path)
    assert len(packed["rgbaFrameHashes"]) == 24
    assert packed["frameRate"] == {"numerator": 24, "denominator": 1}
    assert (
        pack_alpha_sequence(result["frames"], output, packed_path, output_root=tmp_path)
        == packed
    )
    tampered = tmp_path / "external-reference.anicraft"
    document = json.loads(native.read_bytes())
    document["paths"][0] = "file:///outside/native-input.svg"
    tampered.write_text(json.dumps(document), encoding="utf-8")
    from avo.artcraft import ArtCraftError

    with pytest.raises(ArtCraftError, match="vector paths"):
        inspect_lower_third_source(
            tampered,
            output,
            {"primaryText": "Clara Caf\u00e9", "font": "Arial"},
            max_bytes=budget["bytes"],
        )

    with Image.open(result["frames"][0]["locator"]) as beginning:
        assert beginning.getchannel("A").getextrema() == (0, 0)
    with Image.open(result["frames"][8]["locator"]) as hold:
        assert hold.getchannel("A").getbbox() == (47, 267, 319, 325)
        for background in (
            Image.new("RGBA", hold.size, "white"),
            Image.new("RGBA", hold.size, "black"),
            _busy_background(),
        ):
            composite = Image.alpha_composite(background, hold)
            assert composite.getpixel((0, 0)) == background.getpixel((0, 0))
            assert composite.getpixel((60, 285)) == (16, 44, 72, 255)

    next_result = run_lower_third(
        output,
        {"primaryText": "Mar\u00eda", "font": "Arial"},
        directory=tmp_path / "second",
        budget=budget,
        invoke=invoke,
    )
    assert file_fingerprint(native) == original
    assert next_result["nativeSource"]["locator"] != str(native)
    assert next_result["frames"][8]["sha256"] != result["frames"][8]["sha256"]


def test_installed_anicraft_guided_job_round_trips_through_avo_commands(
    tmp_path, monkeypatch
):
    from avo import init_project
    from avo.mcp.bridge import run_cli

    entry = os.environ.get("AVO_ARTCRAFT_ANICRAFT_TEST_CLI")
    if not entry:
        pytest.skip(
            "set AVO_ARTCRAFT_ANICRAFT_TEST_CLI to the installed AniCraft 0.2.1 CLI"
        )
    cli = Path(entry).resolve(strict=True)
    application = cli.with_name("anicraft.exe")
    monkeypatch.setattr(init_project, "load_provider", lambda slug: {"slug": slug})
    spec = {
        "version": 1,
        "jobId": "guided-trial",
        "provider": "neutral-channel",
        "workspace": str(tmp_path),
        "mode": "guided",
        "document": {"state": "empty"},
        "readRoots": [],
        "authoringParameters": {"primaryText": "Clara Caf\u00e9", "font": "Arial"},
        "output": _job_contract(),
        "budget": {"files": 128, "bytes": 16_000_000, "seconds": 60},
    }
    result = run_cli(
        [
            "artcraft",
            "prepare",
            "--request-json",
            json.dumps(request()),
            "--job-spec-json",
            json.dumps(spec),
            "--provider",
            "neutral-channel",
            "--workspace",
            str(tmp_path),
            "--app",
            "anicraft",
            "--operation",
            "lower-third",
            "--mode",
            "guided",
            "--cli",
            str(cli),
            "--application",
            str(application),
            "--json",
        ]
    )
    assert result.ok, result.stderr
    prepared = result.parsed_json
    plan = run_cli(
        [
            "artcraft",
            "run",
            "--job",
            prepared["jobRef"],
            "--expected-head",
            prepared["head"],
            "--json",
        ]
    )
    assert plan.ok, plan.stderr
    handoff_ref = Path(plan.parsed_json["handoff"]["locator"])
    handoff = json.loads(handoff_ref.read_text(encoding="utf-8"))
    assert handoff["artifactState"] == "reference-only"
    assert not Path(handoff["nativeDocument"]).exists()
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.upper().startswith("ANICRAFT_")
    }
    for command in handoff["commands"]:
        assert command[0] == str(cli)
        subprocess.run(
            command,
            cwd=handoff_ref.parent,
            capture_output=True,
            timeout=10,
            check=True,
            env=environment,
        )
    inspected = run_cli(
        [
            "artcraft",
            "inspect",
            "--job",
            prepared["jobRef"],
            "--expected-head",
            plan.parsed_json["head"],
            "--json",
        ]
    )
    assert inspected.ok, inspected.stderr
    assert inspected.parsed_json["checks"]["nativeDocument"] == "returned-unverified"
    assert (
        inspected.parsed_json["sourceObservations"]["editableText"] == "Clara Caf\u00e9"
    )
    assert inspected.parsed_json["sourceObservations"]["fontFamily"] == "Arial"
    assert len(list((handoff_ref.parent / "white").glob("*.png"))) == 24


def _register_native_overlay(tmp_path, monkeypatch, cli):
    from tests.test_artcraft_jobs import _overlay_snapshots, job_spec

    from avo import artcraft, init_project, motion
    from avo.adapters.artcraft import SelectedArtCraftAdapter
    from avo.proof_composition import register_artcraft_export
    from avo.timeline.generated_assets import GeneratedAssetService
    from avo.timeline.workspace import TimelineWorkspace

    project = tmp_path / "avo.project.json"
    project.write_text(
        json.dumps(
            {
                "rawDir": str(tmp_path),
                "videoId": "integration-video",
                "provider": "neutral-channel",
            }
        ),
        encoding="utf-8",
    )
    derived = tmp_path / "edit" / "derived"
    derived.mkdir(parents=True)
    snapshots = _overlay_snapshots(width=640, height=360, frame_count=24)
    heads = {
        key: letter * 64
        for key, letter in zip(
            ("cmap", "bmap", "tracks", "animation", "sync-map"), "abcde", strict=True
        )
    }
    monkeypatch.setattr(
        TimelineWorkspace, "active_dependency_snapshot", lambda _self: heads
    )
    monkeypatch.setattr(
        motion, "_canonical_drawing_heads", lambda _workspace: (snapshots, heads)
    )
    monkeypatch.setattr(GeneratedAssetService, "_current_originals", lambda _self: [])
    monkeypatch.setattr(init_project, "load_provider", lambda slug: {"slug": slug})

    def fixture_runner(executable, _roots, workdir, arguments, *, env, timeout):
        assert executable["locator"] == str(cli)
        assert workdir.is_relative_to(tmp_path)
        return subprocess.run(
            [str(cli), *map(str, arguments)],
            cwd=workdir,
            env=env,
            timeout=timeout,
            capture_output=True,
            check=True,
        ).stdout

    adapter = SelectedArtCraftAdapter(
        observe_confinement=lambda _installed, roots: roots,
        run_confined=fixture_runner,
    )
    brief = request(
        context={
            "kind": "video",
            "project": str(project),
            "videoId": "integration-video",
        }
    )
    intent = artcraft.ArtCraftIntent("explicit", "anicraft", ("lower-third",))
    specification = job_spec(
        tmp_path,
        output=_job_contract(),
        cliPath=str(cli),
        appPath=str(cli.with_name("anicraft.exe")),
        budget={"files": 128, "bytes": 16_000_000, "seconds": 60},
        authoringParameters={"primaryText": "Clara Caf\u00e9", "font": "Arial"},
    )
    job = artcraft.prepare_authoring(
        brief,
        specification,
        decision=artcraft.assess_request(brief, intent=intent),
        intent=intent,
        adapter=adapter,
    )
    rendered = artcraft.run_authoring(
        job["jobRef"], expected_head=job["head"], adapter=adapter
    )
    workspace = TimelineWorkspace.from_project(project)
    record = register_artcraft_export(
        workspace,
        job_ref=job["jobRef"],
        expected_head=rendered["head"],
        output=derived / "speaker.mkv",
        asset_id="artcraft-speaker",
    )
    return workspace, heads, record


def test_installed_anicraft_overlay_contributes_to_full_and_window_proofs(
    tmp_path, monkeypatch
):
    from fractions import Fraction

    import numpy as np
    from tests.integration.test_code_drawn_proof_executor import (
        _add_generated,
        _conformance,
        _frames,
        _frozen_plan,
    )
    from tests.integration.test_ffmpeg_proof_executor import _execution, _pcm

    from avo.adapters.media.timeline_render import TimelineRenderAdapter
    from avo.proof_composition import create_generated_asset_validator
    from avo.timeline.generated_assets import GeneratedAssetService
    from avo.timeline.proof_plan import ProofPlanCompiler

    entry = os.environ.get("AVO_ARTCRAFT_ANICRAFT_TEST_CLI")
    if not entry:
        pytest.skip(
            "set AVO_ARTCRAFT_ANICRAFT_TEST_CLI to the installed AniCraft 0.2.1 CLI"
        )
    cli = Path(entry).resolve(strict=True)
    workspace, heads, record = _register_native_overlay(tmp_path, monkeypatch, cli)
    execution = _conformance(_execution(tmp_path, fps=Fraction(24)))
    native_output = tmp_path / "native-source-test.mkv"
    baseline = _frozen_plan(execution, native_output)
    port = TimelineRenderAdapter(
        generated_asset_validator=create_generated_asset_validator(workspace)
    )
    port.render_proof_plan(baseline, native_output, window=None)

    receipt = record["parameters"]["artcraft"]
    operation = _add_generated(
        execution,
        {
            "record": record,
            "receipt": GeneratedAssetService(workspace).path(record["assetId"]),
            "lock_path": Path(receipt["bindingRef"]["locator"]),
            "lock": {"inputLockHash": receipt["bindingHash"]},
        },
        kind="overlay-video",
        start=18,
        end=42,
        local_start=0,
        z_order=2,
    )
    operation["parameters"]["placement"] = {"x": 0, "y": 0, "width": 640, "height": 360}
    compiler = ProofPlanCompiler(workspace)
    execution["canonicalInputLock"].update(
        heads, **compiler._generated_lock(execution["videoGraph"], execution["output"])
    )
    full = tmp_path / "full.mkv"
    plan = _frozen_plan(execution, full)
    assert port.proof_tool_readiness(plan)["generated:artcraft-speaker"]
    port.render_proof_plan(plan, full, window=None)
    short = tmp_path / "short.mkv"
    port.render_proof_plan(
        plan, short, window={"startFrame": 25, "endFrameExclusive": 39}
    )
    baseline_frames, full_frames = _frames(native_output), _frames(full)
    np.testing.assert_array_equal(_frames(short), full_frames[25:39])
    np.testing.assert_array_equal(full_frames[:19], baseline_frames[:19])
    np.testing.assert_array_equal(full_frames[41:], baseline_frames[41:])
    np.testing.assert_array_equal(_pcm(full), _pcm(native_output))
    assert not np.array_equal(full_frames[28, 285, 65], baseline_frames[28, 285, 65])
    assert not np.array_equal(full_frames[33, 285, 65], baseline_frames[33, 285, 65])
    heads["bmap"] = "f" * 64
    assert not port.proof_tool_readiness(plan)["generated:artcraft-speaker"]
    stale = tmp_path / "stale.mkv"
    with pytest.raises(ValueError, match="ArtCraft .*stale"):
        port.render_proof_plan(
            plan, stale, window={"startFrame": 25, "endFrameExclusive": 39}
        )
    assert not stale.exists()
