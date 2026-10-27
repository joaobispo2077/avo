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
2. Resolve engine/source/readiness first: HyperFrames default, explicit advanced code-drawn, or an honest unsupported Remotion selection.
3. Capture and inventory assets in `ANIMATION-SOURCE-LOG.md`.
4. Create or update `DESIGN.md`.
5. Create `STORYBOARD.md` or a beat map.
6. Build static compositions first.
7. Add primary motion.
8. Add secondary and ambient motion only after hierarchy works.
9. Add transitions and audio synchronization.
10. Validate through the selected engine's actual native check/snapshot/render workflow.
11. Review by format, density, accessibility, and source integrity.
12. Render and compare preview, snapshots, and candidate output.
13. Complete final QC and delivery manifest.

## Engine selection

Resolve current intent and scoped preferences before loading engine-specific
skills or checking their prerequisites. HyperFrames remains the built-in
default. Explicit advanced `code-drawn` uses Canvas, SVG or optional standalone
p5.brush with managed headless Chromium; it does not require HyperFrames,
Remotion or a particular model. Use the
[portable guide](../agent-skills/avo-pipeline/references/code-drawn.md).

Use native `animation engine-show` to inspect engine, winning scope, readiness,
current run choice and recorded source separately. Resolution is invocation >
project > provider/channel > global > default. Global preference operations
need no footage. A default change cannot rewrite an immutable animation or
reinterpret a paused request; deliberate new source authoring uses the existing
revision/invalidation services. See [exact commands](avo-commands.md#native-motion-commands).

For selected HyperFrames, keep its HTML/timing/media contract and installed
entry/core/animation/creative/CLI skills. HyperFrames-only exemplars, registry
kits and specialized workflows below apply only to that branch.

Remotion may fit an existing maintained React/TypeScript/Remotion project,
data-driven template system or explicit request. Its current AVO execution
adapter is unsupported: disclose that readiness and do not silently substitute
another engine. Review its current license for intended use; see the
[decision guide](remotion-decision-guide.md).

For any engine, use one canonical timing/master owner and a documented boundary
for generated assets. No automatic kit conversion, segmentation treatment,
interactive presenter or source port is implied. A working standalone capture
does not establish a canonical proof: admission, source locks, ProofPlan,
reconstruction, Watch/transcript and human approval remain required on supported
native integration paths. Missing capabilities block before execution.

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
- `ANIMATION-EDITLOG.md`: engine/route decisions, versions, renders, reviews.
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

These describe existing project review stages; do not create a duplicate approval
ritual. Current candidate-bound review/explicit human decisions remain authoritative.

Do not invest in high-cost 3D, shaders, particles, or detailed secondary motion
before message, storyboard, layout, and typography are approved.

## Product-promo knowledge base

For selected HyperFrames SaaS demos, feature reveals, and product launch films,
load the curated bundle before composing:

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
