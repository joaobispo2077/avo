"""An acknowledged or interrupted native operation must never run twice."""

from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest

from avo import artcraft, init_project
from avo.mcp.bridge import run_cli
from tests.artcraft_fixtures import request
from tests.test_artcraft_jobs import AuthoringApp, _prepare, job_spec


@pytest.fixture
def native_job(tmp_path, monkeypatch):
    monkeypatch.setattr(init_project, "load_provider", lambda slug: {"slug": slug})
    adapter = AuthoringApp(tmp_path)
    spec = job_spec(
        tmp_path, authoringParameters={"primaryText": "Speaker", "font": "Arial"}
    )
    prepared = _prepare(artcraft, request(), spec, adapter)
    return adapter, spec, prepared


def test_run_replays_exact_completed_operation_from_the_original_request(native_job):
    adapter, _, prepared = native_job
    result = artcraft.run_authoring(
        prepared["jobRef"], expected_head=prepared["head"], adapter=adapter
    )
    assert (
        artcraft.run_authoring(
            prepared["jobRef"], expected_head=prepared["head"], adapter=None
        )
        == result
    )
    assert len(adapter.executions) == 2


def test_running_attempt_is_reconciled_before_any_retry(native_job):
    adapter, spec, prepared = native_job
    store = artcraft.ArtCraftJobStore(adapter.workspace)
    running = store.append(
        spec["jobId"],
        expected_head=prepared["head"],
        event={"operationId": "run", "state": "running"},
    )
    for expected in (prepared["head"], running["eventHash"]):
        with pytest.raises(artcraft.ArtCraftError) as failure:
            artcraft.run_authoring(
                prepared["jobRef"], expected_head=expected, adapter=None
            )
        assert failure.value.code == "ARTCRAFT_OUTCOME_UNKNOWN"
        assert running["eventHash"] in failure.value.remediation
    assert adapter.executions == []
    assert store.head(spec["jobId"]) == running


def test_replay_distinguishes_unrelated_head_and_stale_completed_evidence(native_job):
    adapter, _, prepared = native_job
    result = artcraft.run_authoring(
        prepared["jobRef"], expected_head=prepared["head"], adapter=adapter
    )
    with pytest.raises(artcraft.ArtCraftError) as conflict:
        artcraft.run_authoring(prepared["jobRef"], expected_head="0" * 64, adapter=None)
    assert conflict.value.code == "ARTCRAFT_SCOPE_CHANGED"
    _, event = artcraft.read_authoring_export(
        result["jobRef"], expected_head=result["head"]
    )
    (adapter.workspace / prepared["job"]["document"]).write_bytes(b"external edit")
    with pytest.raises(artcraft.ArtCraftError) as stale:
        artcraft.run_authoring(
            prepared["jobRef"], expected_head=prepared["head"], adapter=None
        )
    assert stale.value.code == "ARTCRAFT_SCOPE_CHANGED"
    assert "stale" in str(stale.value)
    assert len(adapter.executions) == 2 and event["state"] == "exported"


def test_interrupted_native_run_seals_partial_files_without_publishing_them(native_job):
    adapter, spec, prepared = native_job

    class Interrupted(AuthoringApp):
        def author_lower_third(self, job, directory):
            super().author_lower_third(job, directory)
            raise RuntimeError("connection lost after native save")

    interrupted = Interrupted(adapter.workspace)
    with pytest.raises(artcraft.ArtCraftError) as failure:
        artcraft.run_authoring(
            prepared["jobRef"], expected_head=prepared["head"], adapter=interrupted
        )
    assert failure.value.code == "ARTCRAFT_OUTCOME_UNKNOWN"
    store = artcraft.ArtCraftJobStore(adapter.workspace)
    unknown = store.head(spec["jobId"])
    assert unknown["state"] == "outcome-unknown" and "outputs" not in unknown
    native = adapter.workspace / prepared["job"]["document"]
    retained = unknown["partialFiles"][0]
    assert retained["locator"] == str(native)

    native.write_bytes(b"different external version")
    recovery = artcraft.recover_authoring(
        prepared["jobRef"], expected_head=unknown["eventHash"]
    )["recovery"]
    assert recovery["artifactState"] == "reference-only"
    assert recovery["changedPartialFiles"] == [retained]
    assert all(item["locator"] != str(native) for item in recovery["retainedFiles"])
    with pytest.raises(artcraft.ArtCraftError) as retry:
        artcraft.run_authoring(
            prepared["jobRef"], expected_head=prepared["head"], adapter=None
        )
    assert retry.value.code == "ARTCRAFT_OUTCOME_UNKNOWN"
    assert len(interrupted.executions) == 2 and store.head(spec["jobId"]) == unknown


