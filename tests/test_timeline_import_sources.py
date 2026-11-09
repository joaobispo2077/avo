"""US2 selected-byte and source-property failures remain scoped repair results."""

import importlib.util
import subprocess
from copy import deepcopy

import pytest

from avo.adapters.media.otio_reader import read_otio
from avo.timeline.contracts import file_fingerprint
from avo.timeline.import_service import TimelineImportService
from tests.test_timeline_import_media import _mapping, _prepare
from tests.test_timeline_import_service import FIXTURE, REFERENCE, _probe
from tests.test_timeline_import_service import import_project as _import_project

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("opentimelineio") is None,
    reason="optional pinned native reader required",
)


@pytest.fixture(name="import_project")
def import_project_fixture(tmp_path):
    return _import_project.__wrapped__(tmp_path)


def _service(import_project, probe):
    project, provider, _ = import_project
    return TimelineImportService(
        project, provider_root=provider, reader=read_otio, probe=probe
    )


def _blocked(service, prepared):
    result = service.validate(prepared["importId"])
    assert result["status"] == "blocked"
    assert result["readiness"]["mediaReady"] == "failed"
    assert result["readiness"]["activationAllowed"] is False
    assert result["findings"]
    assert all(
        finding["blocking"] and finding["remediation"] for finding in result["findings"]
    )
    assert not service.workspace.artifact_path("cmap").exists()
    return result


@pytest.mark.parametrize("role", ["proof", "preview", "proxy", "masters", "delivery"])
def test_relocated_known_output_bytes_cannot_be_declared_as_original(
    import_project, role
):
    original = import_project[2]
    previous_output = original.parent / "edit" / role / "reference.mov"
    previous_output.parent.mkdir(parents=True)
    previous_output.write_bytes(original.read_bytes())
    service = _service(import_project, _probe)
    prepared = _prepare(service, FIXTURE, mappings={REFERENCE: _mapping(original)})
    result = _blocked(service, prepared)
    assert any(row["code"] == "OTIO_SOURCE_PROHIBITED" for row in result["findings"])


@pytest.mark.parametrize(
    "error",
    [
        subprocess.CalledProcessError(1, "ffprobe", stderr="invalid original"),
        subprocess.TimeoutExpired("ffprobe", 60),
        FileNotFoundError("ffprobe unavailable"),
    ],
)
def test_probe_process_failure_is_actionable_media_block_not_raw_exception(
    import_project, error
):
    def fail(paths):
        raise error

    service = _service(import_project, fail)
    prepared = _prepare(
        service, FIXTURE, mappings={REFERENCE: _mapping(import_project[2])}
    )
    result = _blocked(service, prepared)
    assert any(
        finding["code"] == "OTIO_RUNTIME_UNAVAILABLE" for finding in result["findings"]
    )
    assert any(finding["scope"] == REFERENCE for finding in result["findings"])


@pytest.mark.parametrize(
    "defect",
    [
        "missing-duration",
        "nonfinite-duration",
        "missing-audio-channels",
        "missing-source-record",
    ],
)
def test_invalid_probe_properties_are_scoped_media_blocks(import_project, defect):
    def malformed(paths):
        result = _probe(paths)
        info = result["sources"][0]
        if defect == "missing-duration":
            del info["durationSeconds"]
        elif defect == "nonfinite-duration":
            info["durationSeconds"] = "NaN"
        elif defect == "missing-audio-channels":
            del info["streams"]["audio"][0]["channels"]
        else:
            result["sources"] = []
        return result

    service = _service(import_project, malformed)
    result = _blocked(
        service,
        _prepare(service, FIXTURE, mappings={REFERENCE: _mapping(import_project[2])}),
    )
    assert any(finding["scope"] == REFERENCE for finding in result["findings"])


