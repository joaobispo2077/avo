# EQ suggest knowledge (pipeline router)

Load when the user asks to **check EQ**, **evaluate mud/harshness**, or **audit dialogue tone** without changing the source file.

## Load order

1. [`guidelines-eq.md`](guidelines-eq.md)
2. [`loudness-knowledge.md`](loudness-knowledge.md)
3. This file

## Read-only workflow

1. **Analyze** — no media modification:

   ```bash
   python -m avo.audio_analysis <footage> --suggest-eq --out-dir edit/review/eq --eq-heatmap
   ```

2. **Present** — show table to user:

   | Time range | Issue | Severity | Recommendation |
   |------------|-------|----------|----------------|
   | 1:12–1:18 | mud | medium | Subtractive EQ ~250 Hz |
   | 4:02–4:09 | harsh | high | Tame 5–8 kHz |

3. **Confirm** — EQ suggestions are **informational only**. The render chain still uses the fixed conservative `EQ_CHAIN` until the user approves manual EQ work in a DAW or future per-band controls.

4. **Unified audit** — combine with loudness and NR in one pass:

   ```bash
   python -m avo.audio_audit <footage> --transcript edit/transcripts/<base>.json --project avo.project.json --out-dir edit/review
   ```

## Issue types

| Type | Meaning | Typical fix label |
|------|---------|-------------------|
| `rumble` | Sub-100 Hz excess | High-pass reminder |
| `mud` | 150–400 Hz buildup | Cut ~250 Hz |
| `thin` | Weak 2–4 kHz | Conservative presence boost |
| `harsh` | 5–8 kHz excess | De-ess / presence cut |

## Artifacts

- `edit/review/eq/eq-suggestions.json`
- Optional `eq-suggestions-heatmap.png`

Log substantial decisions in `AUDIO-EDITLOG.md`.
