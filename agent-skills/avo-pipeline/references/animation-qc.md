# /avo.animation-qc reference

## Step/state mapping

**Durable state:** current review.json and candidate-bound evidence

**Workflow steps:** Validate animation qc prerequisites → Run animation qc → Verify and report the animation qc result

**Approval or input gate:** Pause whenever required input or a human decision prevents the next declared step; report the exact reply or artifact needed.

**Stop when:** Missing required input, a failed or stale gate, a required human decision, or verified animation qc completion

**Valid next commands:** /avo.motion or /avo.deliver

HyperFrames / motion **render QC** — after motion slots, before final composite master.

## Preconditions

- [ ] `provider` + `rawDir` declared
- [ ] Motion slot proofs exist under project convention (`edit/preview/` or HyperFrames output paths)
- [ ] Run **after** motion pass; **before** `/avo.deliver` on composite master

## Load skill

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
