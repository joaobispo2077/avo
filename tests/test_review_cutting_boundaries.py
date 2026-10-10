from avo.timeline.review_runner import compare_protected_boundaries


def review(words, candidate_range):
    return compare_protected_boundaries(
        {"words": []},
        {"words": words},
        protected_boundaries=[
            {
                "boundaryId": "repair",
                "kind": "phrase",
                "text": "quero saber",
                "candidateRange": candidate_range,
            }
        ],
        acoustic_checks={"repair": {"confidence": 0.99, "complete": True}},
    )


def test_phrase_elsewhere_cannot_hide_a_missing_local_occurrence():
    words = [
        {"word": "saber", "start": 5, "end": 5.4},
        {"word": "quero", "start": 50, "end": 50.2},
        {"word": "saber", "start": 50.2, "end": 50.5},
    ]
    result = review(words, {"start": 4, "end": 7})
    assert result["status"] == "fail"
    assert result["findings"][0]["candidateWords"] == ["saber"]


def test_full_phrase_at_mapped_local_occurrence_passes():
    words = [
        {"word": "quero", "start": 5, "end": 5.2},
        {"word": "saber", "start": 5.2, "end": 5.5},
    ]
    assert review(words, {"start": 4, "end": 7})["status"] == "pass"


def test_missing_or_invalid_word_clock_cannot_certify_local_presence():
    words = [{"word": "quero"}, {"word": "saber"}]
    assert review(words, {"start": 4, "end": 7})["status"] == "needs-human-judgment"
    assert review(words, {"start": 7, "end": 4})["status"] == "needs-human-judgment"


def test_local_clock_is_half_open_at_neighboring_phrase():
    words = [
        {"word": "quero", "start": 7, "end": 7.2},
        {"word": "saber", "start": 7.2, "end": 7.5},
    ]
    assert review(words, {"start": 4, "end": 7})["status"] == "fail"


def test_partial_token_is_not_a_complete_local_word():
    words = [
        {"word": "euquero", "start": 5, "end": 5.2},
        {"word": "saber", "start": 5.2, "end": 5.5},
    ]
    assert review(words, {"start": 4, "end": 7})["status"] == "fail"
