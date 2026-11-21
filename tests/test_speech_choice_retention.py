"""Reconstruction retains superseded and deferred speech-evidence history."""

from avo.timeline.reconstruction import _required_files
from tests.test_speech_recovery import recovery
from tests.test_speech_recovery_choices import decision


def test_reconstruction_keeps_both_choices_and_their_original_alternatives(tmp_path):
    cutting, _, service, _, request = recovery(tmp_path)
    shown = service.recover(request)
    deferred = service.decide(decision(service, shown, "defer"))
    selected = service.decide(
        decision(
            service,
            shown,
            "original",
            operation_id="resolved",
            previous=deferred["decisionRef"],
        )
    )
    retained = set(
        _required_files(cutting.workspace.raw_dir, [], workspace=cutting.workspace)
    )
    references = [
        request["analysisRef"],
        shown["requestRef"],
        shown["results"][0]["resultRef"],
        deferred["decisionRef"],
        selected["decisionRef"],
    ]
    assert {service.store.directory / ref["locator"] for ref in references} <= retained
