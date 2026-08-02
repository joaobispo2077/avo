# Pre-flight checklist (product promo)

Run before first `preview` and before each render candidate.

---

## Diagnosis

- [ ] Format: product promo / SaaS launch (not short-form talking-head unless hybrid section documented)
- [ ] Provider `DESIGN.md` loaded; brand tokens mapped — no student-kit AIS hex
- [ ] Motion density assigned per act (see [`technique-index.md`](technique-index.md))
- [ ] Multi-scene: [`motion-doctrine`](../../../.agents/skills/motion-doctrine/SKILL.md) read; `ledger.json` planned if >1 seam

---

## Plan artifacts

- [ ] `DESIGN.md` or project `frame.md` exists (use [`design-product-promo.md`](../../templates/animation/design-product-promo.md) template)
- [ ] `STORYBOARD.md` with beat map (use [`storyboard-product-promo.md`](../../templates/animation/storyboard-product-promo.md))
- [ ] `ANIMATION-SOURCE-LOG.md` started for third-party/registry assets
- [ ] One primary message stated in one sentence

---

## Composition contract

- [ ] Root has explicit `data-width`, `data-height`, `data-duration`
- [ ] Every clip has `data-start`, `data-duration`, `data-track-index`
- [ ] Timeline slot-fill anchor present ([`render-contract.md`](render-contract.md) §1)
- [ ] `<video>` elements wrapped; no direct dimension tweens
- [ ] Sub-comps: GSAP + styles inside `<template>`

---

## Seam gate (multi-scene)

- [ ] Vector ledger stamped or tier-A morphs hand-authored
- [ ] `node .agents/skills/motion-doctrine/scripts/seam-gate.mjs` passes (when ledger used)
- [ ] No idle wobble between entry and exit — motion **performs**

---

## Validation

- [ ] `npx hyperframes lint` — zero errors
- [ ] `npx hyperframes check` — review findings
- [ ] Snapshot hero frame per beat at mid-duration
- [ ] Reduced-motion / flashing safety reviewed (no >3 flashes/sec)

---

## AVO pipeline gates

- [ ] Proof at ≤720p before 1080p promotion
- [ ] Human approval after watch-skill LOOP — high confidence ≠ approval
- [ ] Rights/AI disclosure reviewed if synthetic UI or generated assets used

---

## Before final render

- [ ] Draft render verified frame-by-frame (ffmpeg stills at hero moments)
- [ ] Audio sync checked if narration/BGM present
- [ ] Post-encode QC on upload candidate
