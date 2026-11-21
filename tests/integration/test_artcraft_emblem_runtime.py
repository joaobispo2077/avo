"""Opt-in native evidence for the selected VectorCraft to AniCraft handoff."""

import json
import os
import shutil
import subprocess
from fractions import Fraction
from pathlib import Path

import numpy as np
import pytest
from PIL import Image
from tests.artcraft_fixtures import request
from tests.integration.test_artcraft_audio_runtime import (
    _installed_cli as _installed_sound,
)
from tests.integration.test_artcraft_audio_runtime import (
    _prepare_native_cue,
    _tracks_with_generated_cue,
    _with_cue_graph,
)
from tests.integration.test_artcraft_lower_third_runtime import (
    _assert_pinned_native_source,
    _publish_fixture_package,
)
from tests.integration.test_canonical_sound_proof_runtime import recorded_program
from tests.integration.test_code_drawn_proof_executor import (
    _add_generated,
    _conformance,
    _frames,
    _frozen_plan,
)
from tests.integration.test_ffmpeg_proof_executor import _execution, _pcm
from tests.test_artcraft_handoffs import (
    _prepare_animated_emblem,
    _prepare_emblem,
    animated_emblem_spec,
    emblem_spec,
)
from tests.test_artcraft_jobs import _overlay_snapshots, _prepare, job_spec

from avo import artcraft, init_project, motion
from avo.adapters.artcraft import SelectedArtCraftAdapter
from avo.adapters.media.timeline_render import TimelineRenderAdapter
from avo.proof_composition import (
    create_generated_asset_validator,
    register_artcraft_export,
)
from avo.timeline.artcraft_audio import lock_generated_audio
from avo.timeline.contracts import file_fingerprint
from avo.timeline.generated_assets import GeneratedAssetService
from avo.timeline.proof_plan import ProofPlanCompiler
from avo.timeline.tracks import TracksService
from avo.timeline.workspace import TimelineWorkspace

pytestmark = [pytest.mark.integration, pytest.mark.native_artcraft]


def _tools():
    required = ("VECTORCRAFT", "ANICRAFT")
    selectors = [os.environ.get(f"AVO_ARTCRAFT_{app}_TEST_CLI") for app in required]
    if not all(selectors):
        pytest.skip("Select the installed VectorCraft 0.24.1 and AniCraft 0.2.1 CLIs")
    return [Path(selector).resolve(strict=True) for selector in selectors]


def _video_context(path, monkeypatch, *, workspace=None, component="emblem"):
    if workspace is None:
        project = path / "avo.project.json"
        project.write_text(
            json.dumps(
                {
                    "rawDir": str(path),
                    "videoId": "emblem-video",
                    "provider": "neutral-channel",
                }
            ),
            encoding="utf-8",
        )
        workspace = TimelineWorkspace.from_project(project)
    else:
        project = Path(workspace.project_path)
        configuration = json.loads(project.read_text(encoding="utf-8"))
        configuration["videoId"] = workspace.video_id
        project.write_text(json.dumps(configuration), encoding="utf-8")
    heads = {
        key: char * 64
        for key, char in zip(
            ("cmap", "bmap", "tracks", "animation", "sync-map"), "abcde", strict=True
        )
    }
    snapshots = _overlay_snapshots(width=640, height=360, start_frame=0, frame_count=24)
    snapshots["animation"]["components"][0]["componentId"] = component
    snapshots["bmap"]["cues"][0]["componentRef"] = component
    layer = snapshots["tracks"]["videoTracks"]["layers"][0]
    layer["animationRef"] = layer["generator"]["componentId"] = component
    monkeypatch.setattr(
        TimelineWorkspace, "active_dependency_snapshot", lambda _self: heads
    )
    monkeypatch.setattr(
        motion, "_canonical_drawing_heads", lambda _workspace: (snapshots, heads)
    )
    monkeypatch.setattr(GeneratedAssetService, "_current_originals", lambda _self: [])
    monkeypatch.setattr(init_project, "load_provider", lambda slug: {"slug": slug})
    return (
        heads,
        workspace,
        {
            "kind": "video",
            "project": str(workspace.project_path),
            "videoId": workspace.video_id,
        },
    )


def _run(prepared, adapter):
    return artcraft.run_authoring(
        prepared["jobRef"], expected_head=prepared["head"], adapter=adapter
    )


