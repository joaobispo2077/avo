import copy
import json

from tests.test_direction_cli import emitted
from tests.test_direction_service import (
    decide_request,
    prepare_candidate,
    provider_fixture,
)

from avo import cli


def test_native_provider_edit_is_a_new_proposal_and_exact_acceptance_stays_separate(
    tmp_path, monkeypatch, capsys
):
    root = provider_fixture(tmp_path)
    service, _, _, original = prepare_candidate(root)
    proposed = service.propose(original)
    accepted = service.decide(decide_request(proposed))
    previous = service.catalog()["profiles"]["editorial"]["acceptedRef"]
    monkeypatch.setattr("avo.direction_cli.providers_dir", lambda: root.parent)
    edit = decide_request(proposed, action="edit")
    edit["requestId"] = "native-edit"
    edit["expectedIndexHash"] = accepted["expectedIndexHash"]
    edit["edits"] = copy.deepcopy(original["candidate"])
    edit["edits"]["summary"] = "A carefully qualified new direction."
    request = tmp_path / "edit.json"
    request.write_text(json.dumps(edit), encoding="utf8")
    assert (
        cli.main(
            [
                "direction",
                "decide",
                "--provider",
                "neutral",
                "--request",
                str(request),
                "--json",
            ]
        )
        == 0
    )
    revised = emitted(capsys)
    assert revised["status"] == "needs-review"
    assert revised["refs"]["proposal"] != previous
    assert service.catalog()["profiles"]["editorial"]["acceptedRef"] == previous
    assert (
        cli.main(
            [
                "direction",
                "prepare",
                "--provider",
                "neutral",
                "--profile-id",
                "editorial",
                "--refresh-from",
                "editorial@r0001",
                "--json",
            ]
        )
        == 0
    )
    assert emitted(capsys)["refs"]["packet"]
