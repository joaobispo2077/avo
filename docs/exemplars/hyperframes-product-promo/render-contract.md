# Render contract (product-promo)

Non-negotiable rules for HyperFrames product-promo compositions. Merged from student-kit `CLAUDE.md`, AVO determinism rules, and `seam-craft`.

---

## 1. Timeline slot fill (Law #11 — adopted verbatim)

HyperFrames hides a sub-composition when `timeline.duration()` < `data-duration` → **black frame flash**.

Every GSAP timeline must end with a no-op duration anchor:

```javascript
const SLOT = 5; // match clip data-duration in seconds
tl.to({}, { duration: SLOT }, 0); // holds timeline length = slot
window.__timelines["main"] = tl;
```

Non-negotiable. See student-kit `MOTION_PHILOSOPHY.md` §3.8.

---

## 2. One paused timeline per composition

- `gsap.timeline({ paused: true })` registered at `window.__timelines["<data-composition-id>"]`
- Built **synchronously** at page load
- Render duration = root `data-duration`, not perceived animation length

---

## 3. Video and media wrappers

**Never** tween `width`, `height`, `top`, or `left` on a `<video>` element.

```html
<div class="video-wrap">
  <video ...></video>
</div>
```

Animate the wrapper only. Framework owns playback — do not manual play/pause/seek.

---

## 4. Lint before preview

```bash
npx hyperframes lint
```

Zero errors before `preview`. Warnings: document if accepted.

---

## 5. Authoring loop

```text
edit → lint → preview → draft render → verify frames → final render
```

Draft render for iteration only; **do not commit** `.mp4` to AVO repo.

---

## 6. Determinism bans

- No `repeat: -1` on tweens (use finite repeat count)
- No wall-clock timing, unseeded randomness, network during render
- Animate transform/opacity preferentially

Full list: `hyperframes-core/references/determinism-rules.md`

---

## 7. Seam render (multi-scene)

- Master `#root` opaque background — see `seam-craft`
- Vector-matched seams per `motion-doctrine`
- Run `seam-gate.mjs` before render when using ledger

---

## 8. Sub-composition transport

Styles and scripts for sub-comps go **inside** `<template>`, not in outer `<head>`. Each sub-comp loads its own GSAP script tag.

---

## 9. Full-screen backgrounds

Background fills on a **child** with `position:absolute; inset:0` — not on composition root (producer may drop root background in render).

---

## 10. ID uniqueness

Every `id` unique across assembled page. Prefix sub-comp ids: `#<composition-id>-hero`.

---

## 11. Provider brand

Resolve colors, fonts, motion tokens from `providers/<name>/DESIGN.md` — never student-kit AIS defaults in deliverables.
