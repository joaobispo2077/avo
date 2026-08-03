# Regional gain knowledge (level-match)

Load when the user asks to **boost quiet dialogue**, **level-match speech**, or fix **hard-to-hear sections** without re-cutting.

## Load order

1. [`guidelines-eq.md`](guidelines-eq.md)
2. [`loudness-knowledge.md`](loudness-knowledge.md)
3. This file

## Read-only suggest workflow

1. **Analyze** (requires word-timed transcript for best results):

   ```bash
   python -m avo.audio_analysis <footage> --suggest-gain --transcript edit/transcripts/<base>.json --out-dir edit/review/gain
   ```

2. **Present** — table of quiet regions:

   | Time range | Quiet score | Suggested boost % | Confidence |
   |------------|-------------|-------------------|------------|
   | 2:10–2:14 | 0.78 | 25% (Standard) | high |

3. **Preview** — before EDL persist:

   ```bash
   python -m avo.audio_analysis <footage> --preview-gain-segment 130 134 --boost-pct 25 --out-dir edit/review/gain
   ```

4. **Confirm** — segments **> 40%** require explicit user approval (same pattern as NR > 50%).

5. **Persist** — write to `edit/edl.json`:

   ```json
   "audio": {
     "gain_policy": "level_match_speech",
     "gain_default_pct": 0,
     "gain_segments": [
       {
         "start_in_source": 130.0,
         "end_in_source": 134.5,
         "boost_pct": 25,
         "reason": "quiet_dialogue",
         "approved_by_user": true
       }
     ]
   }
   ```

6. **Render** — gain applies at **segment extract**, before EQ/NR, then mix → loudnorm.

## Percent presets

| Label | Boost % | Approx dB |
|-------|---------|-----------|
| Light | 15 | +1.5 |
| Standard | 25 | +2.5 |
| Medium | 40 | +4.0 |
| Strong | 60 | +6.0 (approval required) |

Total boost is capped at **+6 dB** unless the segment is user-approved.

## Unified audit

```bash
python -m avo.audio_audit <footage> --transcript edit/transcripts/<base>.json --out-dir edit/review
```

The `gain` section of `audio-audit.json` mirrors `gain-suggestions.json`.

Log approved segments in `AUDIO-EDITLOG.md`.
