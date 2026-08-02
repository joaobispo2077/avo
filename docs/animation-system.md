# Animation System

This repository uses an AI-assisted animation system for overlays, explainers,
UI demonstrations, data visualization, maps, title sequences, webdocs, and full
video compositions. `AGENTS.md` is canonical.

## Principles

- Animation is visual communication over time.
- Motion must clarify, demonstrate, orient, compare, emphasize, transition, or
  intentionally create supported emotion.
- Static holds and no-motion decisions are valid.
- Evidence, data, maps, documents, product behavior, chronology, and source
  context must remain accurate.
- Final animation must be deterministic, seekable, reproducible, accessible, and
  source-controlled.

## Standard Workflow

1. Intake and diagnose format, viewer, message, sources, brand, audio, density,
   framework context, rights, and risks.
2. Select framework: HyperFrames by default, Remotion only with documented fit.
3. Capture and inventory assets in `ANIMATION-SOURCE-LOG.md`.
4. Create or update `DESIGN.md`.
5. Create `STORYBOARD.md` or a beat map.
6. Build static compositions first.
7. Add primary motion.
8. Add secondary and ambient motion only after hierarchy works.
9. Add transitions and audio synchronization.
10. Validate technically with framework lint/check/snapshot workflows.
11. Review by format, density, accessibility, and source integrity.
12. Render and compare preview, snapshots, and candidate output.
13. Complete final QC and delivery manifest.

## Framework Selection

HyperFrames is preferred because current docs describe HTML compositions,
declared timing, HTML/CSS/JavaScript authoring, seekable runtimes, framework-owned
media playback, deterministic frame-by-frame rendering, agent skills, and
preview/lint/check/snapshot/render workflows.

Remotion is permitted when an existing React/TypeScript/Remotion stack,
data-driven template system, React app integration, required Remotion capability,
or explicit user request makes it lower risk or more maintainable. Review the
current Remotion license before organizational or commercial use.

## Motion Density

- Level 0: Static.
- Level 1: Anchor motion.
- Level 2: Selective support.
- Level 3: Standard motion system.
- Level 4: Dense narrative motion.
- Level 5: Motion-first or fully animated.

Assign density per section. The densest section does not define the whole video.
Use higher density only with stronger hierarchy and clearer review gates.

## Required Artifacts

- `DESIGN.md`: visual and motion design system.
- `STORYBOARD.md`: scene plan and density/hierarchy map.
- `ANIMATION-EDITLOG.md`: framework decisions, versions, renders, reviews.
- `ANIMATION-SOURCE-LOG.md`: source, rights, AI provenance, attribution.
- `SCRIPT.md`: when narration or spoken timing drives the animation.

## Review Gates

1. Brief and framework selection.
2. Design system approval.
3. Storyboard and motion-density approval.
4. Static layout and typography approval.
5. First motion pass.
6. Timing and hierarchy review.
7. Audio synchronization review.
8. Accessibility and source review.
9. Render-candidate QC.
10. Master approval.

Do not invest in high-cost 3D, shaders, particles, or detailed secondary motion
before message, storyboard, layout, and typography are approved.

## Product-promo knowledge base

For SaaS demos, feature reveals, and product launch films, load the curated bundle
before composing:

- [`docs/exemplars/hyperframes-product-promo/README.md`](exemplars/hyperframes-product-promo/README.md)
- Templates: [`design-product-promo.md`](templates/animation/design-product-promo.md),
  [`storyboard-product-promo.md`](templates/animation/storyboard-product-promo.md)
- Spec: [`specs/active/avo-motion-knowledge/`](../specs/active/avo-motion-knowledge/)

Source techniques adapted from [hyperframes-student-kit](https://github.com/nateherkai/hyperframes-student-kit).
**Authoring files only** — reference renders stay upstream. `motion-doctrine` supersedes
conflicting student-kit motion aesthetics.

## Short-form knowledge base

For 9:16 vertical (Shorts/Reels/TikTok) HyperFrames slots:

- [`docs/exemplars/hyperframes-short-form/README.md`](exemplars/hyperframes-short-form/README.md)
- Templates: [`design-short-form.md`](templates/animation/design-short-form.md),
  [`storyboard-short-form.md`](templates/animation/storyboard-short-form.md)
- Spec: [`specs/active/avo-motion-knowledge-phase2/`](../specs/active/avo-motion-knowledge-phase2/)
- Footage orchestrator: `/avo.shorts` + [`short-form-knowledge.md`](../agent-skills/avo-pipeline/references/short-form-knowledge.md)

Face footage stays in project assets — exemplar uses a placeholder div only.

## Final QC

Final animation QC covers message, density, hierarchy, text, captions, evidence,
entrances/holds/exits, fonts/assets, deterministic timing, seeded randomness,
audio sync, flashing safety, rights/AI disclosure, export specs, first/final
frames, file naming, and delivery manifest.
