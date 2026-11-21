"""Reproduced environment workarounds stay scoped to their proof iteration."""

import json

import pytest

from avo.learndown_export import build_timeline_learning_snapshot
from avo.timeline.iterations import IterationLedgerError, IterationLedgerService
from tests.test_iteration_ledger import HASH_A, HASH_B, HASH_C, _iteration, _workspace


def _workaround_iteration():
    reproduction = {"evidenceId": "decoded-proof", "sha256": HASH_C, "kind": "encoded"}
    request = _iteration()
    request["candidate"] = {"sha256": HASH_A, "sizeBytes": 123}
    request["findings"] = [reproduction]
    request["reworkItems"] = [
        {
            "origin": "implementation-defect",
            "summary": "A reproducible frame fault on one runtime",
            "impact": {
                "affectedArtifacts": ["camera-component"],
                "programWindows": [
                    {
                        "windowId": "camera-window",
                        "startFrame": 16,
                        "endFrameExclusive": 24,
                        "reason": "Reproduced frame fault",
                    },
                ],
            },
            "evidenceRefs": [reproduction],
            "workaround": {
                "candidateSha256": HASH_A,
                "environment": {
                    "engine": "native-camera",
                    "engineVersion": "2.1.0",
                    "runtime": "ffmpeg",
                    "runtimeVersion": "7.1.2-test-build",
                    "renderProfile": "review-hd",
                    "platform": "windows-x64",
                },
                "reproductionRef": reproduction,
                "proposal": "Try the alternate filter only in this reproduced case",
            },
        },
    ]
    return request


def test_workaround_survives_reload_without_becoming_provider_advice(tmp_path):
    workspace = _workspace(tmp_path)
    service = IterationLedgerService(workspace)
    request = _workaround_iteration()
    result = service.record_iteration(
        request, actor="agent", reason="Record reproduced defect"
    )
    ledger = IterationLedgerService(workspace).current()
    retained = ledger["reworkItems"][0]
    assert (
        retained["impact"]["programWindows"]
        == request["reworkItems"][0]["impact"]["programWindows"]
    )
    assert retained["workaround"] == request["reworkItems"][0]["workaround"]
    assert (
        result["iteration"]["candidate"]["sha256"]
        == retained["workaround"]["candidateSha256"]
    )
    learning = build_timeline_learning_snapshot(
        ledger=ledger, candidate_snapshot_hash=HASH_B, status="draft"
    )
    exported = json.dumps(learning)
    assert "7.1.2-test-build" not in exported
    assert "alternate filter" not in exported


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (
            lambda r, item: item.update(origin="creator-preference-refinement"),
            "technical defect",
        ),
        (lambda r, item: r["candidate"].update(sha256=HASH_B), "different candidate"),
        (lambda r, item: r.update(findings=[]), "same iteration findings"),
        (lambda r, item: item["impact"].update(programWindows=[]), "exact affected"),
    ],
)
def test_unbound_workaround_does_not_enter_the_ledger(tmp_path, change, message):
    service = IterationLedgerService(_workspace(tmp_path))
    request = _workaround_iteration()
    change(request, request["reworkItems"][0])
    with pytest.raises(IterationLedgerError, match=message):
        service.record_iteration(request, actor="agent", reason="Unbound report")
    assert service.current()["iterations"] == []
