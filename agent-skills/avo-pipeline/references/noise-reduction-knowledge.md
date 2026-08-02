# Noise reduction knowledge (pipeline router)

Load when the user or brief asks for **noise reduction**, **denoise**, **room noise**, **hiss**, or **cleaner dialogue** on existing footage.

## Load order

1. [`docs/audio-post-production-system.md`](../../../docs/audio-post-production-system.md)
2. [`agent-skills/avo-pipeline/references/guidelines-eq.md`](guidelines-eq.md)
3. This file

## Workflow (`noise-reduction` mode)

1. **Analyze** — run suggestions before applying NR:

   ```bash
   python -m avo.audio_analysis <footage> --suggest-nr --transcript edit/transcripts/<base>.json --out-dir edit/review/noise --heatmap
   ```

2. **Present** — show table to user:

   | Time range | Suggested % | Label | Confidence | Reason |
   |------------|-------------|-------|------------|--------|
   | 0:45–0:52 | 70% | Strong | high | high_hiss |

3. **Confirm** — user approves regions and may edit %. Segments **> 50%** require explicit approval.

4. **Persist** — write to `edit/edl.json`:

   ```json
   "audio": {
     "noise_reduction_policy": "conservative_speech_first",
     "restoration_default_pct": 35,
     "restoration_segments": [
       {
         "start_in_source": 45.0,
         "end_in_source": 52.5,
         "strength_pct": 70,
         "reason": "high_hiss",
         "approved_by_user": true
       }
     ]
   }
   ```

5. **Optional preview** — before master promotion:

   ```bash
   python -m avo.audio_analysis <footage> --preview-segment 45 52.5 --strength-pct 70 --out-dir edit/review/noise
   ```

6. **Re-render proof** — segment extract applies per-range strength automatically.

7. **Log** — record default %, segments, and artifact paths in `AUDIO-EDITLOG.md`.

## Percent presets

| Name | % | Use |
|------|---|-----|
| Light | 25 | Minimal cleanup |
| Standard | 35 | Default (matches legacy `nr=8`) |
| Medium | 50 | Noticeable NR |
| Strong | 70 | Segment-only; user approval |
| Aggressive | 85 | Rare; user approval |

Engine cap: **100% → nr ≤ 22 dB**. Never expose raw FFmpeg dB to creators.

## Provider default

Optional `restoration_default_pct` in provider manifest (see `providers/_template/`). EDL explicit values win.
