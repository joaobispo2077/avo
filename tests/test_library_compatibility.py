"""Legacy behavior that library organization must leave unchanged."""

from __future__ import annotations

import json
import shutil

import pytest

from avo import project_inventory, transcribe, transcribe_batch
from test_transcribe_cache import FakeRuntime


def test_single_file_keeps_legacy_output_and_reuses_valid_transcript(tmp_path):
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"recording")
    edit_dir = tmp_path / "edit"
    first = FakeRuntime()

    output = transcribe.transcribe_one(video, edit_dir, runtime=first, verbose=False)
    original = output.read_bytes()
    payload = json.loads(original)
    cached_runtime = FakeRuntime(error="valid cache must not run inference")
    cached_output = transcribe.transcribe_one(
        video, edit_dir, runtime=cached_runtime, verbose=False
    )

    assert output == edit_dir / "transcripts" / "clip.json"
    assert payload["engine"] == "faster-whisper"
    assert payload["language_code"] == "pt-BR"
    assert payload["words"][0]["text"] == "Olá"
    assert payload["source"]["sha256"] == transcribe.source_fingerprint(video)["sha256"]
    assert first.calls == 1 and cached_runtime.calls == 0
    assert cached_output == output and output.read_bytes() == original
    assert not (edit_dir / "library").exists()


def test_directory_stays_flat_and_cached_repeat_does_not_load_runtime(tmp_path):
    (tmp_path / "a.mp4").write_bytes(b"a")
    (tmp_path / "b.mov").write_bytes(b"b")
    (tmp_path / "notes.txt").write_text("not media", encoding="utf-8")
    nested = tmp_path / "camera"
    nested.mkdir()
    (nested / "nested.mp4").write_bytes(b"nested")
    created = []

    def factory(**kwargs):
        runtime = FakeRuntime(model=kwargs["model"])
        created.append(runtime)
        return runtime

    first = transcribe_batch.transcribe_directory(
        tmp_path, runtime_factory=factory, verbose=False
    )
    repeated = transcribe_batch.transcribe_directory(
        tmp_path,
        runtime_factory=lambda **_kwargs: pytest.fail("cached batch loaded runtime"),
        verbose=False,
    )

    assert (first.found, first.cached, first.transcribed, first.failures) == (
        2,
        0,
        2,
        [],
    )
    assert len(created) == 1 and created[0].calls == 2
    assert (repeated.found, repeated.cached, repeated.transcribed) == (2, 2, 0)
    assert repeated.failures == []
    assert {p.name for p in (tmp_path / "edit" / "transcripts").glob("*.json")} == {
        "a.json",
        "b.json",
    }
    assert not (nested / "edit").exists()


def test_failed_refresh_preserves_previous_single_file_transcript(tmp_path):
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"original")
    edit_dir = tmp_path / "edit"
    output = transcribe.transcribe_one(
        video, edit_dir, runtime=FakeRuntime(), verbose=False
    )
    original = output.read_bytes()
    video.write_bytes(b"changed source")

    with pytest.raises(RuntimeError, match="inference failed"):
        transcribe.transcribe_one(
            video,
            edit_dir,
            runtime=FakeRuntime(error="inference failed"),
            verbose=False,
        )

    assert output.read_bytes() == original
    assert (
        transcribe.inspect_cache(output, transcribe.source_fingerprint(video))
        == "stale"
    )


@pytest.mark.parametrize("dry_run", [True, False])
def test_non_library_cleanup_preserves_sources_and_delivery(
    tmp_path, repo_root, dry_run
):
    raw_dir = tmp_path / "raw"
    shutil.copytree(repo_root / "tests" / "fixtures" / "stats-project", raw_dir)
    basename = "20260801-demo-master-v001"
    preserved = project_inventory.resolve_preserved_set(raw_dir, basename)
    expected_bytes = {path: path.read_bytes() for path in preserved.all_paths}
    outside = tmp_path / "outside.bin"
    outside.write_bytes(b"outside selected root")
    preview = raw_dir / "edit" / "preview" / "edit-proof.mp4"

    outcome = project_inventory.run_cleanup(
        raw_dir,
        basename,
        dry_run=dry_run,
        rimraf_runner=lambda path: path.unlink(),
        purge_session=False,
    )

    assert preview in outcome.paths
    assert preview.exists() is dry_run
    assert all(path.read_bytes() == content for path, content in expected_bytes.items())
    assert outside.read_bytes() == b"outside selected root"
    assert not (raw_dir / "edit" / "library").exists()
    assert outcome.leftover == 0
    assert project_inventory.verify_preserved_complete(raw_dir, basename) == []
    receipt = raw_dir / "edit" / "cleanup" / "cleanup-result.json"
    assert receipt.exists() is not dry_run
