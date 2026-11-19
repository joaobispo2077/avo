"""Recovery journals retain their exact dependencies and interrupted results."""

import pytest

from avo.timeline.reconstruction import _required_files
from tests.test_speech_recovery import recovery


def test_media_locators_cannot_be_mistaken_for_preparation_documents():
    from avo.timeline.preparation_retention import _references

    media = {"locator": "documents/original.wav", "sha256": "a" * 64}
    evidence = {"locator": "documents/source-analysis/record.json", "sha256": "b" * 64}
    assert list(
        _references(
            {
                "sourceRef": media,
                "speechDependencies": {"manifestRef": evidence},
                "input": {"analysisRef": evidence},
            }
        )
    ) == [evidence]


def test_recovery_retention_never_reopens_unbounded_journal_readers(
    tmp_path, monkeypatch
):
    from avo.timeline.preparation_retention import retained_preparation_files
    from avo.timeline.store import ArtifactStore

    cutting, _, service, _, request = recovery(tmp_path)
    shown = service.recover(request)

    def forbidden(*args, **kwargs):
        raise AssertionError("retention reopened an unbounded journal reader")

    monkeypatch.setattr(ArtifactStore, "_read_json", forbidden)
    files = retained_preparation_files(cutting.workspace)
    assert service.store.directory / shown["requestRef"]["locator"] in files


def test_recovery_evidence_is_in_reconstruction_and_fallback_inventory(tmp_path):
    from avo.project_inventory import _fallback_reconstruction_metadata

    cutting, _, service, _, request = recovery(tmp_path)
    shown = service.recover(request)
    expected = {
        service.store.ledger.path,
        service.store.directory / request["analysisRef"]["locator"],
        service.store.directory / shown["requestRef"]["locator"],
    }
    assert expected <= set(
        _required_files(cutting.workspace.raw_dir, [], workspace=cutting.workspace)
    )
    assert expected <= set(
        _fallback_reconstruction_metadata(
            cutting.workspace.raw_dir, cutting.workspace.timeline_dir, cutting.workspace
        )
    )


def test_missing_recovery_dependency_blocks_reconstruction(tmp_path):
    cutting, _, service, _, request = recovery(tmp_path)
    shown = service.recover(request)
    (service.store.directory / shown["results"][0]["resultRef"]["locator"]).unlink()
    with pytest.raises(ValueError, match="preparation|recovery"):
        _required_files(cutting.workspace.raw_dir, [], workspace=cutting.workspace)


def test_durable_terminal_result_is_retained_even_before_journal_publication(
    tmp_path, monkeypatch
):
    from avo.timeline.preparation_recovery import PreparationError

    cutting, _, service, _, request = recovery(tmp_path)
    append = service.store._append_preparation

    def interrupted(snapshot, actor, reason):
        if snapshot.get("preparationResults"):
            raise OSError("publication interrupted")
        return append(snapshot, actor, reason)

    monkeypatch.setattr(service.store, "_append_preparation", interrupted)
    with pytest.raises(PreparationError, match="publication interrupted"):
        service.recover(request)
    (attempt,) = service.store._snapshot()["preparationAttempts"]
    result = service.store.recovery_result(attempt)[0]
    retained = _required_files(
        cutting.workspace.raw_dir, [], workspace=cutting.workspace
    )
    assert service.store.directory / result["locator"] in retained
