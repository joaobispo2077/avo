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

Use the linked storyboard to check the intended entrance, readable hold,
payoff and exit. Record the exact observed times. Use continuous playback
for motion handoffs, lip sync and audibility. The sampled vision report
covers the individual frames it observed.

For a full canonical proof, the approval gate lists current BMap cues,
their program times and the count of observed frames. Open the craft checks
in `review.json` for the planned states, exact frame numbers and findings
that cite frames inside each cue. Inspect glyphs, alignment, visual focus,
caption and source safety, and alpha at the relevant states. Play through
the entrances, holds, payoffs and exits, and check that local and program-wide
treatments have a single owner before changing their settings.

Once the current candidate snapshot retains the exact review, the motion map
and storyboard show the linked frame numbers and finding IDs for each cue.
Use the cited intervals to propose changes through their owning motion or
sound command. Repeat the applicable playback and listening review for the
resulting candidate.

Record a proposed workaround with the exact candidate, reproduction finding,
program windows, engine and runtime versions, platform and render profile.
Review the proposed change in that environment through the normal owning stage.

## Output

Write `<rawDir>/edit/review/animation-qc.md` with PASS/FAIL and blockers.

## Related

- Motion stage: [`motion.md`](motion.md)
- Deliver: [`deliver.md`](deliver.md)
