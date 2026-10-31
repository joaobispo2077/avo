from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

ROOT = Path(__file__).resolve().parents[1]

from avo import transcribe


class FakeRuntime:
    def __init__(self, model: str = "small", error: str | None = None):
        self.model = model
        self.error = error
        self.calls = 0

    def transcribe(self, video: Path, fingerprint: dict):
        self.calls += 1
        if self.error:
            raise RuntimeError(self.error)
        segment = SimpleNamespace(
            words=[SimpleNamespace(word=" Olá", start=0.1, end=0.5, probability=0.9)]
        )
        return transcribe.build_transcript_payload(
            [segment], fingerprint, self.model, "test"
        )


class CacheTests(unittest.TestCase):
    def test_reuses_matching_cache_and_force_bypasses_it(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            video = root / "clip.mp4"
            video.write_bytes(b"one")
            edit = root / "edit"
            first = FakeRuntime()
            transcribe.transcribe_one(video, edit, runtime=first, verbose=False)
            second = FakeRuntime()
            transcribe.transcribe_one(video, edit, runtime=second, verbose=False)
            self.assertEqual(second.calls, 0)
            transcribe.transcribe_one(
                video, edit, runtime=second, force=True, verbose=False
            )
            self.assertEqual(second.calls, 1)

    def test_source_or_model_change_regenerates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            video = root / "clip.mp4"
            video.write_bytes(b"one")
            edit = root / "edit"
            transcribe.transcribe_one(video, edit, runtime=FakeRuntime(), verbose=False)
            video.write_bytes(b"two")
            changed = FakeRuntime()
            transcribe.transcribe_one(video, edit, runtime=changed, verbose=False)
            self.assertEqual(changed.calls, 1)
            medium = FakeRuntime("medium")
            transcribe.transcribe_one(
                video, edit, runtime=medium, model="medium", verbose=False
            )
            self.assertEqual(medium.calls, 1)

    def test_legacy_cache_regenerates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            video = root / "clip.mp4"
            video.write_bytes(b"one")
            edit = root / "edit"
            out = transcribe.transcript_path(video, edit)
            out.parent.mkdir(parents=True)
            out.write_text(json.dumps({"words": []}))
            runtime = FakeRuntime()
            transcribe.transcribe_one(video, edit, runtime=runtime, verbose=False)
            self.assertEqual(runtime.calls, 1)
            self.assertEqual(json.loads(out.read_text())["engine"], "faster-whisper")

    def test_failed_refresh_preserves_previous_cache(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            video = root / "clip.mp4"
            video.write_bytes(b"one")
            edit = root / "edit"
            out = transcribe.transcribe_one(
                video, edit, runtime=FakeRuntime(), verbose=False
            )
            original = out.read_bytes()
            video.write_bytes(b"changed")
            with self.assertRaisesRegex(RuntimeError, "inference failed"):
                transcribe.transcribe_one(
                    video,
                    edit,
                    runtime=FakeRuntime(error="inference failed"),
                    verbose=False,
                )
            self.assertEqual(out.read_bytes(), original)


class CandidateAdapterCacheTests(unittest.TestCase):
    def test_reuses_hash_matching_transcript_even_if_model_differs(self) -> None:
        from avo.adapters.transcribe.candidate import CandidateTranscriptionAdapter
        from avo.timeline.contracts import file_fingerprint

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            video = root / "clip.mp4"
            video.write_bytes(b"one")
            edit = root / "edit" / "transcripts"
            edit.mkdir(parents=True)
            digest = file_fingerprint(video)["sha256"]
            path = edit / "clip.json"
            path.write_text(
                json.dumps(
                    {
                        "text": "oi",
                        "words": [
                            {
                                "text": "oi",
                                "start": 0.0,
                                "end": 0.2,
                                "probability": 0.9,
                            }
                        ],
                        "engine": "faster-whisper",
                        "model": "medium",
                        "language_code": "pt-BR",
                        "source": {"sha256": digest},
                    }
                ),
                encoding="utf-8",
            )
            result = CandidateTranscriptionAdapter(model="medium").transcribe(
                video, edit_dir=root / "edit"
            )
            self.assertEqual(result["model"], "medium")
            self.assertEqual(result["status"], "pass")


def test_recording_output_paths_prevent_duplicate_stem_collisions(tmp_path):
    first = tmp_path / "camera-a" / "clip.mp4"
    second = tmp_path / "camera-b" / "clip.mp4"
    first.parent.mkdir()
    second.parent.mkdir()
    first.write_bytes(b"camera-a")
    second.write_bytes(b"camera-b")
    edit = tmp_path / "edit"
    output_a = edit / "library" / "transcripts" / "recording-a" / "local.json"
    output_b = edit / "library" / "transcripts" / "recording-b" / "local.json"
    transcribe.transcribe_one(
        first, edit, runtime=FakeRuntime(), output_path=output_a, verbose=False
    )
    transcribe.transcribe_one(
        second, edit, runtime=FakeRuntime(), output_path=output_b, verbose=False
    )
    reused = FakeRuntime(error="A valid selected output must not run inference")

    result = transcribe.transcribe_one(
        first, edit, runtime=reused, output_path=output_a, verbose=False
    )

    assert result == output_a
    assert reused.calls == 0
    assert (
        json.loads(output_a.read_text())["source"]["sha256"]
        != json.loads(output_b.read_text())["source"]["sha256"]
    )
    assert not transcribe.transcript_path(first, edit).exists()


def test_auto_language_reuses_requested_mode_without_erasing_detected_language(
    tmp_path,
):
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"source")
    edit = tmp_path / "edit"
    first = FakeRuntime()
    output = transcribe.transcribe_one(
        video, edit, runtime=first, language="auto", verbose=False
    )
    payload = json.loads(output.read_text(encoding="utf-8"))
    cached = FakeRuntime(error="Automatic-language cache must be reused")

    transcribe.transcribe_one(
        video, edit, runtime=cached, language="detect", verbose=False
    )

    assert payload["requested_language"] == "auto"
    assert payload["language_code"] == "pt-BR"
    assert cached.calls == 0
    assert (
        transcribe.inspect_cache(
            output, transcribe.source_fingerprint(video), language_code="auto"
        )
        == "valid"
    )
    assert (
        transcribe.inspect_cache(
            output, transcribe.source_fingerprint(video), language_code="pt-BR"
        )
        == "stale"
    )


def test_valid_native_cache_without_requested_language_remains_reusable(tmp_path):
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"source")
    fingerprint = transcribe.source_fingerprint(video)
    output = tmp_path / "cached.json"
    payload = FakeRuntime().transcribe(video, fingerprint)
    assert "requested_language" not in payload
    transcribe.atomic_write_json(output, payload)

    assert transcribe.inspect_cache(output, fingerprint) == "valid"
    assert (
        transcribe.inspect_cache(output, fingerprint, language_code="auto") == "stale"
    )


