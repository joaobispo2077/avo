# Animation design system — short-form vertical

> **Template.** Copy to project `DESIGN.md` or slot spec. Provider brand: `providers/<name>/DESIGN.md`.

## Status

- Project:
- Provider:
- Aspect: **9:16** · 1080×1920
- Max duration: ≤60s (Shorts shelf)

## Message

One hook + one payoff (short-form contract):

> 

## Canvas

| Field | Value |
| ----- | ----- |
| Width | 1080 |
| Height | 1920 |
| FPS | 30 |
| Safe zones | Top/bottom platform UI margins |

## Colors

| Role | Token | Usage |
| ---- | ----- | ----- |
| Canvas | | Ambient background base |
| Ink | | Captions default |
| Accent | | Active caption word, highlights |
| Seam | | y=960 feather band |

## Typography (captions)

| Role | Family | Weight | Size |
| ---- | ------ | ------ | ---- |
| Karaoke | | 900 | 46–58px |

Stroke: layered `text-shadow` — not `-webkit-text-stroke`.

## Face modes

| Mode | Use |
| ---- | --- |
| BOTTOM | Landscape face in lower half — overlay scenes on top |
| FULLSCREEN | Crop-cover — full portrait talking head |

Transition: 0.32s `expo.inOut`, start 0.15s before scene beat.

## Motion density

Default **Level 2–3** for Shorts motion phase — reduce when captions must be read.

## Related

- [`storyboard-short-form.md`](storyboard-short-form.md)
- [`docs/exemplars/hyperframes-short-form/technique-index.md`](../exemplars/hyperframes-short-form/technique-index.md)
