"""Generate original neutral tutorial/comparison sound effects locally."""

from __future__ import annotations

import argparse
import hashlib
import math
import random
import struct
import wave
from pathlib import Path

SAMPLE_RATE = 48000
EFFECT_NAMES = (
    "transfer_whoosh",
    "warning_hit",
    "soft_whoosh",
    "tick",
    "price_pop",
    "cash_register_money",
    "coin_tick",
    "receipt_print",
    "card_confirm",
    "switch_ui_click",
    "switch_ui_chime",
    "soft_transition",
    "transition_hit",
    "verification_chime",
)
DEFAULT_FILENAMES = {
    "transfer_whoosh": "transfer-whoosh.wav",
    "warning_hit": "warning-hit.wav",
    "soft_whoosh": "soft-whoosh.wav",
    "tick": "tick.wav",
    "price_pop": "price-pop.wav",
    "cash_register_money": "cash-register-money.wav",
    "coin_tick": "coin-tick.wav",
    "receipt_print": "receipt-print.wav",
    "card_confirm": "card-confirm.wav",
    "switch_ui_click": "switch-ui-click.wav",
    "switch_ui_chime": "switch-ui-chime.wav",
    "soft_transition": "soft-transition.wav",
    "transition_hit": "transition-hit.wav",
    "verification_chime": "verification-chime.wav",
}


def _fade(index: int, count: int, fade_in: int, fade_out: int) -> float:
    if fade_in and index < fade_in:
        return index / float(fade_in)
    if fade_out and index >= count - fade_out:
        return max(0.0, (count - index - 1) / float(fade_out))
    return 1.0


def _duration(effect: str) -> float:
    return {
        "transfer_whoosh": 0.72,
        "warning_hit": 0.46,
        "soft_whoosh": 0.72,
        "tick": 0.12,
        "price_pop": 0.28,
        "cash_register_money": 0.52,
        "coin_tick": 0.18,
        "receipt_print": 0.62,
        "card_confirm": 0.42,
        "switch_ui_click": 0.13,
        "switch_ui_chime": 0.48,
        "soft_transition": 0.55,
        "transition_hit": 0.46,
        "verification_chime": 0.88,
    }[effect]


