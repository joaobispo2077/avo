import numpy as np

from avo.breath_analysis import analyze_candidates, protected_word_ranges


def test_gaps_are_not_breaths_and_fricatives_inside_words_are_protected():
    rate = 16000
    rng = np.random.default_rng(2)
    pcm = np.zeros(rate * 3, dtype=np.float32)
    pcm[rate : rate * 2] = rng.normal(0, 0.03, rate)
    words = [{"text": "sossego", "start": 1.0, "end": 2.0}]
    result = analyze_candidates(pcm, rate, words)
    assert result["events"] == []
    assert protected_word_ranges(words, rate)[0]["startSample"] == 14720


def test_noise_between_words_is_proposed_not_automatically_certified():
    rate = 16000
    pcm = np.zeros(rate * 3, dtype=np.float32)
    pcm[rate : rate * 2] = np.random.default_rng(3).normal(0, 0.02, rate)
    result = analyze_candidates(
        pcm, rate, [{"start": 0, "end": 0.5}, {"start": 2.5, "end": 3}]
    )
    assert len(result["events"]) == 1
    assert result["events"][0]["status"] == "ambiguous"
    assert result["events"][0]["reason"].startswith("noise-like")


def test_protected_source_sound_and_tonal_sound_are_not_auto_breaths():
    rate = 16000
    pcm = np.zeros(rate * 3, dtype=np.float32)
    pcm[rate : rate * 2] = 0.05 * np.sin(2 * np.pi * 440 * np.arange(rate) / rate)
    result = analyze_candidates(
        pcm, rate, [{"start": 0, "end": 0.5}, {"start": 2.5, "end": 3}]
    )
    assert all(event["status"] != "safe" for event in result["events"])
