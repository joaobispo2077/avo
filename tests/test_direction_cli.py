"""Native provider commands delegate to the same exact services."""

import copy
import json

from avo import cli
from tests.test_direction_service import prepare_candidate, provider_fixture


def configured_provider(tmp_path, monkeypatch):
    root = provider_fixture(tmp_path)
    import avo.direction_cli as surface

    monkeypatch.setattr(surface, "providers_dir", lambda: root.parent)
    return root


def emitted(capsys):
    captured = capsys.readouterr()
    return json.loads(captured.out or captured.err)


def test_catalog_lists_real_defaults_without_writing_provider_state(
    tmp_path, monkeypatch, capsys
):
    root = configured_provider(tmp_path, monkeypatch)
    assert cli.main(["direction", "catalog", "--provider", "neutral", "--json"]) == 0
    result = emitted(capsys)
    assert len(result["builtins"]) == 4
    assert not (root / "direction").exists()


def test_prepare_is_metadata_only_and_has_exact_next_request_state(
    tmp_path, monkeypatch, capsys
):
    root = configured_provider(tmp_path, monkeypatch)
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
    result = emitted(capsys)
    assert result["status"] == "needs-authoring"
    assert result["refs"]["packet"]["documentHash"]
    assert result["expectedIndexHash"] == "absent"
    assert not (root / "direction/index.json").exists()


def test_propose_and_show_use_exact_service_content(tmp_path, monkeypatch, capsys):
    root = configured_provider(tmp_path, monkeypatch)
    _, _, _, request = prepare_candidate(root)
    path = tmp_path / "request.json"
    path.write_text(json.dumps(request))
    assert (
        cli.main(
            [
                "direction",
                "propose",
                "--provider",
                "neutral",
                "--request",
                str(path),
                "--json",
            ]
        )
        == 0
    )
    proposed = emitted(capsys)
    assert proposed["status"] == "needs-review"
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
    assert shown["refs"]["profile"] == proposed["refs"]["proposal"]
    assert shown["reviewState"] == "proposed"


def test_invalid_request_has_documented_exit_and_no_publication(
    tmp_path, monkeypatch, capsys
):
    root = configured_provider(tmp_path, monkeypatch)
    _, _, _, request = prepare_candidate(root)
    request["render"] = True
    path = tmp_path / "invalid.json"
    path.write_text(json.dumps(request))
    assert (
        cli.main(
            [
                "direction",
                "propose",
                "--provider",
                "neutral",
                "--request",
                str(path),
                "--json",
            ]
        )
        == 2
    )
    assert emitted(capsys)["status"] == "invalid-request"
    assert not (root / "direction/index.json").exists()


def test_stale_request_returns_conflict_without_rebinding(
    tmp_path, monkeypatch, capsys
):
    root = configured_provider(tmp_path, monkeypatch)
    service, _, _, request = prepare_candidate(root)
    service.propose(request)
    stale = copy.deepcopy(request)
    stale["requestId"] = "new-stale-request"
    path = tmp_path / "stale.json"
    path.write_text(json.dumps(stale))
    assert (
        cli.main(
            [
                "direction",
                "propose",
                "--provider",
                "neutral",
                "--request",
                str(path),
                "--json",
            ]
        )
        == 3
    )
    assert emitted(capsys)["status"] in {"stale", "conflict"}


def test_explicit_missing_provider_is_unavailable_not_created(
    tmp_path, monkeypatch, capsys
):
    configured_provider(tmp_path, monkeypatch)
    assert (
        cli.main(
            [
                "direction",
                "prepare",
                "--provider",
                "not-found",
                "--profile-id",
                "editorial",
                "--json",
            ]
        )
        == 4
    )
    assert emitted(capsys)["status"] == "unavailable"
    assert not (tmp_path / "not-found").exists()
