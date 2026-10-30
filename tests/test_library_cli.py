"""Native and installed library commands share one structured surface."""

import json
from types import SimpleNamespace

import pytest

from avo import cli, engine_cli
from avo.library.rules import LibraryError
from avo.library_cli import _with_progress, dispatch


def test_organize_invalid_root_is_structured(tmp_path, capsys):
    args = [
        "organize",
        "status",
        "--root",
        str(tmp_path / "missing"),
        "--provider",
        "example",
        "--json",
    ]
    assert cli.main(args) == 2
    assert json.loads(capsys.readouterr().out)["status"] == "invalid-request"
    assert engine_cli.main(args) == 2


def test_organize_help_does_not_load_models(capsys):
    assert engine_cli.main(["organize", "--help"]) == 0
    assert "organize" in capsys.readouterr().out


@pytest.mark.parametrize(
    "operation", ["review", "prepare", "apply", "resume", "reverse", "cancel", "search"]
)
def test_missing_operation_arguments_fail_before_any_service_action(operation):
    with pytest.raises(LibraryError, match="Supply --") as error:
        dispatch(None, SimpleNamespace(library_operation=operation))
    assert error.value.code == "LIB_INVALID_REQUEST"


@pytest.mark.parametrize("operation", ["prepare", "run"])
def test_missing_batch_arguments_fail_before_dispatch(operation):
    with pytest.raises(LibraryError, match="Supply --"):
        dispatch(
            None,
            SimpleNamespace(
                library_operation="batch", library_batch_operation=operation
            ),
        )


def test_failed_import_keeps_an_inspectable_report(tmp_path, monkeypatch):
    from avo.library.service import LibraryService
    from library_fixtures import install_provider

    install_provider(tmp_path / "install")
    monkeypatch.setenv("AVO_ROOT", str(tmp_path / "install"))
    monkeypatch.setattr("avo.library_cli._phase_telemetry", lambda *_: None)
    root = tmp_path / "footage"
    root.mkdir()
    service = LibraryService(root, "example")
    service.scan()
    args = SimpleNamespace(
        library_operation="propose",
        request=root / "missing.json",
        request_sha256="0" * 64,
    )
    with pytest.raises(LibraryError) as error:
        _with_progress(service, args)
    report = service.store.get(error.value.library_report)
    assert report["status"] == "failed"
    assert report["counts"]["failed"] == 1
