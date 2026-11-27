"""Retain recorded ArtCraft sources and operation evidence for one project."""

import json
from pathlib import Path

from avo.artcraft import retained_authoring_files, selected_vector_artwork

from .artcraft_binding import require_artcraft_media_scope
from .artcraft_packages import retained_native_instance_files
from .component_instances import ComponentInstanceService
from .contracts import file_fingerprint, validate_document
from .media_admission import MediaAdmissionError, require_no_forbidden_outputs


def retained_artcraft_files(workspace):
    directory = workspace.timeline_dir / "artcraft-jobs"
    if directory.resolve() != directory:
        raise ValueError("ArtCraft job records require an unaliased timeline directory")
    retained = {}
    artwork = []
    for path in sorted(directory.glob("job-*/job.json")):
        job, _ = _add_artcraft_job(retained, workspace, path)
        if "job" in job.get("artworkRef", {}):
            artwork.append(_retain_linked_artwork(retained, workspace, job))
    _require_artwork_ancestry(workspace, artwork)
    for reference, profile in _track_exports(workspace):
        _add_export_reference(retained, workspace, reference, profile)
    _include_artcraft_files(retained, _native_component_files(workspace))
    return [retained[path] for path in sorted(retained)]


def _retain_linked_artwork(retained, workspace, job):
    source, files = _add_export_reference(
        retained,
        workspace,
        job["artworkRef"],
        ("vectorcraft", "generated-still", "svg"),
    )
    if source["request"]["componentId"] != job["request"]["componentId"]:
        raise ValueError("Retained vector artwork belongs to a different component")
    artwork = selected_vector_artwork(files)
    if artwork != selected_vector_artwork(job["inputs"]):
        raise ValueError("Retained vector artwork differs from the selected input")
    return artwork


def _require_artwork_ancestry(workspace, artwork):
    if not artwork:
        return
    from .migration import inventory_historical_output_fingerprints

    known = inventory_historical_output_fingerprints(
        workspace.raw_dir,
        timeline_dir=workspace.timeline_dir,
        candidate_sizes=frozenset(item["sizeBytes"] for item in artwork),
    )
    try:
        require_no_forbidden_outputs(artwork, known_outputs=known)
    except MediaAdmissionError as error:
        finding = error.finding
        raise ValueError(
            f"{error.code}: linked ArtCraft artwork {finding['locator']} has retained "
            f"{finding['outputRole']} ancestry"
        ) from error


def _add_export_reference(retained, workspace, reference, profile):
    validate_document(reference, "avo.artcraft.schema.json#/$defs/exportRef")
    fingerprint = reference["job"]
    path = Path(fingerprint["locator"])
    if (
        not path.is_absolute()
        or path.resolve() != path
        or file_fingerprint(path) != fingerprint
    ):
        raise ValueError("Retained ArtCraft job reference changed or uses an alias")
    job, files = _add_artcraft_job(
        retained, workspace, path, expected_head=reference["exportHead"]
    )
    output = job["output"]
    if (job["observation"]["app"], output["role"], output["format"]) != profile:
        raise ValueError(
            "Retained ArtCraft export differs from its selected media profile"
        )
    return job, files


def _add_artcraft_job(retained, workspace, path, *, expected_head=None):
    job, files = retained_authoring_files(path, expected_head=expected_head)
    require_artcraft_media_scope(workspace, job, "Retained ArtCraft job")
    _include_artcraft_files(retained, files)
    return job, files


def _include_artcraft_files(retained, references):
    for item in references:
        locator = item["locator"]
        if retained.setdefault(locator, item) != item:
            raise ValueError(f"Conflicting ArtCraft evidence for {locator}")


def _native_component_files(workspace):
    service = ComponentInstanceService(workspace)
    if service.directory.resolve() != service.directory:
        raise ValueError(
            "Native component records require an unaliased timeline directory"
        )
    for path in sorted(service.directory.glob("*.json")):
        if path.resolve() != path:
            raise ValueError("Native component instance uses an aliased record")
        instance = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(instance, dict) and "nativePackage" in instance:
            service._validate(instance)
            if path.stem != instance["instanceId"] or path.stat().st_nlink != 1:
                raise ValueError(
                    "ArtCraft instance identity differs from its retained record"
                )
            yield from retained_native_instance_files(
                instance, workspace.raw_dir, workspace.project.get("provider")
            )


def _track_exports(workspace):
    store = workspace.store("tracks")
    for reference in store.load_index()["revisionRefs"]:
        snapshot = store.revision(reference["revisionId"])["snapshot"]
        for group, field, profile in (
            (
                "audioTracks",
                "generatedAudioRef",
                ("soundcraft", "generated-audio", "wav"),
            ),
            (
                "videoTracks",
                "generatedStillRef",
                ("vectorcraft", "generated-still", "png"),
            ),
        ):
            for layer in (snapshot.get(group) or {}).get("layers", []):
                if field in layer:
                    yield layer[field], profile
