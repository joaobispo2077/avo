"""The optional real local worker retains the existing transcription boundary."""

import os
import shutil

import pytest

from avo.library import batch
from avo.library.service import LibraryService
from library_fixtures import install_provider, make_library
from test_library_batch import decision, request

pytestmark = pytest.mark.integration


@pytest.mark.skipif(
    os.environ.get("AVO_LIBRARY_REAL_ASR") != "1",
    reason="Explicit prepared-local-model acceptance run",
)
def test_real_adapter_batch_is_offline_and_reuses_model_outputs(
    tmp_path, monkeypatch, repo_root
):
    install = tmp_path / "install"
    install_provider(install)
    (install / "config").mkdir()
    for name in ("avo.config.json", "avo.model-catalog.json"):
        shutil.copyfile(repo_root / "config" / name, install / "config" / name)
    monkeypatch.setenv("AVO_ROOT", str(install))
    fixture = make_library(tmp_path / "footage", count=1, playable=True)
    service = LibraryService(
        fixture.root, "example", probe=lambda _: {"durationSeconds": 2, "audio": True}
    )
    service.scan(recursive=True)
    approval = decision(
        service, batch.prepare_batch(service, request(service))["packetRef"]
    )
    result = batch.run_batch(service, approval)
    assert result["status"] == "ok"
    records = service.store.get(service.store.head()["inventoryRef"])["recordings"]
    assert records[0]["transcript"]["sourceSha256"]
    assert records[0]["transcript"]["requestedLanguage"] == "en-US"
    approval = decision(
        service, batch.prepare_batch(service, request(service))["packetRef"]
    )
    repeated = batch.run_batch(service, approval)
    assert repeated["summary"]["reused"] == 1
