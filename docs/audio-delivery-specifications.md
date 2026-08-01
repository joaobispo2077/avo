# Audio Delivery Specifications

**Verification date**: 2026-07-19

## Source Links

- YouTube upload encoding: https://support.google.com/youtube/answer/1722171
- YouTube music-video audio specifications: https://support.google.com/youtube/answer/6039860
- YouTube reused content: https://support.google.com/youtube/answer/1311392
- YouTube altered or synthetic content disclosure: https://support.google.com/youtube/answer/14328491
- YouTube copyright help: https://support.google.com/youtube/topic/2676339
- ITU-R BS.1770: https://www.itu.int/rec/R-REC-BS.1770
- EBU R 128: https://tech.ebu.ch/publications/r128
- EBU Tech 3343: https://tech.ebu.ch/docs/tech/tech3343.pdf

## Standard YouTube Audio Expectations

Use current YouTube upload documentation before every final delivery. Unless the
project documents a different target:

- Use 48 kHz audio for standard YouTube masters.
- Use a YouTube-supported codec/container for the chosen master type.
- Confirm stereo, 5.1, or other channel layout intentionally.
- Avoid unexpected silence, clipped peaks, doubled audio, pops, sync drift, and
  wrong channel mapping.
- For MP4 delivery, follow current YouTube guidance for fast-start upload files.

## Music Video And Partner Deliveries

Use YouTube music-video specifications only when the project is a music-video or
partner delivery that requires them. Prefer lossless audio delivery when that
workflow applies. Preserve musical dynamics unless a documented mastering target
requires otherwise.

## Project-Specific Audio Targets

Fill these per video or channel:

| Field | Requirement |
|---|---|
| Sample rate | 48 kHz for standard YouTube master unless documented otherwise |
| Bit depth | TBD by workflow/master type |
| Codec/container | TBD by delivery type |
| Channel layout | TBD: mono, stereo, 5.1, Eclipsa, or other documented target |
| Loudness target | Channel standard TBD; not an official YouTube mandate |
| True-peak ceiling | Channel standard TBD |
| Measurement standard | TBD: e.g. ITU-R BS.1770 or EBU R 128-style settings |
| Device checks | Headphones, mobile/laptop, TV-style playback when practical |
| Rights/disclosure | `AUDIO-SOURCE-LOG.md`/`SOURCE-LOG.md` reviewed |

## Measurement Notes

- Measure the full approved program, not only a representative excerpt.
- Re-check the encoded upload candidate because codec/export changes can affect
  true peaks.
- Use true-peak checks, not sample peaks alone.
- Record integrated loudness, loudness range when useful, short-term/momentary
  values when useful, true peak, meter standard/settings, and measurement date.
- Keep LUFS/LKFS, LU, and dBTP separate.

## Audio Delivery QC

Before upload or archive, verify:

- Dialogue intelligibility and mix hierarchy.
- Sync and drift across the full program.
- No clipping, pops, unexpected mutes, doubled audio, or bad fades.
- No distracting restoration artifacts.
- Correct sample rate, codec/container, channel layout, and metadata where
  relevant.
- Captions match final audio when captions are required.
- Audio rights, reused-content, AI/synthetic disclosure, sponsorship, privacy,
  and safety risks are reviewed.