def _selected_adapter(tmp_path, *tools):
    discovered, invoked = [], []

    def observe(installation, roots):
        discovered.append(Path(installation["executable"]["locator"]))
        return roots

    def invoke(binary, roots, directory, arguments, *, env, timeout):
        cli = Path(binary["locator"])
        assert cli in tools
        assert directory.is_relative_to(tmp_path)
        assert len(roots["write"]) == 1
        assert directory.is_relative_to(roots["write"][0])
        invoked.append(cli)
        return subprocess.run(
            [str(cli), *map(str, arguments)],
            cwd=directory,
            env=env,
            timeout=timeout,
            capture_output=True,
            check=True,
        ).stdout

    adapter = SelectedArtCraftAdapter(observe_confinement=observe, run_confined=invoke)
    return adapter, discovered, invoked


def _registered_emblem(
    tmp_path, monkeypatch, vector, ani, *, workspace=None, identity_label=False
):
    heads, workspace, context = _video_context(
        tmp_path, monkeypatch, workspace=workspace
    )
    provider = workspace.project["provider"]
    adapter, discovered, invoked = _selected_adapter(tmp_path, vector, ani)
    artwork = _run(
        _prepare_emblem(
            emblem_spec(tmp_path, cliPath=str(vector), provider=provider),
            adapter,
            provider=provider,
        ),
        adapter,
    )
    standalone = artcraft.describe_export_review(
        artwork["jobRef"], expected_head=artwork["head"]
    )["standalone"]
    assert set(discovered) == set(invoked) == {vector}
    discovered.clear()
    invoked.clear()

    specification = animated_emblem_spec(
        workspace.raw_dir,
        standalone["artworkRef"],
        cliPath=str(ani),
        provider=provider,
        readRoots=[str(tmp_path)],
    )
    if identity_label:
        specification["output"].update(width=640, height=360)
        specification["authoringParameters"] = {
            "primaryText": "Speaker",
            "font": "Arial",
        }
        selected = _prepare(
            artcraft,
            request(provider=provider, componentId="emblem", context=context),
            specification,
            adapter,
        )
    else:
        selected = _prepare_animated_emblem(
            specification, adapter, context=context, provider=provider
        )
    rendered = _run(selected, adapter)
    if identity_label:
        selected, rendered = _revise_identity_label(
            specification, context, selected, rendered, adapter
        )
    assert set(discovered) == set(invoked) == {ani}
    assert _run(rendered, None) == rendered
    _, exported = artcraft.read_authoring_export(
        rendered["jobRef"], expected_head=rendered["head"]
    )
    assert exported["saved"]["locator"].endswith(".anicraft")
    assert len(exported["outputs"]) == 24
    bounds = []
    for frame in exported["outputs"]:
        with Image.open(frame["locator"]) as image:
            bounds.append(image.getchannel("A").getbbox())
    assert bounds[0] is None and bounds[-1] is None
    assert bounds[3][0] + 24 == bounds[8][0] == bounds[18][0] == bounds[21][0] + 24

    derived = workspace.raw_dir / "edit" / "derived"
    derived.mkdir(parents=True, exist_ok=True)
    record = register_artcraft_export(
        workspace,
        job_ref=rendered["jobRef"],
        expected_head=rendered["head"],
        output=derived / "emblem.mkv",
        asset_id="artcraft-emblem",
    )
    assert all(
        input_ in [item["fingerprint"] for item in record["inputs"]]
        for input_ in selected["job"]["inputs"]
    )
    return workspace, heads, record, standalone, rendered


