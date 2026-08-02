# Short-form HyperFrames knowledge

Router for 9:16 talking-head + motion overlay + captions compositions. Load when authoring vertical shorts motion **or** when `/avo.shorts` phase 3 motion is active.

## When to load

- TikTok / Reels / YouTube Shorts HyperFrames slot
- Talking-head + karaoke captions + scene overlays
- `/avo.shorts` with motion (not `--skip-motion`)

## Load order

1. [`motion-doctrine`](../../../.agents/skills/motion-doctrine/SKILL.md) — when multi-scene seams apply
2. [`docs/exemplars/hyperframes-short-form/README.md`](../../../docs/exemplars/hyperframes-short-form/README.md)
3. On demand:
   - [`technique-index.md`](../../../docs/exemplars/hyperframes-short-form/technique-index.md)
   - [`audio-sync-protocol.md`](../../../docs/exemplars/hyperframes-short-form/audio-sync-protocol.md)
   - [`face-mode-choreography.md`](../../../docs/exemplars/hyperframes-short-form/face-mode-choreography.md)
   - [`captions-integration.md`](../../../docs/exemplars/hyperframes-short-form/captions-integration.md)
   - [`pre-flight-checklist.md`](../../../docs/exemplars/hyperframes-short-form/pre-flight-checklist.md)
4. Shared [`render-contract.md`](../../../docs/exemplars/hyperframes-product-promo/render-contract.md)
5. Templates: [`design-short-form.md`](../../../docs/templates/animation/design-short-form.md), [`storyboard-short-form.md`](../../../docs/templates/animation/storyboard-short-form.md)
6. Exemplar: [`starter/`](../../../docs/exemplars/hyperframes-short-form/starter/)

## Footage pipeline

| Stage | Reference |
| ----- | --------- |
| Orchestrator | [`shorts.md`](shorts.md) — `/avo.shorts` |
| Motion delegate | [`motion.md`](motion.md) |
| Captions | [`captions.md`](captions.md) → `embedded-captions` |

## Doctrine

**AVO `motion-doctrine` wins** over student-kit short-form pacing rules. See technique-index § Doctrine precedence.

## Not in repo

- Face `.mp4` — project `assets/` only
- Full karaoke implementation — use `embedded-captions`

Attribution: [`allowlist-and-attribution.md`](../../../docs/exemplars/hyperframes-short-form/allowlist-and-attribution.md)
