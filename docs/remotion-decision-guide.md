# Remotion Decision Guide

HyperFrames remains AVO's built-in default; advanced code-drawn is the supported
framework-free option. Remotion can be saved or selected, but its current AVO
execution adapter is a stub and reports unsupported readiness. Never claim that
a saved preference installs or enables a renderer, or silently fall back.
See [selection](../agent-skills/avo-pipeline/references/code-drawn/selection.md)
and the [code-drawn index](code-drawn-motion.md).

## When Remotion Is Justified

These criteria assess a maintained external project or an explicit integration
choice; they do not enable AVO's unsupported adapter. Consider Remotion when one
or more are true:

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

Review the [current upstream Remotion license](https://www.remotion.dev/license)
for the intended software version, organization and use before organizational or
commercial work. Record the applicable terms/decision; do not infer eligibility
from a remembered employee threshold or a previous version's summary. The link
was checked on 2026-10-26; licensing and execution readiness are separate checks.

## External Remotion source expectations

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

Do not mix engines in one deliverable without a documented boundary and a
supported native admission/composition path. A source port requires explicit user
intent and compatible output; selecting code-drawn does not automatically port a
Remotion composition or HyperFrames kit. Acceptable patterns include rendering a self-contained Remotion asset
for import into a HyperFrames master, rendering a HyperFrames overlay for an
existing Remotion master, or porting a composition using an official migration
workflow. Assign one canonical master/timing owner and QC intermediate and final renders
separately. Preserve fingerprints, recursive source ancestry, current input locks,
reconstruction and normal Watch/transcript/human approval gates. A prior proof or
export cannot become the source of a new canonical proof.
