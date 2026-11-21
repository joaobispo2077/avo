"""Proof reuse requires current retained native tool and media evidence."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from avo import artcraft, init_project, project_inventory
from avo.timeline import artcraft_audio, artcraft_stills
from avo.timeline.artcraft_packages import (
    retain_native_instance_sources,
    retain_provider_package,
    verify_provider_package,
)
from avo.timeline.component_instances import ComponentInstanceService
from avo.timeline.contracts import file_fingerprint
from avo.timeline.reconstruction import (
    ReconstructionError,
    build_reconstruction_bundle,
    verify_reconstruction_bundle,
)
from tests.artcraft_fixtures import locked_tool_observation, picture_output, request
from tests.test_artcraft_jobs import AuthoringApp, _prepare, job_spec
from tests.test_artcraft_profiles import EFFECT_OPERATION, effect_spec
from tests.test_artcraft_provider_packages import (
    _observe_fixture,
    _package_from_retained_source,
)
from tests.test_reconstruction_bundle import canonical_project


@pytest.mark.parametrize(
    ("module", "resolve", "app", "role", "format_name", "evidence"),
    [
        (
            artcraft_audio,
            artcraft_audio.resolve_generated_audio,
            "soundcraft",
            "generated-audio",
            "wav",
            "audioEvidence",
        ),
        (
            artcraft_stills,
            artcraft_stills.read_generated_still,
            "vectorcraft",
            "generated-still",
            "png",
            "stillEvidence",
        ),
    ],
)
def test_generated_media_rejects_a_changed_tool_without_launching_it(
    tmp_path, monkeypatch, module, resolve, app, role, format_name, evidence
):
    job_path = tmp_path / "job.json"
    job_path.write_bytes(b"exact synthetic job")
    export = tmp_path / f"component.{format_name}"
    export.write_bytes(b"retained synthetic media")
    reference = {"job": file_fingerprint(job_path), "exportHead": "b" * 64}
    observation = locked_tool_observation(tmp_path, app)
    retained_job = {
        "observation": observation,
        "output": {"role": role, "format": format_name},
        "inputs": [],
    }
    event = {"outputs": [file_fingerprint(export)], evidence: {}}
    monkeypatch.setattr(
        module, "read_authoring_export", lambda *_args, **_kwargs: (retained_job, event)
    )
    assert resolve(reference) == (retained_job, event)
    application = Path(observation["application"]["locator"])
    application.write_bytes(b"x" * observation["application"]["sizeBytes"])
    with pytest.raises(artcraft.ArtCraftError, match="installation has changed"):
        resolve(reference)


def test_reconstruction_retains_selected_native_job_and_its_journal(
    tmp_path, monkeypatch
):
    workspace, master = canonical_project(tmp_path)
    monkeypatch.setattr(init_project, "load_provider", lambda slug: {"slug": slug})
    adapter = AuthoringApp(tmp_path)
    context = {
        "kind": "video",
        "project": str(workspace.project_path),
        "videoId": workspace.video_id,
    }
    spec = job_spec(
        tmp_path,
        provider=workspace.project["provider"],
        authoringParameters={"primaryText": "Speaker", "font": "Arial"},
        output=picture_output(frameCount=24),
    )
    selected = _prepare(
        artcraft, request(provider=spec["provider"], context=context), spec, adapter
    )
    exported = artcraft.run_authoring(
        selected["jobRef"], expected_head=selected["head"], adapter=adapter
    )
    _, event = artcraft.read_authoring_export(
        exported["jobRef"], expected_head=exported["head"]
    )
    native = Path(event["saved"]["locator"])
    scratch = native.with_name("renderer-scratch.bin")
    scratch.write_bytes(b"disposable synthetic tool scratch")

    bundle = build_reconstruction_bundle(
        workspace, master_basename=master, actor="fixture"
    )
    paths = {tmp_path / item["path"] for item in bundle["files"]}
    job = Path(selected["jobRef"])
    assert {
        job,
        job.with_name("events.json"),
        job.with_name("event-verify-run.json"),
        native,
        Path(event["recipe"]["locator"]),
    } <= paths
    assert scratch not in paths
    scratch.unlink()
    assert (
        verify_reconstruction_bundle(tmp_path)["bundleSha256"] == bundle["bundleSha256"]
    )

    for changed in (native, Path(event["recipe"]["locator"])):
        predecessor = changed.read_bytes()
        changed.write_bytes(b"modified retained evidence")
        try:
            with pytest.raises(
                ReconstructionError, match="reconstruction file changed"
            ) as error:
                verify_reconstruction_bundle(tmp_path)
            assert changed.name in str(error.value)
        finally:
            changed.write_bytes(predecessor)
    assert (
        verify_reconstruction_bundle(tmp_path)["bundleSha256"] == bundle["bundleSha256"]
    )


def test_reconstruction_checks_a_selected_native_input_outside_the_video_root(
    tmp_path, monkeypatch
):
    raw = tmp_path / "video"
    raw.mkdir()
    workspace, master = canonical_project(raw)
    monkeypatch.setattr(init_project, "load_provider", lambda slug: {"slug": slug})
    separate_source = tmp_path / "provider-label.anicraft"
    separate_source.write_bytes(b"pinned synthetic native source")
    context = {
        "kind": "video",
        "project": str(workspace.project_path),
        "videoId": workspace.video_id,
    }
    adapter = AuthoringApp(raw)
    spec = job_spec(
        raw,
        provider=workspace.project["provider"],
        readRoots=[str(tmp_path)],
        document={"state": "saved", "source": str(separate_source)},
        authoringParameters={"primaryText": "Speaker", "font": "Arial"},
    )
    prepared = _prepare(
        artcraft, request(provider=spec["provider"], context=context), spec, adapter
    )
    bundle = build_reconstruction_bundle(
        workspace, master_basename=master, actor="fixture"
    )
    assert bundle["externalArtCraftInputs"] == [file_fingerprint(separate_source)]
    assert prepared["job"]["document"] in {item["path"] for item in bundle["files"]}
    assert verify_reconstruction_bundle(raw)["bundleSha256"] == bundle["bundleSha256"]
    separate_source.write_bytes(b"externally edited native source")
    with pytest.raises(ReconstructionError, match="Retained ArtCraft file changed"):
        verify_reconstruction_bundle(raw)


def test_reconstruction_requires_the_exact_selected_effectcraft_font(
    tmp_path, monkeypatch
):
    raw = tmp_path / "video"
    raw.mkdir()
    workspace, master = canonical_project(raw)
    monkeypatch.setattr(init_project, "load_provider", lambda slug: {"slug": slug})
    font = tmp_path / "fonts" / "arial.ttf"
    font.parent.mkdir()
    font.write_bytes(b"synthetic installed font")
    monkeypatch.setattr(artcraft, "_is_effect_system_font", lambda path: path == font)
    observed = {
        **locked_tool_observation(tmp_path, "effectcraft"),
        "operations": [EFFECT_OPERATION],
        "release": "0.24.1",
    }
    adapter = SimpleNamespace(
        observe=lambda **selected: {**observed, "effectiveRoots": selected["roots"]}
    )
    provider = workspace.project["provider"]
    brief = request(
        provider=provider,
        required={
            "behavior": EFFECT_OPERATION,
            "outputRole": "overlay-video",
            "editable": True,
        },
        context={
            "kind": "video",
            "project": str(workspace.project_path),
            "videoId": workspace.video_id,
        },
    )
    _prepare(
        artcraft,
        brief,
        effect_spec(
            raw, provider=provider, effectFont=str(font), readRoots=[str(font.parent)]
        ),
        adapter,
        intent=artcraft.ArtCraftIntent("explicit", "effectcraft", (EFFECT_OPERATION,)),
    )
    bundle = build_reconstruction_bundle(
        workspace, master_basename=master, actor="fixture"
    )
    assert bundle["externalArtCraftInputs"] == [file_fingerprint(font)]
    assert verify_reconstruction_bundle(raw)["bundleSha256"] == bundle["bundleSha256"]
    font.write_bytes(b"replacement installed font")
    with pytest.raises(
        ReconstructionError, match="Retained ArtCraft file changed"
    ) as error:
        verify_reconstruction_bundle(raw)
    assert font.name in str(error.value)


def _approved_package(source, provider):
    source.mkdir()
    native = source / "component.anicraft"
    native.write_bytes(b"immutable synthetic package source")
    (source / "recipe.json").write_bytes(b'{"fixture":"lower-third"}')
    packet = _package_from_retained_source(native, picture_output(), {})
    body = {key: value for key, value in packet.items() if key != "packageHash"}
    package = artcraft.seal_record("package", {**body, "provider": provider})
    evidence = verify_provider_package(
        package, source, provider=package["provider"], source_observer=_observe_fixture
    )
    return package, evidence


def test_reconstruction_refuses_changed_rights_in_the_pinned_video_package(tmp_path):
    raw = tmp_path / "video"
    raw.mkdir()
    workspace, master = canonical_project(raw)
    package, evidence = _approved_package(
        tmp_path / "approved-source", workspace.project["provider"]
    )
    instance_id = "speaker-first-use"
    target = raw / "edit" / "derived" / "provider-components" / instance_id
    retain_native_instance_sources(package, evidence, project_root=raw, target=target)
    service = ComponentInstanceService(workspace)
    service._write_instance(
        service._seal(
            {
                "instanceId": instance_id,
                "kitId": package["componentId"],
                "kitVersion": package["componentVersion"],
                "kitManifestHash": "e" * 64,
                "parameters": {},
                "assetBindings": [],
                "eventBindings": [],
                "safeAreaBindings": {
                    key: [] for key in ("faces", "captions", "evidence", "ui")
                },
                "reviewRefs": [],
                "nativePackage": {
                    key: package[key] for key in ("provider", "app", "packageHash")
                },
                "generatedFiles": [
                    {
                        "path": str(target / "files" / item["path"]),
                        "sha256": item["sha256"],
                    }
                    for item in package["files"]
                ],
            }
        )
    )
    bundle = build_reconstruction_bundle(
        workspace, master_basename=master, actor="fixture"
    )
    assert verify_reconstruction_bundle(raw)["bundleSha256"] == bundle["bundleSha256"]

    rights = target / "files" / package["rightsRef"]
    rights.write_bytes(b"changed rights evidence in pinned copy")
    with pytest.raises(ReconstructionError, match="ArtCraft package"):
        build_reconstruction_bundle(workspace, master_basename=master, actor="fixture")


def test_cleanup_preserves_shared_native_provider_library_below_another_videos_edit(
    tmp_path,
):
    raw = tmp_path / "library-host-video"
    raw.mkdir()
    workspace, master = canonical_project(raw)
    package, evidence = _approved_package(
        tmp_path / "approved-shared-source", "other-provider"
    )
    store = raw / "edit" / "shared-native-library"
    store.mkdir()
    target = store / retain_provider_package(package, evidence, store)
    scratch = raw / "edit" / "ordinary-scratch.bin"
    scratch.write_bytes(b"discardable fixture scratch")
    unrelated = raw / "edit" / "cache" / ("f" * 64) / "manifest.json"
    unrelated.parent.mkdir(parents=True)
    unrelated.write_text("[]", encoding="utf-8")
    publisher = (
        target.parent / "artcraft-package-inflight" / "files" / "component.anicraft"
    )
    publisher.parent.mkdir(parents=True)
    publisher.write_bytes(b"incomplete native write")
    bundle = build_reconstruction_bundle(
        workspace, master_basename=master, actor="fixture"
    )
    assert not any(
        "shared-native-library" in entry["path"] for entry in bundle["files"]
    )

    preview = project_inventory.run_cleanup(
        raw, master, dry_run=True, purge_session=False
    )
    protected = {
        target / "manifest.json",
        *(target / "files" / item["path"] for item in package["files"]),
    }
    assert scratch in preview.paths
    assert unrelated in preview.paths
    assert protected <= set(preview.preserved.all_paths)
    assert protected.isdisjoint(preview.paths)
    assert publisher not in preview.paths

    (target / "files" / package["rightsRef"]).write_bytes(
        b"unreconciled shared package rights"
    )
    with pytest.raises(
        project_inventory.PreservedSetViolation, match="shared ArtCraft library"
    ):
        project_inventory.run_cleanup(raw, master, dry_run=True, purge_session=False)


def test_cleanup_rechecks_shared_package_published_after_candidate_scan(
    tmp_path, monkeypatch
):
    raw = tmp_path / "library-host-video"
    raw.mkdir()
    workspace, master = canonical_project(raw)
    package, evidence = _approved_package(
        tmp_path / "approved-source", "other-provider"
    )
    store = raw / "edit" / "shared-native-library"
    store.mkdir()
    build_reconstruction_bundle(workspace, master_basename=master, actor="fixture")
    scan = project_inventory.scan_delete_candidates

    def scan_with_arrival(raw_dir, preserved):
        candidates, leftover = scan(raw_dir, preserved)
        published = store / retain_provider_package(package, evidence, store)
        return [*candidates, published / "manifest.json"], leftover

    monkeypatch.setattr(project_inventory, "scan_delete_candidates", scan_with_arrival)
    attempted = []
    with pytest.raises(project_inventory.PreservedSetViolation, match="preserved file"):
        project_inventory.run_cleanup(
            raw, master, rimraf_runner=attempted.append, purge_session=False
        )
    assert not attempted


@pytest.mark.parametrize("damage", ["missing", "blank"])
def test_cleanup_refuses_damaged_shared_library_manifest(tmp_path, damage):
    raw = tmp_path / "library-host-video"
    raw.mkdir()
    workspace, master = canonical_project(raw)
    package, evidence = _approved_package(
        tmp_path / "approved-source", "other-provider"
    )
    store = raw / "edit" / "shared-native-library"
    store.mkdir()
    target = store / retain_provider_package(package, evidence, store)
    manifest = target / "manifest.json"
    if damage == "missing":
        manifest.unlink()
    else:
        manifest.write_text("{}", encoding="utf-8")
    build_reconstruction_bundle(workspace, master_basename=master, actor="fixture")
    attempted = []
    with pytest.raises(
        project_inventory.PreservedSetViolation, match="shared ArtCraft library"
    ):
        project_inventory.run_cleanup(
            raw, master, rimraf_runner=attempted.append, purge_session=False
        )
    assert not attempted
    assert (target / "files" / "component.anicraft").is_file()
