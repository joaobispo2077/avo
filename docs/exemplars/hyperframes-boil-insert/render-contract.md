# Render contract (boil insert overlays)

Non-negotiable rules for wiggly/boiling **alpha overlay** compositions. Extends [`../hyperframes-product-promo/render-contract.md`](../hyperframes-product-promo/render-contract.md).

---

## 1. Transparent background (overlays)

Root canvas must be **transparent** for alpha WebM compositing over footage:

```css
body, #root {
  background: transparent;
}
```

Do not use opaque full-frame backgrounds unless delivering a full composite (not an EDL overlay slot).

---

## 2. Timeline slot fill

Every GSAP timeline ends with a duration anchor matching `data-duration`:

```javascript
const SLOT = 3; // seconds — match data-duration
tl.to({}, { duration: SLOT }, 0);
window.__timelines["main"] = tl;
```

---

## 3. Boil determinism

- Drive `feTurbulence` `seed` via GSAP on the **master paused timeline**
- Use `BoilInsert.applyBoil(tl, turbEl, { startTime, duration, fps })`
- **No** `Math.random()`, SMIL, or wall-clock loops
- **No** boil before entrance or after exit — use `BoilLifecycle.boilHoldWindow()`

---

## 4. Reduced motion

When `prefers-reduced-motion: reduce`, skip `applyBoil` — static text/image remains readable.

---

## 5. Export

```bash
npm exec -- hyperframes lint
npm exec -- hyperframes render --format webm --quality draft --output render.webm
```

Promote to high quality only after human approval gate (720p proof first).

---

## 6. EDL wiring

```json
{
  "file": "edit/animations/slot_boil-callout/render.webm",
  "start_in_output": 12.5,
  "duration": 2.5,
  "motion_brief_id": "boil-callout",
  "anchor_in_source": 45.0
}
```

Captions burn **after** overlays (Hard Rule #1).
