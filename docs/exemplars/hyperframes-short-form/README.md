# HyperFrames short-form vertical knowledge base

Curated 9:16 talking-head + motion overlay + captions knowledge. Adapted from [hyperframes-student-kit `short-form-video`](https://github.com/nateherkai/hyperframes-student-kit) and `may-shorts-19` patterns — **authoring sources only**, no face footage in git.

## Load order (agents)

1. [`motion-doctrine`](../../../.agents/skills/motion-doctrine/SKILL.md) — multi-scene / seam work
2. [`../hyperframes-product-promo/render-contract.md`](../hyperframes-product-promo/render-contract.md) — shared render rules
3. [`technique-index.md`](technique-index.md) — 4-layer scaffold, face-mode, pacing
4. [`audio-sync-protocol.md`](audio-sync-protocol.md) — edited-time anchoring
5. [`face-mode-choreography.md`](face-mode-choreography.md) — BOTTOM ↔ FULLSCREEN GSAP
6. [`captions-integration.md`](captions-integration.md) — karaoke route (no duplication)
7. [`pre-flight-checklist.md`](pre-flight-checklist.md)
8. [`starter/`](starter/) — 1080×1920 lint-verified scaffold (face placeholder)
9. [`failure-playbooks.md`](failure-playbooks.md)

Pipeline router: [`short-form-knowledge.md`](../../../agent-skills/avo-pipeline/references/short-form-knowledge.md)

Footage orchestrator: [`shorts.md`](../../../agent-skills/avo-pipeline/references/shorts.md) (`/avo.shorts`)

## Doctrine precedence

**AVO `motion-doctrine` wins.** Student-kit "no dead frames" is adapted as **motion must perform** — not idle wobble. See [`technique-index.md`](technique-index.md) § Doctrine precedence.

## What is not here

- `.mp4` face recordings (use project `assets/` at render time)
- Full karaoke caption implementation (use `embedded-captions` + `captions-overlay`)
