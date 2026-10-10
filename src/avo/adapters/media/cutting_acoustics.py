"""Continuous acoustic observations; no observed duration authorizes removal."""

from __future__ import annotations

from importlib.metadata import version
from math import ceil, floor
from pathlib import Path

import numpy as np

from avo.adapters.media.cutting_audio import extract_dialogue_pcm, read_pcm
from avo.timeline.ports import SpeechAlignmentPort, ToolError
from avo.transcribe import source_fingerprint


def analyze_waveform(path: Path, *, source_start=0.0):
    samples, rate = read_pcm(path)
    window, hop = max(1, rate // 100), max(1, rate // 200)
    frames = []
    for first in range(0, len(samples), hop):
        frame = samples[first : first + window].astype(np.float64)
        spectrum = np.abs(np.fft.rfft(frame, axis=0)) ** 2
        frequencies = np.fft.rfftfreq(len(frame), 1 / rate)
        frames.append(
            {
                "start": source_start + first / rate,
                "end": source_start + min(first + window, len(samples)) / rate,
                "rms": float(np.max(np.sqrt(np.mean(frame**2, axis=0)))),
                "highFrequencyEnergy": float(spectrum[frequencies >= 2000].sum()),
            }
        )
    return {
        "windowMs": 10,
        "hopMs": 5,
        "sampleRate": rate,
        "frames": frames,
        "observed": True,
        "sourceStart": source_start,
        "duration": len(samples) / rate,
    }


def speech_probability_ranges(probabilities, *, source_start=0.0, duration=None):
    ranges, first = [], None
    for index, probability in enumerate(probabilities):
        # Hysteresis is observation-only; no minimum speech length discards syllables.
        if first is None and probability >= 0.5:
            first = index
        elif first is not None and probability < 0.35:
            ranges.append(
                {
                    "start": source_start + first * 0.032,
                    "end": source_start + index * 0.032,
                }
            )
            first = None
    if first is not None:
        end = len(probabilities) * 0.032 if duration is None else duration
        ranges.append(
            {"start": source_start + first * 0.032, "end": source_start + end}
        )
    return ranges


def _vad_observations(audio, rate, injected_model):
    if rate != 16000:
        raise ToolError("cutting-vad-input", "Silero analysis requires 16 kHz PCM")
    if injected_model is None:
        from faster_whisper.utils import get_assets_path
        from faster_whisper.vad import get_vad_model

        model = get_vad_model()
        vad_binding = {
            "engine": "silero-vad",
            "runtime": "faster-whisper",
            "runtimeVersion": version("faster-whisper"),
            "modelSha256": source_fingerprint(
                Path(get_assets_path()) / "silero_vad_v6.onnx"
            )["sha256"],
            "windowSamples": 512,
            "sampleRate": 16000,
            "device": "cpu",
        }
    else:
        model = injected_model
        vad_binding = {
            "engine": "injected-test-model",
            "windowSamples": 512,
            "sampleRate": 16000,
        }
    padded = np.pad(audio[:, 0], (0, (-len(audio)) % 512))
    probabilities = np.asarray(model(padded)).reshape(-1)
    if (
        len(probabilities) != len(padded) // 512
        or not np.isfinite(probabilities).all()
        or np.any(probabilities < 0)
        or np.any(probabilities > 1)
    ):
        raise ToolError(
            "cutting-vad-output", "continuous speech probabilities are invalid"
        )
    return probabilities, vad_binding


def _silence_ranges(speech, source_start, duration):
    # A VAD-only gap stays uncertain until word/acoustic corroboration.
    silences, cursor = [], source_start
    for interval in speech:
        if interval["start"] > cursor:
            silences.append(
                {
                    "start": cursor,
                    "end": interval["start"],
                    "observed": True,
                    "corroborated": False,
                }
            )
        cursor = interval["end"]
    if cursor < source_start + duration:
        silences.append(
            {
                "start": cursor,
                "end": source_start + duration,
                "observed": True,
                "corroborated": False,
            }
        )
    return silences


class CuttingAcousticsAdapter:
    def __init__(
        self,
        transcriber=None,
        vad_model=None,
        aligner: SpeechAlignmentPort | None = None,
        context_classifier=None,
    ):
        self.transcriber = transcriber
        self.vad_model = vad_model
        self.aligner = aligner
        self.context_classifier = context_classifier

    def analyze(self, source, **request):
        extraction = extract_dialogue_pcm(
            source,
            **{
                key: request[key]
                for key in (
                    "selection",
                    "source_range",
                    "fingerprint",
                    "sync_ref",
                    "output_dir",
                )
            },
        )
        wave = analyze_waveform(
            Path(extraction["nativePath"]), source_start=extraction["sourceStart"]
        )
        audio, rate = read_pcm(Path(extraction["analysisPath"]))
        probabilities, vad_binding = _vad_observations(audio, rate, self.vad_model)
        extraction["bindings"]["vad"] = vad_binding
        speech = speech_probability_ranges(
            probabilities, source_start=wave["sourceStart"], duration=wave["duration"]
        )
        silences = _silence_ranges(speech, wave["sourceStart"], wave["duration"])
        transcript = {"words": []}
        if self.transcriber is not None:
            transcript = self.transcriber.transcribe_audio(
                Path(extraction["analysisPath"]),
                request["fingerprint"],
                source_start=wave["sourceStart"],
                analysis_provenance=extraction["bindings"],
            )
        alignment = None
        if self.aligner is not None and transcript["words"]:
            segments = _alignment_segments(
                transcript["words"], wave["sourceStart"], wave["duration"]
            )
            alignment = self.aligner.align(
                Path(extraction["analysisPath"]),
                segments=segments,
                source_start=wave["sourceStart"],
                language=request.get("language", "pt-BR"),
            )
        candidates = pause_candidates(
            alignment,
            wave,
            speech,
            request["source_range"]["sourceId"],
            context_classifier=self.context_classifier,
        )
        return {
            **extraction,
            "words": transcript["words"],
            "speechRanges": speech,
            "silenceRanges": silences,
            "candidates": candidates,
            "alignment": alignment,
            "waveform": wave,
            "speechProbabilities": probabilities.tolist(),
            "coverage": {
                "observed": True,
                "start": wave["sourceStart"],
                "end": wave["sourceStart"] + wave["duration"],
            },
            "transcriptionAvailable": self.transcriber is not None,
        }


def _source_interval(source_id, start, end):
    return {
        "sourceId": source_id,
        "startTicks": floor(start * 1_000_000),
        "endTicksExclusive": ceil(end * 1_000_000),
        "timebase": {"num": 1, "den": 1_000_000},
    }


def _quiet_intervals(frames, before, after, quiet_limit, spectral_limit):
    quiet = []
    for frame in frames:
        if (
            frame["start"] < before["end"]
            or frame["end"] > after["start"]
            or frame["rms"] > quiet_limit
            or frame["highFrequencyEnergy"] > spectral_limit
        ):
            continue
        if quiet and frame["start"] <= quiet[-1]["end"]:
            quiet[-1]["end"] = frame["end"]
        else:
            quiet.append({"start": frame["start"], "end": frame["end"]})
    return quiet


def _candidate(gap, before, after, quiet, speech, thresholds, classifier):
    source_id = gap["sourceId"]
    context = {"dispensable": None, "intentionalPause": None}
    if classifier is not None:
        context = classifier(before, after, gap)
    return {
        "sourceRange": gap,
        "evidence": {
            "quietRanges": [
                _source_interval(source_id, item["start"], item["end"])
                for item in quiet
            ],
            "speechRanges": [
                _source_interval(source_id, item["start"], item["end"])
                for item in speech
            ],
            "wordEdges": {
                "beforeEndTicks": ceil(before["end"] * 1_000_000),
                "afterStartTicks": floor(after["start"] * 1_000_000),
                "status": "observed",
            },
            "adjacentWords": {"before": before["text"], "after": after["text"]},
            "acousticObserved": True,
            "context": context,
            "quietThresholdRms": thresholds[0],
            "spectralThreshold": thresholds[1],
        },
    }


def pause_candidates(
    alignment, waveform, speech, source_id, *, context_classifier=None
):
    """Fuse aligned word neighbors with measured quiet intervals, not ASR gaps.

    Editorial context remains unknown unless a caller supplies source-bound
    observations. Independent acoustic observations do not establish that a
    silence is dispensable.
    """
    if not alignment or not waveform["frames"]:
        return []
    frames = waveform["frames"]
    quiet_limit = min(
        0.005, max(1e-5, float(np.quantile([f["rms"] for f in frames], 0.1)) * 1.5)
    )
    spectral_limit = max(
        1e-12, float(np.quantile([f["highFrequencyEnergy"] for f in frames], 0.1)) * 2
    )
    candidates = []
    for before, after in zip(alignment["words"], alignment["words"][1:]):
        if (
            not before["eligibleEdge"]
            or not after["eligibleEdge"]
            or after["start"] <= before["end"]
        ):
            continue
        quiet = _quiet_intervals(frames, before, after, quiet_limit, spectral_limit)
        if not quiet:
            continue
        interval = max(quiet, key=lambda item: item["end"] - item["start"])
        gap = _source_interval(source_id, interval["start"], interval["end"])
        candidates.append(
            _candidate(
                gap,
                before,
                after,
                quiet,
                speech,
                (quiet_limit, spectral_limit),
                context_classifier,
            )
        )
    return candidates


def _alignment_segments(words, source_start, duration):
    """Bound model inference windows without splitting a word or authoring cuts."""
    groups, current = [], []
    for word in words:
        if current and word["end"] - current[0]["start"] > 20:
            groups.append(current)
            current = []
        current.append(word)
    if current:
        groups.append(current)
    return [
        {
            "start": max(0, group[0]["start"] - source_start - 8),
            "end": min(duration, group[-1]["end"] - source_start + 8),
            "text": " ".join(word["text"] for word in group),
        }
        for group in groups
    ]
