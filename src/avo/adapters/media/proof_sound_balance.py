"""Measure bounded dialogue and post-duck SFX branches without changing the mix."""

import math
import re
import subprocess
from pathlib import Path

from avo.timeline.sound_mix_review import SPEECH_BAND_HZ

MAX_METER_SAMPLES = 30 * 48000
MAX_METERS = 16
MIX_METER = "avo_final_mix"


def balance_targets(nodes, effects, first, last):
    targets = {}
    for identifier, effect in effects.items():
        margin = effect.get("duck", {}).get("minimumDialogueMarginDb")
        if margin is None:
            continue
        region = nodes[identifier]["outputRange"]
        start, end = (
            max(first, region["startSample"]),
            min(last, region["endSampleExclusive"]),
        )
        if start >= end:
            continue
        targets[identifier] = {
            "nodeId": identifier,
            "minimumDialogueMarginDb": margin,
            "window": {"startSample": start, "endSampleExclusive": end},
            "localRange": (start - first, end - first),
        }
    return targets


def statistics_filter(name, fields):
    return f"astats@{name}=metadata=0:reset=0:measure_perchannel=none:measure_overall={fields}"


def attach_meter(filters, label, meter, local_range):
    first, last = local_range
    used, observed = label + "used", label + "observed"
    low, high = SPEECH_BAND_HZ
    filters.extend(
        [
            f"[{label}]asplit=2[{used}][{observed}]",
            f"[{observed}]highpass=f={low},lowpass=f={high},atrim=start_sample={first}:end_sample={last},"
            + statistics_filter(meter, "RMS_level+Number_of_samples")
            + f"[{meter}]",
        ]
    )
    return used


def _meter_outputs(meters):
    return [
        argument
        for name in meters.values()
        for stem in ("dialogue", "effect")
        for argument in ("-map", f"[{name}_{stem}]")
    ]


def analyze_balance(inputs, filters, targets, meters, directory):
    log = ""
    if meters:
        script = Path(directory) / "dialogue-balance.ffgraph"
        command = [
            "ffmpeg",
            "-v",
            "info",
            "-nostats",
            *inputs,
            "-filter_complex_script",
            str(script),
            "-map",
            "[out]",
            *_meter_outputs(meters),
            "-f",
            "null",
            "-",
        ]
        try:
            script.write_text(";\n".join(filters), encoding="utf-8")
            result = subprocess.run(command, capture_output=True, text=True, timeout=45)
            if result.returncode == 0:
                log = result.stderr
        except (OSError, subprocess.TimeoutExpired):
            pass
    return _summarize_dialogue_balance(log, targets, meters)


def statistic(log, meter, field):
    prefix = rf"^\[astats@{re.escape(meter)} @ [^\]]+\]\s+{re.escape(field)}:\s*([-+\w.]+)\s*$"
    matches = re.findall(prefix, log, flags=re.MULTILINE)
    if len(matches) != 1:
        raise ValueError(f"PCM statistics unavailable for {meter}: {field}")
    return float(matches[0])


def _rms(log, meter, count):
    if statistic(log, meter, "Number of samples") != count:
        raise ValueError("Dialogue balance differs from exact selected sample overlap")
    level = statistic(log, meter, "RMS level dB")
    if not math.isfinite(level) and level != -math.inf:
        raise ValueError("Non-finite dialogue balance signal")
    return None if level == -math.inf else level


def _balance(log, meter, target):
    first, last = target["localRange"]
    dialogue, effect = (
        _rms(log, f"{meter}_{stem}", last - first) for stem in ("dialogue", "effect")
    )
    return {
        "status": "measured",
        "dialogueRmsDbfs": dialogue,
        "effectRmsDbfs": effect,
    }


def _summarize_dialogue_balance(log, targets, meters):
    results = []
    for node_id, target in targets.items():
        meter = meters.get(node_id)
        observed = {"status": "bounded-review-required"}
        if meter is not None:
            try:
                observed = _balance(log, meter, target)
            except ValueError:
                observed = {"status": "measurement-unavailable"}
        results.append(
            {
                **{
                    key: target[key]
                    for key in ("nodeId", "window", "minimumDialogueMarginDb")
                },
                "bandHz": list(SPEECH_BAND_HZ),
                **observed,
            }
        )
    return results
