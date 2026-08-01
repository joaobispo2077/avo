# Remotion Decision Guide

Remotion is a conditional alternative, not the default animation framework for
this repository.

## When Remotion Is Justified

Use Remotion when one or more are true:

- The repository already contains a maintained Remotion project.
- The team is standardized on React and TypeScript.
- The animation is highly data-driven and benefits from React props, component
  composition, schemas, or application logic.
- A large template system must generate many variants from structured data.
- Existing Remotion packages, components, player integrations, or rendering
  infrastructure reduce implementation risk.
- The animation must be embedded in or tightly integrated with a React app.
- A supported Remotion capability is required and would be costly or fragile in
  HyperFrames.
- The user explicitly requests Remotion.

## Required Decision Output

- Recommended framework.
- Reasons tied to this project.
- Rejected alternative and why.
- Required packages and skills.
- Licensing or deployment checks.
- Determinism and rendering risks.
- Migration or interoperability plan.

## License Review

Review the current Remotion license before organizational or commercial use. At
research time, the license described free use for individuals, non-profits, and
for-profit organizations with up to three employees, while other entities require
a Company License. Do not infer current eligibility without reviewing the current
license text and project context.

## Authoring Expectations

- Use React components with clear composition boundaries.
- Drive motion from `useCurrentFrame()` and metadata from `useVideoConfig()`.
- Use `interpolate()`, `spring()`, `Sequence`, `Series`, or current official
  timing primitives deliberately.
- Use deterministic `random(seed)` instead of `Math.random()`.
- Use Remotion media components that wait for assets.
- Use `delayRender()` and `continueRender()` or current equivalents for required
  async data.
- Wait for fonts before text measurement or layout.
- Keep components concurrency-safe and independent of render order.
- Verify player behavior and rendered output separately.

## Interoperability Boundaries

Do not mix Remotion and HyperFrames in one deliverable without a documented
boundary. Acceptable patterns include rendering a self-contained Remotion asset
for import into a HyperFrames master, rendering a HyperFrames overlay for an
existing Remotion master, or porting a composition using an official migration
workflow. Assign one master timeline owner and QC intermediate and final renders
separately.
