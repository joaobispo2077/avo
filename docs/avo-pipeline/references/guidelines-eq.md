# Guidelines: --eq

Audio EQ, restoration, and loudness guidelines for speech-led video.

## Load

- [`AGENTS.md`](../../../AGENTS.md) audio rules
- [`docs/audio-post-production-system.md`](../../audio-post-production-system.md)
- Skills when available: `audio-intake-and-diagnosis`, `dialogue-editing-and-restoration`, `audio-post-production`, `loudness-and-audio-delivery-qc`

## Diagnosis checklist

1. **Speech vs music priority:** dialogue lead unless performance/music video
2. **Sources:** mics, camera audio, recorder, system audio; sample rate and sync method
3. **Defects:** hum, rumble, clipping, plosives, mouth noise, broadband noise
4. **Mix hierarchy:** dialogue → critical source → music/SFX → ambience
5. **Delivery target:** documented channel loudness method (not a universal YouTube number)

## EQ / restoration order (default)

1. Sync external audio before creative cutting
2. Gain-stage before EQ/compression
3. Subtractive fixes before presence boosts
4. Narrow hum notches; conservative noise prints
5. De-ess only harsh sibilance
6. Measure loudness + true peak on final export; re-check after encode

## Stop conditions

Back off when voices sound metallic, bubbly, phasey, or over-smoothed.

## After guidelines

Use `/avo.sound` for mix execution, or `/avo.pipeline` if full video path.
