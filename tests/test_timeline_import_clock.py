"""Import clock admission needs complete timing evidence, not rate headers alone."""

from copy import deepcopy

import pytest

from avo.adapters.media.otio_reader import read_otio
from avo.timeline.import_service import TimelineImportService
from tests.test_timeline_import_service import _probe, _trial
from tests.test_timeline_import_service import import_project as _project


@pytest.fixture(name="import_project")
def project_fixture(tmp_path):
    return _project.__wrapped__(tmp_path)


@pytest.mark.parametrize(
    "defect", ["missing", "wrong-bytes", "wrong-stream", "wrong-rate"]
)
def test_rate_headers_alone_cannot_authorize_clock(import_project, defect):
    project, provider, original = import_project

    def inventory(paths):
        result = _probe(paths)
        stream = result["sources"][0]["streams"]["video"][0]
        evidence = stream["clockVerification"]
        if defect == "missing":
            del stream["clockVerification"]
        elif defect == "wrong-bytes":
            evidence["sourceSha256"] = "0" * 64
        elif defect == "wrong-stream":
            evidence["streamIndex"] = 1
        else:
            evidence["frameRate"] = {"num": 25, "den": 1}
        return result

    service = TimelineImportService(
        project, provider_root=provider, reader=read_otio, probe=inventory
    )
    result = service.validate(_trial(service, original)["importId"])
    assert result["status"] == "blocked"
    assert any(row["code"] == "OTIO_RATE_UNVERIFIED" for row in result["findings"])
    assert not service.workspace.artifact_path("cmap").exists()


def test_explicit_clock_port_overrides_inventory_claim_and_persists_evidence(
    import_project,
):
    project, provider, original = import_project
    calls = []

    def verify(path, stream_index, frame_rate, **kwargs):
        calls.append((path, stream_index, frame_rate, kwargs))
        return deepcopy(
            _probe([path])["sources"][0]["streams"]["video"][0]["clockVerification"]
        )

    service = TimelineImportService(
        project,
        provider_root=provider,
        reader=read_otio,
        probe=_probe,
        clock_probe=verify,
    )
    result = service.validate(_trial(service, original)["importId"])
    assert result["status"] == "awaiting-sync"
    assert len(calls) == 1
    source = result["proposal"]["snapshot"]["sources"][0]
    assert (
        source["streamMetadata"]["videoClock"]["sourceSha256"]
        == source["fingerprint"]["sha256"]
    )
    assert calls[0][3]["expected_sha256"] == source["fingerprint"]["sha256"]


def test_clock_port_failure_blocks_even_when_inventory_claims_success(import_project):
    project, provider, original = import_project

    def irregular(*args, **kwargs):
        raise ValueError("Irregular video packet PTS")

    service = TimelineImportService(
        project,
        provider_root=provider,
        reader=read_otio,
        probe=_probe,
        clock_probe=irregular,
    )
    result = service.validate(_trial(service, original)["importId"])
    assert result["status"] == "blocked"
    assert any("Irregular" in row["message"] for row in result["findings"])
