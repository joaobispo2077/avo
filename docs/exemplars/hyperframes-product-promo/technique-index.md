# Product-promo technique index

Adapted from [hyperframes-student-kit `MOTION_PHILOSOPHY.md`](https://github.com/nateherkai/hyperframes-student-kit/blob/main/MOTION_PHILOSOPHY.md). **AVO `motion-doctrine` supersedes** conflicting guidance.

---

## Doctrine precedence

| Topic | Student-kit | AVO rule | Use |
| ----- | ----------- | -------- | --- |
| Ambient motion | Law #4: camera never sleeps | No idle wobble — motion must **perform** | Ambient only when **caused** (grid parallax, particles tied to beat) |
| Scene length | ~1.5s average | Density Level 0–5 per section | Product promo default **Level 3–4**; CTA hold may be Level 0–1 |
| Seam continuity | Whip streaks | Vector law + `cut-the-curve` | Whips only when masking a **matched-vector** seam |
| Brand colors | AIS chrome palette | `providers/<name>/DESIGN.md` | Never hardcode student-kit hex |
| Hero stillness | Law #9 hold | `motion-doctrine` stillness-before-climax | **Allowed** after kinetic beats |

Load [`motion-doctrine`](../../../.agents/skills/motion-doctrine/SKILL.md) before applying techniques below.

---

## Product-promo beat map (30–60s default)

Three-act structure (from student-kit Infinite reference, generalized):

| Act | Time | Purpose | Density |
| --- | ---- | ------- | ------- |
| **1 — Problem** | 0–30% | Pain point, kinetic type, object metaphor | Level 3–4 |
| **2 — Proof** | 30–75% | Benefits (rule of three), UI surfaces, feature cards | Level 3 |
| **3 — CTA** | 75–100% | Logo, tagline, URL — **hold still** | Level 0–1 |

**Rule of threes:** three benefits, three product surfaces, or three feature names — one dominant focus per beat.

---

## Visual vocabulary (product promo)

Techniques safe to use when brand `DESIGN.md` supports dark/premium promos:

### Backgrounds

| Technique | Build | When |
| --------- | ----- | ---- |
| Pure black stage | `body { background: #000 }` | Reset between major beats |
| Perspective grid | `repeating-linear-gradient` + `rotateX` parallax | Depth without clutter |
| Vignette overlay | `radial-gradient` absolute layer | Always-on readability |
| Liquid-glass panel | `backdrop-filter` + inner highlight border | UI cards, product surfaces |

### Type as character

- Words **scale**, **morph**, or **compress** to carry meaning — not decoration
- One idea per beat; split scenes that say two things
- Chrome/light gradient on type reads premium when brand allows — not default

### Object metaphors

- Problem object (e.g. broken card) → solution object (working token)
- **Callback objects** return in act 3 for visual rhyme
- Registry blocks: `npx hyperframes add` — see [`hyperframes-registry`](../../../.agents/skills/hyperframes-registry/SKILL.md)

### Transitions

- Whip/light streak — masks cut, conveys energy (`cut-the-curve` §1)
- Morph mid-flight — tier-A seam; hand-author or stamp from ledger
- Color flip on same layout — benefit pivot without scene cut

### UI / product surfaces

Pattern from `clickup-demo`:

1. Phone/laptop frame slides in on beat
2. Screen content is static HTML/CSS (screenshot or simplified DOM)
3. **Never animate `width`/`height`/`top`/`left` on `<video>`** — wrap and animate wrapper

---

## Registry blocks (common in SaaS demos)

Install via `hyperframes add` when message fits:

| Block family | Typical use |
| ------------ | ------------- |
| `ui-3d-reveal` | Product panel entrance |
| `x-post` | Social proof card |
| `grain-overlay` | Subtle film texture (deterministic) |

Validate block timing against composition `data-duration`. See [`render-contract.md`](render-contract.md) slot-fill rule.

---

## Cross-links (do not duplicate)

| Need | Skill / doc |
| ---- | ----------- |
| Seam parameters + GSAP | `cut-the-curve` |
| White-flash / opaque root | `seam-craft` |
| Composition contract | `hyperframes-core` |
| Animation rules taxonomy | `hyperframes-animation/rules/` |
| Full E2E workflow | `product-launch-video` |
| Provider brand | `providers/<name>/DESIGN.md` |

---

## Reading order for new product promo

1. This index + `motion-doctrine`
2. `render-contract.md` + `pre-flight-checklist.md`
3. `starter/STORYBOARD.md` + `starter/index.html`
4. Upstream [`clickup-demo`](https://github.com/nateherkai/hyperframes-student-kit/tree/main/video-projects/clickup-demo) locally (optional deep dive)
