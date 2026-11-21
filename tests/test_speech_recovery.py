"""Selected recovery uses declared ports here; these are not real ASR/listening claims."""

from copy import deepcopy

import pytest

from avo.editing_craft import resolve_editing_craft_selection
from avo.timeline.preparation_recovery import (
    PreparationError,
    PreparationService,
    validate_recovery_scope,
)
from tests.test_cutting_service import fixture_service
from tests.test_speech_coverage_service import GapAnalysis


def selection(**changes):
    return resolve_editing_craft_selection(
        invocation={"speechRecovery": {"enabled": True, **changes}}
    )


def interval(start, end):
    return {
        "sourceId": "dialogue",
        "startTicks": start,
        "endTicksExclusive": end,
        "timebase": {"num": 1, "den": 48000},
    }


def test_zero_duration_asr_tokens_remain_reviewable_but_cannot_be_aligned_anchors():
    from fractions import Fraction

    from avo.timeline.preparation_recovery import _validate_word_times

    token = {
        "text": "a",
        "start": 0.55,
        "end": 0.55,
        "alignmentStatus": "unsupported",
        "eligibleEdge": False,
    }
    _validate_word_times([token], Fraction(0), Fraction(1))
    with pytest.raises(PreparationError, match="word timing"):
        _validate_word_times(
            [{**token, "alignmentStatus": "aligned", "eligibleEdge": True}],
            Fraction(0),
            Fraction(1),
        )


class RecoveryPort:
    def __init__(self):
        self.calls = []
        self.bindings = {
            "transcription": {
                "status": "observed",
                "model": "declared-fixture",
                "files": {"model.bin": "a" * 64},
                "runtime": {"device": "cpu"},
            },
            "alignment": {"status": "unavailable", "reason": "declared test boundary"},
        }

    def dependency_bindings(self):
        return deepcopy(self.bindings)

    def recover(self, source, **request):
        self.calls.append(deepcopy(request))
        chosen = request["source_range"]
        base = chosen["timebase"]["num"] / chosen["timebase"]["den"]
        start, end = chosen["startTicks"] * base, chosen["endTicksExclusive"] * base
        words = [
            {
                "text": "recovered",
                "start": start,
                "end": end,
                "alignmentStatus": "unsupported",
            }
        ]
        return {
            "transcript": {
                "text": "recovered",
                "words": deepcopy(words),
                "sourceStart": start,
            },
            "analysis": {
                "sourceRef": {
                    "locator": str(source),
                    "sha256": request["fingerprint"]["sha256"],
                },
                "routing": deepcopy(request["selection"]),
                "syncRef": deepcopy(request["sync_ref"]),
                "preprocessing": {"sourceRange": deepcopy(chosen)},
                "language": request["language"],
                "status": "unknown",
                "words": words,
                "alignment": {"status": "missing", "characters": []},
                "tools": [self.dependency_bindings()],
                "coverage": {"observed": False},
                "uncertainty": ["No qualified word alignment"],
                "pauseCandidates": [],
            },
        }


def recovery(tmp_path):
    cutting, cmap = fixture_service(tmp_path, analysis_port=GapAnalysis())
    observed = cutting.analyze()
    reference = observed["coverage"]["speech"][0]["analysisRef"]
    port = RecoveryPort()
    service = PreparationService(cutting.workspace, recovery_port=port)
    request = {
        "contractVersion": "1.0.0",
        "operation": "recover",
        "operationId": "recover-one",
        "actor": "creator",
        "reason": "Review this selected source interval",
        "analysisRef": reference,
        "ranges": [interval(0, 12000)],
        "selection": selection(),
        "language": "en",
    }
    return cutting, cmap, service, port, request


