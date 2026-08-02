# Delivery Specifications

**Verification date**: 2026-07-19

## Source Links

- YouTube upload encoding: https://support.google.com/youtube/answer/1722171
- YouTube aspect ratios: https://support.google.com/youtube/answer/6375112
- YouTube formatting specs: https://support.google.com/youtube/answer/4603579
- YouTube captions: https://support.google.com/youtube/answer/2734796
- YouTube caption editing: https://support.google.com/youtube/answer/2734705
- YouTube chapters: https://support.google.com/youtube/answer/9884579
- YouTube end screens: https://support.google.com/youtube/answer/6388789

For detailed audio measurement and delivery checks, use
`docs/audio-delivery-specifications.md`.

## YouTube Master Expectations

Use current YouTube documentation before every final delivery. Unless the
project documents a different target:

- Export at the same frame rate as recorded/edited.
- Use progressive scan, square pixels, and native aspect ratio.
- Avoid added letterboxing, pillarboxing, padding, stretch, or accidental crop.
- Use a YouTube-supported resolution and aspect ratio.
- Prefer high-quality MP4/H.264, H.265, AV1, or a workflow-appropriate
  mezzanine/upload master.
- Use high-quality YouTube-supported audio, normally AAC-LC or equivalent.
- Use 48 kHz audio for standard YouTube masters.
- Avoid unnecessary re-encoding generations.
- Preserve the highest practical source quality before YouTube recompression.

## Project-Specific Targets

Fill these per video or channel:

| Field | Requirement |
|---|---|
| Resolution | TBD |
| Aspect ratio | TBD |
| Frame rate | Match source/sequence unless documented otherwise |
| Audio sample rate | 48 kHz for standard YouTube master |
| Loudness target | Channel standard TBD; prioritize intelligibility/headroom |
| Captions | Corrected captions required when practical |
| Thumbnail | Truthful candidate frames/contact sheet when requested |
| Derivatives | Shorts (9:16, ≤60s default): [`templates/delivery/delivery-manifest.md`](templates/delivery/delivery-manifest.md); vertical clips via `/avo.reframe`; podcast clips via `/avo.podcast-clip`; trailers via `/avo.trailer`; chapters via `/avo.chapters`; thumbnails via `/avo.thumbnail` |

## Export Types

- **Review exports**: compressed versions for feedback; immutable and versioned.
- **Mezzanine masters**: high-quality archive/intermediate files for future
  derivatives or re-encoding.
- **Upload masters**: YouTube-ready files matching current delivery target.
- **Archive masters**: final retained masters plus captions, thumbnails,
  source logs, edit logs, and rights evidence.

## Delivery Verification

Before upload, verify frame rate, resolution, aspect ratio, codec/container,
progressive output, sample rate, channel mapping, captions, chapters, clean
start/end, thumbnail assets, end-screen space, and `SOURCE-LOG.md`/`EDITLOG.md`
status.
