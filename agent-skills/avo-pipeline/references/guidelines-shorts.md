# Guidelines: --shorts

YouTube Shorts guidelines (vertical ≤60s, or Shorts shelf intent).

## Load

- [`AGENTS.md`](../../../AGENTS.md)
- `youtube-format-playbooks` Shorts/hybrid sections
- [`docs/delivery-specifications.md`](../../delivery-specifications.md) for upload QC

## Diagnosis checklist

1. **Shorts vs long-form extract:** native Short or reframed clip from master?
2. **9:16 safe margins:** captions, faces, product details, evidence
3. **Loop / ending:** intentional hold or CTA; no fake continuation
4. **Title/thumbnail promise** (Shorts title + hook frame)
5. **Music/SFX rights** and reused-content posture

## Editing constraints

- Speech intelligibility beats polish
- Do not manufacture reactions, chronology, or certainty
- Chapter-style resets only when they improve clarity

## Technical QC

- Resolution/aspect match Shorts upload spec (verify current YouTube docs)
- Final transcript from exported Short file when delivering

## After guidelines

**Primary:** `/avo.shorts` — orchestrates diagnosis → trim → watch → motion? → captions? → deliver with Short defaults.

**Escape hatch:** `/avo.trim` + `/avo.motion` + `/avo.captions` + `/avo.deliver` for manual stage control.

**From long-form master:** `/avo.shorts --from-master` (delegates to `/avo.reframe`) or `/avo.reframe` directly with `from`/`to`.
