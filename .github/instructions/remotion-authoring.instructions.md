---
applyTo: "**"
---

# Remotion Authoring Instructions

- Use Remotion only when the framework decision documents a stronger fit than
  HyperFrames or the user explicitly requests it.
- Review the current Remotion license before commercial or organizational use.
- Use React components with clear composition boundaries, props, and schemas for
  reusable/data-driven templates.
- Drive animation from `useCurrentFrame()` and `useVideoConfig()`.
- Use `interpolate()`, `spring()`, `Sequence`, `Series`, or current official
  timing primitives deliberately.
- Use Remotion media components that wait for assets. Use `delayRender()` and
  `continueRender()` or current equivalents for required async data.
- Wait for fonts before text measurement or layout.
- Use deterministic `random(seed)` instead of `Math.random()`.
- Avoid independent clocks, render-order state, unawaited assets, and
  concurrency-unsafe code.
- Verify player behavior and rendered output separately.