@pytest.mark.parametrize(
    "defect,code",
    [
        ("short-file", "OTIO_SOURCE_CHANGED"),
        ("short-picture", "OTIO_SOURCE_CHANGED"),
        ("short-audio", "OTIO_SOURCE_CHANGED"),
        ("video-rate", "OTIO_RATE_UNVERIFIED"),
        ("variable-video-rate", "OTIO_RATE_UNVERIFIED"),
        ("missing-stream", "OTIO_ROUTING_UNVERIFIED"),
        ("wrong-channels", "OTIO_ROUTING_UNVERIFIED"),
        ("unknown-rate", "OTIO_ROUTING_UNVERIFIED"),
        ("layout-conflict", "OTIO_ROUTING_UNVERIFIED"),
    ],
)
def test_export_ranges_and_routing_must_fit_selected_streams(
    import_project, defect, code
):
    def incompatible(paths):
        result = _probe(paths)
        info = result["sources"][0]
        video, audio = info["streams"]["video"][0], info["streams"]["audio"][0]
        if defect == "short-file":
            info["durationSeconds"] = 1
        elif defect == "short-picture":
            video["durationTicks"] = 24
        elif defect == "short-audio":
            audio["durationTicks"] = 48000
        elif defect == "video-rate":
            video["frameRate"] = video["averageFrameRate"] = "25/1"
        elif defect == "variable-video-rate":
            video["averageFrameRate"] = "23/1"
        elif defect == "missing-stream":
            info["streams"]["audio"] = []
        elif defect == "wrong-channels":
            audio["channels"] = 1
        elif defect == "unknown-rate":
            audio["sampleRate"] = 0
        else:
            audio["channelLayout"] = "mono"
        return result

    service = _service(import_project, incompatible)
    result = _blocked(
        service,
        _prepare(service, FIXTURE, mappings={REFERENCE: _mapping(import_project[2])}),
    )
    assert any(finding["code"] == code for finding in result["findings"])


def test_selected_source_changed_during_probe_cannot_enter_proposal(import_project):
    def changed(paths):
        result = _probe(paths)
        paths[0].write_bytes(b"source replaced while probing")
        return result

    service = _service(import_project, changed)
    result = _blocked(
        service,
        _prepare(service, FIXTURE, mappings={REFERENCE: _mapping(import_project[2])}),
    )
    assert any(
        finding["code"] == "OTIO_SOURCE_CHANGED" for finding in result["findings"]
    )


def test_explicit_selected_byte_lock_cannot_be_silently_rebound(import_project):
    original = import_project[2]
    fingerprint = file_fingerprint(original)
    mapping = _mapping(original)
    mapping["fingerprint"] = {
        "path": str(original),
        "sha256": fingerprint["sha256"],
        "sizeBytes": fingerprint["sizeBytes"],
    }
    service = _service(import_project, _probe)
    prepared = _prepare(service, FIXTURE, mappings={REFERENCE: mapping})
    original.write_bytes(b"different selected bytes")
    result = _blocked(service, prepared)
    assert any(
        finding["code"] == "OTIO_SOURCE_CHANGED" for finding in result["findings"]
    )


def test_declared_native_sample_rate_conflict_requires_mapping_repair(import_project):
    mapping = _mapping(import_project[2])
    mapping["audioSelection"]["sourceSampleRate"] = 44100
    service = _service(import_project, _probe)
    result = _blocked(
        service, _prepare(service, FIXTURE, mappings={REFERENCE: mapping})
    )
    assert any(
        finding["code"] == "OTIO_ROUTING_UNVERIFIED" for finding in result["findings"]
    )


def test_fingerprint_verifies_bytes_without_confirming_intended_replacement_identity(
    import_project,
):
    original = import_project[2]
    fingerprint = file_fingerprint(original)
    mapping = _mapping(original, confirmed=False)
    mapping["fingerprint"] = {
        "path": str(original),
        "sha256": fingerprint["sha256"],
        "sizeBytes": fingerprint["sizeBytes"],
    }
    service = _service(import_project, _probe)
    prepared = _prepare(service, FIXTURE, mappings={REFERENCE: mapping})
    before = deepcopy(prepared["session"]["options"]["mappings"])
    result = _blocked(service, prepared)
    assert any(
        finding["code"] == "OTIO_MEDIA_AMBIGUOUS" for finding in result["findings"]
    )
    assert service.load(prepared["importId"])["options"]["mappings"] == before