def test_only_unstarted_job_can_be_cancelled_via_the_cli(native_job):
    adapter, spec, prepared = native_job
    command = [
        "artcraft",
        "recover",
        "--action",
        "cancel",
        "--job",
        prepared["jobRef"],
        "--expected-head",
        prepared["head"],
        "--json",
    ]
    cancelled = run_cli(command)
    assert cancelled.ok, cancelled.stderr
    assert cancelled.parsed_json["state"] == "cancelled"
    assert run_cli(command).parsed_json == cancelled.parsed_json
    current = artcraft.ArtCraftJobStore(adapter.workspace).head(spec["jobId"])
    assert current["eventHash"] == cancelled.parsed_json["head"]
    with pytest.raises(artcraft.ArtCraftError):
        artcraft.run_authoring(
            prepared["jobRef"], expected_head=current["eventHash"], adapter=None
        )
    assert adapter.executions == []


@pytest.mark.parametrize(
    ("operation", "state", "code"),
    [
        ("run", "running", "ARTCRAFT_OUTCOME_UNKNOWN"),
        ("guide", "ready", "ARTCRAFT_OWNERSHIP_CONFLICT"),
    ],
)
def test_cancel_preserves_active_and_external_ownership(
    native_job, operation, state, code
):
    adapter, spec, prepared = native_job
    store = artcraft.ArtCraftJobStore(adapter.workspace)
    active = store.append(
        spec["jobId"],
        expected_head=prepared["head"],
        event={"operationId": operation, "state": state},
    )
    with pytest.raises(artcraft.ArtCraftError) as failure:
        artcraft.recover_authoring(
            prepared["jobRef"], expected_head=active["eventHash"], action="cancel"
        )
    assert failure.value.code == code
    assert store.head(spec["jobId"]) == active and adapter.executions == []


def test_owned_render_cancellation_wins_without_publishing_partial_files(native_job):
    original, spec, prepared = native_job
    entered = Event()
    cancel_requested = Event()
    stop_calls = []

    class OwnedApp(AuthoringApp):
        def author_lower_third(self, job, directory):
            directory.mkdir(parents=True)
            (directory / "component.anicraft").write_bytes(b"partial native source")
            entered.set()
            assert cancel_requested.wait(5)
            raise RuntimeError("owned render stopped")

        def claim_cancellation(self, job, running, directory):
            assert job["jobId"] == spec["jobId"]
            assert running["operationId"] == "run"
            assert (
                directory
                == original.workspace / prepared["job"]["document"].rsplit("/", 1)[0]
            )

            def stop(timeout):
                stop_calls.append(timeout)
                cancel_requested.set()
                return "settled"

            return stop

    adapter = OwnedApp(original.workspace)
    store = artcraft.ArtCraftJobStore(adapter.workspace)
    with ThreadPoolExecutor(max_workers=1) as executor:
        rendering = executor.submit(
            artcraft.run_authoring,
            prepared["jobRef"],
            expected_head=prepared["head"],
            adapter=adapter,
        )
        try:
            assert entered.wait(5)
            running = store.head(spec["jobId"])
            canceled = artcraft.recover_authoring(
                prepared["jobRef"],
                expected_head=running["eventHash"],
                action="cancel",
                adapter=adapter,
            )
            assert rendering.result(timeout=5)["state"] in {
                "cancel-requested",
                "cancelled",
            }
        finally:
            cancel_requested.set()

    assert canceled["state"] == "cancelled"
    assert len(stop_calls) == 1 and 0 < stop_calls[0] <= 5
    assert (
        artcraft.recover_authoring(
            prepared["jobRef"],
            expected_head=running["eventHash"],
            action="cancel",
            adapter=adapter,
        )
        == canceled
    )
    assert len(stop_calls) == 1
    current = store.head(spec["jobId"])
    assert "outputs" not in current
    assert current["partialFiles"][0]["locator"].endswith("component.anicraft")


