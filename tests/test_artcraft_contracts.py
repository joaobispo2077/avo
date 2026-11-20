from copy import deepcopy

import pytest

from avo.timeline.contracts import ContractError, content_hash, validate_document
from tests.artcraft_fixtures import executable_observation, picture_output, request


def _schema(record):
    return f"avo.artcraft.schema.json#/$defs/{record}"


def _decision():
    return {
        "version": 1,
        "requestHash": content_hash(request()),
        "disposition": "eligible",
        "reason": "explicit-request",
        "provider": "neutral-channel",
        "componentId": "speaker-label",
        "scope": {"app": "anicraft", "operations": ["lower-third"]},
        "checkedCandidates": [],
        "missingInputs": [],
    }


def _job(workspace):
    return {
        "version": 1,
        "jobId": "speaker-label-preview",
        "request": request(),
        "decision": _sealed("decision", _decision()),
        "workspace": str(workspace),
        "roots": {"read": [str(workspace)], "write": [str(workspace)]},
        "observation": executable_observation(workspace / "anicraft-cli.exe"),
        "document": "speaker-label.ancproj",
        "inputs": [],
        "recipeHash": "a" * 64,
        "output": picture_output(),
        "budget": {"seconds": 60, "files": 128, "bytes": 4_000_000},
    }


def _package():
    return {
        "version": 1,
        "provider": "neutral-channel",
        "componentId": "speaker-label",
        "componentVersion": "1.0.0",
        "app": "anicraft",
        "sourceRoot": "/external/neutral-channel/native",
        "files": [{"path": "label.ancproj", "sizeBytes": 120, "sha256": "a" * 64}],
        "recipeHash": "b" * 64,
        "parameterSchemaHash": "c" * 64,
        "output": picture_output(),
        "sourceReviewRef": "source-review-1",
        "designReviewRef": "design-review-1",
        "rightsRef": "original-synthetic",
    }


def _receipt():
    return {
        "version": 1,
        "artifactState": "reference-only",
        "app": "anicraft",
        "requestHash": "a" * 64,
        "packageHash": "b" * 64,
        "parameterHash": "c" * 64,
        "recipeHash": "d" * 64,
        "environmentHash": "e" * 64,
        "inputs": [],
        "output": picture_output(),
        "observed": [],
    }


def _sealed(kind, fields):
    return {**fields, f"{kind}Hash": content_hash(fields)}


def test_closed_artcraft_envelopes_accept_only_their_declared_fields(tmp_path):
    for kind, record in {
        "request": request(),
        "decision": _sealed("decision", _decision()),
        "job": _sealed("job", _job(tmp_path)),
        "package": _sealed("package", _package()),
        "receipt": _sealed("receipt", _receipt()),
    }.items():
        assert validate_document(record, _schema(kind)) == record
        with pytest.raises(ContractError, match="Additional properties"):
            validate_document({**record, "trustedByCaller": True}, _schema(kind))


@pytest.mark.parametrize(
    "bad_id", ["../escape", "TwoWords", "name/part", "", "trailing-"]
)
def test_ids_are_stable_portable_values(bad_id):
    with pytest.raises(ContractError, match="requestId"):
        validate_document(request(requestId=bad_id), _schema("request"))


@pytest.mark.parametrize(
    "clock",
    [
        {"numerator": 24, "denominator": 0},
        {"numerator": 23.976, "denominator": 1},
        {"numerator": -24, "denominator": 1},
        {"numerator": True, "denominator": 1},
        {"numerator": float("inf"), "denominator": 1},
    ],
)
def test_output_clock_is_a_finite_positive_rational(clock):
    with pytest.raises(ContractError, match="frameRate"):
        validate_document(picture_output(frameRate=clock), _schema("output"))


def test_provider_only_and_video_contexts_are_disjoint():
    video = {
        "kind": "video",
        "project": "/external/example/avo.project.json",
        "videoId": "source-episode",
    }
    assert validate_document(request(context=video), _schema("request"))
    for context in (
        {"kind": "video", "videoId": "source-episode"},
        {**video, "kind": "provider-only"},
    ):
        with pytest.raises(ContractError, match="context"):
            validate_document(request(context=context), _schema("request"))


def test_record_hash_verifies_every_field_and_nested_decision(tmp_path):
    from avo.artcraft import validate_record

    job = _sealed("job", _job(tmp_path))
    assert validate_record("job", job) == job
    changed = deepcopy(job)
    changed["recipeHash"] = "b" * 64
    with pytest.raises(ContractError, match="jobHash"):
        validate_record("job", changed)
    changed = _job(tmp_path)
    changed["decision"]["componentId"] = "other-label"
    with pytest.raises(ContractError, match="decisionHash"):
        validate_record("job", _sealed("job", changed))


def test_artifact_state_cannot_be_upgraded_by_caller_flag():
    claimed = _receipt()
    claimed["artifactState"] = "admitted"
    with pytest.raises(ContractError, match="rebuildEvidenceHash"):
        validate_document(_sealed("receipt", claimed), _schema("receipt"))


def test_job_events_are_immutable_idempotent_and_compare_current_head(tmp_path):
    from avo.artcraft import ArtCraftJobStore

    store = ArtCraftJobStore(tmp_path)
    prepared = _job(tmp_path)
    job = store.create(prepared)
    assert store.create(prepared) == job
    assert store.load(job["jobId"]) == job
    with pytest.raises(ValueError, match="already exists"):
        store.create({**prepared, "recipeHash": "c" * 64})

    event = {"operationId": "prepare", "state": "prepared"}
    first = store.append(job["jobId"], expected_head="empty", event=event)
    assert store.append(job["jobId"], expected_head="empty", event=event) == first
    with pytest.raises(ValueError, match="operationId"):
        store.append(
            job["jobId"],
            expected_head=first["eventHash"],
            event={**event, "state": "ready"},
        )
    with pytest.raises(ValueError, match="expected head"):
        store.append(
            job["jobId"],
            expected_head="empty",
            event={"operationId": "verify", "state": "ready"},
        )
    ready = store.append(
        job["jobId"],
        expected_head=first["eventHash"],
        event={"operationId": "verify", "state": "ready"},
    )
    assert ready["predecessorHash"] == first["eventHash"]
    assert ready["jobHash"] == job["jobHash"]
    assert ArtCraftJobStore(tmp_path).head(job["jobId"]) == ready


def test_provider_job_refuses_outside_writes_before_creating_a_store(tmp_path):
    from avo.artcraft import ArtCraftJobStore

    working = tmp_path / "selected"
    working.mkdir()
    job = _job(working)
    job["roots"]["write"] = [str(tmp_path)]
    with pytest.raises(ValueError, match="write root"):
        ArtCraftJobStore(working).create(job)
    assert list(working.iterdir()) == []


def test_job_store_recovers_an_exact_event_after_index_write_failure(
    tmp_path, monkeypatch
):
    from avo import artcraft

    store = artcraft.ArtCraftJobStore(tmp_path)
    job_id = store.create(_job(tmp_path))["jobId"]
    event = {"operationId": "prepare", "state": "prepared"}

    def interrupted(*args):
        raise OSError("interrupted index write")

    with monkeypatch.context() as patch:
        patch.setattr(artcraft, "atomic_write_json", interrupted)
        with pytest.raises(OSError, match="interrupted"):
            store.append(job_id, expected_head="empty", event=event)
    assert store.head(job_id) is None
    reopened = artcraft.ArtCraftJobStore(tmp_path)
    after = reopened.append(job_id, expected_head="empty", event=event)
    assert store.head(job_id) == after
