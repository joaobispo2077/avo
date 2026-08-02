# Pre-flight checklist (short-form 9:16)

Run before first preview and before render candidate.

---

## Diagnosis

- [ ] Format: 9:16 short-form (TikTok/Reels/Shorts) — `/avo.guidelines --shorts` if footage pipeline
- [ ] Duration ≤60s for Shorts shelf (or documented override in EDITLOG)
- [ ] Provider `DESIGN.md` loaded — no student-kit AIS hex
- [ ] Motion density Level 2–3 max when captions/text must be read

---

## Audio (source of truth)

- [ ] Edited master exists (`*-edit.mp4` or approved trim output)
- [ ] `ffprobe` duration recorded → root `data-duration`
- [ ] Transcript from **edited** audio only
- [ ] All scene `data-start` values in edited-time — [`audio-sync-protocol.md`](audio-sync-protocol.md)

---

## Scaffold

- [ ] Four layers present: ambient, face, scenes, captions (or documented omission)
- [ ] Face wrapper pattern — no direct `<video>` dimension tweens
- [ ] Seam treatment planned for bottom-half face scenes
- [ ] Separate `<audio>` for VO
- [ ] Timeline slot-fill anchors — [`render-contract.md`](../hyperframes-product-promo/render-contract.md)

---

## Face-mode

- [ ] BOTTOM / FULLSCREEN modes mapped to scene beats
- [ ] Transitions start 0.15s **before** scene content
- [ ] `expo.inOut` (or equivalent) — no instant snaps

---

## Captions

- [ ] Route through `embedded-captions` / [`captions-integration.md`](captions-integration.md)
- [ ] Provider accent tokens — not AIS defaults
- [ ] Word-exact verification timestamps planned

---

## Validation

- [ ] `npx hyperframes lint` — zero errors
- [ ] Draft render + 8–15 word-exact frame extractions
- [ ] Read every PNG — sync, face crop, caption, overlay

---

## AVO pipeline gates

- [ ] `/avo.shorts` human approval after watch-skill LOOP
- [ ] Captions after motion in pipeline order
- [ ] No `.mp4` committed to AVO repo exemplars
