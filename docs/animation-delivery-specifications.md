# Animation Delivery Specifications

**Verification date**: 2026-07-19

Use current YouTube and framework documentation before every final delivery. Do
not hardcode stale bitrate or platform assumptions.

## Source Links

- YouTube upload encoding: https://support.google.com/youtube/answer/1722171
- YouTube altered or synthetic content disclosure: https://support.google.com/youtube/answer/14328491
- YouTube reused content: https://support.google.com/youtube/answer/1311392
- HyperFrames documentation: https://hyperframes.heygen.com/introduction
- Remotion documentation: https://www.remotion.dev/docs

## Project Targets

| Field | Requirement |
|---|---|
| Aspect ratio | TBD: 16:9, 9:16, 1:1, 4:5, or custom |
| Resolution | TBD by platform and project |
| Frame rate | Match source/sequence or documented delivery target |
| Codec/container | TBD by master type and platform |
| Alpha workflow | TBD: WebM/ProRes/PNG sequence or composited master |
| Color assumptions | SDR BT.709 unless project documents otherwise |
| Audio | See `docs/audio-delivery-specifications.md` |
| Captions | Must remain readable and matched to final audio when required |

## File Naming

Use immutable animation versions:

```text
project-animation-v001-board
project-animation-v002-layout
project-animation-v003-motion-pass
project-animation-v004-review
project-animation-v005-render-candidate
project-animation-v006-master
```

Never use `final-final`, overwrite approved review exports, or detach a render
from its source revision/snapshot.

## Snapshot Requirements

Capture or inspect important frames:

- First frame.
- Title/hook frame.
- Dense information frame.
- Every major reveal.
- Every transition family.
- Data/map/document/UI evidence frames.
- Caption-risk frames.
- Flashing/high-intensity frames.
- Final frame.

## Export QC

- Correct aspect ratio, resolution, frame rate, codec/container, alpha, color,
  and audio assumptions.
- No missing fonts/assets, unexpected transparency, black/white flash frames,
  flicker, crop/stretch, bad masks, or broken nested compositions.
- Motion is deterministic, seekable, and reproducible enough for the delivery
  risk.
- Text and captions are readable and on screen long enough.
- Data, maps, documents, UI, product visuals, and evidence remain accurate.
- No unsafe flashing or excessive motion.
- Rights, attribution, reused-content, and AI/synthetic disclosure records are
  complete.

## Delivery Manifest

For each delivered animation, record:

- Source revision or snapshot.
- Framework and version.
- Render command/settings.
- Output file path.
- Duration, resolution, frame rate, codec/container, alpha, audio status.
- Snapshot/check locations.
- QC reviewer and status.
- Rights/source-log status.