def _samples(effect: str) -> list[tuple[float, float]]:
    rng = random.Random(20260719 + sum(ord(ch) for ch in effect))
    duration = _duration(effect)
    count = int(SAMPLE_RATE * duration)
    out: list[tuple[float, float]] = []
    for i in range(count):
        t = i / SAMPLE_RATE
        env = _fade(i, count, int(0.008 * SAMPLE_RATE), int(0.08 * SAMPLE_RATE))

        if effect in {"transfer_whoosh", "soft_whoosh"}:
            sweep = math.sin(2.0 * math.pi * (170.0 * t + 720.0 * t * t))
            noise = (rng.random() * 2.0 - 1.0) * 0.35
            mono = (0.18 * sweep + 0.25 * noise) * (math.sin(math.pi * t / duration) ** 1.8) * env
            if effect == "soft_whoosh":
                mono *= 0.55
            pan = -0.65 + 1.3 * (i / max(1, count - 1))
        elif effect in {"warning_hit", "transition_hit"}:
            mono = (
                0.78 * math.sin(2.0 * math.pi * 92.0 * t)
                + 0.24 * math.sin(2.0 * math.pi * 184.0 * t)
                + 0.08 * (rng.random() * 2.0 - 1.0) * math.exp(-70.0 * t)
            ) * math.exp(-9.5 * t) * env
            if effect == "transition_hit":
                mono *= 0.62
            pan = 0.0
        elif effect == "tick":
            mono = math.sin(2.0 * math.pi * 1800.0 * t) * math.exp(-70.0 * t) * env
            pan = 0.0
        elif effect == "price_pop":
            mono = (
                math.sin(2.0 * math.pi * 420.0 * t) * math.exp(-18.0 * t)
                + 0.35 * math.sin(2.0 * math.pi * 1120.0 * t) * math.exp(-24.0 * t)
            ) * env
            pan = -0.2 + 0.4 * (i / max(1, count - 1))
        elif effect == "cash_register_money":
            bell = math.sin(2.0 * math.pi * 1180.0 * t) * math.exp(-11.0 * t)
            drawer = math.sin(2.0 * math.pi * 115.0 * max(0.0, t - 0.08)) * math.exp(-7.0 * max(0.0, t - 0.08))
            click = (1.0 if 0.045 < t < 0.058 else 0.0) * (rng.random() * 2.0 - 1.0)
            mono = (0.48 * bell + 0.42 * drawer + 0.12 * click) * env
            pan = -0.18 + 0.36 * (i / max(1, count - 1))
        elif effect == "coin_tick":
            mono = (
                math.sin(2.0 * math.pi * 2450.0 * t) * math.exp(-55.0 * t)
                + 0.4 * math.sin(2.0 * math.pi * 3200.0 * max(0.0, t - 0.035)) * math.exp(-65.0 * max(0.0, t - 0.035))
            ) * env
            pan = 0.15
        elif effect == "receipt_print":
            pulses = 0.0
            for n in range(7):
                tt = t - (0.05 + n * 0.055)
                if 0 <= tt < 0.035:
                    pulses += (rng.random() * 2.0 - 1.0) * math.exp(-38.0 * tt)
            mono = (0.22 * pulses + 0.08 * math.sin(2.0 * math.pi * 900.0 * t)) * env
            pan = -0.1 + 0.2 * (i / max(1, count - 1))
        elif effect == "card_confirm":
            first = math.sin(2.0 * math.pi * 740.0 * t) * math.exp(-12.0 * t)
            tt = max(0.0, t - 0.13)
            second = math.sin(2.0 * math.pi * 1046.5 * tt) * math.exp(-12.0 * tt) if t >= 0.13 else 0.0
            mono = (0.42 * first + 0.5 * second) * env
            pan = 0.0
        elif effect == "switch_ui_click":
            mono = (math.sin(2.0 * math.pi * 1650.0 * t) + 0.18 * math.sin(2.0 * math.pi * 3300.0 * t)) * math.exp(-75.0 * t) * env
            pan = 0.0
        elif effect == "switch_ui_chime":
            first = math.sin(2.0 * math.pi * 587.33 * t) * math.exp(-9.0 * t)
            tt = max(0.0, t - 0.09)
            second = math.sin(2.0 * math.pi * 783.99 * tt) * math.exp(-8.0 * tt) if t >= 0.09 else 0.0
            mono = (0.36 * first + 0.48 * second) * env
            pan = 0.0
        elif effect == "soft_transition":
            sweep = math.sin(2.0 * math.pi * (260.0 * t + 300.0 * t * t))
            mono = 0.18 * sweep * (math.sin(math.pi * t / duration) ** 1.6) * env
            pan = -0.35 + 0.7 * (i / max(1, count - 1))
        elif effect == "verification_chime":
            first = math.sin(2.0 * math.pi * 659.25 * t) * math.exp(-5.2 * t)
            second = 0.0
            if t >= 0.16:
                tt = t - 0.16
                second = math.sin(2.0 * math.pi * 880.0 * tt) * math.exp(-5.8 * tt)
            shimmer = 0.15 * math.sin(2.0 * math.pi * 1320.0 * t) * math.exp(-7.0 * t)
            mono = (0.54 * first + 0.62 * second + shimmer) * env
            pan = 0.0
        else:
            raise ValueError(f"unknown effect {effect!r}; choose from {EFFECT_NAMES}")

        left = mono * math.sqrt((1.0 - pan) / 2.0)
        right = mono * math.sqrt((1.0 + pan) / 2.0)
        out.append((left, right))
    return out


def _to_pcm16(samples: list[tuple[float, float]]) -> bytes:
    peak = max(max(abs(left), abs(right)) for left, right in samples)
    if not math.isfinite(peak) or peak <= 0:
        raise ValueError("generated effect has no finite signal")
    scale = 0.68 / peak
    frames = bytearray()
    for left, right in samples:
        frames.extend(struct.pack("<h", int(max(-1.0, min(1.0, left * scale)) * 32767)))
        frames.extend(struct.pack("<h", int(max(-1.0, min(1.0, right * scale)) * 32767)))
    return bytes(frames)


def generate_effect(name: str, output: Path) -> dict[str, object]:
    if name not in EFFECT_NAMES:
        raise ValueError(f"unknown effect {name!r}; choose from {EFFECT_NAMES}")
    samples = _samples(name)
    pcm = _to_pcm16(samples)
    output.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(output), "wb") as wav:
        wav.setnchannels(2)
        wav.setsampwidth(2)
        wav.setframerate(SAMPLE_RATE)
        wav.writeframes(pcm)
    return {
        "effect": name,
        "path": str(output),
        "sample_rate_hz": SAMPLE_RATE,
        "channels": 2,
        "duration_seconds": round(len(samples) / SAMPLE_RATE, 3),
        "sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--effect", choices=EFFECT_NAMES)
    group.add_argument("--all", action="store_true")
    parser.add_argument("-o", "--output", type=Path)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()

    if args.effect:
        if args.output is None:
            parser.error("--effect requires --output")
        print(generate_effect(args.effect, args.output))
        return

    if args.output_dir is None:
        parser.error("--all requires --output-dir")
    for name in EFFECT_NAMES:
        result = generate_effect(name, args.output_dir / DEFAULT_FILENAMES[name])
        print(result)


if __name__ == "__main__":
    main()
