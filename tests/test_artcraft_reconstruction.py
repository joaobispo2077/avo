"""Proof reuse requires current retained native tool and media evidence."""

from pathlib import Path

import pytest

from avo import artcraft, init_project
from avo.timeline import artcraft_audio, artcraft_stills
from avo.timeline.artcraft_packages import (
    retain_native_instance_sources,
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


def test_reconstruction_refuses_changed_rights_in_the_pinned_video_package(tmp_path):
    raw = tmp_path / "video"
    raw.mkdir()
    workspace, master = canonical_project(raw)
    source = tmp_path / "approved-source"
    source.mkdir()
    native = source / "component.anicraft"
    native.write_bytes(b"immutable synthetic package source")
    (source / "recipe.json").write_bytes(b'{"fixture":"lower-third"}')
    packet = _package_from_retained_source(native, picture_output(), {})
    body = {key: value for key, value in packet.items() if key != "packageHash"}
    package = artcraft.seal_record(
        "package", {**body, "provider": workspace.project["provider"]}
    )
    evidence = verify_provider_package(
        package, source, provider=package["provider"], source_observer=_observe_fixture
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
