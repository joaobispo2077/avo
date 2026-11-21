"""Sound admission binds the observed first audio stream, never a guessed index."""

import pytest


def test_source_probe_freezes_actual_nonzero_first_audio_stream(tmp_path, monkeypatch):
    from avo.adapters.media.ffprobe import FfprobeMediaAdapter
    from avo.adapters.registry import build_sound_source_probe

    path = tmp_path / "effect.m4a"
    sha = "a" * 64

    def inventory(self, paths):
        assert paths == [path]
        return {
            "sources": [
                {
                    "fingerprint": {"sha256": sha},
                    "streams": {
                        "audio": [
                            {"index": 3, "sampleRate": 44100, "channels": 1},
                            {"index": 4, "sampleRate": 48000, "channels": 2},
                        ]
                    },
                }
            ]
        }

    monkeypatch.setattr(FfprobeMediaAdapter, "inventory", inventory)
    probe = build_sound_source_probe()
    assert probe(path, expected_sha256=sha) == {
        "sourceSha256": sha,
        "streamIndex": 3,
        "sampleRate": 44100,
        "channels": 1,
    }


@pytest.mark.parametrize("problem", ["source", "audio"])
def test_source_probe_rejects_changed_or_non_audio_sources(
    tmp_path, monkeypatch, problem
):
    from avo.adapters.media.ffprobe import FfprobeMediaAdapter
    from avo.adapters.registry import build_sound_source_probe

    monkeypatch.setattr(
        FfprobeMediaAdapter,
        "inventory",
        lambda *a: {
            "sources": [
                {
                    "fingerprint": {
                        "sha256": "b" * 64 if problem == "source" else "a" * 64
                    },
                    "streams": {"audio": []},
                }
            ]
        },
    )
    with pytest.raises(ValueError):
        build_sound_source_probe()(tmp_path / "source.wav", expected_sha256="a" * 64)
