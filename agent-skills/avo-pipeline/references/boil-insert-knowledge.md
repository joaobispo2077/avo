# Boil insert knowledge (pipeline router)

Load when the user or brief asks for **wiggly**, **boiling**, **hand-drawn**, or **shaky** text/image/video **inserts** on existing footage.

## Load order

1. [`motion-doctrine`](../../../.claude/skills/motion-doctrine/SKILL.md)
2. [`hyperframes`](../../../.claude/skills/hyperframes/SKILL.md) entry
3. [`docs/exemplars/hyperframes-boil-insert/README.md`](../../../docs/exemplars/hyperframes-boil-insert/README.md)

## Skill routes

| Intent | Route |
| ------ | ----- |
| Short callout / quote (≤ ~10 s) | `motion-graphics` → `kinetic-type` |
| Name bar / lower-third | `motion-graphics` → `lower-thirds` |
| Graphic card on talking head | `talking-head-recut` (boil on callout text layer) |
| Pipeline slot on footage | `/avo.motion` → `edit/animations/slot_<id>/` |

## Module path

Copy or reference from exemplar:

- `docs/exemplars/hyperframes-boil-insert/lib/boil-insert.js`
- `docs/exemplars/hyperframes-boil-insert/lib/presets.js`
- `docs/exemplars/hyperframes-boil-insert/lib/lifecycle.js`

Starters: `starter/` (text), `starter-image/` (image/video wrapper).

## Export + EDL

```bash
npm exec -- hyperframes render --format webm --quality draft --output render.webm
```

Register in `edit/edl.json` → `overlays[]` with `anchor_in_source`, `motion_brief_id`, `start_in_output`, `duration`.

## Presets

`subtle` | `standard` (default) | `wild` — from `BoilPresets` or provider `palette.json` → `boil.defaultPreset`.

## Out of scope

Full-program boiling captions, FFmpeg inline boil, global whole-video wiggle.
