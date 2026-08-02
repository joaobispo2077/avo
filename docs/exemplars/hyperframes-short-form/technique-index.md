# Short-form technique index

Adapted from [hyperframes-student-kit `short-form-video`](https://github.com/nateherkai/hyperframes-student-kit/blob/main/.claude/skills/short-form-video/SKILL.md). **AVO `motion-doctrine` supersedes** conflicting guidance.

---

## Doctrine precedence

| Topic | Student-kit | AVO rule | Use |
| ----- | ----------- | -------- | --- |
| "No dead frames" / constant motion | Every 100ms animating | No **idle wobble** — motion **performs** | Secondary motion must serve the beat (underline sweep, checkmark pop) — not breathe-in-place |
| Face Ken Burns drift | Subtle 1.00→1.025 zoom | Allowed if **caused** (continuous reveal hold) | Document in storyboard; not decorative drift between beats |
| Scene pacing ~1–4s | May Shorts autopsy | Density Level 2–3 for Shorts motion phase | Cap motion when captions/text must be read |
| Seam at y=960 | Navy gradient feather | Compatible with `seam-craft` | Required for bottom-half face mode |
| Audio-first timing | Edit audio before comp | Same — **edited-time only** | [`audio-sync-protocol.md`](audio-sync-protocol.md) |

---

## Format defaults

| Field | Value |
| ----- | ----- |
| Canvas | 1080×1920 (9:16) |
| Duration | 10–60s (Shorts shelf ≤60s via `/avo.shorts`) |
| FPS | 30 |
| Layers | 4 (ambient, face, scenes, captions) |

---

## Four-layer scaffold

Every short-form vertical composition uses these tracks:

```text
index.html (root, data-composition-id="main")
├── ambient-bg        track 3 — gradient + drift + vignette (never flat single hex)
├── face-wrapper      track 0 — talking head (animate wrapper, never <video> dims)
├── scene overlays    track 1 — back-to-back, no gaps on same track
├── seam-treatment    track 5 — y=960 feather when face is bottom-half
└── captions          track 2 — karaoke (delegate to embedded-captions skill)
```

- Root `data-duration` = edited audio duration (`ffprobe` on `-edit.mp4`)
- `<audio>` for VO is a **separate element** — not the video's embedded track
- `class="clip"` on timed divs — **never** on `<video>` or `<audio>`

Detail: [`face-mode-choreography.md`](face-mode-choreography.md)

---

## Workflow (HyperFrames authoring)

1. **Edit audio first** → `<name>-edit.mp4`; measure duration
2. **Transcribe** edited audio (`hyperframes transcribe` or pipeline `/avo.transcribe`)
3. **Plan scenes in edited-time** — storyboard table before HTML
4. **Build scaffold** → ambient, face, scenes, captions sub-comps or clips
5. **Lint → draft render → word-exact frame verify → final**

Footage pipeline equivalent: `/avo.shorts` (trim → watch → motion → captions → deliver)

---

## Scene pacing (under doctrine)

- **One idea per scene** — split if two messages
- **Payoff hold ≥1s** on stamp/number/punchline (stillness-before-climax OK)
- **Entrance stagger** 0.1–0.3s — not everything at t=0
- **Vary eases** — ≥3 families per scene for hierarchy
- **One jaw-dropper per ~5s** — type slam, whip, audio-sync hit (must support narration)

---

## Ambient background (minimum stack)

1. Radial gradient (center 15–20% lighter than edge)
2. Optional deterministic grain (CSS or registry block)
3. 4–8 drifting particles OR grid parallax (caused ambient)
4. Vignette overlay

Flat `#000` alone is a placeholder — see provider `DESIGN.md`.

---

## Verification gate (mandatory)

Lint passing ≠ sync correct. Before shipping:

1. Draft render
2. Extract frames at **word-exact** timestamps (not round numbers)
3. Read every PNG — face crop, mode, caption, overlay timing
4. Fix and re-verify

Do not commit draft mp4 to AVO repo — run verification in project `renders/`.

---

## Cross-links

| Need | Doc / skill |
| ---- | ----------- |
| Audio timing | [`audio-sync-protocol.md`](audio-sync-protocol.md) |
| Face GSAP | [`face-mode-choreography.md`](face-mode-choreography.md) |
| Captions | [`captions-integration.md`](captions-integration.md) |
| Render rules | [`../hyperframes-product-promo/render-contract.md`](../hyperframes-product-promo/render-contract.md) |
| Footage pipeline | [`shorts.md`](../../../agent-skills/avo-pipeline/references/shorts.md) |

---

## Upstream deep dive

Clone student-kit locally and open `video-projects/may-shorts-19` alongside `starter/` — compare v2→v4 iteration (README).
