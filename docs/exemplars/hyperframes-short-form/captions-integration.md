# Captions integration (short-form)

AVO does **not** duplicate karaoke caption implementation here. Route to existing skills and apply short-form-specific constraints from student-kit autopsy.

---

## Skills to load

| Skill | Role |
| ----- | ---- |
| [`embedded-captions`](../../../.agents/skills/embedded-captions/SKILL.md) | Caption styles, render chain, identity catalog |
| [`captions-overlay`](../../../.agents/skills/captions-overlay/SKILL.md) | Drop/rail/embed doctrine on footage pipeline |

HyperFrames in-composition captions: follow `embedded-captions` + `/hyperframes` karaoke references.

---

## Short-form styling constraints

| Rule | Rationale |
| ---- | --------- |
| Heavy weight display font (e.g. Montserrat 900), 46–58px at 1080 width | Mobile readability |
| Active word: scale ~1.08 + accent color from **provider** tokens | Pop without layout shift |
| Stroke via layered `text-shadow` | `-webkit-text-stroke` inconsistent in Chromium render |
| Avoid heavy background pill | Stroke holds readability; captions feel on-frame |
| Per-word `<span data-word-start>` + GSAP scoped tweens | Deterministic karaoke |

**Do not** hardcode student-kit AIS accent (`#37bdf8`) — use `providers/<name>/DESIGN.md`.

---

## Timing

- Word timestamps must be in **edited-time** — see [`audio-sync-protocol.md`](audio-sync-protocol.md)
- Retime via `shift()` in captions comp — do not hand-edit transcript JSON per retake

---

## Pipeline order (`/avo.shorts`)

Motion phase (optional) → **captions last** in filter chain — Hard Rule #1 in pipeline skill.

When building HF captions inside a slot, still run `/avo.captions` or embedded-captions QC before master if burning into export.

---

## Track placement

Captions composition on **track 2** in the 4-layer scaffold — see [`technique-index.md`](technique-index.md).

`data-duration` matches root / edited audio duration.

---

## Verification

Include caption legibility in word-exact frame verification — overflow, wrong active word, contrast against face/scene.
