# /avo.animation-qc reference

**Motion engine gate:** Apply [shared arguments](arguments.md) and inspect native
`animation engine-show` with available context before motion-specific skill/setup.
HyperFrames remains the built-in default. For selected code-drawn, follow the
[advanced workflow](code-drawn.md) and common canonical source/review gates.
HyperFrames-only loaders and recipes below apply only to selected HyperFrames.
Unavailable Remotion or incompatible treatments block; never silently substitute.

Review the engine pinned to the actual source/candidate. A changed future default cannot reinterpret an existing render, and standalone asset checks do not establish canonical-composite approval.

## Step/state mapping

**Durable state:** current review.json and candidate-bound evidence

**Workflow steps:** Validate animation qc prerequisites → Run animation qc → Verify and report the animation qc result

**Approval or input gate:** Pause whenever required input or a human decision prevents the next declared step; report the exact reply or artifact needed.

**Stop when:** Missing required input, a failed or stale gate, a required human decision, or verified animation qc completion

**Valid next commands:** /avo.motion or /avo.deliver

Selected-engine motion **render QC** — after motion slots, before final composite master.

## Preconditions

- [ ] `provider` + `rawDir` declared
- [ ] Motion slot proofs exist under project convention (`edit/preview/` or the declared engine output paths)
- [ ] Run **after** motion pass; **before** `/avo.deliver` on composite master

## Selected HyperFrames validation skill

- **`animation-validation-and-render-qc`** — lint/check/snapshot/render parity, accessibility, determinism

## QC checklist (summary)

- [ ] Message and hierarchy readable at target resolution
- [ ] Text/captions not obscured; flashing safety
- [ ] Seeded randomness / seek behavior deterministic
- [ ] Preview vs render parity spot-checked
- [ ] Source attribution and factual labels preserved

## Output

Write `<rawDir>/edit/review/animation-qc.md` with PASS/FAIL and blockers.

## Related

- Motion stage: [`motion.md`](motion.md)
- Deliver: [`deliver.md`](deliver.md)
