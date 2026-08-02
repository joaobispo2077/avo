# Starter storyboard — short-form exemplar

**Composition:** `main` · 1080×1920 · 20s · 30fps  
**Purpose:** Lint-verified 4-layer scaffold reference — **face placeholder**, no mp4.

## Layers

| Track | Layer | Role |
| ----- | ----- | ---- |
| 0 | face-wrapper | Placeholder div + BOTTOM→FULLSCREEN demo transition |
| 1 | scene-hook | Top-half overlay card |
| 2 | captions-stub | Static caption line (replace with karaoke comp) |
| 3 | ambient-bg | Gradient + vignette |

## Beats

| Time | Face mode | Overlay |
| ---- | --------- | ------- |
| 0–8s | BOTTOM | Hook card visible 2–7s |
| 8–20s | FULLSCREEN (transition at 7.85s) | Hook fades; face fills frame |

## Replace in real projects

- Swap `#face-placeholder` for `<video id="face-video">` + project assets
- Add `<audio id="face-audio">` synced to `-edit.mp4`
- Replace captions stub with `embedded-captions` karaoke comp
- Set `data-duration` from `ffprobe` on edited audio