def _revise_identity_label(specification, context, initial, rendered, adapter):
    from avo.adapters.artcraft_anicraft import inspect_lower_third_source

    original, event = artcraft.read_authoring_export(
        initial["jobRef"], expected_head=rendered["head"]
    )
    source = Path(event["saved"]["locator"])
    fingerprint = file_fingerprint(source)
    parameters = {**original["authoringParameters"], "primaryText": "Presenter"}
    revised = {
        **specification,
        "jobId": "identity-label-revision",
        "document": {"state": "saved", "source": str(source)},
        "authoringParameters": parameters,
    }
    brief = request(
        provider=specification["provider"], componentId="emblem", context=context
    )
    selected = _prepare(artcraft, brief, revised, adapter)
    rendered = _run(selected, adapter)
    job, event = artcraft.read_authoring_export(
        selected["jobRef"], expected_head=rendered["head"]
    )
    artwork = artcraft.selected_vector_artwork(job["inputs"])
    facts = inspect_lower_third_source(
        Path(event["saved"]["locator"]),
        job["output"],
        parameters,
        max_bytes=job["budget"]["bytes"],
        artwork=artwork,
    )
    assert facts["editableText"] == "Presenter" and facts["identityVectorHash"]
    assert file_fingerprint(source) == fingerprint
    with Image.open(event["outputs"][8]["locator"]) as frame:
        patch = frame.crop((61, 285, 80, 304))
        colors = {pixel for _, pixel in patch.getcolors(patch.width * patch.height)}
        assert {(245, 248, 251, 255), (16, 44, 72, 255)} <= colors
    intent = artcraft.ArtCraftIntent("explicit", "anicraft", ("lower-third",))
    reuse_spec = {**revised, "mode": "reuse", "jobId": "identity-label-reuse"}
    reuse_spec.pop("cliPath")
    reuse = artcraft.prepare_authoring_reuse(
        brief,
        reuse_spec,
        from_job=selected["jobRef"],
        from_head=rendered["head"],
        intent=intent,
        decision=artcraft.assess_request(brief, intent=intent),
    )
    reused = _run(reuse, None)
    _, copied = artcraft.read_authoring_export(
        reused["jobRef"], expected_head=reused["head"]
    )
    assert [row["sha256"] for row in copied["outputs"]] == [
        row["sha256"] for row in event["outputs"]
    ]
    return reuse, reused


def test_native_vector_identity_survives_an_editable_lower_third_revision(
    tmp_path, monkeypatch
):
    from avo.adapters.artcraft_anicraft import inspect_lower_third_source

    vector, ani = _tools()
    _, _, record, standalone, rendered = _registered_emblem(
        tmp_path, monkeypatch, vector, ani, identity_label=True
    )
    assert standalone["vectorArtwork"] in [
        item["fingerprint"] for item in record["inputs"]
    ]
    job, exported = artcraft.read_authoring_export(
        rendered["jobRef"], expected_head=rendered["head"]
    )
    source = tmp_path / "identity-package-source"
    source.mkdir()
    native = Path(
        shutil.copyfile(exported["saved"]["locator"], source / "label.anicraft")
    )
    shutil.copyfile(exported["recipe"]["locator"], source / "recipe.json")
    artwork = Path(
        shutil.copyfile(standalone["vectorArtwork"]["locator"], source / "identity.svg")
    )
    catalog, store, event = _publish_fixture_package(
        tmp_path,
        native,
        job["output"],
        inspect_lower_third_source,
        parameters=job["authoringParameters"],
        artwork=artwork,
    )
    instance, project, retained_native = _assert_pinned_native_source(
        tmp_path, catalog.path, store, event, native, artwork=artwork
    )
    Path(standalone["vectorArtwork"]["locator"]).write_bytes(b"changed artwork")
    inspection = artcraft.inspect_authoring(
        rendered["jobRef"], expected_head=rendered["head"]
    )
    assert inspection["status"] == "stale"
    _render_retained_identity(
        monkeypatch, ani, instance, project, retained_native, job["output"]
    )


