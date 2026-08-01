---
applyTo: "**"
---

# Animation QC Instructions

- Review static frames before complex motion: layout, hierarchy, typography,
  crop, safe areas, evidence, color, and source accuracy.
- Verify all fonts, media, Lottie, 3D assets, shaders, data files, captions, and
  audio are local/available, supported, and awaited.
- Confirm randomness is seeded and renders do not depend on wall-clock time,
  network responses, unawaited assets, independent clocks, or render order.
- Snapshot important times, compare preview to rendered output, and re-render or
  inspect repeated candidates when determinism risk is high.
- Check motion density, one-message-per-scene clarity, readable holds,
  entrances/exits, audio sync, captions, flicker, pops, missing assets, and first
  and final frames.
- Block delivery for unsafe flashing, excessive motion, unreadable text, hidden
  captions, wrong data/maps/UI/evidence, unresolved rights, missing AI disclosure
  review, or unverified export settings.
