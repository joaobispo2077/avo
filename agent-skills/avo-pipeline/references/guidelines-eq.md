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
5. **Loudness intent:** `platform_fit`, `channel_standard`, or `creative` — see [`loudness-knowledge.md`](loudness-knowledge.md)
6. **Platform / deliverable profile:** long-form, shorts, tiktok, reels (maps to reference preset)
7. **Loudness range preference:** tight, balanced, or preserve_dynamics
8. **Delivery target:** documented channel loudness method (reference preset — not a universal YouTube number)

## EQ / restoration order (default)

1. Sync external audio before creative cutting
2. Gain-stage before EQ/compression
3. Subtractive fixes before presence boosts
4. Narrow hum notches; conservative noise prints
5. De-ess only harsh sibilance
6. **EQ/NR on segment extracts** (percent-based NR — see [`noise-reduction-knowledge.md`](noise-reduction-knowledge.md))
7. **Regional gain** on segment extracts when approved (`gain_segments[]` — see [`gain-knowledge.md`](gain-knowledge.md))
8. Mix hierarchy, then **loudnorm on final master** using resolved profile
9. Measure loudness + true peak on final export; re-check after encode

## Read-only evaluation (before apply)

| Goal | Command |
|------|---------|
| Full audit | `python -m avo.audio_audit <media> --project avo.project.json --out-dir edit/review` |
| Loudness only | `python -m avo.audio_analysis <media> --measure-loudness --project avo.project.json` |
| EQ suggest | `python -m avo.audio_analysis <media> --suggest-eq --eq-heatmap` |
| Gain suggest | `python -m avo.audio_analysis <media> --suggest-gain --transcript …` |

See [`eq-knowledge.md`](eq-knowledge.md) and [`gain-knowledge.md`](gain-knowledge.md). Audit mode never modifies source or master.

## Stop conditions

Back off when voices sound metallic, bubbly, phasey, or over-smoothed.

## After guidelines

Use `/avo.sound` for mix execution, or `/avo.pipeline` if full video path.