def _render_retained_identity(monkeypatch, ani, instance, project, native, output):
    from avo.adapters.artcraft_anicraft import inspect_lower_third_source

    _, workspace, context = _video_context(
        project.parent,
        monkeypatch,
        workspace=TimelineWorkspace.from_project(project),
        component=instance["kitId"],
    )
    adapter, discovered, invoked = _selected_adapter(workspace.raw_dir, ani)
    provider = workspace.project["provider"]
    brief = request(provider=provider, componentId=instance["kitId"], context=context)
    mark = native.parent / "identity.svg"
    original = file_fingerprint(native)
    artwork = file_fingerprint(mark)
    selection = {key: instance[key] for key in ("instanceId", "instanceHash")}
    spec = job_spec(
        workspace.raw_dir,
        cliPath=str(ani),
        provider=provider,
        document={"state": "saved", "source": str(native)},
        authoringParameters=instance["parameters"],
        output=output,
        artworkRef=selection,
        readRoots=[str(workspace.raw_dir)],
    )
    with pytest.raises(artcraft.ArtCraftError, match="selected kit instance"):
        _prepare(
            artcraft,
            brief,
            {**spec, "artworkRef": {**selection, "instanceHash": "0" * 64}},
            adapter,
        )
    assert not discovered and not invoked
    rendered = _run(_prepare(artcraft, brief, spec, adapter), adapter)
    job, exported = artcraft.read_authoring_export(
        rendered["jobRef"], expected_head=rendered["head"]
    )
    facts = inspect_lower_third_source(
        Path(exported["saved"]["locator"]),
        output,
        instance["parameters"],
        max_bytes=job["budget"]["bytes"],
        artwork=artwork,
    )
    assert facts["editableText"] == "Mar\u00eda" and facts["identityVectorHash"]
    assert file_fingerprint(native) == original
    record = register_artcraft_export(
        workspace,
        job_ref=rendered["jobRef"],
        expected_head=rendered["head"],
        output=workspace.raw_dir / "edit" / "derived" / "retained-identity.mkv",
        asset_id="retained-identity",
    )
    assert artwork in [item["fingerprint"] for item in record["inputs"]]
    mark.write_bytes(b"changed retained SVG")
    assert (
        artcraft.inspect_authoring(rendered["jobRef"], expected_head=rendered["head"])[
            "status"
        ]
        == "stale"
    )


def test_native_vector_emblem_becomes_an_editable_animation_and_proof_asset(
    tmp_path, monkeypatch
):
    _, _, _, standalone, rendered = _registered_emblem(tmp_path, monkeypatch, *_tools())
    Path(standalone["vectorArtwork"]["locator"]).write_bytes(b"changed vector export")
    with pytest.raises(artcraft.ArtCraftError, match="export evidence is stale"):
        artcraft.read_authoring_export(
            rendered["jobRef"], expected_head=rendered["head"]
        )


def test_emblem_and_optional_sound_render_through_one_original_footage_proof(
    tmp_path, monkeypatch
):
    vector, ani = _tools()
    sound = _installed_sound()
    workspace = recorded_program(tmp_path)
    cue_workspace = tmp_path / "cue-workspace"
    cue_workspace.mkdir()
    _, _, _, _, exported = _prepare_native_cue(
        cue_workspace, monkeypatch, sound, provider=workspace.project["provider"]
    )
    review = artcraft.describe_export_review(
        exported["jobRef"], expected_head=exported["head"]
    )
    TracksService(workspace).author(
        _tracks_with_generated_cue(workspace, review),
        actor="fixture",
        reason="Explicit optional synthetic sound",
    )
    _, heads, record, _, _ = _registered_emblem(
        tmp_path, monkeypatch, vector, ani, workspace=workspace
    )
    execution = _conformance(_execution(tmp_path, fps=Fraction(24)))
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
        start=0,
        end=24,
        local_start=0,
        z_order=2,
    )
    operation["parameters"]["placement"] = {"x": 0, "y": 0, "width": 640, "height": 360}
    compiler = ProofPlanCompiler(workspace)
    execution["canonicalInputLock"].update(
        heads, **compiler._generated_lock(execution["videoGraph"], execution["output"])
    )
    renderer = TimelineRenderAdapter(
        generated_asset_validator=create_generated_asset_validator(workspace)
    )
    clean, mixed = tmp_path / "emblem-silent.mkv", tmp_path / "emblem-with-cue.mkv"
    with_cue = lock_generated_audio(
        workspace, _with_cue_graph(execution, review), require_applied=False
    )
    renderer.render_proof_plan(_frozen_plan(execution, clean), clean, window=None)
    renderer.render_proof_plan(
        _frozen_plan(with_cue, mixed, events=with_cue["events"]), mixed, window=None
    )
    np.testing.assert_array_equal(_frames(clean), _frames(mixed))
    unchanged, audible = _pcm(clean), _pcm(mixed)
    cue = _pcm(Path(review["standalone"]["audio"]["locator"]))
    assert np.max(np.abs(unchanged[:48000])) > 0.05
    np.testing.assert_allclose(audible[:48000] - unchanged[:48000], cue, atol=3e-7)
    np.testing.assert_array_equal(unchanged[48000:], audible[48000:])
