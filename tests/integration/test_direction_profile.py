"""Provider-only native journey; historical materials remain read-only."""

import json

from tests.test_direction_cli import configured_provider, emitted
from tests.test_direction_contracts import DIMENSIONS, statement

from avo import cli
from avo.direction.rules import visible_word_count
from avo.direction.store import DirectionStore


def test_provider_cli_prepare_review_and_exact_acceptance(
    tmp_path, monkeypatch, capsys
):
    root = configured_provider(tmp_path, monkeypatch)
    protected = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
    assert (
        cli.main(
            [
                "direction",
                "prepare",
                "--provider",
                "neutral",
                "--profile-id",
                "editorial",
                "--json",
            ]
        )
        == 0
    )
    prepared = emitted(capsys)
    store = DirectionStore(root / "direction")
    packet = store.load_document(prepared["refs"]["packet"]["path"])
    record = packet["evidenceRecords"][0]
    item = statement()
    item["evidenceIds"] = [record["evidenceId"]]
    item["independentProjectIds"] = [record["sourceProjectId"]]
    request = {
        "requestId": "native-proposal",
        "packetRef": prepared["refs"]["packet"],
        "expectedIndexHash": prepared["expectedIndexHash"],
        "candidate": {
            "summary": "Natural speech with selective explanatory support.",
            "statements": [item],
            "variants": [],
            "avoidances": [],
            "dimensionCoverage": {k: "unknown" for k in DIMENSIONS},
            "changeSummary": "A tentative first direction.",
        },
        "synthesisProvenance": {
            "executionKind": "driving-agent",
            "agentId": "neutral",
            "modelId": None,
            "packetHash": packet["documentHash"],
            "promptHash": None,
        },
    }
    request_path = tmp_path / "propose.json"
    request_path.write_text(json.dumps(request))
    assert (
        cli.main(
            [
                "direction",
                "propose",
                "--provider",
                "neutral",
                "--request",
                str(request_path),
                "--json",
            ]
        )
        == 0
    )
    proposed = emitted(capsys)
    assert store.load_index()["profiles"]["editorial"]["acceptedRef"] is None
    decision = {
        "requestId": "native-decision",
        "targetRef": proposed["refs"]["proposal"],
        "expectedIndexHash": proposed["expectedIndexHash"],
        "action": "accept",
        "scope": "provider",
        "actor": {"type": "human", "id": "neutral-fixture-creator"},
        "reason": "Fixture review",
        "humanInstruction": {
            "source": "test-fixture:explicit-decision",
            "text": "Accept this exact proposed profile.",
        },
    }
    decision_path = tmp_path / "decide.json"
    decision_path.write_text(json.dumps(decision))
    assert (
        cli.main(
            [
                "direction",
                "decide",
                "--provider",
                "neutral",
                "--request",
                str(decision_path),
                "--json",
            ]
        )
        == 0
    )
    assert emitted(capsys)["status"] == "accepted"
    assert (
        cli.main(
            [
                "direction",
                "show",
                "--provider",
                "neutral",
                "--ref",
                "editorial@r0001",
                "--json",
            ]
        )
        == 0
    )
    shown = emitted(capsys)
    assert shown["reviewState"] == "accepted"
    assert visible_word_count(shown["profile"]["summary"]) <= 500
    assert all(p.read_bytes() == value for p, value in protected.items())
