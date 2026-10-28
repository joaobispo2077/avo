# /avo.motion Command

**Timeline integration:** Owns

## Workflow guidance

**Workflow steps:** Validate motion prerequisites → Run motion → Verify and report the motion result
**Step state source:** pipeline-run.json plus the current canonical timeline revision
**Stopping conditions:** Missing required input, a failed or stale gate, a required human decision, or verified motion completion
**Valid next commands:** /avo.animation-qc or /avo.watch

Follow the shared [step-status response contract](../../agent-skills/avo-pipeline/references/step-status.md) for every progress, input, blocker, and completion response.

Add motion graphics or overlays on an approved cut. HyperFrames is the built-in
default; `code-drawn` is the advanced option without a motion framework.

## Resolve the engine first

Parse [shared arguments](../../agent-skills/avo-pipeline/references/arguments.md)
and current direct intent before any engine-specific skill, install or authoring.
Use native `animation engine-show` with the declared project/provider and optional
`--motion-engine hyperframes|remotion|code-drawn` or `Motion engine: <id>`.

- "No frameworks" or unqualified "avoid HyperFrames" means invocation `code-drawn`,
  not skip-motion or a saved-default change.
- Compatible "avoid HyperFrames; use Remotion" means explicit `remotion`. Report
  its actual unsupported adapter/readiness; never silently choose HyperFrames.
- Questions, quoted reference text and negated avoidance do not request an engine
  change. Contradictory explicit choices need one focused clarification.

For `code-drawn` load the [portable advanced entry](../../agent-skills/avo-pipeline/references/code-drawn.md)
and [selection policy](../../agent-skills/avo-pipeline/references/code-drawn/selection.md).
For selected `hyperframes` use the existing [motion workflow](../../agent-skills/avo-pipeline/references/motion.md)
and its compatible installed skills. Do not load that workflow's HyperFrames-only
instructions as a prerequisite for code-drawn. Engine-specific caption/overlay
kits must be compatible with the selected engine; selection does not convert them.

## Usage

```text
/avo.motion --motion-engine code-drawn
Provider: my-channel
rawDir: /path/to/footage
Create a readable lower third without any frameworks.
Logo: /path/to/logo.png
```

The natural-language intent states what to build. The explicit engine is a one-run
choice. To change a saved global/provider/project default use
`/avo.framework` and the native set/reset commands in the selection guide.

## Instructions

1. Inspect canonical state and confirm required exact cut approval. Read the
   active brief, provider design, source/rights records and target render contract.
2. Normalize intent, inspect the selected engine and report its actual readiness.
   For code-drawn, the advanced responsibility disclosure is informational; it
   adds no repeated approval request.
3. Define the beat/state map and canonical BMap/Tracks placement. Keep editable
   implementation and declared dependencies in the external project's `edit/`.
   Use code-drawn scaffold/check/snapshot/render for drawing assets.
4. Render through the shared canonical coordinator and ProofPlan. A standalone
   `asset.mkv` and generated-asset receipt are inputs requiring canonical binding,
   not a motion-proof approval or permission to bypass the proof pipeline.
5. Run current deterministic QC, Watch and candidate transcript analysis; present
   the exact motion-proof candidate for required human approval before promotion.
   Recheck affected evidence after any source/strategy/placement change.

## Canonical timeline contract

`/avo.motion` blocks until the latest CMap revision and exact generated cut
fingerprint have explicit required approval. It authors BMap cues only in
`cmap-output` time, then resolves Animation and Tracks through shared services.
Raw/semantic anchors are rebase hints, never timing truth. Code-drawn composition
time is local to its generated component; it does not own edited-video placement.

Every proof is rebuilt from canonical originals and current verified intermediates.
Earlier proofs, previews and masters are review references, never picture/audio
bases. A CMap basis change stales affected BMap, Tracks, timed animation, previews,
evidence and approvals before another render or human gate.

## Shared timeline gateway

Uses shared timeline storage, transition guards, invalidation and AI review.
It cannot keep private CMap, BMap, Sync Map, track, animation or approval truth.
