"""Selected measured windows improve coverage without certifying other source time."""

from copy import deepcopy
from fractions import Fraction
from pathlib import Path

import pytest

from avo.timeline.cutting_contracts import make_document
from avo.timeline.preparation import inspect_speech_coverage
from avo.timeline.preparation_facts import merge_selected_measurements
from tests.test_speech_coverage import evidence as coverage_evidence
from tests.test_speech_recovery import interval, recovery
from tests.test_speech_recovery_choices import decision, evidence


def measured_recovery(tmp_path):
    cutting, cmap, service, port, request = recovery(tmp_path)
    original = deepcopy(service._analysis(request["analysisRef"]))
    original.update(
        status="blocked",
        words=[],
        vad=[],
        tools=[],
        coverage={"observed": False},
        alignment={"status": "missing", "characters": []},
        pauseCandidates=[
            {
                "sourceRange": interval(24000, 36000),
                "evidence": {"acousticObserved": True},
            }
        ],
    )
    request["analysisRef"] = cutting.store.save_document(
        make_document("source-analysis", original)
    )
    delegate = port.recover

    def recover_measured(source, **arguments):
        result = delegate(source, **arguments)
        analysis = result["analysis"]
        word = analysis["words"][0]
        word.update(alignmentStatus="aligned", eligibleEdge=True)
        analysis.update(
            status="pass",
            coverage={"observed": True, "start": word["start"], "end": word["end"]},
            vad=[{"start": word["start"], "end": word["end"]}],
            alignment={"status": "pass", "characters": []},
        )
        return result

    port.recover = recover_measured
    return cutting, cmap, service, port, request


def test_selected_aligned_window_carries_its_measurement_without_inventing_the_rest(
    tmp_path,
):
    cutting, cmap, service, _, request = measured_recovery(tmp_path)
    shown = service.recover(request)
    selected = service.decide(decision(service, shown, "recovered"))
    observed = evidence(service, request)
    analysis = observed["analysis"]
    assert analysis["status"] == "pass"
    assert analysis["alignment"]["status"] == "pass"
    assert analysis["coverage"] == {
        "observed": True,
        "intervals": [{"start": 0, "end": 0.25}],
    }
    assert analysis["pauseCandidates"] == []
    coverage = inspect_speech_coverage(
        analysis,
        source_ref=analysis["sourceRef"],
        source_range=analysis["preprocessing"]["sourceRange"],
        routing=analysis["routing"],
        sync_ref=analysis["syncRef"],
    )
    assert [
        (
            row["kind"],
            row["sourceRange"]["startTicks"],
            row["sourceRange"]["endTicksExclusive"],
        )
        for row in coverage["observations"]
    ] == [("unmeasured", 12000, 48000)]
    assert selected["wordAnchorsEligible"] is True
    assert cutting.workspace.store("cmap").head_hash() == cmap["contentHash"]


def test_two_selected_windows_keep_the_unmeasured_middle_and_original_history(tmp_path):
    cutting, _, service, port, request = measured_recovery(tmp_path)
    request["ranges"].append(interval(36000, 48000))
    original = cutting.store.load_document(request["analysisRef"])
    shown = service.recover(request)
    for index in range(2):
        choose = decision(service, shown, "recovered", operation_id=f"choose-{index}")
        choose.update(
            intervalIndex=index, resultRef=shown["results"][index]["resultRef"]
        )
        service.decide(choose)
    analysis = evidence(service, request)["analysis"]
    assert analysis["coverage"] == {
        "observed": True,
        "intervals": [{"start": 0, "end": 0.25}, {"start": 0.75, "end": 1}],
    }
    assert analysis["vad"] == [{"start": 0, "end": 0.25}, {"start": 0.75, "end": 1}]
    coverage = inspect_speech_coverage(
        analysis,
        source_ref=analysis["sourceRef"],
        source_range=analysis["preprocessing"]["sourceRange"],
        routing=analysis["routing"],
        sync_ref=analysis["syncRef"],
    )
    assert coverage["protectedRanges"] == [interval(12000, 36000)]
    assert cutting.store.load_document(request["analysisRef"]) == original
    assert len(port.calls) == 2


@pytest.mark.parametrize("invalid", ["tools", "observed", "status", "activity"])
def test_invalid_recovery_measurement_cannot_borrow_original_provenance(invalid):
    analysis, _ = coverage_evidence()
    incoming = deepcopy(analysis)
    if invalid == "tools":
        incoming["tools"] = []
    elif invalid == "observed":
        incoming["coverage"]["observed"] = False
    elif invalid == "status":
        incoming["status"] = "unknown"
    else:
        incoming["vad"] = [{"start": 0, "end": 2}]
    before = deepcopy(analysis)
    assert (
        merge_selected_measurements(analysis, incoming, (Fraction(1), Fraction(6)))
        is False
    )
    assert analysis == before


def test_old_unproven_measurements_and_pause_certifications_do_not_become_current():
    analysis, request = coverage_evidence()
    incoming = deepcopy(analysis)
    incoming["preprocessing"]["sourceRange"]["endTicksExclusive"] = 2000
    incoming["coverage"] = {"observed": True, "start": 1, "end": 2}
    incoming["vad"] = [incoming["vad"][0]]
    incoming["words"] = [incoming["words"][0]]
    analysis["tools"] = []
    analysis["pauseCandidates"] = [
        {
            "sourceRange": {
                **request["source_range"],
                "startTicks": 3000,
                "endTicksExclusive": 4000,
            }
        }
    ]
    assert (
        merge_selected_measurements(analysis, incoming, (Fraction(1), Fraction(2)))
        is True
    )
    assert analysis["coverage"] == {
        "observed": True,
        "intervals": [{"start": 1, "end": 2}],
    }
    assert analysis["pauseCandidates"] == []


def test_changed_measurement_composer_stales_a_cutting_proposal(tmp_path, monkeypatch):
    import avo.timeline.cutting_service as cutting_module

    cutting, _, _, _, _ = recovery(tmp_path)
    proposal = cutting.analyze()["proposalRef"]
    original = cutting_module.file_fingerprint

    def changed(path):
        fingerprint = original(path)
        if Path(path).name == "preparation_facts.py":
            fingerprint = {**fingerprint, "sha256": "f" * 64}
        return fingerprint

    monkeypatch.setattr(cutting_module, "file_fingerprint", changed)
    with pytest.raises(cutting_module.CuttingServiceError, match="stale"):
        cutting.status(proposal)