def test_default_scope_limits_reject_work_instead_of_silently_clipping_it():
    whole = interval(0, 48000 * 130)
    with pytest.raises(PreparationError, match="interval budget"):
        validate_recovery_scope([interval(0, 48000 * 31)], whole, selection())
    ranges = [
        interval(48000 * start, 48000 * (start + 30)) for start in (0, 30, 60, 90)
    ]
    ranges.append(interval(48000 * 120, 48000 * 121))
    before = deepcopy(ranges)
    with pytest.raises(PreparationError, match="total budget"):
        validate_recovery_scope(ranges, whole, selection())
    assert ranges == before
    assert (
        validate_recovery_scope(ranges, whole, selection(maxTotalSeconds=121)) == ranges
    )


def test_overlapping_selected_intervals_cannot_duplicate_an_attempt():
    with pytest.raises(PreparationError, match="overlap"):
        validate_recovery_scope(
            [interval(0, 10000), interval(9000, 12000)], interval(0, 48000), selection()
        )


def test_recovery_preserves_both_alternatives_and_uncertain_word_timing_without_a_cut(
    tmp_path,
):
    cutting, cmap, service, port, request = recovery(tmp_path)
    original = cutting.store.load_document(request["analysisRef"])
    shown = service.recover(request)
    assert shown["status"] == "pending-review" and shown["approval"] == "not-granted"
    assert len(port.calls) == 1
    (row,) = shown["results"]
    saved = cutting.store.load_document(row["resultRef"])["payload"]
    assert saved["originalAnalysisRef"] == request["analysisRef"]
    assert saved["recovered"]["transcript"]["text"] == "recovered"
    assert saved["wordAnchorsEligible"] is False
    assert saved["selection"] == "pending"
    assert cutting.store.load_document(request["analysisRef"]) == original
    assert cutting.workspace.store("cmap").head_hash() == cmap["contentHash"]


def test_exact_replay_reuses_evidence_and_new_operation_names_do_not_reset_budget(
    tmp_path,
):
    cutting, _, service, port, request = recovery(tmp_path)
    first = service.recover(request)
    again = PreparationService(cutting.workspace, recovery_port=port).recover(request)
    assert len(port.calls) == 1
    assert again["results"][0]["resultRef"] == first["results"][0]["resultRef"]
    renamed = {**request, "operationId": "another-name"}
    with pytest.raises(PreparationError, match="attempt budget"):
        service.recover(renamed)
    assert len(port.calls) == 1


def test_an_explicit_larger_attempt_budget_does_not_rewrite_prior_evidence(tmp_path):
    cutting, _, service, port, request = recovery(tmp_path)
    first = service.recover(request)
    later = {
        **request,
        "operationId": "explicit-second",
        "selection": selection(maxAttemptsPerInterval=2),
    }
    second = service.recover(later)
    assert len(port.calls) == 2
    assert first["results"][0]["resultRef"] != second["results"][0]["resultRef"]
    assert (
        cutting.store.load_document(first["results"][0]["resultRef"])["payload"][
            "selection"
        ]
        == "pending"
    )


def test_interruption_consumes_the_started_attempt_and_cannot_trigger_automatic_retranscription(
    tmp_path,
):
    cutting, _, service, port, request = recovery(tmp_path)

    def interrupted(*_args, **_kwargs):
        raise KeyboardInterrupt("simulate interruption after the durable claim")

    port.recover = interrupted
    with pytest.raises(KeyboardInterrupt):
        service.recover(request)
    forbidden = RecoveryPort()
    forbidden.recover = lambda *_args, **_kwargs: pytest.fail(
        "interrupted attempt was repeated"
    )
    resumed = PreparationService(cutting.workspace, recovery_port=forbidden).recover(
        request
    )
    assert resumed["status"] == "interrupted"
    assert resumed["results"][0]["status"] == "interrupted"


@pytest.mark.parametrize("changed", ["source", "model"])
def test_changed_source_or_model_stales_the_saved_result_without_model_execution(
    tmp_path, changed
):
    cutting, _, service, port, request = recovery(tmp_path)
    first = service.recover(request)
    if changed == "source":
        source = cutting.workspace.store("cmap").load()["revisions"][-1]["snapshot"][
            "sources"
        ][0]
        from pathlib import Path

        with Path(source["locator"]).open("ab") as handle:
            handle.write(b"changed source")
    else:
        port.bindings["transcription"]["files"]["model.bin"] = "f" * 64
    stale = service.recover(request)
    assert stale["status"] == "stale"
    assert stale["requestRef"] == first["requestRef"]
    assert len(port.calls) == 1


