# Face-mode choreography (9:16)

The signature short-form move: talking-head switches between **bottom-half landscape** and **full-screen crop** via GSAP on a **wrapper div** — never on `<video>` directly.

Adapted from student-kit `may-shorts-19` autopsy.

---

## Wrapper setup

```html
<div id="face-wrapper" class="clip" data-start="0" data-duration="20" data-track-index="0">
  <!-- Exemplar: placeholder div. Projects: <video id="face-video" ...></video> -->
  <div id="face-placeholder" aria-hidden="true"></div>
</div>
<audio id="face-audio" src="assets/vo-edit.mp4" ...></audio>
```

- Face source is typically 1920×1080 landscape inside 1080×1920 portrait
- Animate `#face-wrapper` transform only
- Framework owns `<video>` playback — do not manual play/seek

---

## Mode constants (1080×1920 canvas)

```javascript
const BOTTOM = { x: 0, y: 1136, scale: 0.5625 }; // full 16:9 visible in bottom 960px
const FULLSCREEN = { x: -1166.5, y: 0, scale: 1.7778 }; // crop-cover portrait fill
const MODE_DUR = 0.32;
```

`BOTTOM` centers 1920×1080 at 1080×607.5 in the lower half.  
`FULLSCREEN` crops horizontally to fill portrait.

---

## Mode transitions (main timeline)

Transition **0.15s before** new scene content lands:

```javascript
[
  { t: 4.05, mode: FULLSCREEN },
  { t: 9.8, mode: BOTTOM },
].forEach(({ t, mode }) => {
  mainTl.to("#face-wrapper", { ...mode, duration: MODE_DUR, ease: "expo.inOut" }, t - 0.15);
});
```

Instant mode snaps are the #1 jarring frame in vertical video — always interpolate.

Times `t` are **edited-time** — see [`audio-sync-protocol.md`](audio-sync-protocol.md).

---

## Face grading (CSS)

```css
#face-video {
  filter: contrast(1.08) saturate(1.08) brightness(0.97);
}
```

Optional subtle Ken Burns on wrapper (`scale` 1 → 1.025 over full duration, `ease: "none"`) when storyboard documents a continuous hold — not idle wobble between beats.

Side vignette on wrapper `::after` softens the edge against the ambient background.

---

## Seam treatment (bottom-half scenes)

When face is in `BOTTOM` mode, overlay scenes cover the top 960px. Add seam band at y=960:

- Navy→transparent gradient 60–100px
- 2px accent scan line + soft glow
- Drawn **above** face, below scene overlays (track 5)

Razor-sharp horizontal cut at y=960 reads as AI-edited — feather is required.

---

## Render contract reminders

- Never tween `<video>` width/height/top/left — frozen frames in render
- Slot-fill anchor on every timeline — [`render-contract.md`](../hyperframes-product-promo/render-contract.md)
- Separate `<audio>` element for VO mix

---

## Exemplar

See [`starter/index.html`](starter/index.html) — placeholder face + one BOTTOM→FULLSCREEN transition demo (no mp4).
