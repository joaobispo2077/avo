# /avo.motion reference

HyperFrames-first. Load [`hyperframes`](../../../.claude/skills/hyperframes/SKILL.md) entry + [`motion-doctrine`](../../../.claude/skills/motion-doctrine/SKILL.md) when building slots.

**Product promo / SaaS launch:** load [`product-promo-knowledge.md`](product-promo-knowledge.md) first — curated technique index, render contract, and starter exemplar under `docs/exemplars/hyperframes-product-promo/`.

**Short-form vertical (9:16):** load [`short-form-knowledge.md`](short-form-knowledge.md) — 4-layer scaffold, face-mode choreography, audio-sync protocol under `docs/exemplars/hyperframes-short-form/`.

## Density

Default Level 2–3 for explainers; Level 1 for read-heavy segments.

## Common intents → commands

| User asks for | Command / skill |
| ------------- | --------------- |
| Liquid glass cards | [`talking-head.md`](talking-head.md) → talking-head-recut |
| Captions | [`captions.md`](captions.md) → embedded-captions |
| Logo spin / lower third | [`talking-head.md`](talking-head.md) or slot via this command |
| Logo melt / morph | [`general.md`](general.md) → general-video |
| Short motion graphic | [`motion-graphics.md`](motion-graphics.md) |
| Remotion → HyperFrames port | [`remotion-port.md`](remotion-port.md) |
| Screencast oversized cursor | [`screencast.md`](screencast.md) |
| Framework pick (HF vs Remotion) | [`framework.md`](framework.md) — run before first slot |
| Product promo / SaaS demo | [`product-promo-knowledge.md`](product-promo-knowledge.md) → product-launch-video |
| Short-form 9:16 + overlays | [`short-form-knowledge.md`](short-form-knowledge.md) → `/avo.shorts` motion phase |

Run [`framework.md`](framework.md) when framework choice is not already documented.

## Slot layout

```
edit/animations/slot_<id>/
  spec.md
  composition/
  render.mp4
```

Spawn **parallel** sub-agents for multiple slots (SKILL Hard Rule 10).

## Beat map (required before creator review)

Overlays/SFX must store **`anchor_in_source`** (main camera seconds). After any
cut change, recompute `start_in_output` — see [`cuts.md`](cuts.md).

Write **`edit/animations/beat-map.md`** with B-time table (or run
`python -m avo.edl_timeline write-docs edit/edl.json`). Link from `motion_notes`.

## Examples shipped in command

- Cursor logo → liquid glass card spin
- OpenAI logo from folder → melt into verdict card

Preserve brand assets; never invent trademarked logos when user supplies a path.
