"""Check actual decoded boundary signal against declared original selections."""

from __future__ import annotations

from fractions import Fraction
from math import isfinite
from pathlib import Path

import numpy as np

from avo.adapters.media.cutting_audio import _execute, extract_dialogue_pcm, read_pcm
from avo.adapters.media.proof_executor import _dialogue_noise_filter
from avo.audio_restoration import validate_dialogue_noise_policy
from avo.timeline.contracts import content_hash
from avo.timeline.ports import ToolError
from avo.transcribe import source_fingerprint


def _signal_check(expected, actual):
    energy = float(np.dot(expected, expected))
    actual_energy = float(np.dot(actual, actual))
    if energy <= 1e-12:
        return {
            "status": "blocked",
            "reason": "retained speech reference has no observed signal",
        }
    if actual_energy <= energy * 0.01:
        return {"status": "fail", "reason": "retained signal is missing or attenuated"}
    gain = float(np.dot(expected, actual) / energy)
    correlation = float(np.dot(expected, actual) / np.sqrt(energy * actual_energy))
    residual = float(
        np.sqrt(np.mean((actual - expected * gain) ** 2)) / np.sqrt(np.mean(actual**2))
    )
    return {
        "status": "pass" if correlation >= 0.98 and residual <= 0.2 else "fail",
        "correlation": correlation,
        "normalizedResidual": residual,
        "measuredGain": gain,
    }


def _edge_problem(edge, sample_rate, count):
    start, end = edge.get("start"), edge.get("end")
    if not isinstance(start, (float, int)) or not isinstance(end, (float, int)):
        return "retained edge clock is invalid"
    if (
        not isfinite(start)
        or not isfinite(end)
        or not 0 <= start < end <= count / sample_rate
    ):
        return "retained edge clock is invalid"
    if edge.get("observed") is not True and edge.get("status") != "observed":
        return "retained word edges are estimated or unobserved"
    return None


def _near_word(first, hop, rate, edges):
    return any(
        first / rate < edge["end"] + 0.04
        and (first + hop) / rate > edge["start"] - 0.04
        for edge in edges
    )


def _extra_signal(reference, observed):
    reference_rms = float(np.sqrt(np.mean(reference**2)))
    observed_rms = float(np.sqrt(np.mean(observed**2)))
    return reference_rms < 0.001 and observed_rms > max(0.003, reference_rms * 4)


def _quiet_checks(expected, actual, sample_rate, word_edges):
    checks, hop = [], max(1, round(sample_rate * 0.01))
    for first in range(0, len(expected), hop):
        if _near_word(first, hop, sample_rate, word_edges):
            continue
        if _extra_signal(expected[first : first + hop], actual[first : first + hop]):
            checks.append(
                {
                    "kind": "unexpected-signal",
                    "status": "fail",
                    "start": first / sample_rate,
                    "reason": "unexpected audible signal in declared quiet source space",
                }
            )
    return checks


