"""Selected reference aspects remain descriptions rather than production authority."""

import json
from copy import deepcopy

import pytest

from avo.direction.brief import BriefService
from avo.direction.rules import DirectionError
from tests.test_briefstart import context, reference


@pytest.fixture
def project(tmp_path):
    raw = tmp_path / "reference-video"
    raw.mkdir()
    path = raw / "avo.project.json"
    path.write_text(
        json.dumps(
            {
                "schemaVersion": "1.0.0",
                "provider": "neutral-channel",
                "videoId": "reference-video",
                "rawDir": str(raw),
            }
        ),
        encoding="utf-8",
    )
    return path


def packet(service, result):
    return service.store.load_document(result["refs"]["packet"]["path"])


def test_references_only_preserves_exact_selected_aspects_and_usage_limits(project):
    service = BriefService(project)
    descriptor = reference()
    result = service.prepare("references", context(), [descriptor])
    saved = packet(service, result)["sources"][0]
    assert saved["kind"] == "reference"
    assert saved["document"]["selectedAspects"] == descriptor["selectedAspects"]
    assert saved["document"]["knownUsageLimits"] == descriptor["knownUsageLimits"]
    assert "approved" not in saved


def test_unavailable_media_locator_remains_user_described_without_inspection(project):
    service = BriefService(project)
    descriptor = reference()
    descriptor["locator"] = "https://example.invalid/unavailable-video.mp4"
    result = service.prepare("references", context(), [descriptor])
    saved = packet(service, result)["sources"][0]
    assert saved["document"]["observationKind"] == "user-described"
    assert saved["disposition"] == "user-described"


def test_conflicting_references_are_preserved_as_separate_sources(project):
    service = BriefService(project)
    quieter = reference()
    denser = deepcopy(quieter)
    denser.update(
        referenceId="dense-calculation",
        selectedAspects=["Dense progressive graphics"],
        description="Only the calculation section uses denser graphics.",
        applicability=["calculation section"],
    )
    result = service.prepare("references", context(), [quieter, denser])
    sources = packet(service, result)["sources"]
    assert [source["id"] for source in sources] == [
        "natural-delivery",
        "dense-calculation",
    ]
    assert sources[1]["document"]["applicability"] == ["calculation section"]


def test_builtin_and_reference_contributions_stay_distinct(project):
    service = BriefService(project)
    result = service.prepare("builtin:analysis-review@1.0.0", context(), [reference()])
    sources = packet(service, result)["sources"]
    assert [source["kind"] for source in sources] == ["builtin", "reference"]
    assert sources[1]["document"]["observationKind"] == "user-described"


def test_none_plus_reference_is_invalid_instead_of_silent_artistic_selection(project):
    service = BriefService(project)
    with pytest.raises(DirectionError):
        service.prepare("none", context(), [reference()])
    assert not service.root.exists()


def test_references_mode_requires_a_selected_reference(project):
    service = BriefService(project)
    with pytest.raises(DirectionError):
        service.prepare("references", context(), [])
    assert not service.root.exists()


def test_two_descriptors_cannot_collide_under_the_same_reference_identity(project):
    service = BriefService(project)
    changed = reference()
    changed["description"] = "A conflicting descriptor with the old identity."
    with pytest.raises(DirectionError):
        service.prepare("references", context(), [reference(), changed])


def test_current_creator_override_is_retained_beside_reference_context(project):
    service = BriefService(project)
    new_context = context()
    new_context["currentInstructions"] = [
        "Keep this explanation quieter than the energetic reference."
    ]
    result = service.prepare("references", new_context, [reference()])
    assert (
        packet(service, result)["context"]["currentInstructions"]
        == new_context["currentInstructions"]
    )


def test_explicit_utf8_bom_descriptor_is_read_without_opening_its_media_locator(
    project, monkeypatch
):
    from pathlib import Path

    service = BriefService(project)
    descriptor = reference()
    forbidden_media = project.parent / "unavailable-original.mp4"
    descriptor["locator"] = str(forbidden_media)
    path = project.parent / "reference.json"
    path.write_bytes(b"\xef\xbb\xbf" + json.dumps(descriptor).encode("utf-8"))
    original_open = Path.open

    def permitted_open(candidate, *args, **kwargs):
        assert candidate != forbidden_media, (
            "A descriptor is not permission to open its locator."
        )
        return original_open(candidate, *args, **kwargs)

    monkeypatch.setattr(Path, "open", permitted_open)
    result = service.prepare("references", context(), [path])
    saved = packet(service, result)["sources"][0]["document"]
    assert saved == descriptor
    assert not forbidden_media.exists()


def test_oversize_explicit_descriptor_fails_before_a_packet_is_created(project):
    service = BriefService(project)
    path = project.parent / "oversize-reference.json"
    path.write_bytes(b" " * (2 * 1024 * 1024 + 1))
    with pytest.raises(DirectionError):
        service.prepare("references", context(), [path])
    assert not service.root.exists()


@pytest.mark.parametrize("kind", ["missing", "directory"])
def test_unreadable_explicit_descriptor_reports_a_private_path_free_native_error(
    project, kind
):
    service = BriefService(project)
    path = project.parent / "private-reference-location"
    if kind == "directory":
        path.mkdir()
    with pytest.raises(DirectionError) as error:
        service.prepare("references", context(), [path])
    assert error.value.code == "DIR_INVALID_REFERENCE"
    assert str(path) not in str(error.value)
    assert "private-reference-location" not in str(error.value)
    assert not service.root.exists()
