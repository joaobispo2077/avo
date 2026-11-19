# /avo.exports reference

## Step/state mapping

**Durable state:** The immutable handoff, inspection, proposal and qualification records in the canonical timeline directory.

**Approval or input gate:** Confirm the selected target, range and returned evidence. Require the exact qualified review for production export.

**Stop when:** The selected operation is verified, evidence is stale or unsupported, or target review needs a creator decision.

**Valid next commands:** /avo.watch, /avo.trim, /avo.motion or /avo.sound.

Resolve the provider, video and current timeline before preparing an optional
editor handoff. Use the exact selected editor profile. Ask for the intended
range and target only when existing project context leaves them unclear.

Use `avo cli timeline-export status --project FILE` to list target readiness.
Use `prepare`, `inspect-feedback`, `propose-feedback`, `apply-feedback` or
`qualify-target` with `--request FILE`;
each file is an absolute path to a typed local request. Keep the returned
reference and SHA-256 together. See the [editor handoff guide](../../../docs/editor-handoff.md)
for the exact request fields.

Present the validation-only label and affected range for each unsupported
treatment. Compare changes with both the exported example and current timeline.
Show disagreements and ambiguous source occurrences before discussing revisions.
Route selected matching source trims through `apply-feedback`. Use the returned
cutting proposal in the normal preview and editorial approval workflow.