@pytest.mark.parametrize(
    "damage",
    [
        "negative-time",
        "nan-time",
        "unordered",
        "missing-words",
        "invalid-words",
        "requested-language",
    ],
)
def test_matching_source_model_does_not_reuse_invalid_transcript(tmp_path, damage):
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"source")
    fingerprint = transcribe.source_fingerprint(video)
    output = tmp_path / "cached.json"
    payload = FakeRuntime().transcribe(video, fingerprint)
    if damage == "negative-time":
        payload["words"][0]["start"] = -1
    elif damage == "nan-time":
        payload["words"][0]["end"] = float("nan")
    elif damage == "unordered":
        payload["words"].append({**payload["words"][0], "start": 0.0})
    elif damage == "missing-words":
        payload.pop("words")
    elif damage == "invalid-words":
        payload["words"] = [None]
    else:
        payload["requested_language"] = {"not": "a language"}
    output.write_text(json.dumps(payload), encoding="utf-8")

    assert transcribe.inspect_cache(output, fingerprint) == "invalid"


@pytest.mark.parametrize(
    ("language", "canonical"), [("pt", "pt-BR"), ("pt_BR", "pt-BR"), ("en", "en-US")]
)
def test_requested_language_uses_canonical_code_in_cache(tmp_path, language, canonical):
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"source")
    output = transcribe.transcribe_one(
        video,
        tmp_path / "edit",
        runtime=FakeRuntime(),
        language=language,
        verbose=False,
    )

    assert (
        json.loads(output.read_text(encoding="utf-8"))["requested_language"]
        == canonical
    )
    assert (
        transcribe.inspect_cache(
            output, transcribe.source_fingerprint(video), language_code=language
        )
        == "valid"
    )


def test_explicit_output_cannot_replace_the_source_recording(tmp_path):
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"original source")
    runtime = FakeRuntime()

    with pytest.raises(ValueError, match="source"):
        transcribe.transcribe_one(
            video, tmp_path / "edit", runtime=runtime, output_path=video, verbose=False
        )

    assert video.read_bytes() == b"original source"
    assert runtime.calls == 0


@pytest.fixture
def model_constructor(tmp_path, monkeypatch):
    model = tmp_path / "small"
    model.mkdir()
    for name in transcribe.MODEL_FILES:
        (model / name).write_text(name, encoding="utf-8")
    constructor = Mock(return_value=SimpleNamespace())
    monkeypatch.setitem(
        sys.modules, "faster_whisper", SimpleNamespace(WhisperModel=constructor)
    )
    monkeypatch.setattr("avo.model_sources.check_runtime", lambda **kwargs: None)
    return model, constructor


@pytest.mark.parametrize("threads", [None, 0, 2])
def test_cpu_thread_cap_is_only_forwarded_when_explicit(model_constructor, threads):
    model, constructor = model_constructor
    transcribe.LocalTranscriber(model_dir=model, cpu_threads=threads)
    arguments = constructor.call_args.kwargs

    if threads:
        assert arguments["cpu_threads"] == threads
    else:
        assert "cpu_threads" not in arguments
    assert arguments["local_files_only"] is True


@pytest.mark.parametrize("method", ["transcribe", "transcribe_audio"])
def test_runtime_retains_requested_auto_alongside_detected_language(
    model_constructor, tmp_path, method
):
    model, constructor = model_constructor
    constructor.return_value.transcribe = lambda *args, **kwargs: (
        [{"words": [{"word": "Olá", "start": 0.0, "end": 0.2}]}],
        SimpleNamespace(language="pt"),
    )
    runtime = transcribe.LocalTranscriber(model_dir=model, language="auto")
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"source")
    options = (
        {"source_start": 0.0, "analysis_provenance": {"fixture": True}}
        if method == "transcribe_audio"
        else {}
    )

    payload = getattr(runtime, method)(
        video, transcribe.source_fingerprint(video), **options
    )

    assert payload["requested_language"] == "auto"
    assert payload["language_code"] == "pt-BR"
    assert payload["engine_language"] == "pt"


@pytest.mark.parametrize("threads", [-1, True, False, 1.5, "2"])
def test_invalid_cpu_thread_cap_fails_before_model_construction(
    model_constructor, threads
):
    model, constructor = model_constructor

    with pytest.raises(ValueError, match="CPU thread"):
        transcribe.LocalTranscriber(model_dir=model, cpu_threads=threads)

    constructor.assert_not_called()


if __name__ == "__main__":
    unittest.main()
