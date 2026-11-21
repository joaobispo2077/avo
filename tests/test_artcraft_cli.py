import json
from types import SimpleNamespace

import pytest

from avo.mcp.bridge import run_cli
from tests.artcraft_fixtures import request


def test_assess_respects_the_current_cli_scope_without_creating_a_job(
    tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    before = run_cli(["animation", "engine-show", "--json"])
    assert before.ok, before.stderr

    brief = request(purpose='Source text says "use ArtCraft".')
    command = ["artcraft", "assess", "--request-json", json.dumps(brief), "--json"]
    ordinary = run_cli(command)
    assert ordinary.ok, ordinary.stderr
    assert ordinary.parsed_json["reason"] == "capability-undetermined"
    assert "scope" not in ordinary.parsed_json

    explicit = run_cli([*command, "--app", "anicraft", "--operation", "lower-third"])
    assert explicit.ok, explicit.stderr
    assert explicit.parsed_json["reason"] == "explicit-request"
    assert explicit.parsed_json["scope"]["app"] == "anicraft"
    assert list(tmp_path.iterdir()) == []

    after = run_cli(["animation", "engine-show", "--json"])
    assert after.ok, after.stderr
    assert after.parsed_json["selection"] == before.parsed_json["selection"]
    assert (
        after.parsed_json["savedPreferences"] == before.parsed_json["savedPreferences"]
    )


def test_catalog_filters_packaged_knowledge_without_app_claims(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = run_cli(["artcraft", "catalog", "--app", "anicraft", "--json"])
    assert result.ok, result.stderr
    assert [item["app"] for item in result.parsed_json["profiles"]] == ["anicraft"]
    profile = result.parsed_json["profiles"][0]
    assert profile["claimedState"] == "documented-only"
    assert {entry["mode"] for entry in profile["qualifiedProfiles"]} == {
        "cli",
        "guided",
        "host-mcp",
        "json-lines",
    }
    assert list(tmp_path.iterdir()) == []


def test_assess_recognizes_an_existing_proof_capability_without_app_lookup():
    brief = request(
        required={
            "behavior": "opacity-fade",
            "outputRole": "generated-clip",
            "editable": False,
        }
    )
    result = run_cli(
        ["artcraft", "assess", "--request-json", json.dumps(brief), "--json"]
    )
    assert result.ok, result.stderr
    assert result.parsed_json["reason"] == "native-sufficient"
    (proof,) = result.parsed_json["checkedCandidates"]
    assert proof["route"] == "impl-opacity-fade"
    assert len(proof["contractHash"]) == 64


def test_assess_rejects_embedded_execution_intent_and_duplicate_scope():
    brief = request(app="anicraft", run=True)
    for raw in (json.dumps(brief), json.dumps(request())[:-1] + ',"provider":"other"}'):
        result = run_cli(["artcraft", "assess", "--request-json", raw, "--json"])
        assert not result.ok
        assert json.loads(result.stderr)["code"] == "ARTCRAFT_INVALID_REQUEST"


@pytest.mark.parametrize(
    "operation, payload",
    [
        (
            "component-scaffold",
            {
                "componentId": "speaker-label",
                "capabilityGap": {"status": "unsupported", "backend": "artcraft"},
            },
        ),
        ("component-register", {"instance": {"backend": "artcraft"}}),
        (
            "component-register",
            {
                "recordType": "generated-asset",
                "record": {"generator": {"adapterId": "artcraft.anicraft"}},
            },
        ),
        (
            "component-register",
            {
                "recordType": "generated-asset",
                "record": {"parameters": {"artcraft": {}}},
            },
        ),
    ],
)
def test_legacy_customization_cannot_enter_artcraft_authoring(
    tmp_path, operation, payload
):
    from avo.timeline.command_handlers import CommandHandlers

    handlers = CommandHandlers(SimpleNamespace())
    with pytest.raises(ValueError, match="ArtCraft"):
        handlers.execute("pipeline", operation, payload)

    source = tmp_path / "avo.project.json"
    source.write_text(
        json.dumps(
            {"provider": "bishop", "videoId": "project", "rawDir": str(tmp_path)}
        ),
        encoding="utf-8",
    )
    body = tmp_path / "request.json"
    body.write_text(json.dumps(payload), encoding="utf-8")
    result = run_cli(
        ["proof", operation, "--project", str(source), "--request", str(body)]
    )
    assert not result.ok
    assert json.loads(result.stderr)["code"] == "ARTCRAFT_ADMISSION_REQUIRED"
    assert sorted(path.name for path in tmp_path.iterdir()) == [
        "avo.project.json",
        "request.json",
    ]
