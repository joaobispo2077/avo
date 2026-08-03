# Loudness profiles knowledge (pipeline router)

Load when the user asks about **platform loudness**, **LUFS targets**, **YouTube/Shorts/Reels/TikTok audio levels**, or **master normalization**.

## Load order

1. [`docs/audio-delivery-specifications.md`](../../../docs/audio-delivery-specifications.md)
2. [`agent-skills/avo-pipeline/references/guidelines-eq.md`](guidelines-eq.md)
3. This file

## Important copy rule

All preset labels are **reference presets — not official platform requirements**. YouTube upload docs specify codec/sample rate, not a mandated LUFS. Instagram/TikTok do not publish fixed LUFS targets.

## User intent (ask at project start or before final master)

| Intent | When to use |
| ------ | ----------- |
| `platform_fit` | Match deliverable profile (long-form, shorts, tiktok, …) |
| `channel_standard` | Provider-documented channel target (e.g. Bishop −16 LUFS speech-led) |
| `creative` | One-off target; requires `approved_by_user: true` if >3 LU from nearest preset |

Also ask **loudness range preference**: `tight` | `balanced` | `preserve_dynamics`.

## Reference presets (engine catalog)

| Preset id | Label | I (LUFS) | TP (dBTP) | LRA (LU) |
| --------- | ----- | -------- | --------- | -------- |
| `youtube_long_form_speech` | YouTube long-form speech | −16 | −1 | 9 |
| `youtube_shorts` | YouTube Shorts | −14 | −1 | 11 |
| `instagram_reels` | Instagram Reels | −14 | −1 | 11 |
| `tiktok` | TikTok | −14 | −1 | 11 |
| `music_video` | Music video | −14 | −1 | 8 |
| `podcast_clip` | Podcast clip | −16 | −1 | 11 |

## Persist in `avo.project.json`

```json
"deliverable": { "profile": "long-form" },
"audio": {
  "loudness_intent": "platform_fit",
  "loudness_preset": "youtube_long_form_speech",
  "loudness_range_preference": "balanced",
  "loudnorm_enabled": true
}
```

Provider channel standard lives in `providers/<slug>/avo.provider.json` under `loudness.channel_standard`.

## Pre-master analysis

```bash
python -m avo.audio_analysis edit/base_preview.mp4 --measure-loudness \
  --project ../avo.project.json --edl edl.json --out-dir edit/review
```

Writes `edit/review/loudness-analysis.json` with measured vs target and warnings.

## Render

Uses resolved profile automatically. Override for one render:

```bash
python -m avo.render edl.json -o master.mp4 --loudness-preset youtube_shorts
```

Skip normalization: `--no-loudnorm` or `"loudnorm_enabled": false`.

## Audio QC CLI

```bash
python -m avo.audio_qc edit/masters/master.mp4 --project ../avo.project.json --edl edl.json \
  --out edit/review/audio-qc.json
```

Pass/fail: integrated ±1 LU, true peak ≤ target, upload candidate TP delta ≤ 0.3 dBTP.

## Pipeline order (never reverse)

**EQ/NR at segment extract → mix/composite → loudnorm at final master**

Warn when NR segments >50% and target integrated ≥ −14 LUFS.

## Multi-platform

One loudness profile per master render. Long-form + Shorts = separate masters with distinct presets documented in `AUDIO-EDITLOG.md`.
