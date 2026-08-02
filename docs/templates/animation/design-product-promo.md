# Animation design system — product promo

> **Template.** Copy to footage `edit/animations/<slot>/DESIGN.md` or HyperFrames project root. Provider brand authority: `providers/<name>/DESIGN.md`.

## Status

- Project:
- Provider:
- Version:
- Approved by:
- Last updated:

## Message

One sentence — the ONE thing this promo must communicate:

> 

## Canvas

| Deliverable | Aspect | Resolution | FPS |
| ----------- | ------ | ------------ | --- |
| Primary | 16:9 | 1920×1080 | 30 |

Safe zones: keep CTA, logo, and readable type inside platform safe margins.

## Colors (from provider — do not invent)

| Role | Token / value | Usage |
| ---- | ------------- | ----- |
| Canvas | | Background / negative space |
| Ink | | Primary type |
| Accent | | CTAs, highlights — one concept per color |
| Muted | | Secondary panels |

## Typography

| Role | Family | Weight | Size range |
| ---- | ------ | ------ | ---------- |
| Display | | | Hero kinetic type |
| Body | | | UI labels, supporting copy |

## Motion tokens

| Token | Duration | Easing | Usage |
| ----- | -------- | ------ | ----- |
| beat-enter | 0.4–0.6s | power3.out | Word/panel entrance |
| beat-exit | 0.3–0.5s | power4.in | Handoff to next beat |
| hero-hold | 2–5s | none | Logo/CTA stillness |
| seam-whip | 0.3–0.5s | power2.inOut | Vector-matched transition |

## Product-promo patterns

- **Act 1:** problem — kinetic type, dark canvas
- **Act 2:** proof — UI surfaces, rule-of-three benefits
- **Act 3:** CTA — still hold allowed (`motion-doctrine`)

See [`docs/exemplars/hyperframes-product-promo/technique-index.md`](../exemplars/hyperframes-product-promo/technique-index.md).

## What NOT to do

- No student-kit AIS palette unless provider explicitly matches
- No idle wobble between narrative beats
- No essential meaning encoded only through motion
- No `.mp4` committed to AVO repo as reference

## Related files

- `STORYBOARD.md`
- `ANIMATION-SOURCE-LOG.md`
- `ANIMATION-EDITLOG.md`