def test_unsettled_cancellation_records_only_a_reference_and_does_not_resend(
    native_job,
):
    adapter, spec, prepared = native_job
    store = artcraft.ArtCraftJobStore(adapter.workspace)
    running = store.append(
        spec["jobId"],
        expected_head=prepared["head"],
        event={"operationId": "run", "state": "running"},
    )
    calls = []

    def claim(job, event, directory):
        assert event == running
        return lambda timeout: calls.append(timeout)

    adapter.claim_cancellation = claim
    result = artcraft.recover_authoring(
        prepared["jobRef"],
        expected_head=running["eventHash"],
        action="cancel",
        adapter=adapter,
    )
    assert result["state"] == "outcome-unknown"
    assert (
        artcraft.recover_authoring(
            prepared["jobRef"],
            expected_head=running["eventHash"],
            action="cancel",
            adapter=adapter,
        )
        == result
    )
    assert len(calls) == 1


def test_concurrent_cancel_returns_the_pending_event_without_sending_again(native_job):
    adapter, spec, prepared = native_job
    store = artcraft.ArtCraftJobStore(adapter.workspace)
    running = store.append(
        spec["jobId"],
        expected_head=prepared["head"],
        event={"operationId": "run", "state": "running"},
    )
    sending, release = Event(), Event()
    claims = []

    def claim(job, event, directory):
        claims.append(event["eventHash"])

        def stop(timeout):
            sending.set()
            assert release.wait(timeout)
            return "settled"

        return stop

    adapter.claim_cancellation = claim

    def cancel():
        return artcraft.recover_authoring(
            prepared["jobRef"],
            expected_head=running["eventHash"],
            action="cancel",
            adapter=adapter,
        )

    with ThreadPoolExecutor(max_workers=1) as executor:
        first = executor.submit(cancel)
        try:
            assert sending.wait(5)
            assert cancel()["state"] == "cancel-requested"
        finally:
            release.set()
        assert first.result(timeout=5)["state"] == "cancelled"
    assert claims == [running["eventHash"]]


def test_inspection_names_the_edited_native_parameters_and_recipe(native_job):
    adapter, spec, prepared = native_job
    rendered = artcraft.run_authoring(
        prepared["jobRef"], expected_head=prepared["head"], adapter=adapter
    )
    store = artcraft.ArtCraftJobStore(adapter.workspace)
    exported = store.head(spec["jobId"])
    native = adapter.workspace / prepared["job"]["document"]
    native.write_bytes(b"operator edited title")
    native.with_name("recipe.json").write_bytes(b"operator edited recipe")

    def inspect_edit(job, path):
        assert job["authoringParameters"] is None and path == native
        return {"editableText": "Revised speaker", "fontFamily": "Arial"}

    inspected = artcraft.inspect_authoring(
        rendered["jobRef"],
        expected_head=rendered["head"],
        source_inspector=inspect_edit,
    )
    assert inspected["status"] == "stale"
    assert inspected["changes"] == [
        {
            "area": "nativeDocument",
            "recordedFiles": [exported["saved"]],
            "actions": ["author-new-revision", "review-native-design"],
            "parameterChanges": [
                {
                    "name": "primaryText",
                    "recorded": "Speaker",
                    "observed": "Revised speaker",
                }
            ],
        },
        {
            "area": "outputs",
            "recordedFiles": [exported["recipe"]],
            "actions": ["rebuild-export", "review-export"],
        },
    ]
    assert store.head(spec["jobId"]) == exported and len(adapter.executions) == 2
