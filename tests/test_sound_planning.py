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


def candidate(tmp_path, rate=48000, *, partial=False, useful_end=None):
    class NativeFacts(Facts):
        def __call__(self, *args, **kwargs):
            facts = super().__call__(*args, **kwargs)
            facts.update(sampleRate=rate, sourceSamples=rate, analyzedSamples=rate)
            facts["usefulRange"] = {
                "startSample": rate // 10,
                "endSampleExclusive": 3 * rate // 4
                if useful_end is None
                else useful_end,
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


def test_trim_that_rounds_to_no_output_samples_remains_unresolved(tmp_path):
    trim = {"startSample": 19200, "endSampleExclusive": 19201}
    entry = candidate(tmp_path, rate=192000, useful_end=trim["endSampleExclusive"])
    result = fit_sound_candidate(
        opportunity(),
        entry,
        trim_range=trim,
        frame_rate=Fraction(24),
        program_end_frame=90,
    )
    assert result["status"] == "unresolved"
    assert result["issues"] == ["trim-has-no-output-samples"]
    assert result["event"] is None


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


def test_fitted_event_can_bind_the_existing_native_audio_event_owner(tmp_path):
    from avo.adapters.media.proof_audio_bridge import validate_audio_events

    entry = candidate(tmp_path)
    trim = {"startSample": 600, "endSampleExclusive": 48000}
    result = fit_sound_candidate(
        opportunity(),
        entry,
        trim_range=trim,
        frame_rate=Fraction(24),
        program_end_frame=90,
    )
    event = {
        **result["event"],
        "sourceRange": trim,
        "audio": {"nodeId": "selected-sfx"},
    }
    execution = {
        "output": {"frameRate": {"num": 24, "den": 1}},
        "audioGraph": {
            "sampleRate": 48000,
            "nodes": [
                {
                    "nodeId": "selected-sfx",
                    "kind": "sfx",
                    "sourceRange": trim,
                    "sourceSampleRate": 48000,
                    "outputRange": {
                        "startSample": result["event"]["scheduledAudioStartSample"],
                        "endSampleExclusive": result["scheduledAudioEndSample"],
                    },
                }
            ],
        },
        "events": [event],
    }
    assert validate_audio_events(execution) == {"reveal-one"}
    assert result["opportunity"]["visibleRange"] == opportunity()["visibleRange"]


def test_non_aligned_native_trim_uses_the_existing_continuous_source_clock(tmp_path):
    from avo.adapters.media.audio_tracks import compile_continuous_audio_graph

    entry = candidate(tmp_path, 44100)
    trim = {"startSample": 2200, "endSampleExclusive": 40000}
    result = fit_sound_candidate(
        opportunity(),
        entry,
        trim_range=trim,
        frame_rate=Fraction(24),
        program_end_frame=90,
    )
    start = result["event"]["scheduledAudioStartSample"]
    node = {
        "nodeId": "selected-sfx",
        "kind": "source",
        "input": {"sha256": entry["source"]["sha256"], "streamId": "audio:0"},
        "sourceSampleRange": trim,
        "sourceSampleRate": 44100,
        "sourceLayout": "stereo",
        "targetLayout": "stereo",
        "channelMap": [0, 1],
        "outputSampleRange": {
            "startSample": start,
            "endSampleExclusive": result["scheduledAudioEndSample"],
        },
    }
    # The ordinary source compiler validates native endpoint conversion before
    # assembling explicit leading silence; no parallel duration rule is allowed.
    silence = {
        "nodeId": "before-effect",
        "kind": "silence",
        "targetLayout": "stereo",
        "channelMap": [0, 1],
        "outputSampleRange": {"startSample": 0, "endSampleExclusive": start},
    }
    graph = compile_continuous_audio_graph(
        [silence, node],
        [
            {
                "kind": "encode",
                "range": {
                    "startSample": 0,
                    "endSampleExclusive": result["scheduledAudioEndSample"],
                },
            }
        ],
    )
    assert graph["nodes"][1]["sourceSampleRange"] == trim


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
