"""Sound timing fits preserve reviewed native markers, useful attacks and tails."""

from copy import deepcopy
from fractions import Fraction

import pytest

from avo.timeline.event_clock import frame_to_sample, sample_rate_boundary
from avo.timeline.sound_planning import SoundPlanningError, fit_sound_candidate
from tests.test_sfx_catalog import Facts, annotate, make_service, scan


def opportunity(**changes):
    return {
        "eventId": "reveal-one",
        "itemId": "mo04",
        "cueId": "cue-one",
        "kind": "reveal",
        "purpose": "Support the visible comparison reveal",
        "role": "main",
        "visibility": "visible",
        "programFrame": 30,
        "visibleRange": {"startFrame": 24, "endFrameExclusive": 48},
        **changes,
    }


def candidate(tmp_path, rate=48000, *, partial=False):
    class NativeFacts(Facts):
        def __call__(self, *args, **kwargs):
            facts = super().__call__(*args, **kwargs)
            facts.update(sampleRate=rate, sourceSamples=rate, analyzedSamples=rate)
            facts["usefulRange"] = {
                "startSample": rate // 10,
                "endSampleExclusive": 3 * rate // 4,
            }
            if partial:
                facts.update(
                    coverage="partial",
                    analyzedSamples=rate // 2,
                    onsetCoverage="partial",
                )
                facts["usefulRange"]["endSampleExclusive"] = rate // 2
            return facts

    service, _ = make_service(tmp_path, analyzer=NativeFacts())
    generation = scan(service)
    entry = generation["entries"][0]
    generation = annotate(
        service,
        generation["generationId"],
        entry["entryId"],
        {
            "rights": {
                "status": "licensed",
                "license": "fixture",
                "evidenceRef": "rights-review",
            },
            "marker": {"sample": rate // 10, "reviewerRef": "marker-review"},
        },
    )
    return generation["entries"][0]


@pytest.mark.parametrize("rate", [44100, 48000, 96000])
@pytest.mark.parametrize("fps", [Fraction(24), Fraction(30000, 1001)])
def test_fitted_anchor_subtracts_native_trim_before_the_shared_clock(
    tmp_path, rate, fps
):
    entry = candidate(tmp_path, rate)
    original = deepcopy(entry)
    trim = {"startSample": rate // 20, "endSampleExclusive": rate}
    result = fit_sound_candidate(
        opportunity(), entry, trim_range=trim, frame_rate=fps, program_end_frame=90
    )
    assert result["status"] == "fit"
    impact = frame_to_sample(
        30, frame_rate_num=fps.numerator, frame_rate_den=fps.denominator
    )
    offset = sample_rate_boundary(
        rate // 10 - rate // 20, source_rate=rate, target_rate=48000
    )
    assert result["event"]["resolvedImpactSample"] == impact
    assert (
        result["event"]["transientOffset"]["sourceSamples"] == rate // 10 - rate // 20
    )
    assert result["event"]["scheduledAudioStartSample"] + offset == impact
    assert result["scheduledAudioEndSample"] > impact
    assert result["source"]["sourceSha256"] == entry["source"]["sha256"]
    assert (
        result["source"]["measurementHash"] == entry["measurement"]["measurementHash"]
    )
    assert result["acceptance"] == "pending-listening"
    assert entry == original


@pytest.mark.parametrize(
    "problem",
    [
        "pre-roll",
        "tail-space",
        "attack-trim",
        "tail-trim",
        "marker-trim",
        "hidden",
        "unknown",
        "unreviewed",
        "rights",
        "stale-marker",
        "stale-rights",
        "missing",
    ],
)
def test_unfit_candidates_remain_unresolved_without_shortening_or_extending_picture(
    tmp_path, problem
):
    entry = candidate(tmp_path)
    event = opportunity()
    trim, end = {"startSample": 0, "endSampleExclusive": 48000}, 90
    if problem == "pre-roll":
        event.update(
            programFrame=0, visibleRange={"startFrame": 0, "endFrameExclusive": 24}
        )
    elif problem == "tail-space":
        end = 48
    elif problem == "attack-trim":
        trim["startSample"] = 5000
        # A reviewed marker can be later than the start of its useful attack.
        entry["marker"]["sample"] = 6000
    elif problem == "tail-trim":
        trim["endSampleExclusive"] = 35000
    elif problem == "marker-trim":
        trim["startSample"] = 5000
    elif problem in {"hidden", "unknown"}:
        event["visibility"] = problem
    elif problem == "unreviewed":
        entry["marker"] = None
    elif problem == "rights":
        entry["rights"]["status"] = "unknown"
    elif problem == "stale-marker":
        entry["marker"]["sourceSha256"] = "c" * 64
    elif problem == "stale-rights":
        entry["rights"]["sourceSha256"] = "c" * 64
    else:
        entry["source"]["state"] = "missing"
    result = fit_sound_candidate(
        event, entry, trim_range=trim, frame_rate=Fraction(24), program_end_frame=end
    )
    assert result["status"] == "unresolved"
    assert result["issues"]
    assert result["event"] is None
    assert result["scheduledAudioEndSample"] is None


def test_silence_is_an_explicit_choice_without_a_candidate_or_analysis():
    result = fit_sound_candidate(
        opportunity(),
        None,
        trim_range=None,
        frame_rate=Fraction(24),
        program_end_frame=90,
    )
    assert result["status"] == "silence"
    assert result["source"] is None and result["event"] is None


def test_fit_identity_binds_program_clock_and_current_marker_review(tmp_path):
    entry = candidate(tmp_path)
    arguments = {
        "trim_range": {"startSample": 0, "endSampleExclusive": 48000},
        "frame_rate": Fraction(24),
        "program_end_frame": 90,
    }
    first = fit_sound_candidate(opportunity(), entry, **arguments)
    changed_program = fit_sound_candidate(
        opportunity(), entry, **{**arguments, "program_end_frame": 91}
    )
    assert first["event"] == changed_program["event"]
    assert first["fitHash"] != changed_program["fitHash"]
    entry["marker"]["reviewerRef"] = "current-marker-review"
    entry["annotationRevision"] += 1
    changed_review = fit_sound_candidate(opportunity(), entry, **arguments)
    assert (
        first["source"]["measurementHash"]
        == changed_review["source"]["measurementHash"]
    )
    assert (
        first["source"]["annotationHash"] != changed_review["source"]["annotationHash"]
    )
    assert first["fitHash"] != changed_review["fitHash"]


@pytest.mark.parametrize("problem", ["partial-analysis", "license", "rights-evidence"])
def test_incomplete_tail_analysis_or_rights_evidence_cannot_qualify_a_fit(
    tmp_path, problem
):
    entry = candidate(tmp_path, partial=problem == "partial-analysis")
    if problem == "license":
        entry["rights"]["license"] = None
    elif problem == "rights-evidence":
        entry["rights"]["evidenceRef"] = None
    result = fit_sound_candidate(
        opportunity(),
        entry,
        trim_range={"startSample": 0, "endSampleExclusive": 48000},
        frame_rate=Fraction(24),
        program_end_frame=90,
    )
    assert result["status"] == "unresolved" and result["event"] is None


@pytest.mark.parametrize("bad", [True, -1, 1.5])
def test_invalid_event_frames_do_not_become_fitted_candidates(bad):
    with pytest.raises(SoundPlanningError):
        fit_sound_candidate(
            opportunity(programFrame=bad),
            None,
            trim_range=None,
            frame_rate=Fraction(24),
            program_end_frame=90,
        )