def test_disabled_recovery_never_calls_the_port_or_initializes_the_attempt_ledger(
    tmp_path,
):
    cutting, _, service, port, request = recovery(tmp_path)
    request["selection"] = resolve_editing_craft_selection()
    with pytest.raises(PreparationError, match="explicitly enabled"):
        service.recover(request)
    assert port.calls == []
    assert not cutting.store.ledger.path.exists()


@pytest.mark.parametrize("field", ["word-offset", "transcript-offset", "routing"])
def test_recovered_evidence_cannot_escape_its_frozen_source_scope(tmp_path, field):
    cutting, _, service, port, request = recovery(tmp_path)
    delegate = port.recover

    def invalid(source, **kwargs):
        result = delegate(source, **kwargs)
        if field == "word-offset":
            result["analysis"]["words"][0].update(start=40, end=41)
        elif field == "transcript-offset":
            result["transcript"]["sourceStart"] = 40
        else:
            result["analysis"]["routing"]["streamIndex"] = 99
        return result

    port.recover = invalid
    shown = service.recover(request)
    assert shown["status"] == "failed"
    result = cutting.store.load_document(shown["results"][0]["resultRef"])["payload"]
    assert result["recovered"] is None
    assert result["wordAnchorsEligible"] is False


def test_context_change_during_inference_retains_only_stale_ineligible_evidence(
    tmp_path,
):
    cutting, _, service, port, request = recovery(tmp_path)
    delegate = port.recover

    def changed(source, **kwargs):
        result = delegate(source, **kwargs)
        port.bindings["transcription"]["files"]["model.bin"] = "b" * 64
        result["analysis"]["alignment"]["status"] = "pass"
        result["analysis"]["words"][0].update(
            alignmentStatus="aligned", eligibleEdge=True
        )
        return result

    port.recover = changed
    shown = service.recover(request)
    assert shown["status"] == "stale"
    saved = cutting.store.load_document(shown["results"][0]["resultRef"])["payload"]
    assert saved["wordAnchorsEligible"] is False


def test_terminal_result_survives_interrupted_ledger_publication(tmp_path, monkeypatch):
    cutting, _, service, port, request = recovery(tmp_path)
    append = service.store._append_preparation

    def interrupted(snapshot, actor, reason):
        if snapshot.get("preparationResults"):
            raise OSError("simulated publication interruption")
        return append(snapshot, actor, reason)

    monkeypatch.setattr(service.store, "_append_preparation", interrupted)
    with pytest.raises(PreparationError, match="publication interruption"):
        service.recover(request)
    resumed = PreparationService(cutting.workspace, recovery_port=port).recover(request)
    assert resumed["status"] == "pending-review"
    assert resumed["results"][0]["reused"] is True
    assert len(port.calls) == 1
    assert cutting.store._snapshot()["preparationResults"] == [
        resumed["results"][0]["resultRef"]
    ]


def test_competing_identical_requests_cannot_run_the_same_interval_twice(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    cutting, _, service, port, request = recovery(tmp_path)
    entered, release = Event(), Event()
    delegate = port.recover

    def slow(source, **kwargs):
        entered.set()
        assert release.wait(20)
        return delegate(source, **kwargs)

    port.recover = slow
    with ThreadPoolExecutor(max_workers=1) as executor:
        first = executor.submit(service.recover, request)
        try:
            assert entered.wait(20)
            second = PreparationService(cutting.workspace, recovery_port=port).recover(
                request
            )
            assert second["status"] == "running"
        finally:
            release.set()
        assert first.result(timeout=20)["status"] == "pending-review"
    assert len(port.calls) == 1
