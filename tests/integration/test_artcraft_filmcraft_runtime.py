"""Qualify the selected native FilmCraft source-only OTIO exchange."""

import os
import subprocess
from pathlib import Path

import pytest
from tests.test_artcraft_handoffs import film_request, film_spec
from tests.test_artcraft_jobs import _prepare
from tests.test_historical_output_records import _record, _write
from tests.test_timeline_import_service import import_project as _project

from avo import artcraft, init_project, timeline_import_cli
from avo.adapters.artcraft import SelectedArtCraftAdapter
from avo.adapters.media.ffprobe import FfprobeMediaAdapter
from avo.adapters.media.otio_reader import read_otio
from avo.mcp.bridge import run_cli
from avo.timeline.contracts import file_fingerprint
from avo.timeline.import_service import TimelineImportService

pytestmark = pytest.mark.integration


def test_native_filmcraft_returns_exact_source_timeline_for_sync_review(
    tmp_path, monkeypatch
):
    entry = os.environ.get("AVO_ARTCRAFT_FILMCRAFT_TEST_CLI")
    if not entry:
        pytest.skip("set AVO_ARTCRAFT_FILMCRAFT_TEST_CLI to the installed 0.20.1 CLI")
    cli = Path(entry).resolve(strict=True)
    project, provider_dir, _ = _project.__wrapped__(tmp_path)
    original = tmp_path / "camera.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=0x406090:s=320x180:r=24:d=1",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=380:sample_rate=48000:duration=1",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-ac",
            "2",
            "-c:a",
            "aac",
            str(original),
        ],
        check=True,
        timeout=20,
        capture_output=True,
    )
    fingerprint = file_fingerprint(original)
    service = TimelineImportService(
        project,
        provider_root=provider_dir,
        reader=read_otio,
        probe=FfprobeMediaAdapter().inventory,
    )
    monkeypatch.setattr(init_project, "load_provider", lambda slug: {"slug": slug})

    def invoke(binary, roots, directory, arguments, *, env, timeout):
        assert binary["locator"] == str(cli)
        assert roots["write"] == [str(directory)]
        return subprocess.run(
            [str(cli), *map(str, arguments)],
            cwd=directory,
            env=env,
            capture_output=True,
            check=True,
            timeout=timeout,
        ).stdout

    adapter = SelectedArtCraftAdapter(
        observe_confinement=lambda _installed, roots: roots,
        run_confined=invoke,
    )
    intent = artcraft.ArtCraftIntent(
        "explicit", "filmcraft", ("source-linked-timeline-return",)
    )
    spec = film_spec(tmp_path, original, provider=service.provider, cliPath=str(cli))
    prepared = _prepare(
        artcraft, film_request(service.provider), spec, adapter, intent=intent
    )
    exported = artcraft.run_authoring(
        prepared["jobRef"], expected_head=prepared["head"], adapter=adapter
    )
    job, event = artcraft.read_authoring_export(
        prepared["jobRef"], expected_head=exported["head"]
    )
    assert event["interchangeEvidence"]["losses"] == []
    assert file_fingerprint(original) == fingerprint
    result = service.prepare_filmcraft_return(
        job, event, actor="fixture", reason="Native FilmCraft timeline"
    )
    assert result["status"] == "awaiting-sync", result["findings"]
    assert not result["findings"]
    assert not service.workspace.artifact_path("cmap").exists()
    monkeypatch.setattr(timeline_import_cli, "create_service", lambda _: service)
    cli_result = run_cli(
        [
            "artcraft",
            "import-timeline",
            "--project",
            str(project),
            "--job",
            prepared["jobRef"],
            "--expected-head",
            exported["head"],
            "--actor",
            "fixture",
            "--reason",
            "Replay selected exchange",
        ]
    )
    assert cli_result.ok, cli_result.stderr
    assert cli_result.parsed_json["importId"] == result["importId"]
    assert cli_result.parsed_json["status"] == "awaiting-sync"
    prohibited = {
        **fingerprint,
        "locator": str(service.workspace.raw_dir / "edit/proof/previous.mp4"),
    }
    _write(
        service.workspace.raw_dir,
        _record(service.workspace.raw_dir, output=prohibited),
        timeline_dir=service.workspace.timeline_dir,
    )
    reference = service.prepare_filmcraft_return(
        job, event, actor="fixture", reason="Reject prior proof bytes"
    )
    assert reference["status"] == "reference-only"
    assert any(row["code"] == "OTIO_SOURCE_PROHIBITED" for row in reference["findings"])