def _word_checks(edge, expected, actual, rate, fades):
    start, end = edge["start"], edge["end"]
    if any(fade["start"] < end and start < fade["end"] for fade in fades):
        return [
            {
                "word": edge.get("text"),
                "kind": "envelope",
                "status": "fail",
                "reason": "effective fade touches retained speech",
            }
        ]
    first, last = round(start * rate), round(end * rate)
    margin = min(round(rate * 0.02), max(1, (last - first) // 2))
    spans = (
        ("unit", first, last),
        ("onset", first, first + margin),
        ("tail", last - margin, last),
    )
    return [
        {
            "word": edge.get("text"),
            "kind": label,
            **_signal_check(expected[low:high], actual[low:high]),
        }
        for label, low, high in spans
    ]


def _check_status(checks):
    states = {check["status"] for check in checks}
    if "fail" in states:
        return "fail"
    return "blocked" if "blocked" in states else "pass"


def compare_retained_signal(
    expected, actual, sample_rate, word_edges, *, fade_ranges=()
):
    """Physical conformance check, not an ASR or human listening claim."""
    expected, actual = (
        np.asarray(expected, dtype=float),
        np.asarray(actual, dtype=float),
    )
    if not word_edges:
        return {
            "status": "blocked",
            "checks": [],
            "reason": "observed retained word edges are missing",
        }
    for edge in word_edges:
        problem = _edge_problem(edge, sample_rate, len(expected))
        if problem:
            return {"status": "blocked", "checks": [], "reason": problem}
    if len(expected) != len(actual) or not np.isfinite(actual).all():
        return {
            "status": "fail",
            "checks": [],
            "reason": "decoded sample coverage differs from declared original selection",
        }
    checks = _quiet_checks(expected, actual, sample_rate, word_edges)
    for edge in word_edges:
        checks.extend(_word_checks(edge, expected, actual, sample_rate, fade_ranges))
    return {
        "status": _check_status(checks),
        "checks": checks,
        "sampleRate": sample_rate,
    }


def _recipe_window(recipe, node):
    length = (
        node["outputRange"]["endSampleExclusive"] - node["outputRange"]["startSample"]
    )
    values = [
        *recipe["fadeSamples"],
        recipe["windowOffsetSamples"],
        recipe["windowLengthSamples"],
    ]
    if len(recipe["fadeSamples"]) != 2 or any(
        type(x) is not int or x < 0 for x in values
    ):
        raise ValueError("native reference requires exact integer sample bounds")
    if not 0 < values[3] or values[2] + values[3] > length or max(values[:2]) > length:
        raise ValueError("native reference window/fades exceed complete node")
    return length


def _native_recipe_basis(entry):
    recipe = entry["processing"]
    keys = {
        "recipe",
        "node",
        "dialogueNoiseReductionPolicy",
        "fadeSamples",
        "windowOffsetSamples",
        "windowLengthSamples",
    }
    if set(recipe) != keys or recipe["recipe"] != "native-dialogue-v1":
        raise ValueError("unsupported dialogue reference recipe")
    node, selection = recipe["node"], entry["selection"]
    rate = node["sourceSampleRate"]
    bounds, span = node["sourceRange"], entry["source_range"]
    timebase = Fraction(span["timebase"]["num"], span["timebase"]["den"])
    if (
        node["targetSampleRate"] != 48000
        or span["startTicks"] * timebase * rate != bounds["startSample"]
        or span["endTicksExclusive"] * timebase * rate != bounds["endSampleExclusive"]
    ):
        raise ValueError("native reference requires exact complete source node")
    policy = _native_policy(recipe, node, selection)
    if entry.get("gainDb", 0):
        raise ValueError("native reference gain differs from supported recipe")
    return recipe, node, policy, _recipe_window(recipe, node)


def _native_policy(recipe, node, selection):
    policy = recipe["dialogueNoiseReductionPolicy"]
    if policy is not None:
        policy = validate_dialogue_noise_policy(
            policy, selection["streamIndex"], node["channelMap"]
        )
    if list(dict.fromkeys(node["channelMap"])) != selection["channels"]:
        raise ValueError(
            "native reference routing differs from selected original channels"
        )
    return policy


def _native_reference(entry, output_dir):
    recipe, node, policy, length = _native_recipe_basis(entry)
    # Extraction validates the fingerprint, Sync ref, actual rate and routing.
    decoded = extract_dialogue_pcm(
        entry["source"],
        **{
            key: entry[key]
            for key in ("selection", "source_range", "fingerprint", "sync_ref")
        },
        output_dir=output_dir,
    )
    if decoded["sampleRate"] != node["sourceSampleRate"]:
        raise ValueError("native recipe source sample rate differs from original")
    bounds = node["sourceRange"]
    raw_length = bounds["endSampleExclusive"] - bounds["startSample"]
    chain = f"atrim=end_sample={raw_length},asetpts=PTS-STARTPTS"
    if node["sourceSampleRate"] != 48000:
        chain += ",aresample=48000"
    chain += _dialogue_noise_filter(policy, node) + f",apad,atrim=end_sample={length}"
    fade_in, fade_out = recipe["fadeSamples"]
    if fade_in:
        chain += f",afade=t=in:ss=0:ns={fade_in}"
    if fade_out:
        chain += f",afade=t=out:ss={length - fade_out}:ns={fade_out}"
    offset, count = recipe["windowOffsetSamples"], recipe["windowLengthSamples"]
    chain += (
        f",atrim=start_sample={offset}:end_sample={offset + count},asetpts=PTS-STARTPTS"
    )
    chain += ",pan=mono|c0=0.5*c0+0.5*c1"
    destination = output_dir / (content_hash(recipe) + "-processed.wav")
    _execute(
        [
            "ffmpeg",
            "-v",
            "error",
            "-nostdin",
            "-y",
            "-ss",
            str(bounds["startSample"] / node["sourceSampleRate"]),
            "-i",
            str(entry["source"]),
            "-map",
            f"0:{entry['selection']['streamIndex']}",
            "-af",
            chain,
            "-c:a",
            "pcm_s32le",
            str(destination),
        ]
    )
    samples, _rate = read_pcm(destination)
    return samples[:, 0].astype(float)


def _native_package_reference(entries, output_dir):
    from scipy.io import wavfile

    if not all(entry.get("processing") for entry in entries):
        raise ValueError("mixed native and unknown audio reference recipes")
    samples = np.concatenate(
        [_native_reference(entry, output_dir) for entry in entries]
    )
    original, derivative = (
        output_dir / "package-native.wav",
        output_dir / "package-analysis.wav",
    )
    wavfile.write(
        original, 48000, np.clip(samples * 2**31, -(2**31), 2**31 - 1).astype("int32")
    )
    _execute(
        [
            "ffmpeg",
            "-v",
            "error",
            "-nostdin",
            "-y",
            "-i",
            str(original),
            "-af",
            "aresample=16000",
            "-c:a",
            "pcm_s16le",
            str(derivative),
        ]
    )
    return read_pcm(derivative)[0][:, 0].astype(float)


def _reference_audio(entries, output_dir):
    entries = [entries] if isinstance(entries, dict) else entries
    if any(entry.get("processing") for entry in entries):
        return _native_package_reference(entries, output_dir)
    audio = []
    for entry in entries:
        decoded = extract_dialogue_pcm(
            entry["source"],
            **{
                key: entry[key]
                for key in ("selection", "source_range", "fingerprint", "sync_ref")
            },
            output_dir=output_dir,
        )
        samples, rate = read_pcm(Path(decoded["analysisPath"]))
        samples = samples[:, 0].astype(float)
        samples *= 10 ** (entry.get("gainDb", 0) / 20)
        for name, reverse in (("fadeInSeconds", False), ("fadeOutSeconds", True)):
            count = round(entry.get(name, 0) * rate)
            if count:
                ramp = np.linspace(0, 1, count)
                if reverse:
                    samples[-count:] *= ramp[::-1]
                else:
                    samples[:count] *= ramp
        audio.append(samples)
    if not audio:
        raise ToolError(
            "cutting-boundary-reference", "original audio selection is missing"
        )
    return np.concatenate(audio)


def _verify_window(candidate, fingerprint, window, request, output_dir):
    try:
        if window.get("retainedWordEdges") is None or window.get("fadeRanges") is None:
            raise ToolError(
                "cutting-boundary-basis",
                "word/envelope observations are missing",
            )
        start, end = window["localStartSeconds"], window["localEndSeconds"]
        decoded = extract_dialogue_pcm(
            candidate,
            selection=request["candidate_selection"],
            source_range={
                "sourceId": "candidate",
                "startTicks": round(start * 1_000_000),
                "endTicksExclusive": round(end * 1_000_000),
                "timebase": {"num": 1, "den": 1_000_000},
            },
            fingerprint=fingerprint,
            sync_ref=window["expectedAudio"][0]["sync_ref"]
            if isinstance(window["expectedAudio"], list)
            else window["expectedAudio"]["sync_ref"],
            output_dir=output_dir / "candidate",
        )
        actual, rate = read_pcm(Path(decoded["analysisPath"]))
        expected = _reference_audio(window["expectedAudio"], output_dir / "originals")
        result = compare_retained_signal(
            expected,
            actual[:, 0],
            rate,
            window["retainedWordEdges"],
            fade_ranges=window["fadeRanges"],
        )
    except (ToolError, OSError, ValueError, KeyError) as exc:
        result = {
            "status": "blocked",
            "checks": [{"kind": "basis", "status": "blocked", "reason": str(exc)}],
        }
    return result


def _basis_missing(request, required):
    return (
        not required
        or not request.get("windows")
        or not request.get("candidate_selection")
        or not request.get("proof_plan_ref")
        or not request.get("graph_hash")
    )


def _verification_status(payload, required):
    covered = set(payload["occurrenceCoverage"])
    states = {
        item["status"] for item in payload["checks"] if item["kind"] == "occurrence"
    }
    if "fail" in states:
        return "fail"
    return "blocked" if "blocked" in states or not required <= covered else "pass"


class CuttingBoundaryVerifier:
    def __init__(self, output_dir: Path):
        self.output_dir = Path(output_dir)

    def verify(self, candidate: Path, **request):
        if not request.get("proposal_ref"):
            raise ToolError(
                "cutting-boundary-basis", "exact proposal reference is required"
            )
        fingerprint = source_fingerprint(candidate)
        payload = {
            "candidateRef": {
                "locator": str(candidate),
                "sha256": fingerprint["sha256"],
            },
            "proposalRef": request.get("proposal_ref"),
            "proofPlanRef": request.get("proof_plan_ref"),
            "graphHash": request.get("graph_hash"),
            "occurrenceCoverage": [],
            "clockMaps": request.get("clock_maps", []),
            "checks": [],
            "status": "blocked",
        }
        required = set(request.get("required_occurrences", []))
        for name in ("proofPlanRef", "graphHash"):
            if payload[name] is None:
                del payload[name]
        if _basis_missing(request, required):
            payload["checks"].append(
                {
                    "kind": "basis",
                    "status": "blocked",
                    "reason": "exact original/word/envelope review basis is missing",
                }
            )
            return payload
        for window in request["windows"]:
            result = _verify_window(
                candidate, fingerprint, window, request, self.output_dir
            )
            if result["status"] != "blocked":
                payload["occurrenceCoverage"].append(window["occurrenceId"])
            payload["checks"].append(
                {
                    "kind": "occurrence",
                    "occurrenceId": window["occurrenceId"],
                    "status": result["status"],
                    "reason": result.get("reason"),
                }
            )
            payload["checks"].extend(result["checks"])
        payload["status"] = _verification_status(payload, required)
        return payload
